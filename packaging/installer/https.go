package main

// The stub's whole HTTP client: an HTTPS GET over crypto/tls and net, in place of net/http — which is
// most of what this binary used to weigh (the h2 bundle alone is ~0.6 MB) for a client that asks one
// site for three files. What it does, and the rule behind each choice:
//
//   - https:// only, redirect targets included: TLS 1.2 or newer, verified against the SYSTEM's roots
//     (nil RootCAs — the platform verifier on Windows and macOS, the system bundle on Linux), with
//     HTTP/1.1 offered over ALPN.
//   - GET, HTTP/1.1, `Connection: close`: one request per connection, nothing to pool or reuse.
//   - One total deadline per fetch, covering the dial, the handshake, every redirect and every byte.
//   - Redirects (301 302 303 307 308) followed at most maxRedirects times, and only to https://.
//   - Bodies framed by chunked transfer coding, by Content-Length, or by the server closing the
//     connection (which this request asks for) — never more than the caller's limit: a longer body is
//     an error, not a silent truncation.
//   - HTTPS_PROXY (an http:// proxy, through CONNECT) and NO_PROXY, the way net/http's
//     ProxyFromEnvironment served the stub before, so an office behind a mandatory proxy still installs.
//
// Integrity is not this file's job. Every byte it returns is checked afterwards — keys.json and the
// manifest against their signatures, the payload against the signed sha256 and size — so a truncated,
// replayed or hostile body ends as a refusal there, never as an install.

import (
	"bufio"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	maxRedirects   = 5
	maxInterim     = 8        // 1xx responses skipped before the real one
	maxHeaderBytes = 64 << 10 // the header (or trailer) lines of one response, in all
	maxLineBytes   = 16 << 10 // one status, header or chunk-size line
)

// getter fetches over HTTPS. The zero value is what a release uses; tests set roots and proxy.
type getter struct {
	roots *x509.CertPool                            // nil = the system's roots
	proxy func(host, port string) (*url.URL, error) // nil = HTTPS_PROXY / NO_PROXY from the environment
	agent string                                    // the User-Agent header
}

// get fetches rawURL and copies its body into w: at most limit bytes, within timeout for everything.
func (g getter) get(rawURL string, limit int64, timeout time.Duration, w io.Writer) (int64, error) {
	deadline := time.Now().Add(timeout)
	u, err := url.Parse(rawURL)
	if err != nil {
		return 0, err
	}
	for hop := 0; ; hop++ {
		if u.Scheme != "https" || u.Hostname() == "" {
			return 0, fmt.Errorf("refusing %s: only https:// is fetched", u.Redacted())
		}
		next, n, err := g.once(u, limit, deadline, w)
		if err != nil || next == nil {
			return n, err
		}
		if hop == maxRedirects {
			return 0, fmt.Errorf("%s: more than %d redirects", rawURL, maxRedirects)
		}
		u = next
	}
}

// once makes one request: it returns where a redirect points, or how many body bytes went to w.
func (g getter) once(u *url.URL, limit int64, deadline time.Time, w io.Writer) (*url.URL, int64, error) {
	conn, err := g.dial(u, deadline)
	if err != nil {
		return nil, 0, fmt.Errorf("%s: %w", u.Redacted(), err)
	}
	defer conn.Close()
	req := "GET " + u.RequestURI() + " HTTP/1.1\r\nHost: " + u.Host + "\r\nUser-Agent: " + g.agent +
		"\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n"
	if _, err := io.WriteString(conn, req); err != nil {
		return nil, 0, fmt.Errorf("%s: %w", u.Redacted(), err)
	}
	br := bufio.NewReaderSize(conn, maxLineBytes)
	code, hdr, err := readHead(br)
	if err != nil {
		return nil, 0, fmt.Errorf("%s: %w", u.Redacted(), err)
	}
	switch code {
	case 200:
	case 301, 302, 303, 307, 308:
		next, err := u.Parse(hdr["location"])
		if err != nil || hdr["location"] == "" {
			return nil, 0, fmt.Errorf("%s: HTTP %d without a usable Location", u.Redacted(), code)
		}
		return next, 0, nil
	default:
		return nil, 0, fmt.Errorf("%s: HTTP %d", u.Redacted(), code)
	}
	body, err := bodyOf(br, hdr, limit)
	if err == nil {
		var n int64
		if n, err = io.Copy(w, io.LimitReader(body, limit+1)); err == nil && n > limit {
			err = fmt.Errorf("the body is more than the %d bytes allowed", limit)
		}
		if err == nil {
			return nil, n, nil
		}
	}
	return nil, 0, fmt.Errorf("%s: %w", u.Redacted(), err)
}

// dial opens the TLS connection, directly or through the proxy the environment names.
func (g getter) dial(u *url.URL, deadline time.Time) (net.Conn, error) {
	host, port := u.Hostname(), u.Port()
	if port == "" {
		port = "443"
	}
	choose := g.proxy
	if choose == nil {
		choose = proxyFromEnv
	}
	proxy, err := choose(host, port)
	if err != nil {
		return nil, err
	}
	d := net.Dialer{Deadline: deadline}
	var raw net.Conn
	if proxy == nil {
		raw, err = d.Dial("tcp", net.JoinHostPort(host, port))
	} else {
		raw, err = connectVia(&d, proxy, net.JoinHostPort(host, port), deadline)
	}
	if err != nil {
		return nil, err
	}
	tc := tls.Client(raw, &tls.Config{ServerName: host, RootCAs: g.roots, MinVersion: tls.VersionTLS12,
		NextProtos: []string{"http/1.1"}})
	if err = tc.SetDeadline(deadline); err == nil {
		err = tc.Handshake()
	}
	if err != nil {
		raw.Close()
		return nil, err
	}
	return tc, nil
}

// readHead reads the status line and headers of the final response, skipping 1xx interim ones.
// Header names are lower-cased; a repeated header is joined with ", " (RFC 9110 §5.3).
func readHead(br *bufio.Reader) (int, map[string]string, error) {
	for i := 0; i <= maxInterim; i++ {
		line, err := readLine(br)
		if err != nil {
			return 0, nil, err
		}
		proto, rest, _ := strings.Cut(line, " ")
		digits, _, _ := strings.Cut(rest, " ")
		code, err := strconv.Atoi(digits)
		if !strings.HasPrefix(proto, "HTTP/1.") || len(digits) != 3 || err != nil || code < 100 {
			return 0, nil, fmt.Errorf("malformed status line %q", line)
		}
		hdr, err := readFields(br)
		if err != nil || code >= 200 {
			return code, hdr, err
		}
	}
	return 0, nil, errors.New("too many interim (1xx) responses")
}

// readFields reads header — or trailer — lines up to the empty line that ends them.
func readFields(br *bufio.Reader) (map[string]string, error) {
	hdr := map[string]string{}
	for total := 0; ; {
		line, err := readLine(br)
		if err != nil {
			return nil, err
		}
		if line == "" {
			return hdr, nil
		}
		if total += len(line); total > maxHeaderBytes {
			return nil, errors.New("response headers too large")
		}
		name, value, ok := strings.Cut(line, ":")
		if !ok || name == "" || strings.ContainsAny(name, " \t") {
			return nil, fmt.Errorf("malformed header line %q", line) // obsolete line folding included
		}
		name, value = strings.ToLower(name), strings.TrimSpace(value)
		if old, dup := hdr[name]; dup {
			value = old + ", " + value
		}
		hdr[name] = value
	}
}

// readLine reads one CRLF- (or bare LF-) terminated line, without its terminator.
func readLine(br *bufio.Reader) (string, error) {
	b, err := br.ReadSlice('\n')
	switch {
	case err == bufio.ErrBufferFull:
		return "", errors.New("response line too long")
	case err == io.EOF:
		return "", io.ErrUnexpectedEOF
	case err != nil:
		return "", err
	}
	return strings.TrimRight(string(b), "\r\n"), nil
}

// bodyOf picks the body's framing (RFC 9112 §6.3): chunked when the transfer coding says so, else
// Content-Length, else until the server closes the connection.
func bodyOf(br *bufio.Reader, hdr map[string]string, limit int64) (io.Reader, error) {
	if ce := hdr["content-encoding"]; ce != "" && !strings.EqualFold(ce, "identity") {
		return nil, fmt.Errorf("unrequested content-encoding %q", ce)
	}
	if te, ok := hdr["transfer-encoding"]; ok {
		if !strings.EqualFold(te, "chunked") {
			return nil, fmt.Errorf("unsupported transfer-encoding %q", te)
		}
		return &chunked{r: br}, nil
	}
	if cl, ok := hdr["content-length"]; ok {
		n, err := strconv.ParseUint(cl, 10, 63)
		if err != nil {
			return nil, fmt.Errorf("malformed Content-Length %q", cl)
		}
		if int64(n) > limit {
			return nil, fmt.Errorf("the body is %d bytes, more than the %d bytes allowed", n, limit)
		}
		return &exactly{r: br, left: int64(n)}, nil
	}
	return br, nil
}

// exactly reads a Content-Length body and calls an earlier end what it is: a truncation.
type exactly struct {
	r    io.Reader
	left int64
}

func (e *exactly) Read(p []byte) (int, error) {
	if e.left == 0 {
		return 0, io.EOF
	}
	if int64(len(p)) > e.left {
		p = p[:e.left]
	}
	n, err := e.r.Read(p)
	if e.left -= int64(n); err == io.EOF && e.left > 0 {
		err = io.ErrUnexpectedEOF
	}
	return n, err
}

// chunked decodes the chunked transfer coding (RFC 9112 §7.1): extensions are ignored, the trailer
// section is read and dropped.
type chunked struct {
	r    *bufio.Reader
	left int64 // bytes left in the current chunk
	err  error // sticky: io.EOF after the last chunk, or what went wrong
}

func (c *chunked) Read(p []byte) (int, error) {
	if c.err != nil {
		return 0, c.err
	}
	if c.left == 0 {
		line, err := readLine(c.r)
		if err != nil {
			c.err = err
			return 0, err
		}
		size, _, _ := strings.Cut(line, ";")
		n, err := strconv.ParseUint(strings.TrimSpace(size), 16, 63)
		if err != nil {
			c.err = fmt.Errorf("malformed chunk size %q", line)
			return 0, c.err
		}
		if n == 0 {
			if _, c.err = readFields(c.r); c.err == nil {
				c.err = io.EOF
			}
			return 0, c.err
		}
		c.left = int64(n)
	}
	if int64(len(p)) > c.left {
		p = p[:c.left]
	}
	n, err := c.r.Read(p)
	if c.left -= int64(n); err == io.EOF {
		err = io.ErrUnexpectedEOF
	}
	if err == nil && c.left == 0 {
		if line, lerr := readLine(c.r); lerr != nil || line != "" {
			err = errors.New("malformed chunk: its data does not end in CRLF")
		}
	}
	c.err = err
	return n, err
}

// connectVia opens a tunnel to addr through an http:// proxy (HTTP CONNECT, RFC 9110 §9.3.6).
func connectVia(d *net.Dialer, proxy *url.URL, addr string, deadline time.Time) (net.Conn, error) {
	port := proxy.Port()
	if port == "" {
		port = "80"
	}
	conn, err := d.Dial("tcp", net.JoinHostPort(proxy.Hostname(), port))
	if err != nil {
		return nil, fmt.Errorf("proxy %s: %w", proxy.Host, err)
	}
	req := "CONNECT " + addr + " HTTP/1.1\r\nHost: " + addr + "\r\n"
	if proxy.User != nil {
		pw, _ := proxy.User.Password()
		req += "Proxy-Authorization: Basic " + base64.StdEncoding.EncodeToString([]byte(proxy.User.Username()+":"+pw)) + "\r\n"
	}
	br := bufio.NewReaderSize(conn, maxLineBytes)
	if err = conn.SetDeadline(deadline); err == nil {
		_, err = io.WriteString(conn, req+"\r\n")
	}
	if err == nil {
		var code int
		if code, _, err = readHead(br); err == nil && code != 200 {
			err = fmt.Errorf("HTTP %d", code)
		}
	}
	if err == nil && br.Buffered() > 0 {
		err = errors.New("it sent data before the tunnel was used")
	}
	if err != nil {
		conn.Close()
		return nil, fmt.Errorf("proxy %s did not open a tunnel to %s: %w", proxy.Host, addr, err)
	}
	return conn, nil
}

// proxyFromEnv answers as net/http's ProxyFromEnvironment does for an https:// request: HTTPS_PROXY
// (or https_proxy), unless the host is localhost, a loopback address or named by NO_PROXY (or
// no_proxy). The proxy is reached over http:// (a bare host:port means that, as in net/http); an
// https:// or socks5 proxy is refused out loud rather than silently bypassed.
func proxyFromEnv(host, port string) (*url.URL, error) {
	raw := envAny("HTTPS_PROXY", "https_proxy")
	if raw == "" || bypassProxy(host, port, envAny("NO_PROXY", "no_proxy")) {
		return nil, nil
	}
	p, err := url.Parse(raw)
	if err != nil || p.Scheme != "http" && p.Scheme != "https" && p.Scheme != "socks5" && p.Scheme != "socks5h" {
		if q, qerr := url.Parse("http://" + raw); qerr == nil {
			p, err = q, nil
		}
	}
	switch {
	case err != nil:
		return nil, errors.New("HTTPS_PROXY is not a URL") // not echoed: it may hold a password
	case p.Scheme != "http":
		return nil, fmt.Errorf("HTTPS_PROXY %s: this installer reaches a proxy over http:// (CONNECT) only", p.Redacted())
	}
	return p, nil
}

// bypassProxy is NO_PROXY as golang.org/x/net/http/httpproxy reads it: "*", an IP or CIDR, a domain
// that also matches its subdomains ("example.com"), or only its subdomains (".example.com",
// "*.example.com"); any entry may carry a ":port" that must then match too.
func bypassProxy(host, port, noProxy string) bool {
	host = strings.ToLower(host)
	ip := net.ParseIP(host)
	if host == "localhost" || ip != nil && ip.IsLoopback() {
		return true
	}
	for _, e := range strings.Split(noProxy, ",") {
		e = strings.ToLower(strings.TrimSpace(e))
		if e == "*" {
			return true
		}
		if _, cidr, err := net.ParseCIDR(e); err == nil {
			if ip != nil && cidr.Contains(ip) {
				return true
			}
			continue
		}
		ehost, eport := e, ""
		if h, p, err := net.SplitHostPort(e); err == nil {
			ehost, eport = h, p
		}
		ehost = strings.TrimSuffix(strings.TrimPrefix(ehost, "["), "]")
		if ehost == "" || eport != "" && eport != port {
			continue
		}
		if eip := net.ParseIP(ehost); eip != nil {
			if eip.Equal(ip) {
				return true
			}
			continue
		}
		if strings.HasPrefix(ehost, "*.") {
			ehost = ehost[1:]
		}
		if strings.HasPrefix(ehost, ".") && strings.HasSuffix(host, ehost) ||
			host == ehost || strings.HasSuffix(host, "."+ehost) {
			return true
		}
	}
	return false
}

func envAny(names ...string) string {
	for _, n := range names {
		if v := os.Getenv(n); v != "" {
			return v
		}
	}
	return ""
}

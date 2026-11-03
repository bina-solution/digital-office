package main

// The HTTPS client against real TLS servers: net/http's own (httptest) for the ordinary answers, and a
// raw one that writes a canned response byte for byte — for the framings net/http's server never
// produces (a body ended by close, chunk extensions, trailers, 1xx, malformed heads).

import (
	"bufio"
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"
)

// direct is the proxy decision of every test: no proxy, whatever the environment of the machine says.
func direct(string, string) (*url.URL, error) { return nil, nil }

// tlsServer is an httptest TLS server and a getter that trusts exactly its certificate. A release's
// getter trusts the system's roots instead — TestGetVerifiesTheServersCertificate proves that holds.
func tlsServer(t *testing.T, h http.HandlerFunc) (*httptest.Server, getter) {
	t.Helper()
	ts := httptest.NewTLSServer(h)
	t.Cleanup(ts.Close)
	pool := x509.NewCertPool()
	pool.AddCert(ts.Certificate())
	return ts, getter{roots: pool, proxy: direct, agent: "dgo-install/test"}
}

// rawTLS serves `response` verbatim to every connection, after reading the request's head.
func rawTLS(t *testing.T, response string) (string, getter) {
	t.Helper()
	cert := httptest.NewUnstartedServer(nil)
	cert.StartTLS() // only to mint a certificate for 127.0.0.1
	pool := x509.NewCertPool()
	pool.AddCert(cert.Certificate())
	certs := cert.TLS.Certificates
	cert.Close()
	ln, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{Certificates: certs})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				defer c.Close()
				br := bufio.NewReader(c)
				for {
					if line, err := br.ReadString('\n'); err != nil || line == "\r\n" {
						break
					}
				}
				io.WriteString(c, response)
			}()
		}
	}()
	return "https://" + ln.Addr().String() + "/x", getter{roots: pool, proxy: direct, agent: "dgo-install/test"}
}

func fetch(g getter, u string, limit int64) (string, error) {
	var b bytes.Buffer
	n, err := g.get(u, limit, 10*time.Second, &b)
	if err == nil && n != int64(b.Len()) {
		panic("get reported a count that is not what it wrote")
	}
	return b.String(), err
}

func TestGetSendsAMinimalHTTP11GET(t *testing.T) {
	var got *http.Request
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
		got = r
		io.WriteString(w, "the body")
	})
	body, err := fetch(g, ts.URL+"/dl/keys.json?x=1", 1<<10)
	if err != nil || body != "the body" {
		t.Fatalf("body %q, err %v", body, err)
	}
	if got.Method != "GET" || got.Proto != "HTTP/1.1" || got.URL.RequestURI() != "/dl/keys.json?x=1" ||
		got.Host != strings.TrimPrefix(ts.URL, "https://") || got.UserAgent() != "dgo-install/test" ||
		!got.Close || got.Header.Get("Accept-Encoding") != "identity" {
		t.Fatalf("request = %s %s %s host=%q ua=%q close=%v ae=%q", got.Method, got.URL.RequestURI(), got.Proto,
			got.Host, got.UserAgent(), got.Close, got.Header.Get("Accept-Encoding"))
	}
}

func TestGetReadsChunkedBodies(t *testing.T) {
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, "first ")
		w.(http.Flusher).Flush() // a flush before the end makes net/http's server send chunks
		io.WriteString(w, "second")
	})
	if body, err := fetch(g, ts.URL, 1<<10); err != nil || body != "first second" {
		t.Fatalf("body %q, err %v", body, err)
	}
}

func TestGetFollowsRedirectsToHTTPSOnly(t *testing.T) {
	var ts *httptest.Server
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/moved":
			http.Redirect(w, r, "/here", http.StatusFound) // relative, as CDNs often send it
		case "/permanent":
			http.Redirect(w, r, ts.URL+"/here", http.StatusPermanentRedirect)
		case "/downgrade":
			http.Redirect(w, r, "http://"+strings.TrimPrefix(ts.URL, "https://")+"/here", http.StatusMovedPermanently)
		case "/loop":
			http.Redirect(w, r, "/loop", http.StatusTemporaryRedirect)
		case "/nowhere":
			w.WriteHeader(http.StatusFound)
		default:
			io.WriteString(w, "arrived")
		}
	})
	for path, want := range map[string]string{"/moved": "arrived", "/permanent": "arrived"} {
		if body, err := fetch(g, ts.URL+path, 1<<10); err != nil || body != want {
			t.Errorf("%s: body %q, err %v", path, body, err)
		}
	}
	for path, want := range map[string]string{"/downgrade": "only https", "/loop": "more than 5 redirects", "/nowhere": "Location"} {
		if _, err := fetch(g, ts.URL+path, 1<<10); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%s: err %v, want it to contain %q", path, err, want)
		}
	}
}

func TestGetRefusesWhatIsNotA200(t *testing.T) {
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) { http.NotFound(w, r) })
	if _, err := fetch(g, ts.URL+"/dl/keys.json", 1<<10); err == nil || !strings.Contains(err.Error(), "HTTP 404") {
		t.Fatalf("err %v, want HTTP 404", err)
	}
}

func TestGetCapsTheBody(t *testing.T) {
	hundred := strings.Repeat("x", 100)
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/chunked" {
			io.WriteString(w, hundred[:50])
			w.(http.Flusher).Flush() // chunked from here on: no length announced
			io.WriteString(w, hundred[50:])
			return
		}
		w.Header().Set("Content-Length", "100")
		io.WriteString(w, hundred)
	})
	if body, err := fetch(g, ts.URL+"/length", 100); err != nil || body != hundred {
		t.Fatalf("a body of exactly the limit must pass: %d bytes, %v", len(body), err)
	}
	if _, err := fetch(g, ts.URL+"/length", 99); err == nil || !strings.Contains(err.Error(), "100 bytes, more than the 99 bytes allowed") {
		t.Errorf("a Content-Length over the limit must be refused before reading: %v", err)
	}
	if _, err := fetch(g, ts.URL+"/chunked", 99); err == nil || !strings.Contains(err.Error(), "more than the 99 bytes allowed") {
		t.Errorf("a chunked body over the limit must be refused: %v", err)
	}
}

func TestGetRefusesPlainHTTP(t *testing.T) {
	g := getter{proxy: func(string, string) (*url.URL, error) { t.Fatal("no connection may be attempted"); return nil, nil }}
	for _, u := range []string{"http://digital-office.co.il/dl/keys.json", "ftp://digital-office.co.il/x", "https:///nohost"} {
		if _, err := fetch(g, u, 1<<10); err == nil || !strings.Contains(err.Error(), "only https") {
			t.Errorf("%s: err %v", u, err)
		}
	}
}

func TestGetVerifiesTheServersCertificate(t *testing.T) {
	// A release's getter has no roots of its own: it trusts the SYSTEM's, which have never heard of a
	// test server's self-signed certificate — so the handshake must fail, never be skipped.
	ts, _ := tlsServer(t, func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, "secret") })
	_, err := fetch(getter{proxy: direct}, ts.URL, 1<<10)
	if err == nil || !strings.Contains(err.Error(), "certificate") {
		t.Fatalf("an untrusted certificate must fail the handshake: %v", err)
	}
}

func TestGetHasOneDeadline(t *testing.T) {
	release := make(chan struct{})
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "10")
		io.WriteString(w, "slow")
		w.(http.Flusher).Flush()
		<-release // the rest never comes while the client waits
	})
	defer close(release)
	start := time.Now()
	_, err := g.get(ts.URL, 1<<10, 300*time.Millisecond, io.Discard)
	if err == nil || time.Since(start) > 5*time.Second {
		t.Fatalf("a stalled body must end at the deadline: err %v after %v", err, time.Since(start))
	}
}

func TestGetFraming(t *testing.T) {
	cases := []struct {
		name, response, want, err string
	}{
		{"a body ended by the server closing", "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nuntil close", "until close", ""},
		{"HTTP/1.0", "HTTP/1.0 200 OK\r\n\r\nold server", "old server", ""},
		{"bare LF line ends", "HTTP/1.1 200 OK\nContent-Length: 2\n\nok", "ok", ""},
		{"a header without a reason phrase", "HTTP/1.1 200\r\nContent-Length: 2\r\n\r\nok", "ok", ""},
		{"chunks with extensions, upper-case hex and trailers",
			"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5;name=v\r\nhello\r\nA\r\n world, ok\r\n0\r\nX-Trailer: 1\r\n\r\n", "hello world, ok", ""},
		{"1xx interim responses before the real one",
			"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 103 Early Hints\r\nLink: </x>\r\n\r\nHTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok", "ok", ""},
		{"Content-Length longer than the body", "HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nshort", "", "unexpected EOF"},
		{"chunked, cut before the last chunk", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n", "", "unexpected EOF"},
		{"a chunk size that is not hex", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\nhello\r\n0\r\n\r\n", "", "malformed chunk size"},
		{"a chunk size with a sign", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n+5\r\nhello\r\n0\r\n\r\n", "", "malformed chunk size"},
		{"a chunk not ended by CRLF", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhelloX\r\n0\r\n\r\n", "", "does not end in CRLF"},
		{"a compressed body nobody asked for", "HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 2\r\n\r\nok", "", "content-encoding"},
		{"a transfer coding other than chunked", "HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip, chunked\r\n\r\n", "", "transfer-encoding"},
		{"two different Content-Lengths", "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\nok", "", "Content-Length"},
		{"obsolete header line folding", "HTTP/1.1 200 OK\r\nX-A: 1\r\n continued\r\nContent-Length: 2\r\n\r\nok", "", "malformed header"},
		{"HTTP/2 in an HTTP/1.1 answer", "HTTP/2 200\r\n\r\n", "", "malformed status"},
		{"not HTTP at all", "SSH-2.0-OpenSSH_9.6\r\n", "", "malformed status"},
		{"headers past 64 KiB", "HTTP/1.1 200 OK\r\n" + strings.Repeat("X-Pad: "+strings.Repeat("a", 1000)+"\r\n", 70) + "\r\n", "", "too large"},
		{"one line past 16 KiB", "HTTP/1.1 200 OK\r\nX-Pad: " + strings.Repeat("a", 17<<10) + "\r\n\r\n", "", "too long"},
		{"no answer at all", "", "", "unexpected EOF"},
	}
	for _, tc := range cases {
		u, g := rawTLS(t, tc.response)
		body, err := fetch(g, u, 1<<10)
		switch {
		case tc.err == "" && (err != nil || body != tc.want):
			t.Errorf("%s: body %q, err %v, want %q", tc.name, body, err, tc.want)
		case tc.err != "" && (err == nil || !strings.Contains(err.Error(), tc.err)):
			t.Errorf("%s: err %v, want it to contain %q", tc.name, err, tc.err)
		}
	}
}

func TestProxyFromTheEnvironment(t *testing.T) {
	cases := []struct {
		https, httpOnly, noProxy, host, want, err string
	}{
		{host: "digital-office.co.il"},                                                           // nothing set: direct
		{httpOnly: "http://p:3128", host: "digital-office.co.il"},                                // HTTP_PROXY is for http:// requests only
		{https: "proxy.corp:3128", host: "digital-office.co.il", want: "http://proxy.corp:3128"}, // a bare host:port is http://
		{https: "10.0.0.1:3128", host: "digital-office.co.il", want: "http://10.0.0.1:3128"},
		{https: "http://u:p@proxy.corp:8080", host: "digital-office.co.il", want: "http://u:p@proxy.corp:8080"},
		{https: "https://proxy.corp", host: "digital-office.co.il", err: "http:// (CONNECT) only"},
		{https: "socks5://proxy.corp:1080", host: "digital-office.co.il", err: "http:// (CONNECT) only"},
		{https: "proxy.corp:3128", host: "localhost"}, // loopback is never proxied
		{https: "proxy.corp:3128", host: "127.0.0.1"},
		{https: "proxy.corp:3128", host: "::1"},
		{https: "proxy.corp:3128", noProxy: "digital-office.co.il", host: "digital-office.co.il"},
	}
	for _, tc := range cases {
		// Lower case first: on Windows HTTPS_PROXY and https_proxy are one variable.
		t.Setenv("https_proxy", "")
		t.Setenv("no_proxy", "")
		t.Setenv("HTTPS_PROXY", tc.https)
		t.Setenv("HTTP_PROXY", tc.httpOnly)
		t.Setenv("NO_PROXY", tc.noProxy)
		p, err := proxyFromEnv(tc.host, "443")
		got := ""
		if p != nil {
			got = p.String()
		}
		if got != tc.want || (err == nil) != (tc.err == "") || err != nil && !strings.Contains(err.Error(), tc.err) {
			t.Errorf("HTTPS_PROXY=%q NO_PROXY=%q host %s: proxy %q err %v, want %q %q", tc.https, tc.noProxy, tc.host, got, err, tc.want, tc.err)
		}
	}
}

func TestNoProxyReadsLikeNetHTTP(t *testing.T) {
	cases := []struct {
		noProxy, host, port string
		bypass              bool
	}{
		{"*", "digital-office.co.il", "443", true},
		{"example.com", "example.com", "443", true},
		{"example.com", "dl.example.com", "443", true},
		{"example.com", "notexample.com", "443", false},
		{".example.com", "dl.example.com", "443", true},
		{".example.com", "example.com", "443", false},
		{"*.example.com", "dl.example.com", "443", true},
		{"*.example.com", "example.com", "443", false},
		{"example.com:8443", "example.com", "443", false},
		{"example.com:8443", "example.com", "8443", true},
		{" Example.COM , other.net", "example.com", "443", true},
		{"10.0.0.0/8", "10.1.2.3", "443", true},
		{"10.0.0.0/8", "93.184.216.20", "443", false},
		{"10.0.0.0/8", "example.com", "443", false},
		{"10.1.2.3", "10.1.2.3", "443", true},
		{"10.1.2.3:8443", "10.1.2.3", "443", false},
		{"[2001:db8::1]", "2001:db8::1", "443", true},
		{"", "example.com", "443", false},
		{"other.net", "example.com", "443", false},
	}
	for _, tc := range cases {
		if got := bypassProxy(tc.host, tc.port, tc.noProxy); got != tc.bypass {
			t.Errorf("NO_PROXY=%q %s:%s: bypass %v, want %v", tc.noProxy, tc.host, tc.port, got, tc.bypass)
		}
	}
}

// connectProxy is an HTTP proxy that answers CONNECT with `answer`, records the request head (read
// back with the returned func), and — when it answers 200 — tunnels to the requested address.
func connectProxy(t *testing.T, answer string) (*url.URL, func() string) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	var mu sync.Mutex
	var head []string
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				defer c.Close()
				br := bufio.NewReader(c)
				var lines []string
				for {
					line, err := br.ReadString('\n')
					if err != nil || line == "\r\n" {
						break
					}
					lines = append(lines, strings.TrimRight(line, "\r\n"))
				}
				mu.Lock()
				head = lines
				mu.Unlock()
				io.WriteString(c, answer)
				if !strings.HasPrefix(answer, "HTTP/1.1 200") || len(lines) == 0 {
					return
				}
				up, err := net.Dial("tcp", strings.Fields(lines[0])[1])
				if err != nil {
					return
				}
				defer up.Close()
				go io.Copy(up, br)
				io.Copy(c, up)
			}()
		}
	}()
	seen := func() string {
		mu.Lock()
		defer mu.Unlock()
		return strings.Join(head, "\n")
	}
	return &url.URL{Scheme: "http", Host: ln.Addr().String(), User: url.UserPassword("user", "secret")}, seen
}

func TestGetThroughAConnectProxy(t *testing.T) {
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, "through the tunnel") })
	proxy, head := connectProxy(t, "HTTP/1.1 200 Connection established\r\n\r\n")
	g.proxy = func(string, string) (*url.URL, error) { return proxy, nil }
	body, err := fetch(g, ts.URL+"/dl/keys.json", 1<<10)
	if err != nil || body != "through the tunnel" {
		t.Fatalf("body %q, err %v", body, err)
	}
	addr := strings.TrimPrefix(ts.URL, "https://")
	auth := "Proxy-Authorization: Basic " + base64.StdEncoding.EncodeToString([]byte("user:secret"))
	if got := head(); got != "CONNECT "+addr+" HTTP/1.1\nHost: "+addr+"\n"+auth {
		t.Fatalf("the proxy saw:\n%s", got)
	}
}

func TestAProxyThatRefusesTheTunnelIsAnError(t *testing.T) {
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, "unreachable") })
	proxy, _ := connectProxy(t, "HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
	g.proxy = func(string, string) (*url.URL, error) { return proxy, nil }
	if _, err := fetch(g, ts.URL, 1<<10); err == nil || !strings.Contains(err.Error(), "407") {
		t.Fatalf("err %v, want the proxy's 407", err)
	}
}

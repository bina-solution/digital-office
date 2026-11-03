package main

// ws.go — the TCP path over HTTPS. A pair's connection rides a WebSocket (RFC 6455) when the side
// that dials can reach the world only through an HTTP proxy on port 443: a Claude cloud sandbox
// (measured 2026-10-15: every TLS connection goes through an intercepting proxy, nothing inbound),
// a corporate network. The accepting office takes it at its EDGE — traefik terminates TLS on
// `link.<domain>` and hands the upgraded connection to this process (door.go) — so ONE public port
// carries every pair of every office that dials in, where WireGuard would need a published UDP port
// per pair (and an office can publish only one: hooks/prepare 2b).
//
// The proxy may read every byte: an intercepting proxy terminates TLS with a CA of its own. It
// learns nothing it can use. The carriers prove the pair's WireGuard keys to each other before a
// datagram moves (wire.go), and WireGuard encrypts each datagram end to end. TLS is the way through
// here, not the trust — which is why a CA this office was told to accept (DGO_CARRY_CA, the sandbox
// proxy's) is safe to add beside the system's.
//
// Only what a carrier needs is implemented: binary frames both ways, the masking a client owes
// (§5.3), ping/pong/close answered, fragments read as one stream. No extensions, no text semantics.

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha1"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

const (
	wsGUID     = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
	wsProtocol = "dgo-carry.1"
	// The largest frame a peer may send. A session flushes at most 64 KiB at a time (carry.go), so
	// anything near this size is not a carrier.
	wsMaxFrame = 1 << 20

	opCont   = 0x0
	opText   = 0x1
	opBinary = 0x2
	opClose  = 0x8
	opPing   = 0x9
	opPong   = 0xA
)

var errWSFrame = errors.New("websocket: malformed frame")

// wsAddr names a websocket connection: by the host it was dialed at (`link.example.org`), or by the
// address the edge says the peer came from.
type wsAddr string

func (a wsAddr) Network() string { return "ws" }
func (a wsAddr) String() string  { return string(a) }

// wsConn is a net.Conn whose bytes travel as websocket frames over another connection (a TLS one,
// or the edge's plain one). Deadlines, Close and LocalAddr are the underlying connection's.
type wsConn struct {
	net.Conn
	r      *bufio.Reader // the underlying reads; may hold bytes read past the upgrade's head
	client bool          // a client masks every frame it sends, a server never does (§5.1)
	remote net.Addr

	rmu    sync.Mutex
	left   uint64 // bytes of the current data frame not read yet
	masked bool
	key    [4]byte
	pos    int

	wmu sync.Mutex
}

func (c *wsConn) RemoteAddr() net.Addr {
	if c.remote != nil {
		return c.remote
	}
	return c.Conn.RemoteAddr()
}

func (c *wsConn) Read(p []byte) (int, error) {
	c.rmu.Lock()
	defer c.rmu.Unlock()
	for c.left == 0 {
		if err := c.nextFrame(); err != nil {
			return 0, err
		}
	}
	if uint64(len(p)) > c.left {
		p = p[:c.left]
	}
	n, err := c.r.Read(p)
	if c.masked {
		for i := 0; i < n; i++ {
			p[i] ^= c.key[c.pos&3]
			c.pos++
		}
	}
	c.left -= uint64(n)
	return n, err
}

// nextFrame reads frame heads until a data frame with a payload begins, answering control frames
// on the way. The caller holds rmu.
func (c *wsConn) nextFrame() error {
	var h [2]byte
	if _, err := io.ReadFull(c.r, h[:]); err != nil {
		return err
	}
	if h[0]&0x70 != 0 {
		return errWSFrame // a reserved bit: no extension was agreed
	}
	op := h[0] & 0x0f
	masked := h[1]&0x80 != 0
	if masked == c.client {
		return errWSFrame // a server's frames are never masked, a client's always are
	}
	n := uint64(h[1] & 0x7f)
	switch n {
	case 126:
		var b [2]byte
		if _, err := io.ReadFull(c.r, b[:]); err != nil {
			return err
		}
		n = uint64(binary.BigEndian.Uint16(b[:]))
	case 127:
		var b [8]byte
		if _, err := io.ReadFull(c.r, b[:]); err != nil {
			return err
		}
		n = binary.BigEndian.Uint64(b[:])
	}
	var key [4]byte
	if masked {
		if _, err := io.ReadFull(c.r, key[:]); err != nil {
			return err
		}
	}
	if op >= opClose {
		if n > 125 || h[0]&0x80 == 0 {
			return errWSFrame // a control frame is short and never fragmented
		}
		payload := make([]byte, n)
		if _, err := io.ReadFull(c.r, payload); err != nil {
			return err
		}
		if masked {
			for i := range payload {
				payload[i] ^= key[i&3]
			}
		}
		switch op {
		case opClose:
			if len(payload) > 2 {
				payload = payload[:2]
			}
			_ = c.writeFrame(opClose, payload) // the closing handshake, best effort
			return io.EOF
		case opPing:
			return c.writeFrame(opPong, payload)
		case opPong:
			return nil
		}
		return errWSFrame
	}
	if op != opCont && op != opBinary && op != opText {
		return errWSFrame
	}
	if n > wsMaxFrame {
		return errWSFrame
	}
	c.left, c.masked, c.key, c.pos = n, masked, key, 0
	return nil
}

func (c *wsConn) Write(p []byte) (int, error) {
	if err := c.writeFrame(opBinary, p); err != nil {
		return 0, err
	}
	return len(p), nil
}

func (c *wsConn) writeFrame(op byte, p []byte) error {
	c.wmu.Lock()
	defer c.wmu.Unlock()
	return c.writeFrameLocked(op, p)
}

func (c *wsConn) writeFrameLocked(op byte, p []byte) error {
	f := make([]byte, 0, 14+len(p))
	f = append(f, 0x80|op)
	var mask byte
	if c.client {
		mask = 0x80
	}
	switch {
	case len(p) < 126:
		f = append(f, mask|byte(len(p)))
	case len(p) <= 0xffff:
		f = append(f, mask|126)
		f = binary.BigEndian.AppendUint16(f, uint16(len(p)))
	default:
		f = append(f, mask|127)
		f = binary.BigEndian.AppendUint64(f, uint64(len(p)))
	}
	if c.client {
		var key [4]byte
		if _, err := rand.Read(key[:]); err != nil {
			return err
		}
		f = append(f, key[:]...)
		start := len(f)
		f = append(f, p...)
		for i := range p {
			f[start+i] ^= key[i&3]
		}
	} else {
		f = append(f, p...)
	}
	_, err := c.Conn.Write(f)
	return err
}

// Close says goodbye when nothing is being written at that moment, and closes the connection. A
// writer stuck on a dead path holds wmu; waiting for it would make Close as slow as the dead path.
func (c *wsConn) Close() error {
	if c.wmu.TryLock() {
		_ = c.Conn.SetWriteDeadline(time.Now().Add(time.Second))
		_ = c.writeFrameLocked(opClose, []byte{0x03, 0xe8}) // 1000: normal closure
		c.wmu.Unlock()
	}
	return c.Conn.Close()
}

// acceptOf is the Sec-WebSocket-Accept value for a key (§4.2.2).
func acceptOf(key string) string {
	h := sha1.Sum([]byte(key + wsGUID))
	return base64.StdEncoding.EncodeToString(h[:])
}

// hasToken reports whether a comma-separated header names a token (`Connection: keep-alive, Upgrade`).
func hasToken(h http.Header, name, token string) bool {
	for _, v := range h.Values(name) {
		for _, t := range strings.Split(v, ",") {
			if strings.EqualFold(strings.TrimSpace(t), token) {
				return true
			}
		}
	}
	return false
}

// proxyFor is the proxy the environment names for an address (HTTPS_PROXY, HTTP_PROXY, NO_PROXY —
// net/http's own reading of them), or nil. A variable so a test can point it at its own proxy.
var proxyFor = func(u *url.URL) (*url.URL, error) {
	return http.ProxyFromEnvironment(&http.Request{URL: u})
}

// rootCAs is the system's trust plus the CA in DGO_CARRY_CA, when this office was given one (a
// cloud sandbox's intercepting proxy). Read at every dial: dials are seconds apart at the most.
func rootCAs() *x509.CertPool {
	pool, err := x509.SystemCertPool()
	if err != nil || pool == nil {
		pool = x509.NewCertPool()
	}
	if f := strings.TrimSpace(os.Getenv("DGO_CARRY_CA")); f != "" {
		pem, err := os.ReadFile(f)
		switch {
		case err != nil:
			log.Printf("DGO_CARRY_CA: %v", err)
		case len(bytes.TrimSpace(pem)) == 0:
			// the office was given no CA (compose mounts an empty file then): nothing to add
		case !pool.AppendCertsFromPEM(pem):
			log.Printf("DGO_CARRY_CA: %s holds no certificate", f)
		}
	}
	return pool
}

// dialWS opens a connection to a carrier behind an HTTPS edge (`wss://link.example.org/carry`;
// `ws://` only where nothing needs TLS, a test), through the proxy the environment names. The whole
// opening — proxy, TLS, upgrade — has `timeout`.
func dialWS(ctx context.Context, raw string, timeout time.Duration) (net.Conn, error) {
	u, err := url.Parse(raw)
	if err != nil {
		return nil, err
	}
	secure := u.Scheme == "wss"
	if !secure && u.Scheme != "ws" {
		return nil, fmt.Errorf("%s is not a ws:// or wss:// address", raw)
	}
	host, port := u.Hostname(), u.Port()
	if port == "" {
		port = map[bool]string{true: "443", false: "80"}[secure]
	}
	target := net.JoinHostPort(host, port)
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	web := *u
	web.Scheme = map[bool]string{true: "https", false: "http"}[secure]
	proxy, err := proxyFor(&web)
	if err != nil {
		return nil, fmt.Errorf("the proxy setting: %w", err)
	}
	var d net.Dialer
	var conn net.Conn
	if proxy != nil {
		if proxy.Scheme != "http" {
			return nil, fmt.Errorf("proxy %s: only an http:// proxy is supported", proxy.Redacted())
		}
		at := proxy.Host
		if proxy.Port() == "" {
			at = net.JoinHostPort(proxy.Hostname(), "80")
		}
		if conn, err = d.DialContext(ctx, "tcp", at); err != nil {
			return nil, fmt.Errorf("proxy %s: %w", proxy.Redacted(), err)
		}
	} else if conn, err = d.DialContext(ctx, "tcp", target); err != nil {
		return nil, err
	}
	if dl, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(dl)
	}
	fail := func(e error) (net.Conn, error) {
		_ = conn.Close()
		return nil, e
	}
	if proxy != nil {
		var b strings.Builder
		fmt.Fprintf(&b, "CONNECT %s HTTP/1.1\r\nHost: %s\r\n", target, target)
		if proxy.User != nil {
			pw, _ := proxy.User.Password()
			cred := base64.StdEncoding.EncodeToString([]byte(proxy.User.Username() + ":" + pw))
			fmt.Fprintf(&b, "Proxy-Authorization: Basic %s\r\n", cred)
		}
		b.WriteString("\r\n")
		if _, err := io.WriteString(conn, b.String()); err != nil {
			return fail(fmt.Errorf("proxy %s: %w", proxy.Redacted(), err))
		}
		br := bufio.NewReader(conn)
		resp, err := http.ReadResponse(br, &http.Request{Method: http.MethodConnect})
		if err != nil {
			return fail(fmt.Errorf("proxy %s: %w", proxy.Redacted(), err))
		}
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			return fail(fmt.Errorf("proxy %s refused %s: %s", proxy.Redacted(), target, resp.Status))
		}
		if br.Buffered() > 0 {
			return fail(fmt.Errorf("proxy %s sent bytes before the tunnel began", proxy.Redacted()))
		}
	}
	stream := conn
	if secure {
		tc := tls.Client(conn, &tls.Config{ServerName: host, RootCAs: rootCAs(),
			MinVersion: tls.VersionTLS12, NextProtos: []string{"http/1.1"}})
		if err := tc.HandshakeContext(ctx); err != nil {
			return fail(fmt.Errorf("tls with %s: %w", host, err))
		}
		stream = tc
	}
	nonce := make([]byte, 16)
	if _, err := rand.Read(nonce); err != nil {
		return fail(err)
	}
	key := base64.StdEncoding.EncodeToString(nonce)
	req := "GET " + u.RequestURI() + " HTTP/1.1\r\nHost: " + u.Host + "\r\nUpgrade: websocket\r\n" +
		"Connection: Upgrade\r\nSec-WebSocket-Key: " + key + "\r\nSec-WebSocket-Version: 13\r\n" +
		"Sec-WebSocket-Protocol: " + wsProtocol + "\r\nUser-Agent: dgo-carry\r\n\r\n"
	if _, err := io.WriteString(stream, req); err != nil {
		return fail(err)
	}
	rb := bufio.NewReaderSize(stream, 16<<10)
	resp, err := http.ReadResponse(rb, &http.Request{Method: http.MethodGet})
	if err != nil {
		return fail(fmt.Errorf("%s: %w", raw, err))
	}
	if resp.StatusCode != http.StatusSwitchingProtocols {
		_ = resp.Body.Close()
		return fail(fmt.Errorf("%s answered %s, not a websocket", raw, resp.Status))
	}
	if !strings.EqualFold(resp.Header.Get("Upgrade"), "websocket") || !hasToken(resp.Header, "Connection", "upgrade") ||
		resp.Header.Get("Sec-WebSocket-Accept") != acceptOf(key) {
		return fail(fmt.Errorf("%s answered 101 without a valid websocket handshake", raw))
	}
	_ = stream.SetDeadline(time.Time{})
	return &wsConn{Conn: stream, r: rb, client: true, remote: wsAddr(u.Host)}, nil
}

// acceptWS answers the upgrade a carrier asked for and returns the connection it became. `source`
// is the address the peer is known by (the edge's X-Real-Ip). A request that is not a websocket
// upgrade is answered 400 here, and nothing is returned.
func acceptWS(w http.ResponseWriter, r *http.Request, source string) (net.Conn, error) {
	key := r.Header.Get("Sec-WebSocket-Key")
	nonce, kerr := base64.StdEncoding.DecodeString(key)
	if r.Method != http.MethodGet || !strings.EqualFold(r.Header.Get("Upgrade"), "websocket") ||
		!hasToken(r.Header, "Connection", "upgrade") || r.Header.Get("Sec-WebSocket-Version") != "13" ||
		kerr != nil || len(nonce) != 16 {
		http.Error(w, "this address carries DGO links: a websocket upgrade, and nothing else", http.StatusBadRequest)
		return nil, errors.New("not a websocket upgrade")
	}
	hj, ok := w.(http.Hijacker)
	if !ok {
		http.Error(w, "this server cannot hand the connection over", http.StatusInternalServerError)
		return nil, errors.New("no hijacker")
	}
	conn, brw, err := hj.Hijack()
	if err != nil {
		return nil, err
	}
	_ = conn.SetDeadline(time.Time{}) // the server's header timeout is not the session's
	head := "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
		"Sec-WebSocket-Accept: " + acceptOf(key) + "\r\n"
	if hasToken(r.Header, "Sec-WebSocket-Protocol", wsProtocol) {
		head += "Sec-WebSocket-Protocol: " + wsProtocol + "\r\n"
	}
	head += "\r\n"
	if _, err := brw.WriteString(head); err != nil {
		_ = conn.Close()
		return nil, err
	}
	if err := brw.Flush(); err != nil {
		_ = conn.Close()
		return nil, err
	}
	return &wsConn{Conn: conn, r: brw.Reader, client: false, remote: wsAddr(source)}, nil
}

// tcpOf finds the TCP connection under a carried one, so a session can tune it (no delay, keepalive)
// whichever way it arrived.
func tcpOf(c net.Conn) *net.TCPConn {
	for {
		switch x := c.(type) {
		case *net.TCPConn:
			return x
		case *wsConn:
			c = x.Conn
		case *tls.Conn:
			c = x.NetConn()
		default:
			return nil
		}
	}
}

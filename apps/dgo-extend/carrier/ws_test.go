package main

// The relayed path, as tests: websocket frames cross both ways intact (masked one way, plain the
// other, control frames answered), a pair comes up THROUGH an intercepting-style chain — a CONNECT
// proxy, a TLS edge that hands the upgrade on, the hub's door — and carries datagrams both ways;
// the door answers its three paths and nothing else; a relay that is not an address is refused.

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func wsPair() (*wsConn, *wsConn) {
	a, b := net.Pipe()
	return &wsConn{Conn: a, r: bufio.NewReader(a), client: true},
		&wsConn{Conn: b, r: bufio.NewReader(b), client: false}
}

func TestWebsocketFramesCrossBothWays(t *testing.T) {
	client, server := wsPair()
	defer client.Close()
	defer server.Close()
	for _, size := range []int{1, 125, 126, 4000, 65535, 65536, 70000} {
		want := bytes.Repeat([]byte{byte(size)}, size)
		for _, dir := range []struct {
			from, to *wsConn
			name     string
		}{{client, server, "client→server"}, {server, client, "server→client"}} {
			go func(w *wsConn) { _, _ = w.Write(want) }(dir.from)
			got := make([]byte, size)
			if _, err := io.ReadFull(dir.to, got); err != nil {
				t.Fatalf("%s %d bytes: %v", dir.name, size, err)
			}
			if !bytes.Equal(got, want) {
				t.Fatalf("%s %d bytes arrived changed", dir.name, size)
			}
		}
	}
}

func TestAPingIsAnsweredAndAnUnmaskedClientFrameRefused(t *testing.T) {
	a, b := net.Pipe()
	client := &wsConn{Conn: a, r: bufio.NewReader(a), client: true}
	defer client.Close()
	defer b.Close()
	// The server side, written by hand: a ping, then data.
	go func() { _, _ = b.Write([]byte{0x80 | opPing, 2, 'h', 'i', 0x80 | opBinary, 3, 'a', 'b', 'c'}) }()
	pong := make(chan []byte, 1)
	go func() {
		head := make([]byte, 2+4+2) // fin|pong, masked|2, key, payload
		_, _ = io.ReadFull(b, head)
		pong <- head
	}()
	got := make([]byte, 3)
	if _, err := io.ReadFull(client, got); err != nil || string(got) != "abc" {
		t.Fatalf("the data after a ping: %q %v", got, err)
	}
	h := <-pong
	if h[0] != 0x80|opPong || h[1] != 0x80|2 {
		t.Fatalf("the ping was not answered with a masked pong: % x", h)
	}
	if p := []byte{h[6] ^ h[2], h[7] ^ h[3]}; string(p) != "hi" {
		t.Fatalf("the pong did not carry the ping's payload: %q", p)
	}

	c, d := net.Pipe()
	server := &wsConn{Conn: d, r: bufio.NewReader(d), client: false}
	defer server.Close()
	go func() { _, _ = c.Write([]byte{0x80 | opBinary, 1, 'x'}); c.Close() }()
	if _, err := server.Read(make([]byte, 1)); err == nil {
		t.Fatal("a server accepted an unmasked frame from a client")
	}
}

// connectProxy is the smallest CONNECT proxy: it checks the credentials it was given, counts the
// tunnels it opened, and copies bytes.
func connectProxy(t *testing.T, user, pass string) (*url.URL, *atomic.Int32) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	var tunnels atomic.Int32
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				br := bufio.NewReader(c)
				req, err := http.ReadRequest(br)
				if err != nil || req.Method != http.MethodConnect {
					return
				}
				if u, p, ok := req.BasicAuth(); !ok || u != user || p != pass {
					// BasicAuth reads Authorization; a proxy's is Proxy-Authorization.
					req.Header.Set("Authorization", req.Header.Get("Proxy-Authorization"))
					if u, p, ok = req.BasicAuth(); !ok || u != user || p != pass {
						_, _ = io.WriteString(c, "HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
						return
					}
				}
				up, err := net.Dial("tcp", req.Host)
				if err != nil {
					_, _ = io.WriteString(c, "HTTP/1.1 502 Bad Gateway\r\n\r\n")
					return
				}
				defer up.Close()
				tunnels.Add(1)
				_, _ = io.WriteString(c, "HTTP/1.1 200 Connection established\r\n\r\n")
				go func() { _, _ = io.Copy(up, br) }()
				_, _ = io.Copy(c, up)
			}(c)
		}
	}()
	return &url.URL{Scheme: "http", Host: ln.Addr().String(), User: url.UserPassword(user, pass)}, &tunnels
}

func TestAPairComesUpThroughAProxyAndAnEdge(t *testing.T) {
	hub, spoke := newOffice(t), newOffice(t)
	doorPort := freeTCP(t)

	// The edge: TLS terminated, the upgrade handed to the hub's door — what traefik does.
	doorURL, _ := url.Parse(fmt.Sprintf("http://127.0.0.1:%d", doorPort))
	edge := httptest.NewTLSServer(httputil.NewSingleHostReverseProxy(doorURL))
	defer edge.Close()
	caFile := filepath.Join(t.TempDir(), "edge-ca.pem")
	if err := os.WriteFile(caFile, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: edge.Certificate().Raw}), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("DGO_CARRY_CA", caFile)

	// The spoke reaches the world only through a proxy that wants credentials.
	proxy, tunnels := connectProxy(t, "sandbox", "s3cret")
	old := proxyFor
	proxyFor = func(*url.URL) (*url.URL, error) { return proxy, nil }
	t.Cleanup(func() { proxyFor = old })

	relay := strings.Replace(edge.URL, "https://", "wss://", 1) + "/carry"
	hubPair := pairOf(hub, spoke, "wg7", "claude-cloud")
	raw := planDoc{V: 1, Door: fmt.Sprintf("127.0.0.1:%d", doorPort), Pairs: []pairConfig{hubPair}}
	writePlanDoc(t, hub, raw)
	spokePair := pairOf(spoke, hub, "wg7", "vps1")
	spokePair.Relay = relay
	spoke.plan(t, "", spokePair)
	hub.start(t)
	spoke.start(t)

	waitFor(t, "the relayed pair to come up", func() bool {
		return spoke.state(t).Pairs["wg7"].State == "up" && hub.state(t).Pairs["wg7"].State == "up"
	})
	waitFor(t, "spoke → hub", func() bool { return crosses(t, spoke, hub, "from the sandbox") })
	waitFor(t, "hub → spoke", func() bool { return crosses(t, hub, spoke, "from vps1") })
	if tunnels.Load() == 0 {
		t.Fatal("the spoke reached the edge without its proxy")
	}
	st := spoke.state(t).Pairs["wg7"]
	if !st.Dialed || st.Remember != "" || !strings.Contains(st.Via, "127.0.0.1") {
		t.Fatalf("a relayed session: dialed, via the edge, nothing remembered as an address: %+v", st)
	}
	if hs := hub.state(t); !hs.DoorOpen {
		t.Fatalf("the hub does not say its door is open: %+v", hs)
	}

	// The relayed connection dies (the sandbox's proxy dropped it): the spoke comes back by itself.
	spoke.c.mu.Lock()
	s := spoke.c.pairs["wg7"].current()
	spoke.c.mu.Unlock()
	s.close()
	waitFor(t, "the spoke to come back through the relay", func() bool {
		st := spoke.state(t).Pairs["wg7"]
		return st.State == "up" && st.Ups >= 2
	})
	waitFor(t, "traffic after the reconnect", func() bool { return crosses(t, hub, spoke, "again") })
}

func writePlanDoc(t *testing.T, o *office, doc planDoc) {
	t.Helper()
	raw, _ := json.Marshal(doc)
	tmp := filepath.Join(o.dir, "carry.json.tmp")
	if err := os.WriteFile(tmp, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, filepath.Join(o.dir, "carry.json")); err != nil {
		t.Fatal(err)
	}
}

func TestTheDoorAnswersItsThreePathsAndNothingElse(t *testing.T) {
	var seen atomic.Value
	app := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen.Store(fmt.Sprintf("%s %s real=%s cookie=%q xff=%q", r.Method, r.URL.Path,
			r.Header.Get("X-Real-Ip"), r.Header.Get("Cookie"), r.Header.Get("X-Forwarded-For")))
		_, _ = io.WriteString(w, `{"state":"pending"}`)
	}))
	defer app.Close()
	appURL, _ := url.Parse(app.URL)
	hub := newOffice(t)
	hub.start(t)
	front := httptest.NewServer(newDoor(hub.c, appURL))
	defer front.Close()

	do := func(method, path, body string, hdr map[string]string) (int, string) {
		req, _ := http.NewRequest(method, front.URL+path, strings.NewReader(body))
		for k, v := range hdr {
			req.Header.Set(k, v)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		return resp.StatusCode, string(b)
	}
	if code, _ := do("GET", "/carry", "", nil); code != http.StatusBadRequest {
		t.Fatalf("a plain GET of /carry: %d, want 400", code)
	}
	for _, p := range []string{"/", "/api/link", "/api/pair", "/join/../api/link", "/healthz"} {
		if code, _ := do("GET", p, "", nil); code != http.StatusNotFound {
			t.Fatalf("GET %s through the door: %d, want 404", p, code)
		}
	}
	if code, _ := do("PUT", "/join", "{}", nil); code != http.StatusNotFound {
		t.Fatalf("PUT /join: %d, want 404", code)
	}
	code, body := do("POST", "/join", `{"offer":"DGOPAIR1:x"}`,
		map[string]string{"X-Real-Ip": "203.0.113.9", "Cookie": "authentik_session=abc", "X-Forwarded-For": "93.184.216.7"})
	if code != http.StatusOK || !strings.Contains(body, "pending") {
		t.Fatalf("POST /join was not passed to the app: %d %s", code, body)
	}
	if got := seen.Load().(string); got != `POST /join real=203.0.113.9 cookie="" xff=""` {
		t.Fatalf("what the app was told: %s", got)
	}
	if code, _ := do("GET", "/join/abcdefgh1234", "", nil); code != http.StatusOK {
		t.Fatalf("GET /join/<id>: %d", code)
	}
	if code, _ := do("POST", "/join", strings.Repeat("x", joinBodyLimit+10), nil); code == http.StatusOK {
		t.Fatal("a join body past the limit reached the app")
	}
	limited := false
	for i := 0; i < joinPerMinute+2; i++ {
		if code, _ := do("POST", "/join", "{}", map[string]string{"X-Real-Ip": "198.51.100.7"}); code == http.StatusTooManyRequests {
			limited = true
			break
		}
	}
	if !limited {
		t.Fatalf("one address sent more than %d join requests in a minute", joinPerMinute)
	}
	// …and the limit is per address: another one is still answered.
	if code, _ := do("POST", "/join", "{}", map[string]string{"X-Real-Ip": "198.51.100.8"}); code != http.StatusOK {
		t.Fatalf("another address was limited too: %d", code)
	}
}

// The second reader of 2026-10-19: a hub that declares a link host before it holds any pair has no
// key file yet, and its door must still open — it is how the first pair arrives.
func TestTheDoorOpensBeforeTheOfficeHasAKey(t *testing.T) {
	hub := newOffice(t)
	if err := os.Remove(filepath.Join(hub.dir, "wg-private.key")); err != nil {
		t.Fatal(err)
	}
	port := freeTCP(t)
	writePlanDoc(t, hub, planDoc{V: 1, Door: fmt.Sprintf("127.0.0.1:%d", port)})
	hub.start(t)
	waitFor(t, "the door to open with no key", func() bool { return hub.state(t).DoorOpen })
	resp, err := http.Get(fmt.Sprintf("http://127.0.0.1:%d/carry", port))
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("a plain GET of /carry on a keyless hub: %d, want 400", resp.StatusCode)
	}
}

func TestARelayThatIsNotAnAddressIsRefused(t *testing.T) {
	hub := newOffice(t)
	base := pairOf(hub, hub, "wg7", "x")
	for relay, why := range map[string]string{
		"https://link.example.org/carry":   "not ws",
		"wss:///carry":                     "no host",
		"wss://u:p@link.example.org/carry": "credentials",
	} {
		pc := base
		pc.Relay = relay
		if checkPair(&pc) == "" {
			t.Fatalf("relay %q (%s) was accepted", relay, why)
		}
	}
	pc := base
	pc.Relay = "wss://link.example.org/carry"
	pc.Dial = []string{"10.0.0.1:51443"}
	if checkPair(&pc) == "" {
		t.Fatal("a relayed pair that also dials an address was accepted")
	}
	pc.Dial = nil
	if why := checkPair(&pc); why != "" {
		t.Fatalf("a good relay was refused: %s", why)
	}
}

func TestADialThroughAProxyThatRefusesSaysSo(t *testing.T) {
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	defer ln.Close()
	go func() {
		c, err := ln.Accept()
		if err != nil {
			return
		}
		defer c.Close()
		_, _ = http.ReadRequest(bufio.NewReader(c))
		_, _ = io.WriteString(c, "HTTP/1.1 403 Forbidden\r\n\r\n")
	}()
	old := proxyFor
	proxyFor = func(*url.URL) (*url.URL, error) { return &url.URL{Scheme: "http", Host: ln.Addr().String()}, nil }
	defer func() { proxyFor = old }()
	_, err := dialWS(context.Background(), "wss://link.example.org/carry", 3*time.Second)
	if err == nil || !strings.Contains(err.Error(), "403") {
		t.Fatalf("a refusing proxy: %v", err)
	}
}

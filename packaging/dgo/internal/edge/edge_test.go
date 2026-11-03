package edge

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// fakeAuth stands in for forward-auth's /auth/traefik: a request carrying the cookie `dgo_session=ok`
// is the owner; any other is sent to sign in, with a cookie of its own. It records what it was asked.
func fakeAuth(t *testing.T, asked *http.Header) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/auth/traefik" {
			http.NotFound(w, r)
			return
		}
		*asked = r.Header.Clone()
		if c, err := r.Cookie("dgo_session"); err == nil && c.Value == "ok" {
			w.Header().Set("X-authentik-username", "owner")
			w.Header().Set("X-authentik-groups", "admins")
			w.WriteHeader(http.StatusOK)
			return
		}
		http.SetCookie(w, &http.Cookie{Name: "dgo_state", Value: "s", Path: "/"})
		http.Redirect(w, r, "http://signin.localhost:8080/login?rd=x", http.StatusFound)
	}))
	t.Cleanup(srv.Close)
	return srv
}

// fakeApp answers with the identity it was handed and the Host it saw.
func fakeApp(t *testing.T, hits *int) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*hits++
		_, _ = io.WriteString(w, "user="+r.Header.Get("X-authentik-username")+" host="+r.Host)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func mustURL(t *testing.T, raw string) *url.URL {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return u
}

func edgeFor(t *testing.T, auth, app, signin string) *Server {
	t.Helper()
	s, err := New(map[string]Route{
		"console.localhost": {Upstream: mustURL(t, app), Gated: true},
		"signin.localhost":  {Upstream: mustURL(t, signin)},
	}, auth+"/auth/traefik", t.Logf)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func get(s *Server, host, target string, cookie *http.Cookie, extra map[string]string) *httptest.ResponseRecorder {
	r := httptest.NewRequest("GET", target, nil)
	r.Host = host
	if cookie != nil {
		r.AddCookie(cookie)
	}
	for k, v := range extra {
		r.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}

// An anonymous request to a gated host gets the identity service's answer, verbatim — its 302, its
// Location and its cookie — and never reaches the app.
func TestAnonymousGetsTheSignInAnswerVerbatim(t *testing.T) {
	var asked http.Header
	hits := 0
	s := edgeFor(t, fakeAuth(t, &asked).URL, fakeApp(t, &hits).URL, fakeApp(t, new(int)).URL)
	w := get(s, "console.localhost:8080", "/apps?x=1", nil, nil)
	if w.Code != http.StatusFound || w.Header().Get("Location") != "http://signin.localhost:8080/login?rd=x" {
		t.Fatalf("= %d to %q, want the identity service's 302", w.Code, w.Header().Get("Location"))
	}
	if !strings.Contains(w.Header().Get("Set-Cookie"), "dgo_state=s") {
		t.Errorf("the identity service's cookie did not reach the browser: %q", w.Header().Get("Set-Cookie"))
	}
	if hits != 0 {
		t.Fatal("an anonymous request reached the app")
	}
	// what forward-auth was asked: the request as the browser made it, port and query included
	for k, want := range map[string]string{"X-Forwarded-Host": "console.localhost:8080", "X-Forwarded-Uri": "/apps?x=1",
		"X-Forwarded-Proto": "http", "X-Forwarded-Method": "GET"} {
		if got := asked.Get(k); got != want {
			t.Errorf("forward-auth was asked %s=%q, want %q", k, got, want)
		}
	}
}

// A signed-in request reaches the app carrying the identity the service named — and a client's own
// identity headers and forwarded host never do, on a gated host or an open one.
func TestTheAppGetsOnlyTheServicesIdentity(t *testing.T) {
	var asked http.Header
	hits := 0
	s := edgeFor(t, fakeAuth(t, &asked).URL, fakeApp(t, &hits).URL, fakeApp(t, new(int)).URL)
	forged := map[string]string{"X-authentik-username": "mallory", "X-Forwarded-Host": "evil.example"}

	w := get(s, "console.localhost:8080", "/", &http.Cookie{Name: "dgo_session", Value: "ok"}, forged)
	if w.Code != http.StatusOK || w.Body.String() != "user=owner host=console.localhost:8080" {
		t.Fatalf("= %d %q, want the app with the service's identity and the browser's host", w.Code, w.Body.String())
	}
	if asked.Get("X-Forwarded-Host") != "console.localhost:8080" || asked.Get("X-authentik-username") != "" {
		t.Errorf("forward-auth was asked with a client's own header: host %q, user %q",
			asked.Get("X-Forwarded-Host"), asked.Get("X-authentik-username"))
	}
	if !strings.Contains(asked.Get("Cookie"), "dgo_session=ok") {
		t.Error("the browser's cookie did not reach forward-auth")
	}

	w = get(s, "signin.localhost:8080", "/login", nil, forged)
	if w.Code != http.StatusOK || !strings.HasPrefix(w.Body.String(), "user= ") {
		t.Fatalf("the open sign-in host = %d %q, want it served with no identity", w.Code, w.Body.String())
	}
}

// A host nobody declared is not served; the edge's own health answers; a silent identity service is a
// 502, not an open door.
func TestUnknownHostsHealthAndASilentIdentityService(t *testing.T) {
	hits := 0
	app := fakeApp(t, &hits)
	dead := httptest.NewServer(http.NotFoundHandler())
	deadURL := dead.URL
	dead.Close()
	s := edgeFor(t, deadURL, app.URL, app.URL)

	if w := get(s, "evil.example", "/", nil, nil); w.Code != http.StatusNotFound {
		t.Errorf("an undeclared host = %d, want 404", w.Code)
	}
	if w := get(s, "127.0.0.1:8080", "/healthz", nil, nil); w.Code != http.StatusOK {
		t.Errorf("/healthz = %d, want 200", w.Code)
	}
	if w := get(s, "console.localhost", "/", &http.Cookie{Name: "dgo_session", Value: "ok"}, nil); w.Code != http.StatusBadGateway || hits != 0 {
		t.Fatalf("with the identity service down = %d (app hit %d time(s)), want 502 and no app", w.Code, hits)
	}
}

// The second reader's tricks: an underscore spelling (a WSGI app reads X_Authentik_Username as the
// identity), a `Connection:` naming the identity headers so the proxy would drop the ones the gate set,
// and forwarding or X-DGO-* headers the app would believe from the edge. None reaches the app; the
// gate's identity does.
func TestNoSpellingOrHopTrickForgesOrErasesTheIdentity(t *testing.T) {
	var asked http.Header
	app := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var got []string
		for k := range r.Header {
			if Claimed(k) && k != "X-Forwarded-For" && k != "X-Forwarded-Host" && k != "X-Forwarded-Proto" && !strings.HasPrefix(k, "X-Authentik-") {
				got = append(got, k)
			}
		}
		_, _ = io.WriteString(w, "user="+r.Header.Get("X-authentik-username")+" stray="+strings.Join(got, ","))
	}))
	t.Cleanup(app.Close)
	s := edgeFor(t, fakeAuth(t, &asked).URL, app.URL, app.URL)

	r := httptest.NewRequest("GET", "/", nil)
	r.Host = "console.localhost"
	r.AddCookie(&http.Cookie{Name: "dgo_session", Value: "ok"})
	r.Header["X_Authentik_Username"] = []string{"mallory"}
	r.Header.Set("Connection", "X-Authentik-Username, X-Authentik-Groups")
	r.Header.Set("X-Forwarded-Uri", "/admin")
	r.Header.Set("X-Real-Ip", "10.0.0.1")
	r.Header.Set("X-DGO-Office", "elsewhere")
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	if w.Code != http.StatusOK || w.Body.String() != "user=owner stray=" {
		t.Fatalf("= %d %q, want the gate's identity and nothing a client wrote", w.Code, w.Body.String())
	}
	if asked.Get("X_Authentik_Username") != "" {
		t.Error("forward-auth was asked with a client's underscore identity")
	}
}

// A 2xx that names nobody is not a sign-in (an --auth at the wrong path): refused, never open.
func TestA2xxNamingNobodyIsRefused(t *testing.T) {
	hits := 0
	auth := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(auth.Close)
	s := edgeFor(t, auth.URL, fakeApp(t, &hits).URL, fakeApp(t, new(int)).URL)
	if w := get(s, "console.localhost", "/", nil, nil); w.Code != http.StatusBadGateway || hits != 0 {
		t.Fatalf("= %d (app hit %d time(s)), want 502 and no app", w.Code, hits)
	}
}

// The edge listens on loopback only.
func TestTheEdgeListensOnLoopbackOnly(t *testing.T) {
	var stderr strings.Builder
	if code := Main("", []string{"--listen", "0.0.0.0:0", "--open", "x.localhost=http://127.0.0.1:1"}, &stderr); code != 2 ||
		!strings.Contains(stderr.String(), "not a loopback address") {
		t.Fatalf("--listen 0.0.0.0:0 = %d %q, want refused", code, stderr.String())
	}
}

// The phone's edge (DGO-1090): forward-auth and the app each on a Unix socket of its own, and the edge on
// one too, which only its owner may open — a request reaches the app with the identity, as over TCP.
func TestTheEdgeSpeaksUnixSockets(t *testing.T) {
	dir, err := os.MkdirTemp("", "edge") // short: a socket's path has a limit of ~100 bytes
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	serve := func(name string, h http.Handler) string {
		t.Helper()
		path := filepath.Join(dir, name)
		ln, err := ListenUnix(path)
		if err != nil {
			t.Fatal(err)
		}
		srv := &http.Server{Handler: h}
		go srv.Serve(ln)
		t.Cleanup(func() { srv.Close() })
		return path
	}
	auth := serve("fa.sock", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if c, err := r.Cookie("dgo_session"); err == nil && c.Value == "ok" && r.URL.Path == "/auth/traefik" {
			w.Header().Set("X-authentik-username", "owner")
			return
		}
		http.Redirect(w, r, "http://signin.localhost:8080/login", http.StatusFound)
	}))
	app := serve("app.sock", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "user="+r.Header.Get("X-authentik-username")+" host="+r.Host)
	}))
	s, err := New(map[string]Route{"console.localhost": {Upstream: &url.URL{Scheme: "unix", Path: app}, Gated: true}}, "unix:"+auth, t.Logf)
	if err != nil {
		t.Fatal(err)
	}
	edge := serve("edge.sock", s)
	if st, err := os.Stat(edge); err != nil || st.Mode().Perm() != 0o600 {
		t.Fatalf("the edge's socket: %v, want mode 0600", err)
	}
	c := &http.Client{Transport: &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		var d net.Dialer
		return d.DialContext(ctx, "unix", edge)
	}}, Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	ask := func(cookie string) (int, string) {
		t.Helper()
		req, err := http.NewRequest("GET", "http://console.localhost:8080/x", nil)
		if err != nil {
			t.Fatal(err)
		}
		if cookie != "" {
			req.AddCookie(&http.Cookie{Name: "dgo_session", Value: cookie})
		}
		res, err := c.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer res.Body.Close()
		b, _ := io.ReadAll(res.Body)
		return res.StatusCode, string(b)
	}
	if code, body := ask("ok"); code != http.StatusOK || body != "user=owner host=console.localhost:8080" {
		t.Fatalf("signed in, over the sockets: %d %q", code, body)
	}
	if code, _ := ask(""); code != http.StatusFound {
		t.Fatalf("anonymous, over the sockets: %d, want the sign-in's 302", code)
	}
	var stderr strings.Builder
	if code := Main("", []string{"--listen", "unix://host/edge.sock", "--open", "x.localhost=http://127.0.0.1:1"}, &stderr); code != 2 {
		t.Fatalf("--listen unix://host/edge.sock = %d %q, want refused as the upstreams are", code, stderr.String())
	}
	for _, bad := range []string{"unix:fa.sock", "unix://host/fa.sock", "unix:/" + strings.Repeat("x", maxSocketPath)} {
		if _, err := New(map[string]Route{"console.localhost": {Upstream: mustURL(t, "http://127.0.0.1:1"), Gated: true}}, bad, t.Logf); err == nil {
			t.Fatalf("--auth %s was accepted", bad)
		}
		if _, err := New(map[string]Route{"x.localhost": {Upstream: mustURL(t, bad)}}, "", t.Logf); err == nil {
			t.Fatalf("the upstream %s was accepted", bad)
		}
	}
}

// The phone's machine (DGO-1090): while it reports its port, a host the edge has no route for is the
// machine's — gated as the console is, and handed on with the identity forward-auth answered, signed for
// that one request (never the token itself), the core's own sign-in left out and the app's cookies kept;
// a client's own signature never gets through; with no machine, such a host is nobody's.
func TestUnroutedHostsAreTheMachinesWhileItRuns(t *testing.T) {
	var asked http.Header
	auth := fakeAuth(t, &asked)
	var seen *http.Request
	vm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.Clone(r.Context())
		_, _ = io.WriteString(w, "the machine")
	}))
	t.Cleanup(vm.Close)
	port := vm.Listener.Addr().(*net.TCPAddr).Port
	hits := 0
	s := edgeFor(t, auth.URL, fakeApp(t, &hits).URL, auth.URL)
	up := false
	s.Machine = func() (int, string) {
		if !up {
			return 0, ""
		}
		return port, "the-machines-token-of-this-boot-0123456789"
	}
	if w := get(s, "n8n.localhost:8080", "/", &http.Cookie{Name: "dgo_session", Value: "ok"}, nil); w.Code != http.StatusNotFound || seen != nil {
		t.Fatalf("with no machine, an unrouted host = %d (reached: %v)", w.Code, seen != nil)
	}
	up = true
	if w := get(s, "n8n.localhost:8080", "/", nil, nil); w.Code != http.StatusFound || seen != nil {
		t.Fatalf("anonymous, to the machine = %d (reached: %v), want the sign-in", w.Code, seen != nil)
	}
	w := get(s, "n8n.localhost:8080", "/x?y=1", &http.Cookie{Name: "dgo_session", Value: "ok"},
		map[string]string{EdgeSig: "forged", EdgeAt: "1", "X-authentik-username": "intruder", "Cookie": "n8n-auth=theirs; dgo_session=ok"})
	if w.Code != http.StatusOK || w.Body.String() != "the machine" || seen == nil {
		t.Fatalf("signed in, to the machine = %d %q", w.Code, w.Body.String())
	}
	const token = "the-machines-token-of-this-boot-0123456789"
	at := seen.Header.Get(EdgeAt)
	if seen.Header.Get("X-authentik-username") != "owner" || seen.Host != "n8n.localhost:8080" || seen.URL.RequestURI() != "/x?y=1" ||
		seen.Header.Get(EdgeSig) != EdgeSigned(token, at, seen.Header.Get(EdgeNonce), "GET", "n8n.localhost:8080", "/x?y=1", seen.Header) ||
		at == "1" || len(seen.Header.Get(EdgeNonce)) != 32 {
		t.Fatalf("handed on: user %q, Host %q, %s, signed %q at %q", seen.Header.Get("X-authentik-username"), seen.Host,
			seen.URL.RequestURI(), seen.Header.Get(EdgeSig), at)
	}
	for _, h := range seen.Header.Values("Cookie") {
		if strings.Contains(h, "dgo_session") {
			t.Fatalf("the core's sign-in reached the machine: %q", h)
		}
	}
	if !strings.Contains(seen.Header.Get("Cookie"), "n8n-auth=theirs") {
		t.Fatalf("the app's own cookie was lost: %q", seen.Header.Get("Cookie"))
	}
	for k, vs := range seen.Header {
		for _, v := range vs {
			if strings.Contains(v, token) {
				t.Fatalf("the token itself reached the machine in %s", k)
			}
		}
	}
	if hits != 0 {
		t.Fatal("the console's upstream was asked for the machine's host")
	}
}

// While the machine is down, a host of an app the office runs in its machine waits for it: an anonymous
// caller signs in first and starts nothing; the owner gets a page that loads itself again (a browser's) or
// a plain 503 (an API's), the machine asked for. Any other host — and /healthz — answers as before.
func TestUnroutedHostsWaitForTheMachine(t *testing.T) {
	var asked http.Header
	auth := fakeAuth(t, &asked)
	hits := 0
	s := edgeFor(t, auth.URL, fakeApp(t, &hits).URL, auth.URL)
	s.Machine = func() (int, string) { return 0, "" }
	has, woke := true, 0
	s.Wake = func(host string, ask bool) (string, bool) {
		if host != "n8n.localhost" {
			return "", false
		}
		if ask {
			woke++
		}
		return "unpacked: 40% <b>", has
	}
	owner := &http.Cookie{Name: "dgo_session", Value: "ok"}
	if w := get(s, "n8n.localhost:8080", "/", nil, map[string]string{"Accept": "text/html"}); w.Code != http.StatusFound || woke != 0 {
		t.Fatalf("anonymous = %d (woke %d), want the sign-in and nothing started", w.Code, woke)
	}
	w := get(s, "n8n.localhost:8080", "/", owner, map[string]string{"Accept": "text/html,application/xhtml+xml"})
	if w.Code != http.StatusServiceUnavailable || woke != 1 || !strings.Contains(w.Body.String(), `http-equiv="refresh"`) ||
		!strings.Contains(w.Body.String(), "unpacked: 40% &lt;b&gt;") || w.Header().Get("Retry-After") == "" {
		t.Fatalf("the owner's page = %d (woke %d) %q", w.Code, woke, w.Body.String())
	}
	if w := get(s, "n8n.localhost:8080", "/api/x", owner, map[string]string{"Accept": "application/json"}); w.Code != http.StatusServiceUnavailable ||
		w.Header().Get("Content-Type") != "text/plain; charset=utf-8" || woke != 2 {
		t.Fatalf("the owner's API call = %d %q (woke %d)", w.Code, w.Header().Get("Content-Type"), woke)
	}
	if w := get(s, "typo.localhost:8080", "/", owner, nil); w.Code != http.StatusNotFound || woke != 2 {
		t.Fatalf("a host of no app in the machine = %d (woke %d)", w.Code, woke)
	}
	if w := get(s, "n8n.localhost:8080", "/healthz", nil, nil); w.Code != http.StatusOK || woke != 2 {
		t.Fatalf("/healthz = %d (woke %d)", w.Code, woke)
	}
	has = false
	if w := get(s, "n8n.localhost:8080", "/", owner, nil); w.Code != http.StatusNotFound || woke != 2 {
		t.Fatalf("an office with no app in its machine = %d (woke %d)", w.Code, woke)
	}
	if hits != 0 {
		t.Fatal("the console's upstream was asked for the machine's host")
	}
}

// A gated host cannot be declared without the identity service to ask.
func TestAGatedHostNeedsTheIdentityService(t *testing.T) {
	_, err := New(map[string]Route{"console.localhost": {Upstream: mustURL(t, "http://127.0.0.1:1"), Gated: true}}, "", t.Logf)
	if err == nil {
		t.Fatal("a gated host was accepted with no --auth")
	}
}

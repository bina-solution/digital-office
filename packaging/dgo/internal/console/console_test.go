package console

import (
	"bufio"
	"bytes"
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// shell lays out a minimal console as the image lays out /app: static/ (the entry, the wizard, a
// compressible script, an image), modules.yaml beside it, and the registry and peer directories.
// It returns the static directory and the environment the native side requires.
func shell(t *testing.T) (string, map[string]string) {
	t.Helper()
	root := t.TempDir()
	static := filepath.Join(root, "static")
	for name, body := range map[string]string{
		"static/index.html": "<!doctype html><title>shell</title>", "static/install.html": "<!doctype html><title>wizard</title>",
		"static/app.js": strings.Repeat("let shell = 1;\n", 60), "static/pic.png": "png", "modules.yaml": "",
		"generated/.keep": "", "peers.d/.keep": "",
	} {
		p := filepath.Join(root, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return static, map[string]string{"GENERATED_REGISTRY": filepath.Join(root, "generated"),
		"CONSOLE_PEERS_DIR": filepath.Join(root, "peers.d"), "APP_MANAGEMENT_URL": "http://127.0.0.1:9"}
}

func env(vars map[string]string, kv ...string) func(string) (string, bool) {
	m := map[string]string{}
	for k, v := range vars {
		m[k] = v
	}
	for i := 0; i+1 < len(kv); i += 2 {
		m[kv[i]] = kv[i+1]
	}
	return func(k string) (string, bool) { v, ok := m[k]; return v, ok }
}

// counted is a server whose proxy only counts what it is handed.
func counted(t *testing.T, c Config) (*Server, *int) {
	t.Helper()
	if c.Upstream == "" {
		c.Upstream = "http://127.0.0.1:9"
	}
	c.Logf = t.Logf
	s, err := New(c)
	if err != nil {
		t.Fatal(err)
	}
	proxied := new(int)
	s.proxy = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { *proxied++; w.WriteHeader(599) })
	return s, proxied
}

// TestRequestsOutsideTheProofAreTheContainers: every route this slice does not answer, every method
// but GET and HEAD, and every request shape the native code is not proven on goes to the container.
func TestRequestsOutsideTheProofAreTheContainers(t *testing.T) {
	static, vars := shell(t)
	s, proxied := counted(t, Config{Static: static, Lookup: env(vars)})
	cases := []request{
		// app.py's other routes — health, identity, the planes, the app doors
		fetch("/healthz"), fetch("/index.html"), fetch("/api/connections"),
		fetch("/api/conn/oauth/google/start"), fetch("/api/svc/drive/manifest"), fetch("/api/svc/drive/connections/x"),
		fetch("/api/anything"), fetch("/a/drive/"), fetch("/a/drive/api/files?x=1"), fetch("/a/drive"), fetch("/a/"),
		// paths werkzeug redirects or Python resolves its own way
		fetch("/sub/"), fetch("/sub//app.js"), fetch("/./app.js"), fetch("/../app.py"), fetch("/caf%C3%A9.js"), fetch("/x:y.js"),
		fetch("/back%5Cslash.js"), fetch("/tab%09.js"), fetch("/%2e%2e/secret.txt"), fetch("/a%5c..%5csecret.txt"),
		// methods
		ask("POST", "/app.js"), ask("PUT", "/healthz"), ask("DELETE", "/api/modules"), ask("OPTIONS", "/app.js"), ask("PATCH", "/x"),
		ask("POST", "/"),
		// request shapes
		fetch("/app.js", "Range", "bytes=0-9"), fetch("/app.js", "Range", ""), fetch("/app.js", "Range", "bytes=0-9", "If-Range", `"x"`),
		fetch("/app.js", "If-Modified-Since", "Monday, 13-Oct-26 10:00:00 GMT"), fetch("/app.js", "If-Modified-Since", "Mon, 13 Oct 2026 10:00:00 gmt"),
		fetch("/app.js", "If-Modified-Since", "Mon, 13 Oct 2026 10:00:00 +0000"),
		fetch("/app.js", "Accept-Encoding", "gzip", "Accept-Encoding", "deflate"), fetch("/app.js", "If-None-Match", `"a"`, "If-None-Match", `"b"`),
		fetch("/app.js", "Accept-Encoding", "deflate\xa0"), fetch("/app.js", "Accept-Encoding", "deflate;q=nan"),
		fetch("/app.js", "Accept-Encoding", "deflate;q=1_0"), fetch("/api/version", "Accept-Encoding", "gzip", "Accept-Encoding", "br"),
	}
	for _, r := range cases {
		if got := serve(s, proxied, r); got != nil {
			t.Errorf("%s %s %q: answered natively (%d) — must be the container's", r.Method, r.Path, r.Headers, got.Code)
		}
	}
	// …and what IS native stays native: a request this port is proven on is not sent anywhere
	for _, r := range []request{fetch("/"), fetch("/?next=x"), ask("HEAD", "/"), fetch("/app.js"), ask("HEAD", "/pic.png"),
		fetch("/deep/link"), fetch("/api"), fetch("/a"), fetch("/api/modules"), fetch("/api/version"),
		fetch("/app.js", "If-Range", `"x"`), fetch("/app.js", "Accept-Encoding", "gzip;q=0.5, br")} {
		if serve(s, proxied, r) == nil {
			t.Errorf("%s %s %q: proxied, must be answered here", r.Method, r.Path, r.Headers)
		}
	}
}

// TestTheContainerSeesTheRequestAsTheEdgeSentIt: from the trusted edge, the proxy is transparent —
// method, path, the query's own bytes (DSH's `??@scope/…` plugin URLs, a `;`), the Host werkzeug builds
// redirects from, the forwarding and identity headers the edge wrote, the body — and adds no
// Accept-Encoding of its own; the container's answer comes back as it was, an event stream as written.
func TestTheContainerSeesTheRequestAsTheEdgeSentIt(t *testing.T) {
	type seen struct {
		method, host, path, query, body string
		header                          http.Header
	}
	got := make(chan seen, 1)
	release := make(chan struct{})
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/a/chat/events" {
			w.Header().Set("Content-Type", "text/event-stream")
			io.WriteString(w, "data: one\n\n")
			w.(http.Flusher).Flush()
			<-release
			io.WriteString(w, "data: two\n\n")
			return
		}
		b, _ := io.ReadAll(r.Body)
		got <- seen{r.Method, r.Host, r.URL.Path, r.URL.RawQuery, string(b), r.Header.Clone()}
		w.Header()["X-Container"] = []string{"yes"}
		w.WriteHeader(http.StatusCreated)
		io.WriteString(w, "made")
	}))
	defer up.Close()
	static, vars := shell(t)
	trusted, _ := ParseTrusted("127.0.0.1, ::1")
	s, err := New(Config{Static: static, Upstream: up.URL, Trusted: trusted, Lookup: env(vars), Logf: t.Logf})
	if err != nil {
		t.Fatal(err)
	}
	front := httptest.NewServer(s)
	defer front.Close()
	client := &http.Client{Transport: &http.Transport{DisableCompression: true}}

	q := "?@scope/pkg/client.js,@x/y/client.js&rev=1;2"
	req, _ := http.NewRequest("POST", front.URL+"/a/bina/plugins/?"+q, strings.NewReader("payload"))
	req.Host = "console.localhost"
	for k, v := range map[string]string{"X-Forwarded-For": "10.0.0.1", "X-Forwarded-Proto": "https",
		"X-Forwarded-Host": "console.example", "X-Authentik-Username": "owner"} {
		req.Header.Set(k, v)
	}
	res, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	answer, _ := io.ReadAll(res.Body)
	res.Body.Close()
	in := <-got
	switch {
	case in.method != "POST" || in.path != "/a/bina/plugins/" || in.query != q || in.body != "payload":
		t.Errorf("the request changed on the way: %s %s ?%s %q", in.method, in.path, in.query, in.body)
	case in.host != "console.localhost":
		t.Errorf("Host %q, the edge sent console.localhost", in.host)
	case in.header.Get("X-Forwarded-For") != "10.0.0.1" || in.header.Get("X-Forwarded-Proto") != "https" ||
		in.header.Get("X-Forwarded-Host") != "console.example":
		t.Errorf("forwarding headers rewritten: %v", in.header)
	case in.header.Get("X-Authentik-Username") != "owner":
		t.Errorf("the trusted edge's identity header did not reach the container")
	case in.header.Get("Accept-Encoding") != "":
		t.Errorf("the proxy asked for %q itself", in.header.Get("Accept-Encoding"))
	case res.StatusCode != http.StatusCreated || string(answer) != "made" || res.Header.Get("X-Container") != "yes":
		t.Errorf("the container's answer changed: %d %q %v", res.StatusCode, answer, res.Header)
	}

	// an event stream arrives as it is written, not when it ends
	res, err = client.Get(front.URL + "/a/chat/events")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	first := make(chan string, 1)
	go func() { line, _ := bufio.NewReader(res.Body).ReadString('\n'); first <- line }()
	select {
	case line := <-first:
		if line != "data: one\n" {
			t.Errorf("first event %q", line)
		}
	case <-time.After(5 * time.Second):
		t.Error("the first event was held back until the stream ended")
	}
	close(release)
}

// TestIdentityIsBelievedOnlyFromTheTrustedProxy: a caller that is not the trusted edge cannot claim a
// user — every identity header is gone before the container (or anything here) sees the request —
// and the edge itself cannot pass on a `_` spelling, which only a client smuggling one past it writes.
func TestIdentityIsBelievedOnlyFromTheTrustedProxy(t *testing.T) {
	static, vars := shell(t)
	trusted, err := ParseTrusted("10.1.0.0/16, 192.0.2.7")
	if err != nil {
		t.Fatal(err)
	}
	var seen http.Header
	s, err := New(Config{Static: static, Upstream: "http://127.0.0.1:9", Trusted: trusted, Lookup: env(vars), Logf: t.Logf})
	if err != nil {
		t.Fatal(err)
	}
	s.proxy = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { seen = r.Header.Clone() })
	claims := map[string]string{
		"X-Authentik-Username": "owner", "X-Authentik-Groups": "admins", "X-Authentik-Jwt": "x", "X_Authentik_Username": "owner",
		"X-Dgo-From": "guest", "X-Dgo-Office": "macbook", "Remote-User": "owner", "X-Forwarded-User": "owner",
		"X-Auth-Request-Email": "o@x", "X-Webauth-User": "owner", "X-Remote-User": "owner", "X-Real-Ip": "10.0.0.1",
		"X-Forwarded-For": "10.0.0.1", "Forwarded": "for=10.0.0.1",
	}
	call := func(from string) http.Header {
		r := httptest.NewRequest("GET", "/api/connections", nil) // a route the container answers, so what reaches it is seen
		r.RemoteAddr = from
		for k, v := range claims {
			r.Header[k] = []string{v}
		}
		r.Header.Set("Accept", "application/json")
		s.ServeHTTP(httptest.NewRecorder(), r)
		return seen
	}
	for _, from := range []string{"192.0.2.1:4000", "127.0.0.1:4000", "[::1]:4000", "10.2.0.1:80"} {
		h := call(from)
		for k := range claims {
			if _, ok := h[k]; ok {
				t.Errorf("from %s: %s reached the container", from, k)
			}
		}
		if h.Get("Accept") != "application/json" {
			t.Errorf("from %s: an ordinary header was removed", from)
		}
	}
	for _, from := range []string{"10.1.2.3:4000", "192.0.2.7:1", "[::ffff:10.1.0.9]:2"} {
		h := call(from)
		for k := range claims {
			_, ok := h[k]
			if smuggled := strings.Contains(k, "_"); ok == smuggled {
				t.Errorf("from the trusted %s: %s present=%v", from, k, ok)
			}
		}
	}
}

// TestAListenerOffLoopbackNeedsATrustedProxy: only this machine may reach a console that names no
// edge; an address others can reach is refused until the edge allowed to assert identity is named.
func TestAListenerOffLoopbackNeedsATrustedProxy(t *testing.T) {
	edge, _ := ParseTrusted("172.18.0.0/16")
	for _, c := range []struct {
		listen  string
		trusted []netip.Prefix
		ok      bool
	}{
		{"127.0.0.1:8000", nil, true}, {"localhost:8000", nil, true}, {"[::1]:8000", nil, true}, {"127.9.9.9:1", nil, true},
		{":8000", nil, false}, {"0.0.0.0:8000", nil, false}, {"[::]:8000", nil, false}, {"172.18.0.1:8000", nil, false},
		{"0.0.0.0:8000", edge, true}, {"172.18.0.1:8000", edge, true}, {"no-port", nil, false},
	} {
		if err := listenAllowed(c.listen, c.trusted); (err == nil) != c.ok {
			t.Errorf("listenAllowed(%q, %v) = %v", c.listen, c.trusted, err)
		}
	}
	for _, bad := range []string{"10.0.0.0/33", "not-an-address", "10.0.0.1/8/2"} {
		if _, err := ParseTrusted(bad); err == nil {
			t.Errorf("ParseTrusted(%q) accepted", bad)
		}
	}
	p, err := ParseTrusted(" 10.0.0.9/8 ,, ::1 ")
	if err != nil || len(p) != 2 || p[0].String() != "10.0.0.0/8" || p[1].String() != "::1/128" {
		t.Errorf("ParseTrusted = %v %v", p, err)
	}
	static, _ := shell(t)
	var out bytes.Buffer
	if code := Main("", []string{"--listen", "0.0.0.0:0", "--static", static, "--upstream", "http://x"}, &out); code != 2 ||
		!strings.Contains(out.String(), "--trusted-proxy") {
		t.Errorf("Main off loopback without --trusted-proxy = %d %q", code, out.String())
	}
}

// TestTheRollbackNeedsOnlyTheContainer: DGO_CONSOLE=container reads nothing of the native side — no
// --static, no registry, no plane — so nothing of it can keep the container from being reached.
func TestTheRollbackNeedsOnlyTheContainer(t *testing.T) {
	s, proxied := counted(t, Config{Static: filepath.Join(t.TempDir(), "not-there"), Lookup: env(nil, "DGO_CONSOLE", "container")})
	for _, p := range []string{"/", "/app.js", "/healthz", "/api/version", "/api/modules", "/deep/link"} {
		if serve(s, proxied, fetch(p)) != nil {
			t.Errorf("%s answered natively under DGO_CONSOLE=container", p)
		}
	}
}

// TestTheNativeSideRefusesToGuessItsInputs: on a host, app.py's defaults name its own container
// (/app/generated, /app/peers.d, http://app-management:8080); a missing one would answer an empty rail
// or never show the wizard, without an error anywhere — so it refuses to start instead.
func TestTheNativeSideRefusesToGuessItsInputs(t *testing.T) {
	static, vars := shell(t)
	for _, name := range []string{"GENERATED_REGISTRY", "CONSOLE_PEERS_DIR", "APP_MANAGEMENT_URL"} {
		without := map[string]string{}
		for k, v := range vars {
			if k != name {
				without[k] = v
			}
		}
		if _, err := New(Config{Static: static, Upstream: "http://x", Lookup: env(without), Logf: t.Logf}); err == nil || !strings.Contains(err.Error(), name) {
			t.Errorf("without %s: New = %v", name, err)
		}
	}
	if _, err := New(Config{Static: static, Upstream: "http://x", Lookup: env(vars, "GENERATED_REGISTRY", filepath.Join(static, "app.js")),
		Logf: t.Logf}); err == nil || !strings.Contains(err.Error(), "is not a directory") {
		t.Errorf("GENERATED_REGISTRY naming a file: New = %v", err)
	}
	if _, err := New(Config{Static: static, Upstream: "http://x", Lookup: env(vars, "CONSOLE_OFFICE_TTL_S", "ten"), Logf: t.Logf}); err == nil {
		t.Error("CONSOLE_OFFICE_TTL_S=ten accepted; app.py fails to start on it")
	}
}

func TestMainRefusesWhatItCannotServe(t *testing.T) {
	t.Setenv("DGO_CONSOLE_UPSTREAM", "")
	t.Setenv("DGO_CONSOLE_TRUSTED_PROXY", "")
	t.Setenv("DGO_CONSOLE", "")
	static, _ := shell(t)
	for _, c := range []struct {
		args []string
		code int
		says string
	}{
		{nil, 2, "usage: dgo be-child console"},
		{[]string{"--static", static}, 2, "--upstream"},
		{[]string{"--static", static, "--upstream", "http://x", "extra"}, 2, "usage"},
		{[]string{"--static", static, "--upstream", "http://x", "--trusted-proxy", "10.0.0.0/99"}, 2, "neither an address nor a CIDR"},
		{[]string{"--static", filepath.Join(static, "app.js"), "--upstream", "http://x"}, 1, "is not a directory"},
		{[]string{"--static", static, "--upstream", "ftp://x"}, 1, "is not an http(s) URL"},
		{[]string{"--static", static, "--upstream", "http://x"}, 1, "GENERATED_REGISTRY is not set"},
	} {
		var out bytes.Buffer
		if code := Main("", c.args, &out); code != c.code || !strings.Contains(out.String(), c.says) {
			t.Errorf("Main(%q) = %d %q; want %d and %q", c.args, code, out.String(), c.code, c.says)
		}
	}
	// the rollback starts without --static or any of the native side's inputs
	t.Setenv("DGO_CONSOLE", "container")
	var out bytes.Buffer
	if code := Main("", []string{"--listen", "127.0.0.1:-1", "--upstream", "http://x"}, &out); code != 1 || !strings.Contains(out.String(), "listen tcp") {
		t.Errorf("Main in container mode must get as far as the listener: %d %q", code, out.String())
	}
}

func TestPlainPaths(t *testing.T) {
	for p, want := range map[string]bool{
		"app.js": true, "sub/deep.js": true, ".hidden": true, "space name.js": true, "a=b.css": true, "100%.js": true,
		"": false, "sub/": false, "a//b": false, "./a": false, "a/../b": false, "..": false, `a\b`: false, "c:x": false,
		"caf\xc3\xa9.js": false, "tab\t.js": false, "del\x7f": false,
	} {
		if plain(p) != want {
			t.Errorf("plain(%q) = %v", p, !want)
		}
	}
}

// TestShutdownWaitsForTheRequestsInFlight: a stop that arrives while a request is being answered
// lets it finish before serve returns (and dgo exits), as gunicorn's graceful_timeout does.
func TestShutdownWaitsForTheRequestsInFlight(t *testing.T) {
	inHandler, finished := make(chan struct{}), make(chan struct{})
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(inHandler)
		time.Sleep(time.Second) // a download, a proxied POST, an event stream…
		io.WriteString(w, "done")
		close(finished)
	})}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, stop := context.WithCancel(context.Background())
	go http.Get("http://" + ln.Addr().String() + "/")
	go func() { <-inHandler; stop() }()
	if err := serveUntil(ctx, srv, ln, 10*time.Second); err != nil {
		t.Fatal(err)
	}
	select {
	case <-finished:
	default:
		t.Error("serveUntil returned before the request in flight finished")
	}
}

// TestTheShellIsTheTreeReadAtStart: what is served and the digest an open page compares itself with
// come from one tree, read at start — an edit under a running server changes neither, so they cannot
// disagree (the edit is served after a restart, as an image change is after a rebuild).
func TestTheShellIsTheTreeReadAtStart(t *testing.T) {
	static, vars := shell(t)
	s, proxied := counted(t, Config{Static: static, Lookup: env(vars)})
	before := serve(s, proxied, fetch("/api/version")).Body.String()
	shellPage := serve(s, proxied, fetch("/")).Body.String()
	if err := os.WriteFile(filepath.Join(static, "app.js"), []byte("console.log('a new build')\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(static, "index.html"), []byte("<p>new"), 0o644); err != nil {
		t.Fatal(err)
	}
	if after := serve(s, proxied, fetch("/api/version")).Body.String(); after != before {
		t.Errorf("the digest moved without the served files: %s → %s", before, after)
	}
	if body := serve(s, proxied, fetch("/app.js")).Body.String(); strings.Contains(body, "a new build") {
		t.Error("an edit under the running server is served while the digest still names the old tree")
	}
	if page := serve(s, proxied, fetch("/")).Body.String(); page != shellPage || serve(s, proxied, fetch("/deep/link")).Body.String() != shellPage {
		t.Error("`/` and a deep link are not the same tree's index.html")
	}
	s2, proxied2 := counted(t, Config{Static: static, Lookup: env(vars)})
	if restarted := serve(s2, proxied2, fetch("/api/version")).Body.String(); restarted == before {
		t.Error("a restart over the edited tree must name a new shell")
	}
}

// TestALinkOutOfStaticIsNotServed: a link inside --static — a junction on Windows (no privilege
// needed), a symlink elsewhere — whose target is outside it is answered with werkzeug's 404, at the
// link and below it; a link that stays inside is served as app.py serves it.
func TestALinkOutOfStaticIsNotServed(t *testing.T) {
	static, vars := shell(t)
	outside := filepath.Join(filepath.Dir(filepath.Dir(static)), filepath.Base(filepath.Dir(static))+"-outside")
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(outside) })
	if err := os.WriteFile(filepath.Join(outside, "private.txt"), []byte("A FILE OUTSIDE --static"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(static, "inner"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(static, "inner", "kept.js"), []byte("inside"), 0o644); err != nil {
		t.Fatal(err)
	}
	link := func(target, name string) {
		dst := filepath.Join(static, name)
		var err error
		if runtime.GOOS == "windows" {
			var out []byte
			if out, err = exec.Command("cmd", "/c", "mklink", "/J", dst, target).CombinedOutput(); err != nil {
				t.Skipf("mklink /J: %v %s", err, out)
			}
			return
		}
		if err = os.Symlink(target, dst); err != nil {
			t.Skipf("symlink: %v", err)
		}
	}
	link(outside, "j")
	link(filepath.Join(static, "inner"), "alias")
	s, proxied := counted(t, Config{Static: static, Lookup: env(vars)})
	for _, p := range []string{"/j/private.txt", "/j", "/j/nothing/here"} {
		got := serve(s, proxied, fetch(p))
		if got == nil || got.Code != http.StatusNotFound || got.Body.String() != notFoundPage || strings.Contains(got.Body.String(), "OUTSIDE") {
			t.Errorf("%s through a link out of --static: %v", p, got)
		}
	}
	if got := serve(s, proxied, fetch("/alias/kept.js")); got == nil || got.Code != 200 || got.Body.String() != "inside" {
		t.Errorf("/alias/kept.js through a link that stays inside: %v", got)
	}
}

// TestHostNamesAnswerAsTheLinuxImage: on a Windows or macOS host the filesystem folds case and strips
// a trailing dot or space, and Windows has device names; the image is Linux, where none of these
// names a file — so each answers the shell's index.html here too, never another file's bytes.
func TestHostNamesAnswerAsTheLinuxImage(t *testing.T) {
	static, vars := shell(t)
	s, proxied := counted(t, Config{Static: static, Lookup: env(vars)})
	for _, p := range []string{"/APP.JS", "/App.js", "/app.js.", "/app.js%20", "/app.js...", "/NUL", "/nul", "/NUL.js", "/CON",
		"/con.txt", "/AUX", "/PRN", "/COM1", "/LPT1", "/CONIN$", "/CONOUT$", "/INDEX.HTML", "/x/..%20/app.js", "/...%20/app.js"} {
		got := serve(s, proxied, fetch(p))
		if got == nil || got.Code != 200 || got.Header().Get("Content-Disposition") != "inline; filename=index.html" {
			t.Errorf("%s: %v — the image answers its index.html", p, got)
		}
	}
}

package serve

// The second reader's probes (review-core-serve.md, rcs-probe/), kept as tests: what they found, each
// asserted as it must now be.

import (
	"bufio"
	"bytes"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// A native answer is Flask's, or the native plane steps aside: state files PyYAML refuses, keys Python
// makes one, escapes it keeps as half a character — and a state string Go and Python strip or lower
// apart, which must now be answered, and alike.
func TestReviewNativeAnswersAgreeOrStepAside(t *testing.T) {
	repo := fixture(t, office)
	o := startOracle(t, repo)
	h := &heard{status: 599}
	s := &server{repo: repo, upstream: h, log: log.New(io.Discard, "", 0)}
	bs := string(rune(92))
	const top = "schema_version: 1\napps:\n  traefik: { enabled: true }\n"
	cases := []struct {
		name, state, path string
		native            bool // must be answered here (else either way, but alike when answered)
	}{
		{"office name starts with @", top + "office:\n  name: @deer\n", "/api/office", false},
		{"office name is =", top + "office:\n  name: =\n", "/api/office", false},
		{"office name holds ': '", top + "office:\n  name: a: b\n", "/api/office", false},
		{"office name escape beyond U+10FFFF", top + "office:\n  name: \"" + bs + "U00110000\"\n", "/api/office", false},
		{"office name lone surrogate escape", top + "office:\n  name: \"" + bs + "ud800\"\n", "/api/office", false},
		{"remote entry with ': ' in a value", top + "remote:\n- office: vps1: x\n", "/api/remote", false},
		{"remote entry, surrogate-pair escape", top + "remote:\n- office: vps1\n  label: \"" + bs + "ud83d" + bs + "ude00\"\n", "/api/remote", false},
		{"remote entry, keys 1 and true", top + "remote:\n- office: vps1\n  1: x\n  true: y\n", "/api/remote", false},
		{"remote value starts with %", top + "remote:\n- office: %vps1\n", "/api/remote", false},
		{"a layer-3 app on, state with a leading \\x1c", top + "  drive: { state: \"" + bs + "x1cenabled\" }\n", "/api/office", true},
		{"state ARCH(U+0130)VED beside enabled: true", top + "  drive: { state: ARCH" + string(rune(0x130)) + "VED, enabled: true }\n", "/api/office", true},
	}
	for _, c := range cases {
		write(t, repo, map[string]string{"platform.state.yaml": c.state})
		q := exchange{Method: "GET", Path: c.path}
		before := h.count()
		got := ask(s, q)
		native := h.count() == before
		want := o.ask(t, q)
		agree := got.Status == want.Status && got.ContentType == want.ContentType && bytes.Equal(got.Body, want.Body)
		switch {
		case native && !agree:
			t.Errorf("%s: answered here, and not as app.py answers\n go:    %d %s\n flask: %d %.160s", c.name, got.Status, got.Body, want.Status, want.Body)
		case c.native && !native:
			t.Errorf("%s: handed to the container; it must be answered here", c.name)
		}
	}
}

// What the proxy hands on and what the boundary lets through, as the second reader asked it.
func TestReviewProxyAndBoundary(t *testing.T) {
	h := &heard{}
	up := httptest.NewServer(h)
	t.Cleanup(up.Close)
	s, err := newServer(t.TempDir(), up.URL, "", log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	// 1. a header named in Connection is dropped on the way — but not the door's stamp: the container
	// takes the office of a restore from it, never from the body
	ask(s, exchange{Method: "POST", Path: "/api/apps/drive/enable", Body: []byte(`{"restore": {"archive": "a.tgz", "office": "someone-else"}}`),
		ContentType: "application/json", Headers: [][2]string{{"X-DGO-Office", "macbook"}, {"Connection", "X-DGO-Office"}}})
	if got := h.last().header.Get("X-DGO-Office"); got != "macbook" {
		t.Errorf("1. the container got X-DGO-Office %q; the door wrote macbook", got)
	}
	// 2. a page served on another port of this machine posts a write, as no-cors fetch sends it
	before := h.count()
	r := exchange{Method: "POST", Path: "/api/apps/drive/uninstall", ContentType: "text/plain;charset=UTF-8",
		Headers: [][2]string{{"Origin", "http://localhost:5173"}, {"Sec-Fetch-Site", "same-site"}, {"Sec-Fetch-Mode", "no-cors"}}}.request()
	r.Host = "localhost:7071"
	rec := httptest.NewRecorder()
	s.ServeHTTP(rec, r)
	if rec.Code != http.StatusForbidden || h.count() != before {
		t.Errorf("2. a page of another origin: %d, the container heard it: %v", rec.Code, h.count() != before)
	}
	// 3. SCRIPT_NAME (gunicorn's forwarder header) is not handed on
	ask(s, exchange{Method: "POST", Path: "/zz/api/reconcile", Headers: [][2]string{{"X-DGO-Office", "macbook"}, {"SCRIPT_NAME", "/zz"}}})
	if got := h.last(); got.uri != "/zz/api/reconcile" || got.header.Get("SCRIPT_NAME") != "" {
		t.Errorf("3. the container got %s with SCRIPT_NAME %q", got.uri, got.header.Get("SCRIPT_NAME"))
	}
	// 4. the request line's target reaches the container as it was sent, a literal `#` and all — and the
	// route it names to the server is the route refused here
	q := exchange{Method: "POST", Path: "/api/x", ContentType: "application/json", Body: []byte(`{}`)}
	r = q.request()
	r.URL.Path, r.URL.RawPath, r.RequestURI = "/api/reconcile#x", "", "/api/reconcile#x"
	s.ServeHTTP(httptest.NewRecorder(), r)
	if got := h.last().uri; got != "/api/reconcile#x" {
		t.Errorf("4. /api/reconcile#x reached the container as %s", got)
	}
	before = h.count()
	r = exchange{Method: "POST", Path: "/api/x", Headers: door}.request()
	r.URL.Path, r.URL.RawPath, r.RequestURI = "/api/reconcile#x", "", "/api/reconcile#x"
	rec = httptest.NewRecorder()
	s.ServeHTTP(rec, r)
	if rec.Code != http.StatusForbidden || h.count() != before || !strings.Contains(rec.Body.String(), "does not converge") {
		t.Errorf("4. a linked POST /api/reconcile#x: %d %s, the container heard it: %v", rec.Code, rec.Body, h.count() != before)
	}
}

// rawAsk sends one request line as written — a lower-case method, a fragment, an absolute target — and
// reads the answer: status, body and Location.
func rawAsk(t *testing.T, base, method, target string, headers []string) (int, string) {
	t.Helper()
	addr := strings.TrimPrefix(base, "http://")
	c, err := net.Dial("tcp", addr)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	_ = c.SetDeadline(time.Now().Add(30 * time.Second))
	req := method + " " + target + " HTTP/1.1\r\nHost: " + addr + "\r\nConnection: close\r\nContent-Length: 0\r\n"
	for _, h := range headers {
		req += h + "\r\n"
	}
	if _, err := io.WriteString(c, req+"\r\n"); err != nil {
		t.Fatal(err)
	}
	resp, err := http.ReadResponse(bufio.NewReader(c), nil)
	if err != nil {
		return -1, "read: " + err.Error()
	}
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	return resp.StatusCode, strings.TrimSpace(string(b)) + " | Location=" + resp.Header.Get("Location")
}

// Request lines a linked caller may write for a guarded route, sent raw to app.py under Werkzeug and to
// this process in front of it: wherever app.py's router reaches a guarded view (its own refusal is the
// answer there), this process has refused the request itself, the container never asked — and every
// other line gets the container's own answer.
func TestReviewGuardPathVariants(t *testing.T) {
	repo := fixture(t, office)
	write(t, repo, map[string]string{"platform.state.yaml": "schema_version: 1\napps:\n  drive: { state: enabled }\n"})
	flask := live(t, repo)
	s, err := newServer(repo, flask, "", log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	cnt := &counting{h: s.upstream}
	s.upstream = cnt
	front := httptest.NewServer(s)
	t.Cleanup(front.Close)
	stamp := []string{"X-DGO-Office: macbook"}
	for _, v := range []struct{ method, target string }{
		{"POST", "/api/reconcile"}, {"post", "/api/reconcile"}, {"PoSt", "/api/reconcile"},
		{"POST", "/api/reconcile/"}, {"POST", "//api/reconcile"}, {"POST", "/api/%72econcile"},
		{"POST", "/api/reconcile%2F"}, {"POST", "/API/reconcile"}, {"POST", "/./api/reconcile"},
		{"POST", "/api/reconcile#x"}, {"POST", "/api/reconcile?x#y"}, {"POST", "http://127.0.0.1/api/reconcile"},
		{"POST", "/api/apps/drive/disable"}, {"post", "/api/apps/drive/disable"}, {"POST", "/api/apps/drive%2Fx/disable"},
		{"PUT", "/api/office"}, {"put", "/api/office"}, {"POST", "///api/apps/drive/archive"},
	} {
		before := cnt.n.Load()
		gs, gb := rawAsk(t, front.URL, v.method, v.target, stamp)
		reached := cnt.n.Load() > before
		fs, fb := rawAsk(t, flask, v.method, v.target, stamp)
		guarded := fs == http.StatusForbidden && strings.Contains(fb, "linked office")
		switch {
		case guarded && (reached || gs != http.StatusForbidden || gb != fb):
			t.Errorf("%s %s: app.py refuses it (%.80s); here %d, the container asked: %v (%.80s)", v.method, v.target, fb, gs, reached, gb)
		case !guarded && gs != fs:
			t.Errorf("%s %s: %d here, %d from app.py", v.method, v.target, gs, fs)
		}
	}
}

// routePath reads the path the container's server and Werkzeug route by, from the request line.
func TestRoutePathIsTheServersPath(t *testing.T) {
	for target, want := range map[string]string{
		"/api/reconcile":                     "/api/reconcile",
		"/api/reconcile#x":                   "/api/reconcile",
		"/api/office?a#b":                    "/api/office",
		"/a#b?c":                             "/a",
		"//api/reconcile":                    "/api/reconcile",
		"///api/reconcile":                   "/api/reconcile",
		"/api/%72econcile":                   "/api/reconcile",
		"/api/reconcile%2F":                  "/api/reconcile/",
		"http://127.0.0.1/api/reconcile?q#f": "/api/reconcile",
		"http://127.0.0.1":                   "/",
		"/api//reconcile":                    "/api//reconcile",
		"/api/apps/a%2Fb/room":               "/api/apps/a/b/room",
		"/./api/reconcile":                   "/./api/reconcile",
	} {
		r := httptest.NewRequest("GET", "/", nil)
		r.RequestURI = target
		if got := routePath(r); got != want {
			t.Errorf("%s: routed as %s, the server routes %s", target, got, want)
		}
	}
}

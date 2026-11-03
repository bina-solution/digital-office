package serve

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// ── the oracle: app.py itself ─────────────────────────────────────────────────────────────────────

// checkout is the repository this package sits in — the oracle is its app.py — or the test skips.
func checkout(t *testing.T) string {
	t.Helper()
	d, _ := os.Getwd()
	for {
		if _, err := os.Stat(filepath.Join(d, "platform-base", "app-management", "app.py")); err == nil {
			return d
		}
		parent := filepath.Dir(d)
		if parent == d {
			t.Skip("not inside the checkout: no platform-base/app-management/app.py above here")
		}
		d = parent
	}
}

// python finds an interpreter that imports the given modules, the way each OS has one, or the test skips.
func python(t *testing.T, modules string) []string {
	t.Helper()
	for _, c := range [][]string{{"python3"}, {"python"}, {"py", "-3"}} {
		if _, err := exec.LookPath(c[0]); err != nil {
			continue
		}
		if exec.Command(c[0], append(c[1:], "-c", "import "+modules)...).Run() == nil {
			return c
		}
	}
	t.Skip("no python with " + modules + " on PATH")
	return nil
}

// oracleCmd runs testdata/oracle.py by a python that has the modules — never writing bytecode beside
// the checkout's files.
func oracleCmd(t *testing.T, modules string, args ...string) *exec.Cmd {
	t.Helper()
	py := python(t, modules)
	cmd := exec.Command(py[0], append(append(py[1:], filepath.Join("testdata", "oracle.py")), args...)...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	return cmd
}

func appPy(t *testing.T) string {
	return filepath.Join(checkout(t), "platform-base", "app-management", "app.py")
}

// absent, as the content of a file in a case, deletes the file.
const absent = "\x00"

// fixture is a repository app.py and this package read alike: it carries the compiler (app.py imports
// platform/manager and shells out to reconcile.py), and whatever the test writes into it.
func fixture(t *testing.T, files map[string]string) string {
	t.Helper()
	repo := t.TempDir()
	compiler, _ := filepath.Glob(filepath.Join(checkout(t), "platform", "manager", "*.py"))
	copies := map[string]string{}
	for _, f := range compiler {
		b, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		copies["platform/manager/"+filepath.Base(f)] = string(b)
	}
	write(t, repo, copies)
	write(t, repo, files)
	return repo
}

// write lays files into the repository; absent deletes one.
func write(t *testing.T, repo string, files map[string]string) {
	t.Helper()
	for rel, body := range files {
		p := filepath.Join(repo, filepath.FromSlash(rel))
		if body == absent {
			if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
				t.Fatal(err)
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

// office is the catalog of the synthetic cases: two installable apps and two of the core.
var office = map[string]string{
	"apps/drive/app.json":            `{"id": "drive", "layer": 3}`,
	"apps/notes/app.json":            `{"id": "notes", "layer": 3}`,
	"platform-base/traefik/app.json": `{"id": "traefik", "layer": 1}`,
	"platform-base/console/app.json": `{"id": "console", "layer": 2}`,
}

// exchange is one request, as the oracle and this package are both asked it.
type exchange struct {
	Method      string      `json:"method"`
	Path        string      `json:"path"`
	Headers     [][2]string `json:"headers,omitempty"`
	Body        []byte      `json:"body,omitempty"`
	ContentType string      `json:"content_type,omitempty"`
	Now         int64       `json:"now,omitempty"` // the oracle's clock for this request (oracle.py Clock); 0 is the real one
}

// answer is what is compared: status, type, the bytes.
type answer struct {
	Status      int    `json:"status"`
	ContentType string `json:"content_type"`
	Body        []byte `json:"body"`
}

func (q exchange) String() string {
	return fmt.Sprintf("%s %s %v %q %q", q.Method, q.Path, q.Headers, q.ContentType, q.Body)
}

func same(t *testing.T, what string, got, want answer) {
	t.Helper()
	if got.Status != want.Status || got.ContentType != want.ContentType || !bytes.Equal(got.Body, want.Body) {
		t.Errorf("%s\n go:    %d %s %s\n flask: %d %s %s", what, got.Status, got.ContentType, got.Body,
			want.Status, want.ContentType, want.Body)
	}
}

// oracle is app.py answering through Flask's test client, in-process, one request per line. The test
// rewrites the fixture between two requests, and app.py reads its files on each, as in the office.
type oracle struct {
	in     io.WriteCloser
	out    *bufio.Reader
	stderr *lockedBuffer
}

func startOracle(t *testing.T, repo string) *oracle {
	t.Helper()
	cmd := oracleCmd(t, "yaml, flask", "client", appPy(t), repo)
	in, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	o := &oracle{in: in, out: bufio.NewReader(out), stderr: &lockedBuffer{}}
	cmd.Stderr = o.stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { in.Close(); _ = cmd.Wait() })
	return o
}

func (o *oracle) ask(t *testing.T, q exchange) answer {
	t.Helper()
	line, _ := json.Marshal(q)
	if _, err := o.in.Write(append(line, '\n')); err != nil {
		t.Fatalf("the oracle is gone: %v\n%s", err, o.stderr)
	}
	got, err := o.out.ReadBytes('\n')
	if err != nil {
		t.Fatalf("the oracle stopped answering: %v\n%s", err, o.stderr)
	}
	var a answer
	if err := json.Unmarshal(got, &a); err != nil {
		t.Fatalf("the oracle answered %q: %v", got, err)
	}
	return a
}

// live is app.py served by Werkzeug on a free port of this machine: app-management's container, as
// far as anything sent through the proxy can tell. Its base URL.
func live(t *testing.T, repo string) string {
	t.Helper()
	cmd := oracleCmd(t, "yaml, flask", "serve", appPy(t), repo)
	out, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	errb := &lockedBuffer{}
	cmd.Stderr = errb
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
	port := make(chan string, 1)
	go func() {
		line, _ := bufio.NewReader(out).ReadString('\n')
		port <- strings.TrimSpace(line)
	}()
	select {
	case p := <-port:
		if p == "" {
			t.Fatalf("app.py did not start:\n%s", errb)
		}
		return "http://127.0.0.1:" + p
	case <-time.After(time.Minute):
		t.Fatalf("app.py did not start within a minute:\n%s", errb)
	}
	return ""
}

// lockedBuffer collects what a child process or a logger writes, for a failure message.
type lockedBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuffer) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}

func (l *lockedBuffer) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.String()
}

// ── this package, asked the same ─────────────────────────────────────────────────────────────────

// request is what a caller on this machine sends: from loopback, addressed to it.
func (q exchange) request() *http.Request {
	r := httptest.NewRequest(q.Method, q.Path, bytes.NewReader(q.Body))
	r.RemoteAddr, r.Host = "127.0.0.1:50000", "127.0.0.1:7071"
	for _, h := range q.Headers {
		r.Header.Add(h[0], h[1])
	}
	if q.ContentType != "" {
		r.Header.Set("Content-Type", q.ContentType)
	}
	return r
}

func ask(h http.Handler, q exchange) answer {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, q.request())
	return answer{Status: rec.Code, ContentType: rec.Header().Get("Content-Type"), Body: rec.Body.Bytes()}
}

// nativeOnly is the native mode with a container that must not be asked: these tests compare the
// native answer, and one that fell back to the container would compare the container's instead.
func nativeOnly(t *testing.T, repo string) *server {
	never := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Errorf("%s %s reached the container: it must be answered natively", r.Method, r.URL)
		w.WriteHeader(http.StatusTeapot)
	})
	return &server{repo: repo, upstream: never, log: log.New(io.Discard, "", 0)}
}

// heard is a container that keeps what reaches it and answers with what it is given (299 by default).
type heard struct {
	mu     sync.Mutex
	reqs   []heardReq
	status int
	header http.Header
	body   []byte
}

type heardReq struct {
	method, uri, host string
	header            http.Header
	body              []byte
}

func (h *heard) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	b, _ := io.ReadAll(r.Body)
	h.mu.Lock()
	h.reqs = append(h.reqs, heardReq{r.Method, r.RequestURI, r.Host, r.Header.Clone(), b})
	h.mu.Unlock()
	for k, vs := range h.header {
		w.Header()[k] = vs
	}
	if h.status == 0 {
		w.WriteHeader(299)
	} else {
		w.WriteHeader(h.status)
	}
	_, _ = w.Write(h.body)
}

func (h *heard) count() int { h.mu.Lock(); defer h.mu.Unlock(); return len(h.reqs) }

func (h *heard) last() heardReq { h.mu.Lock(); defer h.mu.Unlock(); return h.reqs[len(h.reqs)-1] }

// counting counts what a handler is asked.
type counting struct {
	n atomic.Int64
	h http.Handler
}

func (c *counting) ServeHTTP(w http.ResponseWriter, r *http.Request) { c.n.Add(1); c.h.ServeHTTP(w, r) }

var door = [][2]string{{"X-DGO-Office", "macbook"}} // what the link's door stamps on a request it delivers

// ── the route table is G85's ─────────────────────────────────────────────────────────────────────

// TestTheRouteTableIsG85s holds the table to the gate's own enumeration of app.py: the same routes in
// the same order under the same method, and a refusal of a linked caller exactly where the gate finds
// one. A route added to app.py fails this until it is here — answered, refused or handed on.
func TestTheRouteTableIsG85s(t *testing.T) {
	gate := filepath.Join(checkout(t), "scripts", "refactor", "link-write-guard-lint.py")
	out, err := oracleCmd(t, "ast", "routes", gate).Output() // the gate needs nothing beyond the standard library
	if err != nil {
		t.Fatalf("G85's enumeration: %v", err)
	}
	var g85 []struct {
		Func    string   `json:"func"`
		Rule    string   `json:"rule"`
		Methods []string `json:"methods"`
		Guarded bool     `json:"guarded"`
	}
	if err := json.Unmarshal(out, &g85); err != nil {
		t.Fatal(err)
	}
	if len(g85) != len(routes) {
		t.Fatalf("G85 enumerates %d routes of app.py, the table holds %d:\n%s", len(g85), len(routes), out)
	}
	refused := 0
	for i, g := range g85 {
		rt := routes[i]
		if g.Func != rt.fn || g.Rule != rt.rule || len(g.Methods) != 1 || g.Methods[0] != rt.method || g.Guarded != (rt.linked != "") {
			t.Errorf("route %d: G85 has %s %v %s guarded=%v; the table has %s %s %s refusal=%q", i, g.Func, g.Methods,
				g.Rule, g.Guarded, rt.fn, rt.method, rt.rule, rt.linked)
		}
		if rt.linked != "" {
			refused++
		}
	}
	t.Logf("%d routes, %d of them refusing a linked caller — G85's enumeration, route for route", len(routes), refused)
}

// ── the native answers are Flask's ────────────────────────────────────────────────────────────────

// TestNativeAnswersAreFlasks asks app.py and this package the native routes on one repository, case
// after case, and requires the same status, type and bytes: sorted keys, \u escapes, and Python's
// str() and repr() of every value included.
func TestNativeAnswersAreFlasks(t *testing.T) {
	repo := fixture(t, office)
	o := startOracle(t, repo)
	s := nativeOnly(t, repo)
	const apps = "schema_version: 1\napps:\n"
	cases := []struct{ name, state string }{
		{"a checkout with no state file", absent},
		{"core apps only: not installed", apps + "  traefik: { enabled: true }\n  console: { state: enabled, by: cli }\n"},
		{"a layer-3 app switched on", apps + "  traefik: { enabled: true }\n  drive: { state: enabled, by: user }\n"},
		{"the legacy form", apps + "  notes: { enabled: true }\n"},
		{"off, archived, unknown, a core app on", apps + "  drive: { state: archived }\n  notes: { enabled: false }\n" +
			"  ghost: { state: enabled }\n  traefik: { state: enabled }\n"},
		{"a state read as the compiler reads it", apps + "  drive: { state: ' Enabled ' }\n"},
		{"an entry app.py cannot read, after the one that answers", apps + "  drive: { state: enabled }\n  notes: { state: 5 }\n"},
		{"no apps at all", "schema_version: 1\n"},
		{"an empty file", ""},
		{"line breaks of three kinds: CR, CR LF and LF", "schema_version: 1\rapps:\r\n  drive: { state: enabled }\noffice:\r  name: x\r"},
		{"the wizard's record", apps + "  traefik: { enabled: true }\noffice:\n  name: הלשכה בחיפה\n  animal: deer\n  hue: lime\n" +
			"  terms_version: '2026-10-09.1'\n  terms_accepted_at: '2026-10-09T18:00:00Z'\n  installed_at: '2026-10-09T18:01:00Z'\n"},
		{"what str() makes of a record", apps + "  traefik: { enabled: true }\noffice:\n  name: 5\n  animal: true\n  hue: 1.0\n" +
			"  terms_version: .inf\n  terms_accepted_at: null\n  installed_at: ''\n  colour: red\n"},
		{"installed_at: false is a signature (str(False) is not empty)", apps + "  traefik: { enabled: true }\noffice:\n  installed_at: false\n"},
		{"an office block that is not a mapping", apps + "  drive: { enabled: true }\noffice: [a, b]\n"},
		{"the remote block, every kind of value", apps + "remote:\n- office: vps1\n  label: { he: שרת פיתוח, en: \"dev 🐘\" }\n" +
			"  fetched: 1791129653\n  weight: 1.5\n  zero: -0.0\n  big: 1.0e+20\n  never: .nan\n  far: -.inf\n  on: yes\n" +
			"  none: ~\n  80: a numeric key\n  escapes: \"a\\x7fb\\x85c\\Ld\\te\"\n  apps:\n  - { app: indox, alias: incoming, port: 8080 }\n  - []\n"},
		{"a remote block that is not a list", apps + "remote: { office: vps1 }\n"},
		// these add manifests, so they come last. A core-shipped layer-3 app (`"core": true`, DGO-1090) is no
		// sign of a set-up office; one whose `core` is not exactly true still is.
		{"a core-shipped app alone, switched on", apps + "  extend: { state: enabled }\n"},
		{"a core-shipped app beside one whose core is not true", apps + "  extend: { state: enabled }\n  almost: { state: enabled }\n"},
		{"a core-shipped app beside one whose core is 1", apps + "  extend: { state: enabled }\n  one: { state: enabled }\n"},
		// app.py finds manifests with glob, which skips a hidden directory
		{"an app in a hidden directory, switched on", apps + "  .hidden: { state: enabled }\n"},
	}
	n := 0
	for _, c := range cases {
		write(t, repo, map[string]string{"platform.state.yaml": c.state})
		if strings.Contains(c.state, "extend:") {
			write(t, repo, map[string]string{
				"apps/extend/app.json": `{"id": "extend", "layer": 3, "core": true}`,
				"apps/almost/app.json": `{"id": "almost", "layer": 3, "core": "yes"}`,
				"apps/one/app.json":    `{"id": "one", "layer": 3, "core": 1}`,
			})
		}
		if strings.Contains(c.state, ".hidden") {
			write(t, repo, map[string]string{"apps/.hidden/app.json": `{"id": ".hidden", "layer": 3}`})
		}
		qs := []exchange{
			{Method: "GET", Path: "/api/office"},
			{Method: "GET", Path: "/api/office", Headers: door}, // a linked office reads the record too
			{Method: "GET", Path: "/healthz"},
		}
		if c.state != absent {
			qs = append(qs, exchange{Method: "GET", Path: "/api/remote"}) // with no file it is app.py's 500
		}
		for _, q := range qs {
			same(t, c.name+": "+q.String(), ask(s, q), o.ask(t, q))
			n++
		}
	}
	t.Logf("%d answers on %d states of the office, each byte-identical to Flask's", n, len(cases))
}

// A phone's office root (DGO-1090): no checkout, no compiler, no registry — only the core's state file
// and the core apps' manifests (the marker is main.go's, which finds the root) — and /api/office is
// answered from it, the container never asked. A fresh
// core office is not installed: its extensions are `core`, so the install wizard is its first screen.
func TestAnOfficeRootAnswersNatively(t *testing.T) {
	repo := t.TempDir()
	write(t, repo, map[string]string{
		".dgo-office-root":               "dgo office root 1\n",
		"platform.state.yaml":            "schema_version: 1\napps:\n  console: { enabled: true }\n  dgo-extend: { enabled: true }\n",
		"platform-base/console/app.json": `{"id": "console", "layer": 2}`,
		"apps/dgo-extend/app.json":       `{"id": "dgo-extend", "layer": 3, "core": true}`,
	})
	a := ask(nativeOnly(t, repo), exchange{Method: "GET", Path: "/api/office"})
	if a.Status != http.StatusOK || !strings.Contains(string(a.Body), `"installed":false`) {
		t.Fatalf("/api/office from an office root = %d %s, want 200 and not installed", a.Status, a.Body)
	}
}

// TestTheOfficeAsItIsAnswersAsFlask asks the same of this checkout's own catalog and state file.
func TestTheOfficeAsItIsAnswersAsFlask(t *testing.T) {
	root := checkout(t)
	files := map[string]string{}
	for _, g := range []string{"apps/*/app.json", "platform-base/*/app.json", "platform.state.yaml"} {
		m, _ := filepath.Glob(filepath.Join(root, filepath.FromSlash(g)))
		for _, f := range m {
			b, err := os.ReadFile(f)
			if err != nil {
				t.Fatal(err)
			}
			rel, _ := filepath.Rel(root, f)
			files[filepath.ToSlash(rel)] = string(b)
		}
	}
	repo := fixture(t, files)
	o := startOracle(t, repo)
	s := nativeOnly(t, repo)
	qs := []exchange{{Method: "GET", Path: "/api/office"}}
	if _, ok := files["platform.state.yaml"]; ok {
		qs = append(qs, exchange{Method: "GET", Path: "/api/remote"})
	}
	for _, q := range qs {
		got := ask(s, q)
		same(t, "this office: "+q.String(), got, o.ask(t, q))
		t.Logf("%s on this checkout: %d, %d bytes, identical to Flask's", q.Path, got.Status, len(got.Body))
	}
}

// ── the refusals are app.py's ─────────────────────────────────────────────────────────────────────

// TestEveryLinkRefusalIsFlasks sends every route that refuses a linked caller what a linked caller
// sends — the door's header — and requires app.py's own 403, byte for byte, from this package alone:
// the container is never asked. Then the spellings WSGI reads as the same header, and the bodies with
// which enable is a plain switch-on.
func TestEveryLinkRefusalIsFlasks(t *testing.T) {
	repo := fixture(t, office)
	write(t, repo, map[string]string{"platform.state.yaml": "schema_version: 1\napps:\n  drive: { state: enabled }\n"})
	o := startOracle(t, repo)
	s := nativeOnly(t, repo)
	bodies := map[string]string{"api_remote_put": `{"remote": []}`, "api_office_put": `{"name": "x"}`, "api_move": `{"to": "vps1"}`}
	n := 0
	for _, rt := range routes {
		if rt.linked == "" {
			continue
		}
		for _, aid := range []string{"drive", "traefik", "nope"} { // installable, core, unknown: the refusal comes first
			q := exchange{Method: rt.method, Path: strings.ReplaceAll(rt.rule, "<aid>", aid), Headers: door}
			if b, ok := bodies[rt.fn]; ok {
				q.Body, q.ContentType = []byte(b), "application/json"
			}
			same(t, rt.fn+": "+q.String(), ask(s, q), o.ask(t, q))
			n++
			if !strings.Contains(rt.rule, "<aid>") {
				break
			}
		}
	}
	for _, h := range [][][2]string{
		{{"x-dgo-office", "macbook"}},
		{{"X_DGO_Office", "macbook"}},                // the same header to WSGI
		{{"X-DGO-Office", ""}, {"X-DGO-Office", ""}}, // two empty copies join into a value
	} {
		q := exchange{Method: "POST", Path: "/api/apps/drive/disable", Headers: h}
		same(t, "header spelling: "+q.String(), ask(s, q), o.ask(t, q))
		n++
	}
	for _, b := range []struct{ ct, body string }{
		{"", ""},
		{"application/json", "   "},
		{"application/json", "{}"},
		{"application/json", `{"restore": null}`},
		{"application/json", `{"restore": "x"}`},
		{"application/json", `{"restore": []}`},
		{"application/json", "[]"},
		{"application/json", "0"},
		{"application/json", `""`},
		{"application/json", "false"},
		{"application/json", "null"},
		{"text/plain", `{"restore": {"archive": "a.tgz"}}`}, // not typed JSON: Flask does not read it
		{"", `{"restore": {"archive": "a.tgz"}}`},
		{"Application/JSON; charset=utf-8", `{"restore": 1}`},
		{"application/vnd.dgo+json", `{"restore": 1}`},
	} {
		q := exchange{Method: "POST", Path: "/api/apps/drive/enable", Headers: door, Body: []byte(b.body), ContentType: b.ct}
		same(t, "a plain switch-on: "+q.String(), ask(s, q), o.ask(t, q))
		n++
	}
	t.Logf("%d refusals of a linked caller, each app.py's own, none of them asked of the container", n)
}

// TestWhatTheGuardCannotDecideIsTheContainers: enable with an object `restore` is a move placing an
// app here — the peer's business — and bytes that Go and Python could read apart are Python's to read.
// Those reach the container, the body intact; so does a caller that did not come over a link.
func TestWhatTheGuardCannotDecideIsTheContainers(t *testing.T) {
	h := &heard{}
	s := &server{repo: t.TempDir(), upstream: h, log: log.New(io.Discard, "", 0)}
	reach := func(what string, q exchange) {
		t.Helper()
		before := h.count()
		if a := ask(s, q); a.Status != 299 || h.count() != before+1 {
			t.Errorf("%s: answered %d here; the container must decide", what, a.Status)
			return
		}
		if got := h.last().body; !bytes.Equal(got, q.Body) {
			t.Errorf("%s: the container got %q, not the body sent", what, got)
		}
	}
	for _, b := range []string{
		`{"restore": {"archive": "a.tgz"}}`, // a move placing an app here
		`{"restore": {}}`,                   // app.py itself refuses it, in its own words (400)
		`[1]`, `"x"`, `NaN`,                 // truthy and not an object: app.py fails on it
		`{not json`,                       // Go cannot read it; what Python makes of it is Python's answer
		"\xef\xbb\xbf" + `{"restore": 1}`, // a BOM, which Python reads past
		`{"restore": 1}` + strings.Repeat(" ", maxGuardBody), // more than the guard reads
	} {
		q := exchange{Method: "POST", Path: "/api/apps/drive/enable", Headers: door, Body: []byte(b), ContentType: "application/json"}
		reach(fmt.Sprintf("enable %.40q", b), q)
	}
	twoTypes := append(append([][2]string{}, door...), [2]string{"Content-Type", "text/plain"}, [2]string{"Content-Type", "application/json"})
	reach("enable with two Content-Types", exchange{Method: "POST", Path: "/api/apps/drive/enable", Headers: twoTypes, Body: []byte(`{"restore": 1}`)})
	reach("a caller that did not come over a link", exchange{Method: "POST", Path: "/api/reconcile", Body: []byte(`{}`), ContentType: "application/json"})
	reach("one empty header, which is none to Flask", exchange{Method: "POST", Path: "/api/reconcile",
		Headers: [][2]string{{"X-DGO-Office", ""}, {"X-DGO-Request", "dgo-test"}}})
	reach("a route whose refusal the container makes", exchange{Method: "POST", Path: "/api/catalog/preview", Headers: door, Body: []byte(`{}`)})
}

// ── the container: unchanged, and the whole of the rollback ───────────────────────────────────────

// TestTheProxyChangesNothing sends a request with everything a caller may put in one through the
// proxy to a container that keeps it: the method, the path as encoded, the query verbatim (the
// console's `??` lesson), every header — none added, the forwarding ones left as they came — and the
// body. The answer comes back the same way: status, headers, body.
func TestTheProxyChangesNothing(t *testing.T) {
	h := &heard{status: 207, header: http.Header{"Content-Type": {"text/x-test"}, "Set-Cookie": {"s=1"}, "X-Said": {"a", "b"}},
		body: []byte("the container's own bytes\n")}
	up := httptest.NewServer(h)
	t.Cleanup(up.Close)
	s, err := newServer(t.TempDir(), up.URL, "", log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	// a `;` and a bad escape too: Go's proxy drops a parameter it cannot parse unless told otherwise
	const uri = "/api/catalog/preview?ref=a%2Fb&q=??@scope/pkg/client.js,@x/y.js&rev=1&t=a;b&p=%zz"
	sent := [][2]string{{"X-DGO-Office", "macbook"}, {"X-Authentik-Username", "owner"}, {"X-Forwarded-Prefix", "/a/app-management"},
		{"X-Forwarded-For", "10.0.0.1"}, {"Cookie", "a=b"}}
	// …and what is not handed on: names with `_` (gunicorn takes SCRIPT_NAME and PATH_INFO from a trusted
	// forwarder), while a Connection naming the link's stamp leaves the stamp in place
	withheld := [][2]string{{"SCRIPT_NAME", "/zz"}, {"PATH_INFO", "/api/reconcile"}, {"X_DGO_Office", "x"}, {"Connection", "X-DGO-Office"}}
	a := ask(s, exchange{Method: "POST", Path: uri, Headers: append(append([][2]string{}, sent...), withheld...),
		Body: []byte(`{"ref": "x"}`), ContentType: "application/json"})
	got := h.last()
	if got.method != "POST" || got.uri != uri || string(got.body) != `{"ref": "x"}` {
		t.Errorf("the container got %s %s %q", got.method, got.uri, got.body)
	}
	for _, kv := range append(sent, [2]string{"Content-Type", "application/json"}) {
		if v := got.header.Values(kv[0]); len(v) != 1 || v[0] != kv[1] {
			t.Errorf("%s reached the container as %q, sent as %q", kv[0], v, kv[1])
		}
	}
	for k := range got.header {
		if strings.Contains(k, "_") {
			t.Errorf("%s reached the container", k)
		}
	}
	for _, added := range []string{"X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "Accept-Encoding", "User-Agent"} {
		if v, ok := got.header[added]; ok {
			t.Errorf("the proxy added %s: %q", added, v)
		}
	}
	if got.host != strings.TrimPrefix(up.URL, "http://") {
		t.Errorf("the container was addressed as %q, not by its own name", got.host)
	}
	if a.Status != 207 || a.ContentType != "text/x-test" || string(a.Body) != "the container's own bytes\n" {
		t.Errorf("the answer came back as %d %s %q", a.Status, a.ContentType, a.Body)
	}
	rec := httptest.NewRecorder()
	s.ServeHTTP(rec, exchange{Method: "GET", Path: "/api/apps/a%2Fb/room"}.request())
	if rec.Header().Get("Set-Cookie") != "s=1" || strings.Join(rec.Header().Values("X-Said"), ",") != "a,b" {
		t.Errorf("the container's headers came back as %v", rec.Header())
	}
	if got := h.last().uri; got != "/api/apps/a%2Fb/room" {
		t.Errorf("an encoded path reached the container as %s", got)
	}
}

// TestAContainerThatDoesNotAnswerIsSaidSo: a 502, in the plane's own shape, naming where it looked.
func TestAContainerThatDoesNotAnswerIsSaidSo(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	gone := "http://" + ln.Addr().String()
	ln.Close()
	s, err := newServer(t.TempDir(), gone, "", log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	a := ask(s, exchange{Method: "GET", Path: "/api/apps"})
	if a.Status != http.StatusBadGateway || a.ContentType != "application/json" || !strings.Contains(string(a.Body), "did not answer at "+gone) {
		t.Fatalf("an absent container: %d %s %s", a.Status, a.ContentType, a.Body)
	}
}

// TestTheRollbackHandsEveryRouteToTheContainer: BBOX_CONTROL_PLANE=container — the native routes and
// the link refusals included; this process then answers nothing of its own but its boundary.
func TestTheRollbackHandsEveryRouteToTheContainer(t *testing.T) {
	h := &heard{}
	s := &server{repo: t.TempDir(), container: true, upstream: h, log: log.New(io.Discard, "", 0)}
	for i, q := range []exchange{
		{Method: "GET", Path: "/healthz"},
		{Method: "GET", Path: "/api/office"},
		{Method: "GET", Path: "/api/remote"},
		{Method: "POST", Path: "/api/reconcile", Headers: door},
		{Method: "POST", Path: "/api/apps/drive/enable", Headers: door},
	} {
		if a := ask(s, q); a.Status != 299 || h.count() != i+1 {
			t.Errorf("%s: answered %d here under the rollback", q, a.Status)
		}
	}
}

// TestThroughTheProcessAnswersAreTheContainers puts app.py behind this process as its container, live,
// and asks both the same requests: through the process an answer is the container's own, byte for
// byte — for every route it hands on, for what its readers cannot vouch for, and under
// BBOX_CONTROL_PLANE=container for every route at all; and a native answer is the same answer too.
func TestThroughTheProcessAnswersAreTheContainers(t *testing.T) {
	repo := fixture(t, office)
	write(t, repo, map[string]string{"platform.state.yaml": "schema_version: 1\napps:\n  traefik: { enabled: true }\n  drive: { state: enabled }\n"})
	flask := live(t, repo)
	logs := &lockedBuffer{}
	front := map[string]string{}
	counter := map[string]*counting{}
	for _, plane := range []string{"native", "container"} {
		s, err := newServer(repo, flask, plane, log.New(logs, "", 0))
		if err != nil {
			t.Fatal(err)
		}
		counter[plane] = &counting{h: s.upstream}
		s.upstream = counter[plane]
		srv := httptest.NewServer(s)
		t.Cleanup(srv.Close)
		front[plane] = srv.URL
	}
	client := &http.Client{Transport: &http.Transport{}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	over := func(base string, q exchange) (answer, string) {
		t.Helper()
		req, err := http.NewRequest(q.Method, base+q.Path, bytes.NewReader(q.Body))
		if err != nil {
			t.Fatal(err)
		}
		for _, h := range q.Headers {
			req.Header.Add(h[0], h[1])
		}
		if q.ContentType != "" {
			req.Header.Set("Content-Type", q.ContentType)
		}
		resp, err := client.Do(req)
		if err != nil {
			t.Fatalf("%s: %v", q, err)
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		return answer{resp.StatusCode, resp.Header.Get("Content-Type"), b}, resp.Header.Get("Allow") + "|" + resp.Header.Get("Location")
	}
	compare := func(plane string, q exchange, native bool) {
		t.Helper()
		before := counter[plane].n.Load()
		want, wantHead := over(flask, q)
		got, gotHead := over(front[plane], q)
		same(t, plane+": "+q.String(), got, want)
		if gotHead != wantHead {
			t.Errorf("%s: %s: Allow|Location %q, the container's %q", plane, q, gotHead, wantHead)
		}
		if reached := counter[plane].n.Load() > before; reached != (plane == "container" || !native) {
			t.Errorf("%s: %s: reached the container: %v", plane, q, reached)
		}
	}
	restore, empty := []byte(`{"restore": {"archive": "a.tgz"}}`), []byte(`{}`)
	steps := []struct {
		q      exchange
		native bool
	}{
		{exchange{Method: "GET", Path: "/healthz"}, true},
		{exchange{Method: "GET", Path: "/api/office"}, true},
		{exchange{Method: "GET", Path: "/api/office", Headers: door}, true},
		{exchange{Method: "GET", Path: "/api/remote"}, true},
		{exchange{Method: "POST", Path: "/api/reconcile", Headers: door}, true},
		{exchange{Method: "PUT", Path: "/api/office", Headers: door, Body: []byte(`{"name": "x"}`), ContentType: "application/json"}, true},
		{exchange{Method: "POST", Path: "/api/apps/drive/enable", Headers: door}, true},
		{exchange{Method: "GET", Path: "/api/apps"}, false},
		{exchange{Method: "GET", Path: "/readyz"}, false},
		{exchange{Method: "GET", Path: "/api/catalog"}, false},
		{exchange{Method: "GET", Path: "/api/apps/drive/job"}, false},
		{exchange{Method: "POST", Path: "/api/apps/drive/enable", Body: empty, ContentType: "application/json"}, false},    // no docker engine here: app.py's 503
		{exchange{Method: "POST", Path: "/api/apps/traefik/disable", Body: empty, ContentType: "application/json"}, false}, // a core app: its 403
		{exchange{Method: "POST", Path: "/api/apps/nope/disable", Body: empty, ContentType: "application/json"}, false},    // no such app: its 404
		{exchange{Method: "POST", Path: "/api/apps/drive/enable", Headers: [][2]string{{"X-DGO-Office", "NOT AN OFFICE"}},
			Body: restore, ContentType: "application/json"}, false}, // an invalid office on the link: app.py's 400
		{exchange{Method: "POST", Path: "/api/apps/drive/enable", Headers: door, Body: restore, ContentType: "application/json"}, false},
		{exchange{Method: "POST", Path: "/api/apps/drive/enable", Headers: door, Body: []byte(`[1]`), ContentType: "application/json"}, false},
		{exchange{Method: "POST", Path: "/api/apps/drive/enable", Headers: door, Body: []byte(`{not json`), ContentType: "application/json"}, false},
		{exchange{Method: "POST", Path: "/api/catalog/preview", Headers: door, Body: []byte(`{}`), ContentType: "application/json"}, false},
		{exchange{Method: "GET", Path: "/"}, false},
		{exchange{Method: "GET", Path: "/app.js"}, false},
		{exchange{Method: "GET", Path: "/nope"}, false},
		{exchange{Method: "POST", Path: "/api/apps", Body: empty, ContentType: "application/json"}, false}, // a method app.py does not take: 405
		{exchange{Method: "POST", Path: "//api/reconcile", Headers: door}, true},                           // Werkzeug folds the slashes: refused here too
	}
	for _, plane := range []string{"native", "container"} {
		for _, st := range steps {
			compare(plane, st.q, st.native)
		}
	}
	// what the native readers cannot vouch for is the container's, and its answer is the one given
	const state = "platform.state.yaml"
	for _, c := range []struct {
		name  string
		files map[string]string
		path  string
	}{
		{"a state file that is not a mapping", map[string]string{state: "- a\n- b\n"}, "/api/office"},
		{"a state file that is not a mapping", map[string]string{state: "- a\n- b\n"}, "/api/remote"},
		{"apps: that is not a mapping", map[string]string{state: "schema_version: 1\napps: [drive]\n"}, "/api/office"},
		{"an entry app.py cannot read, reached first", map[string]string{state: "schema_version: 1\napps:\n  notes: { state: 5 }\n  drive: { state: enabled }\n"}, "/api/office"},
		{"no state file", map[string]string{state: absent}, "/api/remote"},
		{"a manifest the compiler refuses", map[string]string{state: "schema_version: 1\napps:\n  drive: { state: enabled }\n",
			"apps/odd/app.json": `{"id": "other", "layer": 3}`}, "/api/office"},
	} {
		write(t, repo, c.files)
		compare("native", exchange{Method: "GET", Path: c.path}, false)
	}
	// what the one reader now reads as Python does is answered here — and Flask's answer is the same: a
	// record field holding a list, spelled as office_block()'s str() spells it, and the anchors yamlish
	// reads as safe_dump writes them (the console's registry carries one per linked-office tile); the
	// manifest the compiler refuses is gone again, so the catalog loads
	for _, c := range []struct{ state, path string }{
		{"schema_version: 1\noffice:\n  name: [a, b]\n", "/api/office"},
		{"schema_version: 1\napps: &a\n  drive: { state: enabled }\n", "/api/office"},
		{"schema_version: 1\nremote: &r []\n", "/api/remote"},
	} {
		write(t, repo, map[string]string{state: c.state, "apps/odd/app.json": absent})
		compare("native", exchange{Method: "GET", Path: c.path}, true)
	}
	if n := strings.Count(logs.String(), "answered by the container"); n != 6 {
		t.Errorf("%d fallbacks said in the log, want 6:\n%s", n, logs)
	}
	t.Logf("%d requests in each plane and 6 reads the native readers do not vouch for: every answer through the process is app.py's own", len(steps))
}

// ── the boundary ──────────────────────────────────────────────────────────────────────────────────

// TestTheBoundary: app-management is published on no port; this process is on the host's loopback,
// which every browser tab reaches. Refused, in both planes and before any route: a caller from another
// address, a request for another host (DNS rebinding), a page of another site (cross-site request
// forgery). This machine's own callers, by any of its names, are answered.
func TestTheBoundary(t *testing.T) {
	for _, plane := range []bool{false, true} {
		h := &heard{}
		s := &server{repo: t.TempDir(), container: plane, upstream: h, log: log.New(io.Discard, "", 0)}
		for _, c := range []struct {
			name string
			edit func(*http.Request)
			want string
		}{
			{"a caller from another address", func(r *http.Request) { r.RemoteAddr = "192.0.2.1:1234" }, "this machine only"},
			{"an IPv6 caller from elsewhere", func(r *http.Request) { r.RemoteAddr = "[2001:db8::1]:1234" }, "this machine only"},
			{"a request for another host", func(r *http.Request) { r.Host = "rebound.example:7071" }, "addressed to this machine"},
			{"a page of another site", func(r *http.Request) { r.Header.Set("Origin", "https://evil.example") }, "no page but its own"},
			{"a page with no origin of its own", func(r *http.Request) { r.Header.Set("Origin", "null") }, "no page but its own"},
			{"a page on another port of this machine", func(r *http.Request) { r.Header.Set("Origin", "http://localhost:5173") }, "no page but its own"},
			{"this machine by another name", func(r *http.Request) { r.Header.Set("Origin", "http://localhost:7071") }, "no page but its own"},
			{"a cross-site fetch", func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "cross-site") }, "no page but its own"},
			{"a same-site fetch", func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "same-site") }, "no page but its own"},
			{"a form's post", func(r *http.Request) { r.Header.Set("Content-Type", "application/x-www-form-urlencoded") }, "as JSON"},
			{"a no-cors text post", func(r *http.Request) { r.Header.Set("Content-Type", "text/plain;charset=UTF-8") }, "as JSON"},
			{"a post with no type", func(r *http.Request) { r.Header.Del("Content-Type") }, "as JSON"},
			{"a lower-case method", func(r *http.Request) { r.Method = "post"; r.Header.Del("Content-Type") }, "as JSON"},
		} {
			r := exchange{Method: "POST", Path: "/api/apps/drive/uninstall", ContentType: "application/json"}.request()
			c.edit(r)
			rec := httptest.NewRecorder()
			s.ServeHTTP(rec, r)
			if rec.Code != http.StatusForbidden || !strings.Contains(rec.Body.String(), c.want) || h.count() != 0 {
				t.Errorf("container=%v, %s: %d %s (the container heard %d)", plane, c.name, rec.Code, rec.Body, h.count())
			}
		}
		for _, c := range []struct {
			name string
			edit func(*http.Request)
		}{
			{"a call on this machine", func(*http.Request) {}},
			{"by the name localhost", func(r *http.Request) { r.Host = "localhost:7071" }},
			{"over IPv6", func(r *http.Request) { r.RemoteAddr, r.Host = "[::1]:5555", "[::1]:7071" }},
			{"a page of this listener's own origin", func(r *http.Request) {
				r.Header.Set("Origin", "http://127.0.0.1:7071")
				r.Header.Set("Sec-Fetch-Site", "same-origin")
			}},
			{"a page of its own origin by name", func(r *http.Request) {
				r.Host = "localhost:7071"
				r.Header.Set("Origin", "http://LOCALHOST:7071")
			}},
			{"an address typed by hand", func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "none") }},
		} {
			for _, method := range []string{"GET", "POST"} {
				r := exchange{Method: method, Path: "/healthz", ContentType: "application/json"}.request()
				c.edit(r)
				rec := httptest.NewRecorder()
				s.ServeHTTP(rec, r)
				if rec.Code == http.StatusForbidden {
					t.Errorf("container=%v, %s %s: refused: %s", plane, method, c.name, rec.Body)
				}
			}
		}
		// a write a page could not send without asking: JSON, the office's own header, the door's stamp
		for _, h := range [][2]string{{"Content-Type", "application/json"}, {"X-DGO-Request", "a-script"}, {"X-DGO-Office", "macbook"}} {
			r := exchange{Method: "POST", Path: "/api/apps/drive/archive", Headers: [][2]string{h}}.request()
			rec := httptest.NewRecorder()
			s.ServeHTTP(rec, r)
			if strings.Contains(rec.Body.String(), "as JSON") {
				t.Errorf("container=%v, a write with %s: refused as a page's", plane, h[0])
			}
		}
	}
}

// TestListenIsLoopbackOnly: a bare port is 127.0.0.1; an address of another interface is refused
// before anything is bound.
func TestListenIsLoopbackOnly(t *testing.T) {
	for _, a := range []string{":0", "0", "127.0.0.1:0", "localhost:0"} {
		ln, err := listenLoopback(a)
		if err != nil {
			t.Errorf("--listen %s: %v", a, err)
			continue
		}
		if ip := ln.Addr().(*net.TCPAddr).IP; !ip.IsLoopback() {
			t.Errorf("--listen %s bound %s", a, ip)
		}
		ln.Close()
	}
	for _, a := range []string{"0.0.0.0:0", "[::]:0", "192.0.2.10:0"} {
		if ln, err := listenLoopback(a); err == nil {
			ln.Close()
			t.Errorf("--listen %s was bound; it must be refused", a)
		} else if !strings.Contains(err.Error(), "not a loopback address") {
			t.Errorf("--listen %s: %v", a, err)
		}
	}
}

// TestWhatTheProcessIsGivenIsChecked: a misspelt rollback is refused, not read as "native", and the
// container's address must be one.
func TestWhatTheProcessIsGivenIsChecked(t *testing.T) {
	quiet := log.New(io.Discard, "", 0)
	for _, plane := range []string{"", "native", "container"} {
		if _, err := newServer(".", "http://app-management:8080", plane, quiet); err != nil {
			t.Errorf("BBOX_CONTROL_PLANE=%q: %v", plane, err)
		}
	}
	if _, err := newServer(".", "http://app-management:8080", "contianer", quiet); err == nil {
		t.Error("a misspelt BBOX_CONTROL_PLANE must be refused")
	}
	// outside a checkout (dgo hands be-child an empty root there) only the rollback has nothing to read
	for _, plane := range []string{"", "native"} {
		if _, err := newServer("", "http://app-management:8080", plane, quiet); err == nil || !strings.Contains(err.Error(), "not inside a DGO checkout") {
			t.Errorf("no checkout, BBOX_CONTROL_PLANE=%q: %v; want a refusal", plane, err)
		}
	}
	if _, err := newServer("", "http://app-management:8080", "container", quiet); err != nil {
		t.Errorf("no checkout, BBOX_CONTROL_PLANE=container: %v", err)
	}
	for _, u := range []string{"app-management:8080", "ftp://app-management", "http://"} {
		if _, err := newServer(".", u, "", quiet); err == nil {
			t.Errorf("--container %s must be refused", u)
		}
	}
}

// TestMatchPicksTheRuleWerkzeugPicks: a named rule before the catch-all, `<aid>` one non-empty
// segment, and nothing for what app.py's router would redirect or refuse with a 405.
func TestMatchPicksTheRuleWerkzeugPicks(t *testing.T) {
	for _, c := range []struct{ method, path, want string }{
		{"GET", "/api/remote", "api_remote_get"},
		{"PUT", "/api/remote", "api_remote_put"},
		{"GET", "/api/apps", "api_apps"},
		{"GET", "/api/apps/drive/room", "api_room"},
		{"POST", "/api/apps/drive/enable", "api_enable"},
		{"GET", "/api/apps/drive/enable", "static_files"},
		{"GET", "/", "index"},
		{"GET", "/app.js", "static_files"},
		{"POST", "/api/apps//enable", ""},
		{"POST", "/api/apps/a/b/enable", ""},
		{"POST", "//api/reconcile", ""},
		{"GET", "//x", ""},
		{"POST", "/api/office", ""},
		{"POST", "/api/reconcile/", ""},
	} {
		got := ""
		if rt := match(c.method, c.path); rt != nil {
			got = rt.fn
		}
		if got != c.want {
			t.Errorf("%s %s matched %q, want %q", c.method, c.path, got, c.want)
		}
	}
}

package console

import (
	"bytes"
	"compress/gzip"
	"compress/zlib"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── the oracle: platform-base/console/app.py itself, answering through Flask's test client ────────

// noOracle skips a test whose oracle is not on this machine — or fails it where DGO_ORACLE_REQUIRED=1
// (CI): a proof that does not run must not read as a proof that passed.
func noOracle(t *testing.T, why string) {
	t.Helper()
	if os.Getenv("DGO_ORACLE_REQUIRED") == "1" {
		t.Fatal("DGO_ORACLE_REQUIRED=1 and " + why)
	}
	t.Skip(why)
}

func repoRoot(t *testing.T) string {
	t.Helper()
	d, _ := os.Getwd()
	for {
		if _, err := os.Stat(filepath.Join(d, "platform-base", "console", "app.py")); err == nil {
			return d
		}
		parent := filepath.Dir(d)
		if parent == d {
			noOracle(t, "not inside the checkout (no platform-base/console/app.py above)")
		}
		d = parent
	}
}

// oraclePython is the interpreter the console's image runs — the minor version its Dockerfile's
// `FROM python:X.Y` names — with everything app.py imports.
func oraclePython(t *testing.T, repo string) []string {
	t.Helper()
	df, err := os.ReadFile(filepath.Join(repo, "platform-base", "console", "Dockerfile"))
	m := regexp.MustCompile(`(?m)^FROM python:(\d+\.\d+)`).FindSubmatch(df)
	if err != nil || m == nil {
		t.Fatalf("the console's Dockerfile names no python:X.Y base (%v)", err)
	}
	want := string(m[1])
	probe := "import sys, flask, flask_compress, requests, yaml; print('%d.%d' % sys.version_info[:2])"
	for _, c := range [][]string{{"python3"}, {"python"}, {"py", "-" + want}} {
		if _, err := exec.LookPath(c[0]); err != nil {
			continue
		}
		out, err := exec.Command(c[0], append(c[1:], "-c", probe)...).Output()
		if err == nil && strings.TrimSpace(string(out)) == want {
			return c
		}
	}
	noOracle(t, "no python "+want+" with flask, flask-compress, requests and PyYAML on PATH (the console image's)")
	return nil
}

// pyRun runs the oracle's interpreter with input as JSON on stdin and decodes the JSON it prints.
func pyRun(t *testing.T, py []string, argv []string, input, out any) {
	t.Helper()
	in, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(py[0], append(append([]string{}, py[1:]...), argv...)...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	cmd.Stdin = bytes.NewReader(in)
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		t.Fatalf("python %v: %v\n%s", argv, err, stderr.String())
	}
	if err := json.Unmarshal(stdout.Bytes(), out); err != nil {
		t.Fatalf("python %v printed no JSON: %v\n%s\n%s", argv, err, stdout.String(), stderr.String())
	}
}

// office is a console laid out as the image lays /app out: static/ — the shell's real files and one
// of every other kind a shell could hold — modules.yaml, generated/ (the compiler's registry) and
// peers.d/ (the remote placements and link.json).
type office struct {
	repo, root, static, gen, peers string
	py                             []string
}

func newOffice(t *testing.T) office {
	t.Helper()
	repo := repoRoot(t)
	py := oraclePython(t, repo)
	root := t.TempDir()
	o := office{repo: repo, root: root, py: py, static: filepath.Join(root, "static"),
		gen: filepath.Join(root, "generated"), peers: filepath.Join(root, "peers.d")}
	shell := filepath.Join(repo, "platform-base", "console", "static")
	entries, err := os.ReadDir(shell)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		body, err := os.ReadFile(filepath.Join(shell, e.Name()))
		if err != nil {
			t.Fatal(err)
		}
		o.write(t, "static/"+e.Name(), string(body))
	}
	text := strings.Repeat("// one line of the shell, and another\n", 40)
	var gz bytes.Buffer // a pre-compressed asset: served as it is, its coding named by its suffix
	zw := gzip.NewWriter(&gz)
	zw.Write([]byte(text))
	zw.Close()
	for name, body := range map[string]string{
		"sub/deep.js": text, "empty.txt": "", "tiny.css": "a{b:c}", "data.json": `{"k":"` + strings.Repeat("v", 600) + `"}`,
		"pic.png": strings.Repeat("\x89PNG\x00\x01", 120), "bundle.js.gz": gz.String(), "icon.svgz": gz.String(), "noext": text,
		".hidden": text, "UPPER.JS": text, "space name.js": text, "eq=name.css": text, "notes.md": text,
	} {
		o.write(t, "static/"+name, body)
	}
	for _, d := range []string{o.gen, o.peers} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	return o
}

func (o office) write(t *testing.T, rel, body string) {
	t.Helper()
	p := filepath.Join(o.root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

// writeYAML writes v as reconcile.py writes the registry — yaml.safe_dump(sort_keys=False,
// allow_unicode=True, default_flow_style=False) after its comment line — so the fixture is what an
// office holds, byte for byte: a linked office's tile shares one label object between the tile and
// its `remote` block, as serve.module_entries builds it, which safe_dump writes as &id001 / *id001.
func (o office) writeYAML(t *testing.T, rel string, v any) {
	t.Helper()
	var text string
	pyRun(t, o.py, []string{"-c", `import sys, json, yaml
v = json.load(sys.stdin)
for tile in v if isinstance(v, list) else []:
    r = tile.get("remote") if isinstance(tile, dict) else None
    if isinstance(r, dict) and isinstance(tile.get("label"), dict) and r.get("label") == tile["label"]:
        r["label"] = tile["label"]
json.dump("# GENERATED by platform/manager/reconcile.py from each app's routing[].module — DO NOT EDIT.\n"
          + yaml.safe_dump(v, sort_keys=False, allow_unicode=True, default_flow_style=False), sys.stdout)`}, v, &text)
	o.write(t, rel, text)
}

func (o office) writeJSON(t *testing.T, rel string, v any) {
	t.Helper()
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	o.write(t, rel, string(b)+"\n")
}

// env is what both are given: the registry and peers of the fixture, and an app-management nobody
// answers at (an office whose plane cannot be asked is not a fresh one: `/` is the shell).
func (o office) env() map[string]string {
	return map[string]string{"GENERATED_REGISTRY": o.gen, "CONSOLE_PEERS_DIR": o.peers, "BUILD_VERSION": " 2.0.2 ",
		"APP_MANAGEMENT_URL": "http://127.0.0.1:9"}
}

type request struct {
	Method  string      `json:"method"`
	Path    string      `json:"path"`
	Headers [][2]string `json:"headers"`
}

type answer struct {
	Status  int         `json:"status"`
	Headers [][2]string `json:"headers"`
	Body    []byte      `json:"body"`
	Decoded []byte      `json:"decoded"`
}

func fetch(path string, headers ...string) request { return ask("GET", path, headers...) }

func ask(method, path string, headers ...string) request {
	r := request{Method: method, Path: path, Headers: [][2]string{}}
	for i := 0; i+1 < len(headers); i += 2 {
		r.Headers = append(r.Headers, [2]string{headers[i], headers[i+1]})
	}
	return r
}

// flask answers the requests with app.py on this fixture.
func (o office) flask(t *testing.T, env map[string]string, reqs []request) []answer {
	t.Helper()
	var out struct {
		Versions  map[string]string `json:"versions"`
		Responses []answer          `json:"responses"`
	}
	pyRun(t, o.py, []string{filepath.Join("testdata", "oracle.py")}, map[string]any{
		"app": filepath.Join(o.repo, "platform-base", "console", "app.py"), "root": o.root, "env": env, "requests": reqs,
	}, &out)
	t.Logf("oracle: %v", out.Versions)
	return out.Responses
}

// native is the Go server on the same fixture and environment; a request it does not answer is
// counted, never sent anywhere.
func (o office) native(t *testing.T, vars map[string]string) (*Server, *int) {
	t.Helper()
	return counted(t, Config{Static: o.static, Lookup: env(vars)})
}

// serve runs one request through the native server: its answer, or nil when it was left to the proxy.
func serve(s *Server, proxied *int, r request) *httptest.ResponseRecorder {
	hr := httptest.NewRequest(r.Method, r.Path, nil)
	for _, h := range r.Headers {
		hr.Header.Add(h[0], h[1])
	}
	rec := httptest.NewRecorder()
	before := *proxied
	s.ServeHTTP(rec, hr)
	if *proxied != before {
		return nil
	}
	return rec
}

// diff says how a native answer differs from app.py's, or "": the status, every header but Date (a
// clock reading), and the body. A body the server compressed — a JSON answer, or a file whose ETag
// names the coding — is compared decoded (two compressors never write the same bytes) and without
// Content-Length, which counts those bytes; a file stored compressed (`.gz`) is its own bytes.
func diff(want answer, got *httptest.ResponseRecorder) string {
	res := got.Result()
	coding, etag := res.Header.Get("Content-Encoding"), res.Header.Get("ETag")
	compressed := coding != "" && (etag == "" || strings.HasSuffix(etag, ":"+coding+`"`))
	lines := func(hs [][2]string) string {
		var out []string
		for _, h := range hs {
			if h[0] != "Date" && !(compressed && h[0] == "Content-Length") {
				out = append(out, h[0]+": "+h[1])
			}
		}
		sort.Strings(out)
		return strings.Join(out, "\n")
	}
	var mine [][2]string
	for k, vs := range res.Header {
		for _, v := range vs {
			mine = append(mine, [2]string{k, v})
		}
	}
	body, theirs := got.Body.Bytes(), want.Body
	if compressed {
		var err error
		if body, err = decode(coding, body); err != nil {
			return "the body does not decode: " + err.Error()
		}
		theirs = want.Decoded
	}
	cl := res.Header.Get("Content-Length")
	switch {
	case res.StatusCode != want.Status:
		return fmt.Sprintf("status %d, Flask %d", res.StatusCode, want.Status)
	case lines(mine) != lines(want.Headers):
		return fmt.Sprintf("headers\n--- go ---\n%s\n--- flask ---\n%s", lines(mine), lines(want.Headers))
	case !bytes.Equal(body, theirs):
		return fmt.Sprintf("body (%d bytes, Flask %d)", len(body), len(theirs))
	case compressed && cl != "" && got.Body.Len() > 0 && cl != fmt.Sprint(got.Body.Len()):
		return "Content-Length does not count the compressed body"
	}
	return ""
}

func decode(coding string, body []byte) ([]byte, error) {
	var r io.Reader
	var err error
	switch {
	case coding == "" || len(body) == 0: // identity, or a HEAD's empty body
		return body, nil
	}
	switch coding {
	case "gzip":
		r, err = gzip.NewReader(bytes.NewReader(body))
	case "deflate":
		r, err = zlib.NewReader(bytes.NewReader(body))
	default:
		return nil, fmt.Errorf("coding %q", coding)
	}
	if err != nil {
		return nil, err
	}
	return io.ReadAll(r)
}

// compare runs every request through both and requires the same answer, each natively.
func compare(t *testing.T, o office, env map[string]string, reqs []request) []answer {
	t.Helper()
	want := o.flask(t, env, reqs)
	s, proxied := o.native(t, env)
	for i, r := range reqs {
		got := serve(s, proxied, r)
		if got == nil {
			t.Errorf("%s %s %v: proxied, expected a native answer", r.Method, r.Path, r.Headers)
			continue
		}
		if d := diff(want[i], got); d != "" {
			t.Errorf("%s %s %v: %s", r.Method, r.Path, r.Headers, d)
		}
	}
	return want
}

// ── the static files ──────────────────────────────────────────────────────────────────────────────

// codings are Accept-Encoding offers whose answer flask-compress takes among gzip, deflate and
// none — each one a rule of its negotiation, quirks included (q=0 is taken; `x ; q=` is ignored;
// an unreadable q is 1.0).
var codings = []string{"", "gzip", "deflate", "gzip, deflate", "identity", "DEFLATE", "deflate;q=0",
	"gzip;q=0.5, deflate;q=0.4", "identity;q=1, deflate;q=0.5", "deflate ; q=0.5", "*;q=0", "deflate;q=abc",
	"gzip;q=1.0, identity;q=0.5", "gzip;q=1e0, deflate;q=.9"}

func TestStaticFilesMatchFlask(t *testing.T) {
	o := newOffice(t)
	o.write(t, "modules.yaml", "- id: settings\n  name: x\n  order: 13\n")
	var reqs []request
	for _, p := range []string{"/", "/?next=%2Fm%2Fapps", "/app.js", "/style.css", "/favicon.svg", "/install.html", "/desktop.js",
		"/ext-route.js", "/no/such/thing", "/api", "/a", "/healthzz", "/sub/deep.js", "/sub", "/empty.txt", "/tiny.css",
		"/data.json", "/pic.png", "/bundle.js.gz", "/icon.svgz", "/noext", "/.hidden", "/UPPER.JS", "/space%20name.js",
		"/eq=name.css", "/notes.md", "/app.js?v=7&x=;y"} {
		reqs = append(reqs, fetch(p), ask("HEAD", p))
	}
	for _, p := range []string{"/", "/app.js", "/favicon.svg", "/tiny.css", "/pic.png", "/bundle.js.gz", "/no/such/thing", "/data.json"} {
		for _, c := range codings[1:] {
			reqs = append(reqs, fetch(p, "Accept-Encoding", c))
		}
		reqs = append(reqs, ask("HEAD", p, "Accept-Encoding", "deflate"))
	}
	compare(t, o, o.env(), reqs)
}

// TestTheEntryIsTheShellOrTheWizardAsAppPySays: `/` is the install wizard only while app-management
// says the office is not installed — asked again each time while it says so, remembered once it is
// installed — and the shell whenever the plane answers an error, something other than a JSON object,
// or nothing at all. One fake plane answers both app.py and this server.
func TestTheEntryIsTheShellOrTheWizardAsAppPySays(t *testing.T) {
	answer := struct {
		status int
		body   string
	}{}
	plane := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/office" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(answer.status)
		io.WriteString(w, answer.body)
	}))
	defer plane.Close()
	o := newOffice(t)
	vars := o.env()
	vars["APP_MANAGEMENT_URL"] = plane.URL
	// …and /api/office, the brand line's record, from the same plane
	reqs := []request{fetch("/"), fetch("/?x=1"), ask("HEAD", "/"), fetch("/", "Accept-Encoding", "gzip, deflate"),
		fetch("/api/office"), ask("HEAD", "/api/office"), fetch("/api/office", "Accept-Encoding", "gzip")}
	for _, c := range []struct {
		name, body string
		status     int
	}{
		{"fresh", `{"installed": false, "office": {}}`, 200}, {"installed", `{"installed": "2026-10-15", "office": {"name": "x"}}`, 200},
		{"no installed field", `{"office": {}}`, 200}, {"an error", `{"installed": false}`, 500},
		{"not JSON", `nope`, 200}, {"a list", `[1]`, 200}, {"installed as 0", `{"installed": 0}`, 200},
	} {
		t.Run(c.name, func(t *testing.T) {
			answer.status, answer.body = c.status, c.body
			compare(t, o, vars, reqs)
		})
	}
}

// TestNotFoundIsWerkzeugs: a shell without index.html has nothing to fall back to — app.py answers
// werkzeug's NotFound page, and so does this.
func TestNotFoundIsWerkzeugs(t *testing.T) {
	o := newOffice(t)
	if err := os.Remove(filepath.Join(o.static, "index.html")); err != nil {
		t.Fatal(err)
	}
	compare(t, o, o.env(), []request{fetch("/nothing"), ask("HEAD", "/nothing"), fetch("/"), fetch("/deep/link", "Accept-Encoding", "gzip, deflate")})
}

// TestConditionalAnswersMatchFlask: the validators a browser sends back, as app.py answers them —
// 304 for a match, If-None-Match winning over If-Modified-Since, 412 for an If-Match that does not
// hold (and for `*`, which werkzeug never counts), and a 200 for the ETag of a compressed answer,
// which app.py never matches.
func TestConditionalAnswersMatchFlask(t *testing.T) {
	o := newOffice(t)
	paths := []string{"/app.js", "/no/such/thing"}
	first := o.flask(t, o.env(), []request{fetch(paths[0]), fetch(paths[1]),
		fetch(paths[0], "Accept-Encoding", "deflate"), fetch(paths[1], "Accept-Encoding", "deflate")})
	var reqs []request
	for i, p := range paths {
		etag, last := named(first[i].Headers, "ETag"), named(first[i].Headers, "Last-Modified")
		compressed := named(first[i+2].Headers, "ETag")
		if !strings.HasSuffix(compressed, `:deflate"`) {
			t.Fatalf("%s: the compressed answer's ETag is %s", p, compressed)
		}
		lm, err := time.Parse(http.TimeFormat, last)
		if err != nil {
			t.Fatal(err)
		}
		earlier, later := lm.Add(-time.Hour).Format(http.TimeFormat), lm.Add(24*time.Hour).Format(http.TimeFormat)
		weak, bare := "W/"+etag, strings.Trim(etag, `"`)
		for _, hs := range [][]string{
			{"If-None-Match", etag}, {"If-None-Match", weak}, {"If-None-Match", `"other"`}, {"If-None-Match", "*"},
			{"If-None-Match", `"x", ` + etag}, {"If-None-Match", bare}, {"If-None-Match", `""`}, {"If-None-Match", ""},
			{"If-None-Match", compressed}, {"If-None-Match", compressed, "Accept-Encoding", "deflate"},
			{"If-Match", etag}, {"If-Match", `"nope"`}, {"If-Match", "*"}, {"If-Match", weak},
			{"If-Modified-Since", last}, {"If-Modified-Since", earlier}, {"If-Modified-Since", later}, {"If-Modified-Since", ""},
			{"If-None-Match", `"other"`, "If-Modified-Since", last}, {"If-None-Match", etag, "If-Modified-Since", earlier},
			{"If-None-Match", etag, "Accept-Encoding", "deflate"}, {"If-Match", `"nope"`, "Accept-Encoding", "deflate"},
			{"If-Range", etag},
		} {
			reqs = append(reqs, fetch(p, hs...), ask("HEAD", p, hs...))
		}
	}
	answers := compare(t, o, o.env(), reqs)
	codes := map[int]int{}
	for _, a := range answers {
		codes[a.Status]++
	}
	if codes[304] == 0 || codes[412] == 0 || codes[200] == 0 {
		t.Fatalf("the corpus must reach 200, 304 and 412, reached %v", codes)
	}
}

func named(hs [][2]string, name string) string {
	for _, h := range hs {
		if h[0] == name {
			return h[1]
		}
	}
	return ""
}

// TestOffersOnlyFlaskCanWrite: a client whose best offer is zstd or br — every browser — gets the best
// of what the standard library writes: the same bytes once decoded, the same headers but the coding
// (and the ETag suffix that names it). The one measured difference from app.py, by design.
func TestOffersOnlyFlaskCanWrite(t *testing.T) {
	o := newOffice(t)
	o.write(t, "modules.yaml", strings.Repeat("- id: v\n  name: a view with a long enough name to compress\n", 12))
	var reqs []request
	for _, p := range []string{"/app.js", "/favicon.svg", "/no/such/thing", "/api/modules"} {
		for _, c := range []string{"gzip, deflate, br, zstd", "gzip, deflate, br", "br", "*", "zstd;q=1, gzip;q=0.5, deflate;q=0.4"} {
			reqs = append(reqs, fetch(p, "Accept-Encoding", c))
		}
	}
	want := o.flask(t, o.env(), reqs)
	s, proxied := o.native(t, o.env())
	sizes := map[string][2]int{}
	for i, r := range reqs {
		got := serve(s, proxied, r)
		if got == nil {
			t.Fatalf("%s %v: proxied", r.Path, r.Headers)
		}
		res := got.Result()
		theirs, mine := named(want[i].Headers, "Content-Encoding"), res.Header.Get("Content-Encoding")
		if theirs != "zstd" && theirs != "br" {
			t.Fatalf("%s %v: Flask chose %q — this corpus is for zstd and br", r.Path, r.Headers, theirs)
		}
		body, err := decode(mine, got.Body.Bytes())
		if err != nil || !bytes.Equal(body, want[i].Decoded) {
			t.Errorf("%s %v: %s decodes to other bytes than Flask's %s (%v)", r.Path, r.Headers, mine, theirs, err)
		}
		strip := func(hs [][2]string) string {
			var out []string
			for _, h := range hs {
				switch h[0] {
				case "Date", "Content-Encoding", "Content-Length":
				case "ETag":
					out = append(out, "ETag: "+regexp.MustCompile(`:[a-z]+"$`).ReplaceAllString(h[1], `"`))
				default:
					out = append(out, h[0]+": "+h[1])
				}
			}
			sort.Strings(out)
			return strings.Join(out, "\n")
		}
		var hs [][2]string
		for k, vs := range res.Header {
			hs = append(hs, [2]string{k, vs[0]})
		}
		if strip(hs) != strip(want[i].Headers) {
			t.Errorf("%s %v: headers beyond the coding differ\n--- go ---\n%s\n--- flask ---\n%s", r.Path, r.Headers, strip(hs), strip(want[i].Headers))
		}
		if r.Headers[0][1] == "gzip, deflate, br, zstd" {
			sizes[r.Path+" "+theirs+"→"+mine] = [2]int{len(want[i].Body), got.Body.Len()}
		}
	}
	t.Logf("a browser's offer, Flask's bytes vs these: %v", sizes)
}

// ── the JSON routes ───────────────────────────────────────────────────────────────────────────────

// jsonRequests are the two JSON routes under each way of asking for them.
func jsonRequests() []request {
	var reqs []request
	for _, p := range []string{"/api/version", "/api/modules", "/api/modules?x=1"} {
		reqs = append(reqs, fetch(p), ask("HEAD", p))
		for _, c := range []string{"gzip", "deflate", "gzip, deflate", "identity", "gzip;q=0.5, deflate;q=0.9", "*;q=0"} {
			reqs = append(reqs, fetch(p, "Accept-Encoding", c))
		}
	}
	return reqs
}

type obj = map[string]any

// remoteTile is a linked office's tile as serve.module_entries writes it, door included.
func remoteTile(alias, office, label string, order int) obj {
	id := alias + "." + office
	return obj{"id": id, "name": "בינה", "icon": "spark", "group": "ראשי", "desc": "הסוכן · " + label, "order": order,
		"external": true, "host": id, "embed": "/a/" + alias + "/", "proxy": "/a/" + id + "/",
		"door":   obj{"base": "http://" + id + ":9004", "host": alias + ".localhost", "user": "owner", "from": []any{"guest"}},
		"office": office, "label": obj{"he": label, "en": office},
		"remote": obj{"office": office, "label": obj{"he": label, "en": office}, "link": office, "address": "10.9.0.2",
			"commit": "", "mark": nil, "port": 9004, "api_port": 9005, "alias": alias, "module_id": ""}}
}

// TestJSONRoutesMatchFlask runs /healthz, /api/version and /api/modules on four offices: a working one
// (compiled tiles, peers — one new, one the registry already names, one carrying its own mark — and
// a fresh link measurement), one without a compiled registry, one whose measurement is stale, and one
// of edges (ids that are equal only to Python — True and 1 — string orders, falsy fields, numbers
// where strings are expected).
func TestJSONRoutesMatchFlask(t *testing.T) {
	now := time.Now().Unix()
	long := strings.Repeat("כל הקבצים של הלשכה, במקום אחד ", 6)
	working := func(t *testing.T, at int64) office {
		o := newOffice(t)
		o.writeYAML(t, "generated/console.modules.yaml", []any{
			obj{"id": "drive", "name": "דרייב", "icon": "folder", "group": "ראשי", "embed": "/a/drive/", "desc": long, "order": 5, "alias": "drive", "service": "drive"},
			obj{"id": "notes", "name": "פתקים 📝", "icon": "note", "group": "ראשי", "embed": "/a/notes/", "desc": "a: b # not a comment", "order": 5, "alias": "notes"},
			obj{"id": "n8n", "name": "n8n", "icon": "flow", "group": "כלים", "desc": "", "order": 20, "external": true, "host": "n8n", "alias": "n8n", "signed_in": "/.dgo/signed-in", "enter": "/.dgo/enter"},
			obj{"id": "plain", "name": "yes", "icon": "x", "group": "כלים", "embed": "/a/plain/", "desc": `'quoted' "double" \ back`, "alias": "plain"},
			remoteTile("bina", "macbook", "המקבוק", 900),
			remoteTile("mail", "vps1", "השרת", 901),
		})
		if reg, _ := os.ReadFile(filepath.Join(o.gen, "console.modules.yaml")); !bytes.Contains(reg, []byte("label: &id001")) ||
			!bytes.Contains(reg, []byte("label: *id001")) {
			t.Fatalf("the registry must carry the anchors the compiler writes for a linked office's label:\n%s", reg)
		}
		o.writeJSON(t, "peers.d/vps1--files.json", obj{"office": "vps1", "alias": "files", "label": "השרת", "base": "http://dgo-link:9000",
			"module": obj{"id": "files.vps1", "name": "קבצים", "icon": "folder", "order": 30, "embed": "/a/files/"}})
		o.writeJSON(t, "peers.d/macbook--drive.json", obj{"office": "macbook", "alias": "drive", "label": "המקבוק", "base": "http://x:1",
			"module": obj{"id": "drive", "name": "a placement the registry already names", "order": 1, "embed": "/a/drive/"}})
		o.writeJSON(t, "peers.d/zz--marked.json", obj{"office": "zz", "alias": "m", "module": obj{"id": "m.zz", "order": 2,
			"remote": obj{"office": "zz", "label": "written by hand"}}})
		o.write(t, "peers.d/notes.txt", "not a placement")
		o.writeJSON(t, "peers.d/link.json", obj{"at": at, "offices": obj{
			"vps1": obj{"ok": false, "hop": "tunnel", "why": "המנהרה נפלה."}, "macbook": obj{"ok": true, "hop": "", "why": ""}}})
		o.write(t, "modules.yaml", "- id: settings\n  name: הגדרות מסוף\n  icon: monitor\n  order: 13\n- id: framed\n  embed: /a/x/\n  order: 1\n- id: about\n  order: 13\n")
		return o
	}
	t.Run("working office", func(t *testing.T) { o := working(t, now); compare(t, o, o.env(), jsonRequests()) })
	t.Run("stale measurement", func(t *testing.T) { o := working(t, now-3600); compare(t, o, o.env(), jsonRequests()) })
	t.Run("no compiled registry", func(t *testing.T) {
		o := working(t, now)
		if err := os.Remove(filepath.Join(o.gen, "console.modules.yaml")); err != nil {
			t.Fatal(err)
		}
		compare(t, o, o.env(), jsonRequests())
	})
	t.Run("edges", func(t *testing.T) {
		o := newOffice(t)
		o.writeYAML(t, "generated/console.modules.yaml", []any{
			obj{"id": true, "name": "t", "order": "b"},
			obj{"id": "x", "name": "x", "order": "a", "remote": obj{"office": 7}},
			obj{"name": "no id", "order": "c"},
		})
		o.writeJSON(t, "peers.d/a.json", obj{"alias": "one", "module": obj{"id": 1, "order": "z"}})
		o.writeJSON(t, "peers.d/b.json", obj{"alias": "", "module": obj{"id": "b"}})
		o.writeJSON(t, "peers.d/c.json", []any{})
		o.writeJSON(t, "peers.d/d.json", 0)
		o.write(t, "peers.d/e.json", "{not json")
		o.writeJSON(t, "peers.d/f.json", obj{"alias": "f", "module": obj{"name": "no id either", "order": "d"}})
		o.writeJSON(t, "peers.d/g.json", obj{"alias": "g", "module": obj{"id": "g", "order": "e"}, "office": "7", "label": nil, "link": "", "commit": 0})
		o.writeJSON(t, "peers.d/link.json", obj{"at": now, "offices": obj{"7": obj{"ok": 0}, "nobody": "not an object, never asked"}})
		o.write(t, "modules.yaml", "- id: v\n  order: aa\n- id: w\n  embed: ''\n  order: ab\n")
		env := o.env()
		env["BUILD_VERSION"] = "\x1f 2.0.2-בדיקה \t"
		compare(t, o, env, jsonRequests())
	})
}

// TestWhatThisPortCannotReadIsTheContainers: inputs app.py raises on (its answer is a 500) and inputs
// Python reads that Go would read differently go to the container — never a native guess.
func TestWhatThisPortCannotReadIsTheContainers(t *testing.T) {
	now := time.Now().Unix()
	deep := func(n int) string { return strings.Repeat("[", n) + strings.Repeat("]", n) }
	cases := []struct {
		name     string
		setup    func(t *testing.T, o office)
		statuses [2]int // app.py's own answer to /api/modules and /api/version
	}{
		{"orders an int and a str", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{obj{"id": "a", "order": 1}, obj{"id": "b", "order": "x"}})
		}, [2]int{500, 500}},
		{"a registry that is a mapping", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", obj{"id": "a"})
		}, [2]int{500, 500}},
		{"a peer file holding a list", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{obj{"id": "a"}})
			o.writeJSON(t, "peers.d/x.json", []any{"a"})
		}, [2]int{500, 500}},
		{"offices that are a list", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{remoteTile("bina", "macbook", "המקבוק", 900)})
			o.writeJSON(t, "peers.d/link.json", obj{"at": now, "offices": []any{"macbook"}})
		}, [2]int{500, 500}},
		{"a measurement that is a string", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{remoteTile("bina", "macbook", "המקבוק", 900)})
			o.writeJSON(t, "peers.d/link.json", obj{"at": now, "offices": obj{"macbook": "down"}})
		}, [2]int{500, 500}},
		{"a lone surrogate in a peer file", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{obj{"id": "a", "order": 1}})
			o.write(t, "peers.d/x.json", `{"alias": "x", "office": "vps1", "module": {"id": "x.vps1", "name": "\ud800", "order": 2}}`)
		}, [2]int{200, 500}},
		// Deep enough for json.loads itself on every Python an office has: 3000 levels it reads on 3.12.3,
		// 3.12.14 and 3.14.4 alike (measured 2026-10-31), and the 500 this case was written on came from
		// further along an app.py the console image has left; 100000 is a RecursionError on all three.
		{"nesting Python cannot read", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{obj{"id": "a", "order": 1}})
			o.write(t, "peers.d/x.json", `{"alias": "x", "module": {"id": "x", "deep": `+deep(100000)+`, "order": 2}}`)
		}, [2]int{500, 500}},
		{"nesting past this port's limit", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{obj{"id": "a", "order": 1}})
			o.write(t, "peers.d/x.json", `{"alias": "x", "module": {"id": "x", "deep": `+deep(maxDepth+5)+`, "order": 2}}`)
		}, [2]int{200, 200}},
		{"a YAML anchor on a scalar", func(t *testing.T, o office) {
			o.write(t, "generated/console.modules.yaml", "- id: &n a\n  name: *n\n")
		}, [2]int{200, 200}},
		{"NaN in a peer file", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{obj{"id": "a"}})
			o.write(t, "peers.d/x.json", `{"alias": "x", "module": {"id": "x", "order": NaN}}`)
		}, [2]int{200, 200}},
		{"an integer past 64 bits", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{obj{"id": "a"}})
			o.write(t, "peers.d/x.json", `{"alias": "x", "module": {"id": "x", "order": 123456789012345678901234567890}}`)
		}, [2]int{200, 200}},
		{"a measurement time written as a string", func(t *testing.T, o office) {
			o.writeYAML(t, "generated/console.modules.yaml", []any{obj{"id": "a"}})
			o.writeJSON(t, "peers.d/link.json", obj{"at": fmt.Sprint(now), "offices": obj{}})
		}, [2]int{200, 200}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			o := newOffice(t)
			o.write(t, "modules.yaml", "")
			c.setup(t, o)
			reqs := []request{fetch("/api/modules"), fetch("/api/version")}
			s, proxied := o.native(t, o.env())
			for _, r := range reqs {
				if got := serve(s, proxied, r); got != nil {
					t.Errorf("%s answered natively (%d) — must be the container's", r.Path, got.Code)
				}
			}
			for i, a := range o.flask(t, o.env(), reqs) {
				if a.Status != c.statuses[i] {
					t.Errorf("%s: app.py answered %d, this case says %d", reqs[i].Path, a.Status, c.statuses[i])
				}
			}
		})
	}
}

// TestMimeTablesArePythons: guess_type of every extension Python knows, in both cases, through the
// suffix and encoding maps, against Python's own — with the registry and mime.types switched off, as
// the image has them.
func TestMimeTablesArePythons(t *testing.T) {
	o := office{repo: repoRoot(t)}
	o.py = oraclePython(t, o.repo)
	// the tables themselves, both ways: a type Python has and this one lacks fails here by name
	var tables struct{ Types, Encodings, Suffixes map[string]string }
	pyRun(t, o.py, []string{"-c", `import sys, json, mimetypes
mimetypes._winreg = None
mimetypes._mimetypes_read_windows_registry = None
mimetypes.knownfiles[:] = []
mimetypes.init()
json.dump({"Types": mimetypes.types_map, "Encodings": mimetypes.encodings_map, "Suffixes": mimetypes.suffix_map}, sys.stdout)`}, nil, &tables)
	for _, c := range []struct {
		name       string
		mine, want map[string]string
	}{{"types_map", pyTypeOf, tables.Types}, {"encodings_map", pyEncodings, tables.Encodings}, {"suffix_map", pySuffixes, tables.Suffixes}} {
		for k, v := range c.want {
			if c.mine[k] != v {
				t.Errorf("%s[%q]: Python %q, this table %q", c.name, k, v, c.mine[k])
			}
		}
		for k := range c.mine {
			if _, ok := c.want[k]; !ok {
				t.Errorf("%s[%q]: in this table, not in Python's", c.name, k)
			}
		}
	}
	// …and guess_type over them, in both cases, through the suffix and encoding maps
	names := []string{"noext", ".bashrc", "..js", "a.", "x.tar.gz", "x.tgz", "X.TGZ", "y.svgz", "y.SVG.GZ", "z.js.Z", "z.js.z",
		"w.css.br", "w.xz", "q.bz2", "a.b.c.html", "file.JS", "pkg.taz", "pkg.tz", "pkg.tbz2", "pkg.txz", "x.unknown"}
	for ext := range tables.Types {
		names = append(names, "f"+ext, "F"+strings.ToUpper(ext), "f"+ext+".gz")
	}
	var want [][2]*string
	pyRun(t, o.py, []string{"-c", `import sys, json, mimetypes
mimetypes._winreg = None
mimetypes._mimetypes_read_windows_registry = None
mimetypes.knownfiles[:] = []
mimetypes.init()
json.dump([list(mimetypes.guess_type(n)) for n in json.load(sys.stdin)], sys.stdout)`}, names, &want)
	for i, n := range names {
		typ, enc := guessType(n)
		w := func(p *string) string {
			if p == nil {
				return ""
			}
			return *p
		}
		if typ != w(want[i][0]) || enc != w(want[i][1]) {
			t.Errorf("guess_type(%q) = %q %q, Python %q %q", n, typ, enc, w(want[i][0]), w(want[i][1]))
		}
	}
}

// TestNegotiationIsFlaskCompresss: choose() against flask-compress's own _choose_algorithm over the
// same server lists, on every rule of it and its quirks.
func TestNegotiationIsFlaskCompresss(t *testing.T) {
	o := office{repo: repoRoot(t)}
	o.py = oraclePython(t, o.repo)
	headers := append(append([]string{}, codings...), "gzip, deflate, br, zstd", "br", "*", "*;q=0.1", "identity, deflate",
		"deflate;q=0.5, identity;q=0.5", "gzip;q=-1", "gzip;q=inf, deflate;q=2", "gzip;q=-Infinity", "x;q=0.5=1, deflate",
		"gzip;q=0.5;level=1", "  gzip  ,  deflate ", ",,", "deflate;Q=0.5, gzip;q=0.6", "gzip;q=+.5, deflate;q=5.")
	type pair struct {
		Server []string `json:"server"`
		Header string   `json:"header"`
	}
	var in []pair
	for _, h := range headers {
		in = append(in, pair{bufferedEncodings, h}, pair{streamedEncodings, h})
	}
	var want []*string
	pyRun(t, o.py, []string{"-c", `import sys, json
from flask_compress.flask_compress import _choose_algorithm
json.dump([_choose_algorithm(tuple(p["server"]), p["header"]) for p in json.load(sys.stdin)], sys.stdout)`}, in, &want)
	for i, p := range in {
		got, ok := choose(p.Server, p.Header)
		w := ""
		if want[i] != nil {
			w = *want[i]
		}
		if !ok || got != w {
			t.Errorf("choose(%v, %q) = %q %v, flask-compress %q", p.Server, p.Header, got, ok, w)
		}
	}
	for _, h := range []string{"gzip;q=nan", "gzip;q=1_0"} {
		if _, ok := choose(bufferedEncodings, h); ok {
			t.Errorf("%q: Python's float() reads this q in its own way; the request must go to the container", h)
		}
	}
}

// TestETagListsAreWerkzeugs: parseETags against werkzeug's parse_etags on the shapes a header takes.
func TestETagListsAreWerkzeugs(t *testing.T) {
	o := office{repo: repoRoot(t)}
	o.py = oraclePython(t, o.repo)
	values := []string{"", `"a"`, `W/"a"`, `w/"a"`, "*", `"*"`, `"a", "b"`, `"a",W/"b" , "c"`, "a, b", `""`, `W/""`, `"a"x, "b"`,
		`"a" , *`, "*, \"a\"", `"a`, `a"b"`, `W/`, `"x:deflate"`, `"1.5-2-3"`, "\t\"a\"\t,\t\"b\"",
		// what tells one parser from another (the second reader of the 3.1.9 port): a blank after the
		// weak marker, two tags with no comma, an empty item, a trailing comma, a weak bare token, blanks
		`W/ "a"`, `"a" "b"`, `"a",,"b"`, `"a",`, `w/x`, "   "}
	var want []struct {
		Star   bool      `json:"star"`
		Strong []*string `json:"strong"`
		Weak   []*string `json:"weak"`
	}
	pyRun(t, o.py, []string{"-c", `import sys, json
from werkzeug.http import parse_etags
out = []
for v in json.load(sys.stdin):
    e = parse_etags(v)
    out.append({"star": e.star_tag, "strong": sorted(e._strong, key=str), "weak": sorted(e._weak, key=str)})
json.dump(out, sys.stdout)`}, values, &want)
	set := func(xs []*string) string {
		var out []string
		for _, x := range xs {
			if x == nil {
				out = append(out, "\x00")
			} else {
				out = append(out, *x)
			}
		}
		sort.Strings(out)
		return strings.Join(out, "|")
	}
	keys := func(m map[string]bool) string {
		var out []string
		for k := range m {
			out = append(out, k)
		}
		sort.Strings(out)
		return strings.Join(out, "|")
	}
	for i, v := range values {
		e := parseETags(v)
		if e.star != want[i].Star || keys(e.strong) != set(want[i].Strong) || keys(e.weak) != set(want[i].Weak) {
			t.Errorf("parse_etags(%q): got star %v strong [%s] weak [%s], werkzeug %v [%s] [%s]", v, e.star,
				keys(e.strong), keys(e.weak), want[i].Star, set(want[i].Strong), set(want[i].Weak))
		}
	}
}

// TestModificationTimesAreCPythons: st_mtime's float, its repr in the ETag, and the second
// Last-Modified rounds it to — for times on and around the microsecond rounding edge.
func TestModificationTimesAreCPythons(t *testing.T) {
	o := office{repo: repoRoot(t)}
	o.py = oraclePython(t, o.repo)
	var in [][2]int64
	for _, sec := range []int64{0, 1, 1792012906, 4102444800} {
		for _, ns := range []int64{0, 1, 499999, 500000, 999999499, 999999500, 999999501, 999999999, 123456789, 740035000, 100} {
			in = append(in, [2]int64{sec, ns})
		}
	}
	var want [][2]string
	pyRun(t, o.py, []string{"-c", `import sys, json, datetime, calendar
out = []
for sec, ns in json.load(sys.stdin):
    f = sec + ns * 1e-9
    when = datetime.datetime.fromtimestamp(f, datetime.timezone.utc)
    out.append([repr(f), str(calendar.timegm(when.utctimetuple()))])
json.dump(out, sys.stdout)`}, in, &want)
	for i, p := range in {
		f := stMtime(time.Unix(p[0], p[1]))
		if got := [2]string{yamlish.FloatRepr(f), fmt.Sprint(pySecond(f))}; got != want[i] {
			t.Errorf("st_mtime of %d s + %d ns: got %v, CPython %v", p[0], p[1], got, want[i])
		}
	}
	// repr at the edges of its notation switch and of float64 (the second reader's probe)
	edges := []float64{math.Copysign(0, -1), 0, 1e16, 9999999999999998, 1e15, 1e-4, 9.999e-5, 1e-5, 0.1 + 0.2, 1e22, 5e-324,
		math.MaxFloat64, -1.5e-7, 123456789012345680, 1.7e9 + 0.123456789, 2.5, 1e100}
	var hexes, reprs []string
	for _, v := range edges {
		hexes = append(hexes, strconv.FormatFloat(v, 'x', -1, 64))
	}
	pyRun(t, o.py, []string{"-c", `import sys, json
json.dump([repr(float.fromhex(h)) for h in json.load(sys.stdin)], sys.stdout)`}, hexes, &reprs)
	for i, v := range edges {
		if got := yamlish.FloatRepr(v); got != reprs[i] {
			t.Errorf("repr(%v) = %q here, %q in CPython", v, got, reprs[i])
		}
	}
}

package console

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"
)

// The console's files built into dgo (builtin.go, -tags consoleembed) are served by the code that
// serves --static, from a tree read another way (readBuiltIn). These tests hand that reader a snapshot
// laid out as packaging/build-binaries.sh lays it out — through os.DirFS, so they run without the tag —
// and require what --static answers over the same files. embedded_test.go makes the same demands of
// the real embed, under the tag, on the console's own files.

// snapshotAt is the commit-time of the snapshots here, as `git show -s --format=%ct` writes one.
const snapshotAt = 1792039664

// layOut writes a snapshot as the release build lays it out — static/, modules.yaml, commit-time —
// and returns its directory.
func layOut(t *testing.T, files map[string]string, modules string) string {
	t.Helper()
	snap := t.TempDir()
	all := map[string]string{"modules.yaml": modules, "commit-time": fmt.Sprintf("%d\n", snapshotAt)}
	for name, body := range files {
		all["static/"+name] = body
	}
	for name, body := range all {
		p := filepath.Join(snap, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return snap
}

// staticTwin is --static over app (laid out as /app: static/ and modules.yaml), given the two facts a
// directory has and a binary does not as the built-in tree has them — every file's modification time
// is the snapshot's commit time, and the path its ETags hash is the image's /app/static. Everything else
// it reads from the files itself. The times of app's files are changed: pass a copy.
func staticTwin(t *testing.T, app string, at int64, vars map[string]string) (*Server, *int) {
	t.Helper()
	when := time.Unix(at, 0)
	err := filepath.WalkDir(filepath.Join(app, "static"), func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		return os.Chtimes(p, when, when)
	})
	if err != nil {
		t.Fatal(err)
	}
	s, proxied := counted(t, Config{Static: filepath.Join(app, "static"), Lookup: env(vars)})
	s.static = imageStatic
	return s, proxied
}

// sameTrees says how two trees differ in the files they hold — names and bytes — or "".
func sameTrees(a, b *tree) string {
	var diffs []string
	for name, f := range a.files {
		if g, ok := b.files[name]; !ok {
			diffs = append(diffs, name+": only built in")
		} else if !bytes.Equal(f.body, g.body) {
			diffs = append(diffs, name+": other bytes")
		}
	}
	for name := range b.files {
		if _, ok := a.files[name]; !ok {
			diffs = append(diffs, name+": only in --static")
		}
	}
	if len(a.refused)+len(b.refused) > 0 {
		diffs = append(diffs, fmt.Sprintf("refused links: %v %v", a.refused, b.refused))
	}
	sort.Strings(diffs)
	return strings.Join(diffs, "; ")
}

// shellPaths is a URL path for every file of a tree, sorted — index.html as `/`: by its name it is
// werkzeug's redirect to `/`, the container's to answer.
func shellPaths(t *tree) []string {
	out := []string{"/"}
	for name := range t.files {
		if name != "index.html" {
			out = append(out, (&url.URL{Path: "/" + name}).EscapedPath())
		}
	}
	sort.Strings(out)
	return out
}

// fileRequests asks each path every way a browser or a cache does: plainly, by HEAD, offering each
// coding, and with the validators s itself answered — a 304 by ETag and by date, a 412 by If-Match.
func fileRequests(t *testing.T, s *Server, proxied *int, paths []string) []request {
	t.Helper()
	var reqs []request
	for _, p := range paths {
		first := serve(s, proxied, fetch(p))
		if first == nil {
			t.Fatalf("%s: proxied", p)
		}
		etag, last := first.Header().Get("ETag"), first.Header().Get("Last-Modified")
		reqs = append(reqs, fetch(p), ask("HEAD", p), fetch(p, "Accept-Encoding", "deflate"),
			fetch(p, "Accept-Encoding", "gzip, deflate, br, zstd"), ask("HEAD", p, "Accept-Encoding", "deflate"),
			fetch(p, "If-None-Match", etag), fetch(p, "If-Modified-Since", last), fetch(p, "If-Match", `"other"`),
			fetch(p, "If-None-Match", etag, "Accept-Encoding", "deflate"))
	}
	return reqs
}

// headerLines is a header set as sorted `name: value` lines.
func headerLines(h map[string][]string) string {
	var out []string
	for k, vs := range h {
		for _, v := range vs {
			out = append(out, k+": "+v)
		}
	}
	sort.Strings(out)
	return strings.Join(out, "\n")
}

// sameAnswers requires the built-in server and its --static twin to answer every request alike — the
// status, every header, and the body byte for byte, compressed ones included: one compressor writes
// both — and each natively. It returns how many answers it compared, by status.
func sameAnswers(t *testing.T, b *Server, bp *int, s *Server, sp *int, reqs []request) map[int]int {
	t.Helper()
	codes := map[int]int{}
	for _, r := range reqs {
		got, want := serve(b, bp, r), serve(s, sp, r)
		switch {
		case got == nil || want == nil:
			t.Errorf("%s %s %v: proxied (built in: %v, --static: %v)", r.Method, r.Path, r.Headers, got == nil, want == nil)
		case got.Code != want.Code:
			t.Errorf("%s %s %v: status %d, --static %d", r.Method, r.Path, r.Headers, got.Code, want.Code)
		case headerLines(got.Header()) != headerLines(want.Header()):
			t.Errorf("%s %s %v: headers\n--- built in ---\n%s\n--- --static ---\n%s", r.Method, r.Path, r.Headers,
				headerLines(got.Header()), headerLines(want.Header()))
		case !bytes.Equal(got.Body.Bytes(), want.Body.Bytes()):
			t.Errorf("%s %s %v: body (%d bytes, --static %d)", r.Method, r.Path, r.Headers, got.Body.Len(), want.Body.Len())
		default:
			codes[got.Code]++
		}
	}
	return codes
}

// sameVersion requires /api/version from both alike but for `shell`, which is the digest app.py writes
// in the image (paths joined with `/`) for the built-in tree and on this host for --static: the two are
// one value wherever the host's separator is `/`, or the tree has no directory below static/.
func sameVersion(t *testing.T, b *Server, bp *int, s *Server, sp *int) {
	t.Helper()
	for _, r := range []request{fetch("/api/version"), ask("HEAD", "/api/version")} {
		got, want := serve(b, bp, r), serve(s, sp, r)
		if got == nil || want == nil {
			t.Fatalf("%s /api/version: proxied", r.Method)
		}
		theirs := strings.Replace(want.Body.String(), s.tree.digest, b.tree.digest, 1)
		if got.Code != want.Code || headerLines(got.Header()) != headerLines(want.Header()) || got.Body.String() != theirs {
			t.Errorf("%s /api/version: %d %v %q, --static %d %v %q", r.Method, got.Code, got.Header(), got.Body, want.Code, want.Header(), want.Body)
		}
	}
	nested := false
	for name := range b.tree.files {
		nested = nested || strings.Contains(name, "/")
	}
	if (filepath.Separator == '/' || !nested) && b.tree.digest != s.tree.digest {
		t.Errorf("shell %s built in, %s from --static: one tree must have one digest here", b.tree.digest, s.tree.digest)
	}
}

// TestTheBuiltInShellIsServedAsStatic: a snapshot holding every kind of file — nested, hidden, empty,
// compressible and not, stored compressed, odd names — is served by the built-in reader exactly as
// --static serves the same files, the console's own views (modules.yaml) read from the snapshot.
func TestTheBuiltInShellIsServedAsStatic(t *testing.T) {
	text := strings.Repeat("// one line of the shell, and another\n", 40)
	snap := layOut(t, map[string]string{
		"index.html": "<!doctype html><title>shell</title>" + text, "install.html": "<!doctype html><title>wizard</title>",
		"app.js": text, "sub/deep.js": text, "sub/inner/leaf.css": text, "empty.txt": "", "tiny.css": "a{b:c}",
		"data.json": `{"k":"` + strings.Repeat("v", 600) + `"}`, "pic.png": strings.Repeat("\x89PNG\x00\x01", 120),
		"bundle.js.gz": "\x1f\x8b" + text, "noext": text, ".hidden": text, "_under.js": text, "UPPER.JS": text,
		"space name.js": text, "eq=name.css": text, "notes.md": text,
	}, "- id: settings\n  name: הגדרות מסוף\n  view: settings\n  order: 13\n- id: framed\n  embed: /a/x/\n  order: 1\n")
	root := t.TempDir()
	vars := map[string]string{"GENERATED_REGISTRY": filepath.Join(root, "generated"), "CONSOLE_PEERS_DIR": filepath.Join(root, "peers.d"),
		"APP_MANAGEMENT_URL": "http://127.0.0.1:9", "BUILD_VERSION": "2.0.2"}
	for _, d := range []string{vars["GENERATED_REGISTRY"], vars["CONSOLE_PEERS_DIR"]} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	b, bp := counted(t, Config{Shell: os.DirFS(snap), Lookup: env(vars)})
	s, sp := staticTwin(t, snap, snapshotAt, vars)
	if d := sameTrees(b.tree, s.tree); d != "" {
		t.Fatalf("the two readers hold other files: %s", d)
	}
	reqs := append(fileRequests(t, s, sp, shellPaths(b.tree)),
		fetch("/?next=%2Fm%2Fapps"), fetch("/deep/link"), fetch("/no/such/thing.js", "Accept-Encoding", "deflate"),
		fetch("/api/modules"), fetch("/api/modules", "Accept-Encoding", "gzip, deflate"))
	codes := sameAnswers(t, b, bp, s, sp, reqs)
	if codes[200] == 0 || codes[304] == 0 || codes[412] == 0 {
		t.Errorf("the corpus must reach 200, 304 and 412, reached %v", codes)
	}
	// compiled tiles beside the console's own views: modules.yaml is read again, from the snapshot
	tiles := "- id: drive\n  name: דרייב\n  embed: /a/drive/\n  order: 5\n  desc: " + strings.Repeat("כל הקבצים ", 60) + "\n"
	if err := os.WriteFile(filepath.Join(vars["GENERATED_REGISTRY"], "console.modules.yaml"), []byte(tiles), 0o644); err != nil {
		t.Fatal(err)
	}
	sameAnswers(t, b, bp, s, sp, []request{fetch("/api/modules"), fetch("/api/modules", "Accept-Encoding", "deflate")})
	sameVersion(t, b, bp, s, sp)
	t.Logf("%d files, %d answers alike %v; shell %s built in, %s from --static", len(b.tree.files), len(reqs), codes, b.tree.digest, s.tree.digest)
}

// TestTheBuiltInDigestIsTheImages: the `shell` of a built-in tree is app.py's own _shell_build() as
// the console's Linux image runs it — over the same files, directories nested and named so that `/`
// and `\` would order them differently — on any host; --static's stays app.py's on this host.
func TestTheBuiltInDigestIsTheImages(t *testing.T) {
	o := newOffice(t) // the shell's real files and one of every other kind
	for _, name := range []string{"a/1.js", "a/x/2.js", "a0/3.js", "a=b/4.js", "a=b/c/5.js"} {
		o.write(t, "static/"+name, "// "+name+"\n")
	}
	o.write(t, "modules.yaml", "")
	o.write(t, "commit-time", fmt.Sprint(snapshotAt))
	// imageStatic is the image's STATIC because its Dockerfile works in /app and copies static/ there
	df, err := os.ReadFile(filepath.Join(o.repo, "platform-base", "console", "Dockerfile"))
	if err != nil || !strings.Contains(string(df), "\nWORKDIR /app\n") || !strings.Contains(string(df), "\nCOPY static/ ./static/\n") {
		t.Errorf("the console's Dockerfile no longer puts the shell at %s (%v):\n%s", imageStatic, err, df)
	}
	built, err := readBuiltIn(os.DirFS(o.root))
	if err != nil {
		t.Fatal(err)
	}
	static, err := readTree(o.static)
	if err != nil {
		t.Fatal(err)
	}
	if d := sameTrees(built, static); d != "" {
		t.Fatalf("the two readers hold other files: %s", d)
	}
	var out struct {
		Responses  []answer `json:"responses"`
		ImageShell string   `json:"image_shell"`
	}
	pyRun(t, o.py, []string{filepath.Join("testdata", "oracle.py")}, map[string]any{
		"app": filepath.Join(o.repo, "platform-base", "console", "app.py"), "root": o.root, "env": o.env(),
		"requests": []request{fetch("/api/version")},
	}, &out)
	var host struct{ Shell string }
	if err := json.Unmarshal(out.Responses[0].Body, &host); err != nil || host.Shell == "" {
		t.Fatalf("app.py's /api/version: %s (%v)", out.Responses[0].Body, err)
	}
	if built.digest != out.ImageShell {
		t.Errorf("shell %s built in, %s from app.py in its image", built.digest, out.ImageShell)
	}
	if static.digest != host.Shell {
		t.Errorf("shell %s from --static, %s from app.py on this host", static.digest, host.Shell)
	}
	t.Logf("app.py's shell: %s in its image, %s on this host", out.ImageShell, host.Shell)
}

// TestABuiltInShellIsWholeOrRefused: a snapshot without its time or its files — or no shell at all —
// is refused at start, never served as an empty or undated shell.
func TestABuiltInShellIsWholeOrRefused(t *testing.T) {
	root := t.TempDir()
	vars := map[string]string{"GENERATED_REGISTRY": root, "CONSOLE_PEERS_DIR": root, "APP_MANAGEMENT_URL": "http://127.0.0.1:9"}
	whole := layOut(t, map[string]string{"index.html": "x"}, "")
	for _, c := range []struct {
		name, remove, write, says string
	}{
		{"no commit-time", "commit-time", "", "commit-time"},
		{"a commit-time that is no number", "", "yesterday", "not a number of seconds"},
		{"no static/", "static", "", "static"},
	} {
		t.Run(c.name, func(t *testing.T) {
			snap := layOut(t, map[string]string{"index.html": "x"}, "")
			if c.remove != "" {
				if err := os.RemoveAll(filepath.Join(snap, c.remove)); err != nil {
					t.Fatal(err)
				}
			}
			if c.write != "" {
				if err := os.WriteFile(filepath.Join(snap, "commit-time"), []byte(c.write), 0o644); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := New(Config{Shell: os.DirFS(snap), Upstream: "http://x", Lookup: env(vars), Logf: t.Logf}); err == nil ||
				!strings.Contains(err.Error(), "built into dgo") || !strings.Contains(err.Error(), c.says) {
				t.Errorf("New = %v; want a refusal naming %q", err, c.says)
			}
		})
	}
	if _, err := New(Config{Upstream: "http://x", Lookup: env(vars), Logf: t.Logf}); err == nil || !strings.Contains(err.Error(), "--static is required") {
		t.Errorf("neither --static nor a built-in shell: New = %v", err)
	}
	// --static wins over the copy built in: it is how a developer serves an edit
	static, _ := shell(t)
	s, err := New(Config{Static: static, Shell: os.DirFS(whole), Upstream: "http://x", Lookup: env(vars), Logf: t.Logf})
	if err != nil || s.static == imageStatic || s.tree.files["app.js"] == nil {
		t.Errorf("--static beside a built-in shell: %v, serving %v", err, s)
	}
}

// TestMainNeedsNoStaticWithABuiltInShell: in a dgo that carries the console's files, --static is
// optional — Main reads the copy built in and gets as far as its listener — and its usage says so; in
// one that does not, --static stays required.
func TestMainNeedsNoStaticWithABuiltInShell(t *testing.T) {
	for _, k := range []string{"DGO_CONSOLE", "DGO_CONSOLE_UPSTREAM", "DGO_CONSOLE_TRUSTED_PROXY"} {
		t.Setenv(k, "")
	}
	root := t.TempDir()
	t.Setenv("GENERATED_REGISTRY", root)
	t.Setenv("CONSOLE_PEERS_DIR", root)
	t.Setenv("APP_MANAGEMENT_URL", "http://127.0.0.1:9")
	defer func(was fs.FS) { builtIn = was }(builtIn)
	snap := os.DirFS(layOut(t, map[string]string{"index.html": "x"}, ""))
	args := []string{"--listen", "127.0.0.1:-1", "--upstream", "http://x"}
	for _, c := range []struct {
		shell fs.FS
		args  []string
		code  int
		says  string
	}{
		{nil, args, 2, "--static <dir> --upstream"},
		{snap, args, 1, "listen tcp"},
		{snap, nil, 2, "[--static <dir>] --upstream"},
	} {
		builtIn = c.shell
		var out bytes.Buffer
		if code := Main("", c.args, &out); code != c.code || !strings.Contains(out.String(), c.says) {
			t.Errorf("built in: %v, Main(%q) = %d %q; want %d and %q", c.shell != nil, c.args, code, out.String(), c.code, c.says)
		}
	}
}

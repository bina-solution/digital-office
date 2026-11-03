//go:build consoleembed

package console

import (
	"bytes"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// The console's files as THIS binary carries them (builtin.go): the release build's copy is the
// console as committed, byte for byte, and serving it is serving --static. packaging/build-binaries.sh
// runs these in its copy of the module, right after filling snapshot/, with DGO_CONSOLE_SOURCE naming
// the platform-base/console it copied from (its extraction of HEAD).

// consoleSource is the platform-base/console the snapshot was copied from: DGO_CONSOLE_SOURCE, else
// this checkout's.
func consoleSource(t *testing.T) string {
	t.Helper()
	if s := os.Getenv("DGO_CONSOLE_SOURCE"); s != "" {
		return s
	}
	return filepath.Join(repoRoot(t), "platform-base", "console")
}

// sourceFiles is the source as the snapshot must hold it: static/'s files and modules.yaml, by their
// slash paths.
func sourceFiles(t *testing.T, src string) map[string][]byte {
	t.Helper()
	files := map[string][]byte{}
	err := filepath.WalkDir(filepath.Join(src, "static"), func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err == nil {
			files[filepath.ToSlash(rel)], err = os.ReadFile(p)
		}
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	if files["modules.yaml"], err = os.ReadFile(filepath.Join(src, "modules.yaml")); err != nil {
		t.Fatal(err)
	}
	return files
}

// builtInAt is the commit-time the binary carries.
func builtInAt(t *testing.T) int64 {
	t.Helper()
	raw, err := fs.ReadFile(builtIn, "commit-time")
	if err != nil {
		t.Fatal(err)
	}
	at, err := strconv.ParseInt(strings.TrimSpace(string(raw)), 10, 64)
	if err != nil || at <= 0 {
		t.Fatalf("commit-time %q", raw)
	}
	return at
}

// TestEmbeddedShellIsTheCommittedConsole: the binary holds static/ and modules.yaml of the source —
// every file and no other, each byte for byte — and its commit-time, nothing else.
func TestEmbeddedShellIsTheCommittedConsole(t *testing.T) {
	want := sourceFiles(t, consoleSource(t))
	got := map[string][]byte{}
	err := fs.WalkDir(builtIn, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || p == "commit-time" {
			return err
		}
		got[p], err = fs.ReadFile(builtIn, p)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	var diffs []string
	size := 0
	for p, body := range want {
		size += len(body)
		if g, ok := got[p]; !ok {
			diffs = append(diffs, p+": not in the binary")
		} else if !bytes.Equal(g, body) {
			diffs = append(diffs, p+": other bytes in the binary")
		}
	}
	for p := range got {
		if _, ok := want[p]; !ok {
			diffs = append(diffs, p+": in the binary, not in the source")
		}
	}
	sort.Strings(diffs)
	if len(diffs) > 0 {
		t.Fatalf("the binary's console is not the source's:\n%s", strings.Join(diffs, "\n"))
	}
	t.Logf("%d files, %d bytes, byte-identical to %s; commit-time %d", len(want), size, consoleSource(t), builtInAt(t))
}

// TestEmbeddedShellAnswersAsStatic: every file of the binary's shell — and `/`, a deep link and the
// two JSON routes — is answered exactly as --static answers over the source's files: status, every
// header, body.
func TestEmbeddedShellAnswersAsStatic(t *testing.T) {
	app := t.TempDir() // a copy of the source: its files' times are set, and the source is never touched
	for p, body := range sourceFiles(t, consoleSource(t)) {
		dst := filepath.Join(app, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(dst, body, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	vars := map[string]string{"GENERATED_REGISTRY": filepath.Join(app, "generated"), "CONSOLE_PEERS_DIR": filepath.Join(app, "peers.d"),
		"APP_MANAGEMENT_URL": "http://127.0.0.1:9", "BUILD_VERSION": "2.0.2"}
	for _, d := range []string{vars["GENERATED_REGISTRY"], vars["CONSOLE_PEERS_DIR"]} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	b, bp := counted(t, Config{Shell: builtIn, Lookup: env(vars)})
	s, sp := staticTwin(t, app, builtInAt(t), vars)
	if d := sameTrees(b.tree, s.tree); d != "" {
		t.Fatalf("the binary's shell and --static's hold other files: %s", d)
	}
	reqs := append(fileRequests(t, s, sp, shellPaths(b.tree)),
		fetch("/?next=%2Fm%2Fapps"), fetch("/deep/link"), fetch("/no/such/thing.js", "Accept-Encoding", "deflate"),
		fetch("/api/modules"), fetch("/api/modules", "Accept-Encoding", "gzip, deflate"))
	codes := sameAnswers(t, b, bp, s, sp, reqs)
	sameVersion(t, b, bp, s, sp)
	t.Logf("%d files, %d answers alike %v; shell %s", len(b.tree.files), len(reqs), codes, b.tree.digest)
}

// TestEmbeddedDigestIsAppPys: the binary's `shell` is app.py's own _shell_build() over the source, as
// the console's image runs it.
func TestEmbeddedDigestIsAppPys(t *testing.T) {
	src := consoleSource(t)
	o := office{repo: filepath.Dir(filepath.Dir(src)), root: t.TempDir()}
	o.py = oraclePython(t, o.repo)
	o.static, o.gen, o.peers = filepath.Join(o.root, "static"), filepath.Join(o.root, "generated"), filepath.Join(o.root, "peers.d")
	for p, body := range sourceFiles(t, src) {
		o.write(t, p, string(body))
	}
	for _, d := range []string{o.gen, o.peers} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	var out struct {
		ImageShell string `json:"image_shell"`
	}
	pyRun(t, o.py, []string{filepath.Join("testdata", "oracle.py")}, map[string]any{
		"app": filepath.Join(src, "app.py"), "root": o.root, "env": o.env(), "requests": []request{}}, &out)
	b, _ := counted(t, Config{Shell: builtIn, Lookup: env(o.env())})
	if b.tree.digest != out.ImageShell {
		t.Fatalf("shell %s in the binary, %s from app.py", b.tree.digest, out.ImageShell)
	}
	t.Logf("shell %s, app.py's", b.tree.digest)
}

package store

import (
	"archive/zip"
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

// TestMain keeps the trust memory of a test run in a fresh directory, never the user's ~/.dgo.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "dgo-home-")
	if err != nil {
		panic(err)
	}
	os.Setenv("DGO_HOME", dir)
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

// signedVersion is the version every signed test index carries unless a test says otherwise.
const signedVersion = "1.0.0"

// ── the oracle: platform/manager/catalog.py ──────────────────────────────────────────────────────

func repoRoot(t *testing.T) string {
	d, _ := os.Getwd()
	for {
		if _, err := os.Stat(filepath.Join(d, "platform", "manager", "catalog.py")); err == nil {
			return d
		}
		parent := filepath.Dir(d)
		if parent == d {
			t.Skip("not inside the checkout")
		}
		d = parent
	}
}

// python is the first interpreter with PyYAML, found once for the whole package.
var python = func() func(*testing.T) []string {
	var once sync.Once
	var found []string
	return func(*testing.T) []string {
		once.Do(func() {
			for _, c := range [][]string{{"python3"}, {"python"}, {"py", "-3"}} {
				if _, err := exec.LookPath(c[0]); err != nil {
					continue
				}
				if exec.Command(c[0], append(c[1:], "-c", "import yaml")...).Run() == nil {
					found = c
					return
				}
			}
		})
		return found
	}
}()

// oracle is the Python the proof runs. Without one a test fails — a skipped oracle proves nothing,
// and CI would read green — unless DGO_SKIP_ORACLE=1 says that this run goes without it on purpose.
func oracle(t *testing.T) []string {
	t.Helper()
	if py := python(t); py != nil {
		return py
	}
	if os.Getenv("DGO_SKIP_ORACLE") != "1" {
		t.Fatal("no python with PyYAML on PATH — catalog.py is this package's oracle (DGO_SKIP_ORACLE=1 runs without it on purpose)")
	}
	return nil
}

// catalogPy runs catalog.py with the environment its oracle needs: UTF-8 on every OS, and no
// DEPLOYMENT_NAME — catalog.py would name the catalog after it, this build after a flag. It returns
// the output, LF-only, and the exit code; err is only for a catalog.py that could not be started.
func catalogPy(root string, py []string, args ...string) (string, int, error) {
	cmd := exec.Command(py[0], append(append(py[1:], filepath.Join(root, "platform", "manager", "catalog.py")), args...)...)
	for _, kv := range os.Environ() {
		if !strings.HasPrefix(strings.ToUpper(kv), "DEPLOYMENT_NAME=") {
			cmd.Env = append(cmd.Env, kv)
		}
	}
	cmd.Env = append(cmd.Env, "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	out, err := cmd.CombinedOutput()
	if ee, ok := err.(*exec.ExitError); ok {
		return strings.ReplaceAll(string(out), "\r\n", "\n"), ee.ExitCode(), nil
	}
	return strings.ReplaceAll(string(out), "\r\n", "\n"), 0, err
}

// pyBuild is catalog.py's build (`bbox catalog build --unsigned`) of apps into out, and what it
// printed; it may run beside the test's own goroutine, so it reports instead of failing the test.
func pyBuild(root string, py []string, apps, out string) (string, error) {
	text, code, err := catalogPy(root, py, "build", "--out", out, "--unsigned", "--source", apps)
	if err == nil && code != 0 {
		err = fmt.Errorf("catalog.py build exited %d:\n%s", code, text)
	}
	return text, err
}

// pyIndex is pyBuild, without what it printed.
func pyIndex(root string, py []string, apps, out string) error {
	_, err := pyBuild(root, py, apps, out)
	return err
}

// leftOut is the links a build's output names as left out — "<id>/<path>", in report()'s words,
// which catalog.py prints too (on stderr, which may land inside a line of stdout).
func leftOut(text string) map[string]bool {
	links := map[string]bool{}
	for _, l := range strings.Split(text, "\n") {
		if _, rest, ok := strings.Cut(l, "left out, links are never followed: "); ok {
			for _, x := range strings.Split(rest, ", ") {
				links[x] = true
			}
		}
	}
	return links
}

// goIndex is this build of source — signed by c's key at signedVersion, its key list beside it, when
// there is a chain.
func goIndex(t *testing.T, source string, c *chain) (map[string]any, string, *Built) {
	t.Helper()
	out := filepath.Join(t.TempDir(), "index")
	o := Options{Root: repoRoot(t), Source: source, Out: out}
	if c != nil {
		o.Key, o.Keys, o.Version = c.key, c.keys, signedVersion
	}
	b, err := Build(o)
	if err != nil {
		t.Fatal(err)
	}
	return readJSON(t, filepath.Join(out, indexName)), out, b
}

func readJSON(t *testing.T, path string) map[string]any {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var v map[string]any
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatalf("%s: %v", path, err)
	}
	return v
}

func entries(ix map[string]any) []map[string]any {
	var out []map[string]any
	for _, e := range ix["entries"].([]any) {
		out = append(out, e.(map[string]any))
	}
	return out
}

// pair is one tree built by both: this package's index, directory and the links it left out, and
// catalog.py's index, directory and the links it named (nil without an oracle).
type pair struct {
	ix      map[string]any
	out     string
	links   map[string]bool
	pyIx    map[string]any
	pyOut   string
	pyLinks map[string]bool
}

// both builds src with this package and — where Python is, at the same time — with catalog.py.
func both(t *testing.T, src string, c *chain) pair {
	t.Helper()
	py, root, pyOut := oracle(t), repoRoot(t), t.TempDir()
	done := make(chan error, 1)
	var pyText string
	if py != nil {
		go func() {
			var err error
			pyText, err = pyBuild(root, py, filepath.Join(src, "apps"), pyOut)
			done <- err
		}()
	}
	var p pair
	var b *Built
	p.ix, p.out, b = goIndex(t, src, c)
	p.links = map[string]bool{}
	for _, l := range b.Links {
		p.links[l] = true
	}
	if py == nil {
		return p
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	p.pyIx, p.pyOut, p.pyLinks = readJSON(t, filepath.Join(pyOut, "index-v1.json")), pyOut, leftOut(pyText)
	return p
}

// agree requires this build to be catalog.py's: the index's format and repo; every entry field for
// field — but the artifact's size and sha256, each deflater's own bytes; every artifact's members,
// one for one; and the links each build names as left out. It returns the members compared.
func agree(t *testing.T, p pair) int {
	t.Helper()
	if p.pyIx == nil {
		return 0
	}
	if p.ix["format"] != p.pyIx["format"] {
		t.Errorf("format %v, catalog.py %v", p.ix["format"], p.pyIx["format"])
	}
	if !reflect.DeepEqual(p.links, p.pyLinks) {
		t.Errorf("links left out: this build names %v, catalog.py %v", sortedKeys(p.links), sortedKeys(p.pyLinks))
	}
	pr, gr := p.pyIx["repo"].(map[string]any), p.ix["repo"].(map[string]any)
	for _, k := range []string{"name", "artifact_base", "mirrors"} {
		if !reflect.DeepEqual(pr[k], gr[k]) {
			t.Errorf("repo.%s %s, catalog.py %s", k, js(gr[k]), js(pr[k]))
		}
	}
	if _, has := gr["generated"]; has {
		t.Error("repo.generated is a clock: this build never writes one")
	}
	pe, ge := entries(p.pyIx), entries(p.ix)
	if len(pe) != len(ge) {
		t.Fatalf("catalog.py publishes %d entries, this build %d", len(pe), len(ge))
	}
	n := 0
	for i := range pe {
		a, b := bare(pe[i]), bare(ge[i])
		if !reflect.DeepEqual(a, b) {
			var diff []string
			for _, k := range sortedKeys(union(a, b)) {
				if !reflect.DeepEqual(a[k], b[k]) {
					diff = append(diff, fmt.Sprintf("  %s: catalog.py %s\n  %*s  dgo        %s", k, js(a[k]), len(k), "", js(b[k])))
				}
			}
			t.Errorf("entry %v differs from catalog.py's:\n%s", a["id"], strings.Join(diff, "\n"))
			continue
		}
		pa, ga := pe[i]["artifact"].(map[string]any), ge[i]["artifact"].(map[string]any)
		n += sameMembers(t, filepath.Join(p.pyOut, "artifacts", pa["name"].(string)), filepath.Join(p.out, artifactsDir, ga["name"].(string)))
	}
	return n
}

// bare is an entry without the artifact's bytes-dependent fields: its size and sha256.
func bare(e map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range e {
		out[k] = v
	}
	if a, ok := e["artifact"].(map[string]any); ok {
		c := map[string]any{}
		for k, v := range a {
			if k != "size" && k != "sha256" {
				c[k] = v
			}
		}
		out["artifact"] = c
	}
	return out
}

func union(a, b map[string]any) map[string]bool {
	u := map[string]bool{}
	for k := range a {
		u[k] = true
	}
	for k := range b {
		u[k] = true
	}
	return u
}

// js is a value as compact JSON with its characters as themselves (sorted keys, as the index).
func js(v any) string {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	enc.Encode(v)
	return strings.TrimSuffix(b.String(), "\n")
}

// gitQuotes is whether git's default core.quotepath quotes a name — one catalog.py lost until it
// listed with -z.
func gitQuotes(name string) bool {
	for i := 0; i < len(name); i++ {
		if c := name[i]; c < 0x20 || c == '"' || c == '\\' || c >= 0x7f {
			return true
		}
	}
	return false
}

// sameMembers requires two artifacts to hold the same files, on every OS: the names in order, and
// for each its bytes, its date, its permission bits and the system that made it (Unix: the one whose
// bits those are). It returns the members compared.
func sameMembers(t *testing.T, pyZip, goZip string) int {
	t.Helper()
	a, err := zip.OpenReader(pyZip)
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	b, err := zip.OpenReader(goZip)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	base := filepath.Base(goZip)
	names := func(fs []*zip.File) []string {
		var out []string
		for _, f := range fs {
			out = append(out, f.Name)
		}
		return out
	}
	if pyNames, goNames := names(a.File), names(b.File); !reflect.DeepEqual(pyNames, goNames) {
		if only, mine := minus(pyNames, goNames), minus(goNames, pyNames); len(only)+len(mine) > 0 {
			t.Errorf("%s: other members — only catalog.py packs %v, only this build %v", base, only, mine)
		} else {
			t.Errorf("%s: the same members in another order\n catalog.py %v\n dgo        %v", base, pyNames, goNames)
		}
		return 0
	}
	for i, fa := range a.File {
		fb := b.File[i]
		if !bytes.Equal(read(t, fa), read(t, fb)) {
			t.Errorf("%s: %s: the bytes differ", base, fa.Name)
		}
		if !fa.Modified.Equal(fb.Modified) {
			t.Errorf("%s: %s: dated %v, catalog.py %v", base, fa.Name, fb.Modified, fa.Modified)
		}
		if ma, mb := fa.ExternalAttrs>>16&0o777, fb.ExternalAttrs>>16&0o777; ma != mb {
			t.Errorf("%s: %s: mode %o, catalog.py %o", base, fa.Name, mb, ma)
		}
		if sa, sb := fa.CreatorVersion>>8, fb.CreatorVersion>>8; sa != sb {
			t.Errorf("%s: %s: made by system %d, catalog.py by %d", base, fa.Name, sb, sa)
		}
	}
	return len(b.File)
}

// minus is the names of a that b does not hold, in a's order.
func minus(a, b []string) []string {
	in := map[string]bool{}
	for _, x := range b {
		in[x] = true
	}
	out := []string{}
	for _, x := range a {
		if !in[x] {
			out = append(out, x)
		}
	}
	return out
}

func read(t *testing.T, f *zip.File) []byte {
	r, err := f.Open()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	b, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func newKey(t *testing.T) ed25519.PrivateKey {
	_, k, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	return k
}

// rootFile writes a key's public half the way `relsign pubkey` prints it.
func rootFile(t *testing.T, key ed25519.PrivateKey) string {
	p := filepath.Join(t.TempDir(), "root.pub")
	if err := os.WriteFile(p, []byte(base64.StdEncoding.EncodeToString(key.Public().(ed25519.PublicKey))+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

// chain is what the owner's ceremony makes for the store: a root — its public half in a file, as
// `relsign pubkey` prints it — and a signing key that the root's keys.json names for the index, at the
// store's default site. Every key is minted here, at runtime.
type chain struct {
	root, key ed25519.PrivateKey
	rootFile  string
	keys      []byte // keys.json, version 1
}

func newChain(t *testing.T) *chain {
	t.Helper()
	root, key := newKey(t), newKey(t)
	return &chain{root: root, key: key, rootFile: rootFile(t, root), keys: keyList(t, root, defaultBaseURL, 1, listed(key, trust.IndexType))}
}

// listed is a keys.json entry for key, trusted for types, from a day ago for a year.
func listed(key ed25519.PrivateKey, types ...string) trust.KeyEntry {
	now := time.Now().UTC()
	return trust.KeyEntry{PublicKey: base64.StdEncoding.EncodeToString(key.Public().(ed25519.PublicKey)), Types: types,
		NotBefore: now.AddDate(0, 0, -1).Format(time.RFC3339), NotAfter: now.AddDate(1, 0, 0).Format(time.RFC3339)}
}

// keyList is keys.json as relsign writes it — the trust module's shape, sealed — signed by root for
// site, living two months.
func keyList(t *testing.T, root ed25519.PrivateKey, site string, version int64, keys ...trust.KeyEntry) []byte {
	t.Helper()
	body, err := json.Marshal(trust.KeysDoc{Site: site, Version: version, Expires: time.Now().UTC().AddDate(0, 2, 0).Format(time.RFC3339), Keys: keys})
	if err != nil {
		t.Fatal(err)
	}
	env, err := trust.Seal(root, trust.KeysType, body)
	if err != nil {
		t.Fatal(err)
	}
	return env
}

// TestIndexMatchesCatalogPy runs catalog.py's build and this one on the checkout: the same apps, every
// entry the same field for field, every artifact the same members, the same links left out. Then the
// chain from the other side: catalog.py's own verifier accepts this build's artifacts against this
// build's index, and says so in the lines `dgo index verify` prints.
func TestIndexMatchesCatalogPy(t *testing.T) {
	t.Parallel()
	py := oracle(t)
	if py == nil {
		t.Skip("DGO_SKIP_ORACLE=1")
	}
	root := repoRoot(t)
	c := newChain(t)
	p := both(t, root, c)
	members := agree(t, p)
	for _, e := range entries(p.ix) {
		a := e["artifact"].(map[string]any)
		raw, err := os.ReadFile(filepath.Join(p.out, filepath.FromSlash(a["url"].(string))))
		if err != nil {
			t.Fatal(err)
		}
		if sum := sha256.Sum256(raw); hex.EncodeToString(sum[:]) != a["sha256"] || float64(len(raw)) != a["size"] {
			t.Errorf("%s: the index's size/sha256 are not the artifact's", e["id"])
		}
	}

	pyText, pyCode, err := catalogPy(root, py, "verify", "--insecure", filepath.Join(p.out, indexName))
	if err != nil {
		t.Fatal(err)
	}
	var goText, goErr bytes.Buffer
	goCode := verify(p.out, c.rootFile, "", &goText, &goErr)
	if pyCode != 0 || goCode != 0 {
		t.Fatalf("verify: catalog.py exit %d, dgo exit %d\n%s\n%s%s", pyCode, goCode, pyText, goText.String(), goErr.String())
	}
	if a, b := entryLines(pyText), entryLines(goText.String()); a != b {
		t.Errorf("verify's per-entry lines differ\n--- catalog.py ---\n%s\n--- dgo ---\n%s", a, b)
	}
	t.Logf("%d entries identical to catalog.py's, %d artifact members identical (%d named as git quotes them), links both left out: %v; catalog.py verifies this build's artifacts",
		len(entries(p.ix)), members, countQuoted(t, p), sortedKeys(p.links))

	// the office's own index is installable: INDOX's requirements all resolve, from apps and the platform
	var plan, perr bytes.Buffer
	if code := install(p.out, c.rootFile, "", "indox", "", "", &plan, &perr); code != 0 || !strings.Contains(plan.String(), "workflow (") || !strings.Contains(plan.String(), "  platform: ") {
		t.Fatalf("dgo index install --dry-run indox: exit %d\n%s%s", code, plan.String(), perr.String())
	}
	t.Logf("dgo index install --dry-run indox\n%s", plan.String())
}

// countQuoted is how many members, over the whole index, have a name git quotes — each one that
// catalog.py lost before it listed with -z.
func countQuoted(t *testing.T, p pair) int {
	n := 0
	for _, e := range entries(p.ix) {
		r, err := zip.OpenReader(filepath.Join(p.out, filepath.FromSlash(e["artifact"].(map[string]any)["url"].(string))))
		if err != nil {
			t.Fatal(err)
		}
		for _, f := range r.File {
			if gitQuotes(f.Name) {
				n++
			}
		}
		r.Close()
	}
	return n
}

// entryLines are a verify report's per-entry lines and its verdict.
func entryLines(s string) string {
	var out []string
	for _, l := range strings.Split(s, "\n") {
		if strings.HasPrefix(l, "  ok ") || strings.HasPrefix(l, "  TAMPERED ") || strings.HasPrefix(l, "  MISSING ") || strings.HasPrefix(l, "VERIFY ") {
			out = append(out, l)
		}
	}
	return strings.Join(out, "\n")
}

// ── one fixture per rule: each built by both, the two required to agree ──────────────────────────

// tree writes files (slash path → content) into a fresh directory: a source tree for Build.
func tree(t *testing.T, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	for rel, body := range files {
		p := filepath.Join(dir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

// manifest is a valid layer-3 manifest plus extra JSON fields.
func manifest(id, extra string) string {
	if extra != "" {
		extra = "," + extra
	}
	return fmt.Sprintf(`{"id":%q,"layer":3,"title":{"he":"x"},"kind":"service"%s}`, id, extra)
}

// built builds src with this package and, with the oracle, catalog.py, and requires them to agree.
func built(t *testing.T, src string) pair {
	t.Helper()
	p := both(t, src, nil)
	agree(t, p)
	return p
}

// field is one field of the entry for id, as the published JSON spells it.
func field(t *testing.T, ix map[string]any, id, key string) string {
	t.Helper()
	for _, e := range entries(ix) {
		if e["id"] == id {
			return js(e[key])
		}
	}
	t.Fatalf("no entry %s", id)
	return ""
}

func TestOnlyLayer3IsPublishedAndThePlatformIsNamed(t *testing.T) {
	t.Parallel()
	p := built(t, tree(t, map[string]string{
		"platform-base/db/app.json": `{"id":"db","layer":1,"title":{"he":"x"},"kind":"service","capabilities":[{"name":"sql","type":"protocol"}]}`,
		"apps/a/app.json":           manifest("a", `"use":[{"capability":"sql"}]`),
	}))
	if got := js(p.ix["platform"]); got != `{"sql":["db"]}` {
		t.Errorf("platform = %s", got)
	}
	if n := len(entries(p.ix)); n != 1 {
		t.Errorf("%d entries: layers 1–2 are the chassis, never an entry", n)
	}
	if purpose, has := p.ix["purpose"]; has {
		t.Errorf("purpose = %v: what the signed payload is, is its envelope's type (%s), not a field of the index", purpose, trust.IndexType)
	}
}

func TestAMinimalManifestTakesCatalogPysDefaults(t *testing.T) {
	t.Parallel()
	p := built(t, tree(t, map[string]string{"apps/a/app.json": manifest("a", "")}))
	for key, want := range map[string]string{
		"version":      `"0.0.0"`,
		"summary":      `{}`,
		"provides":     `[]`,
		"uses":         `[]`,
		"connections":  `[]`,
		"routing":      `[]`,
		"volumes":      `[]`,
		"on_uninstall": `"prompt"`,
		"resources":    `{}`,
		"automations":  `{"n8n":false,"requires_stdlib":null,"workflows":0}`,
		"runtime":      `{"docker_socket":false,"host_paths":[],"images":[],"ports":[],"privileged":false,"services":[]}`,
	} {
		if got := field(t, p.ix, "a", key); got != want {
			t.Errorf("%s = %s, want %s", key, got, want)
		}
	}
	if got := field(t, p.ix, "a", "artifact"); !strings.Contains(got, `"files":1,"format":"zip","name":"a-0.0.0.zip"`) || !strings.Contains(got, `"url":"artifacts/a-0.0.0.zip"`) {
		t.Errorf("artifact = %s", got)
	}
}

func TestProvidesUsesAndConnectionsKeepCatalogPysShape(t *testing.T) {
	t.Parallel()
	p := built(t, tree(t, map[string]string{"apps/a/app.json": manifest("a", `
		"capabilities":[{"name":"c1","type":"protocol","interface":"c1.v1","required_ops":["x"]},{"name":"c2","type":"service"}],
		"use":[{"capability":"u1"},{"capability":"u2","strength":"wants","ops":["get","put"],"dependency":"weak"}],
		"connections":[{"id":"k1"},{"id":"k2","required":false}]`)}))
	for key, want := range map[string]string{
		"provides":    `[{"interface":"c1.v1","name":"c1","type":"protocol"},{"interface":null,"name":"c2","type":"service"}]`,
		"uses":        `[{"capability":"u1","ops":[],"strength":"requires"},{"capability":"u2","ops":["get","put"],"strength":"wants"}]`,
		"connections": `[{"id":"k1","required":true},{"id":"k2","required":false}]`,
	} {
		if got := field(t, p.ix, "a", key); got != want {
			t.Errorf("%s = %s\nwant %s", key, got, want)
		}
	}
}

func TestRoutingSaysAuthSsoAndTileAsCatalogPy(t *testing.T) {
	t.Parallel()
	p := built(t, tree(t, map[string]string{"apps/a/app.json": manifest("a", `"routing":[
		{"host":"a","port":80,"sso":{"slug":"a"},"module":{"id":"a","icon":"x"}},
		{"host":"b","port":81,"auth":"none","sso":{},"module":{"icon":"y"}},
		{"host":"c","port":82}]`)}))
	want := `[{"auth":"sso","host":"a","port":80,"sso":true,"tile":true},{"auth":"none","host":"b","port":81,"sso":false,"tile":false},` +
		`{"auth":"sso","host":"c","port":82,"sso":false,"tile":false}]`
	if got := field(t, p.ix, "a", "routing"); got != want {
		t.Errorf("routing = %s\nwant %s", got, want)
	}
}

func TestDataAndResourcesPassThrough(t *testing.T) {
	t.Parallel()
	p := built(t, tree(t, map[string]string{"apps/a/app.json": manifest("a", `"version":"1.2.3",
		"data":{"volumes":["v1","v2"],"on_uninstall":"keep"},"resources":{"cpus":0.5,"memory":"1g"}`)}))
	for key, want := range map[string]string{
		"version": `"1.2.3"`, "volumes": `["v1","v2"]`, "on_uninstall": `"keep"`, "resources": `{"cpus":0.5,"memory":"1g"}`,
	} {
		if got := field(t, p.ix, "a", key); got != want {
			t.Errorf("%s = %s, want %s", key, got, want)
		}
	}
}

// A blueprint directory's workflows are its ids, each file's stem: n8n-as-code's <id>.workflow.ts and
// a legacy <id>.json — one workflow when it is there in both forms — and nothing else. catalog.py
// counted *.json alone, so every real entry said 0 and its disclosure "Imports 0 workflow(s)".
func TestWorkflowsAreTheBlueprintsWorkflowIDs(t *testing.T) {
	t.Parallel()
	p := built(t, tree(t, map[string]string{
		"apps/a/app.json": `{"id":"a","layer":3,"title":{"he":"x"},"kind":"blueprint",` +
			`"blueprints":{"n8n":" blueprint/n8n ","requires_stdlib":">=1.0"}}`,
		"apps/a/blueprint/n8n/one.json":          "{}",
		"apps/a/blueprint/n8n/two.json":          "{}",
		"apps/a/blueprint/n8n/two.workflow.ts":   "export {}",
		"apps/a/blueprint/n8n/three.workflow.ts": "export {}",
		"apps/a/blueprint/n8n/README.md":         "x",
	}))
	if got := field(t, p.ix, "a", "automations"); got != `{"n8n":true,"requires_stdlib":">=1.0","workflows":3}` {
		t.Errorf("automations = %s", got)
	}
}

func TestComposeFactsAreReadOffTheComposeFile(t *testing.T) {
	t.Parallel()
	p := built(t, tree(t, map[string]string{
		"apps/a/app.json": manifest("a", `"compose":"docker-compose.yml"`),
		"apps/a/docker-compose.yml": `services:
  web:
    image: example/web:1
    privileged: true
    ports: ["8080:80", 9000, "8080:80"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./data:/data
      - named:/srv
      - type: bind
        source: /etc
        target: /etc
  worker:
    build: .
  tool:
    image: ""
  note: just a string
`,
	}))
	want := `{"docker_socket":true,"host_paths":["./data:/data","/var/run/docker.sock:/var/run/docker.sock"],` +
		`"images":["(built from source: worker)","example/web:1"],"ports":["8080:80","9000"],"privileged":true,"services":["tool","web","worker"]}`
	if got := field(t, p.ix, "a", "runtime"); got != want {
		t.Errorf("runtime = %s\nwant %s", got, want)
	}
}

func TestManifestSHA256IsTheFilesOwnBytes(t *testing.T) {
	t.Parallel()
	body := manifest("a", "") + "\r\n"
	p := built(t, tree(t, map[string]string{"apps/a/app.json": body}))
	sum := sha256.Sum256([]byte(body))
	if got := field(t, p.ix, "a", "manifest_sha256"); got != `"`+hex.EncodeToString(sum[:])+`"` {
		t.Errorf("manifest_sha256 = %s", got)
	}
}

// members is an artifact's names and modes.
func members(t *testing.T, zipPath string) string {
	t.Helper()
	r, err := zip.OpenReader(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	var out []string
	for _, f := range r.File {
		out = append(out, fmt.Sprintf("%s %o", f.Name, f.ExternalAttrs>>16&0o777))
	}
	return strings.Join(out, ", ")
}

// Outside any repository, catalog.py walks the directory: build detritus, local secrets and VCS files
// stay out; hooks/ is executable whatever the file says.
func TestArtifactSkipsWhatAFreshCloneWouldNotHave(t *testing.T) {
	t.Parallel()
	src := tree(t, map[string]string{
		"apps/a/app.json":                manifest("a", ""),
		"apps/a/hooks/run":               "echo",
		"apps/a/sub/keep.txt":            "k",
		"apps/a/x.pyc":                   "",
		"apps/a/x.pyo":                   "",
		"apps/a/__pycache__/m.py":        "",
		"apps/a/node_modules/m/index.js": "",
		"apps/a/sub/.venv/bin/python":    "",
		"apps/a/.pytest_cache/v":         "",
		"apps/a/.git/config":             "",
		"apps/a/sub/.DS_Store":           "",
		"apps/a/Thumbs.db":               "",
		"apps/a/portainer_password.txt":  "x",
	})
	p := built(t, src)
	if got, want := members(t, filepath.Join(p.out, artifactsDir, "a-0.0.0.zip")), "a/app.json 644, a/hooks/run 755, a/sub/keep.txt 644"; got != want {
		t.Errorf("members = %s\nwant      %s", got, want)
	}
}

// git runs git in dir for a fixture repository.
func git(t *testing.T, dir string, stdin string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir, "-c", "core.autocrlf=false"}, args...)...)
	cmd.Stdin = strings.NewReader(stdin)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

// In a repository the artifact is what git tracks — an untracked file stays out — every name exactly,
// a non-ASCII one too (catalog.py lost it until it listed with -z), each with the mode git records
// whatever the disk says: here the disk says the opposite for two files, as Windows' does for every
// file it calls executable.
func TestArtifactIsWhatGitTracks(t *testing.T) {
	t.Parallel()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("no git on PATH")
	}
	src := tree(t, map[string]string{
		"apps/a/app.json":    manifest("a", ""),
		"apps/a/tool.sh":     "echo",
		"apps/a/notes.txt":   "n",
		"apps/a/שלום.txt":    "x",
		"apps/a/untracked.x": "u",
	})
	git(t, src, "", "init", "-q")
	git(t, src, "", "config", "core.quotepath", "true") // git's default, whatever the builder's own config says
	git(t, src, "", "add", "apps/a/app.json", "apps/a/tool.sh", "apps/a/notes.txt", "apps/a/שלום.txt")
	git(t, src, "", "update-index", "--chmod=+x", "apps/a/tool.sh")
	if err := os.Chmod(filepath.Join(src, "apps", "a", "notes.txt"), 0o755); err != nil { // after the add: git keeps 100644
		t.Fatal(err)
	}
	p := both(t, src, nil)
	if got, want := members(t, filepath.Join(p.out, artifactsDir, "a-0.0.0.zip")), "a/app.json 644, a/notes.txt 644, a/tool.sh 755, a/שלום.txt 644"; got != want {
		t.Errorf("members = %s\nwant      %s", got, want)
	}
	agree(t, p) // catalog.py's: the same names, and the modes git records, on every OS
}

// A link is never followed: one git tracks (mode 120000) is left out by name, without the disk being
// asked — by catalog.py too, which packed the text file a checkout without symlinks leaves (Windows)
// and followed the link elsewhere; and one on disk, outside git or where git has a file, the same, by
// both. Each is named in the build's report.
func TestALinkIsNeverFollowed(t *testing.T) {
	t.Parallel()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("no git on PATH")
	}
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), ".env": "TOKEN=1", "apps/a/data": "../../.env"})
	git(t, src, "", "init", "-q")
	git(t, src, "", "add", "apps/a/app.json")
	blob := git(t, src, "../../.env", "hash-object", "-w", "--stdin")
	git(t, src, "", "update-index", "--add", "--cacheinfo", "120000,"+blob+",apps/a/data")
	p := both(t, src, nil)
	agree(t, p) // catalog.py leaves it out and names it, as this build does
	_, out, b := goIndex(t, src, nil)
	if got := members(t, filepath.Join(out, artifactsDir, "a-0.0.0.zip")); got != "a/app.json 644" || strings.Join(b.Links, ",") != "a/data" {
		t.Errorf("a symlink git tracks: members %s, links %v", got, b.Links)
	}
	var report bytes.Buffer
	b.report(&report)
	if !strings.Contains(report.String(), "left out, links are never followed: a/data") {
		t.Errorf("the build must say what it left out:\n%s", report.String())
	}

	walked := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "secret.txt": "TOKEN=1"})
	if err := os.Symlink(filepath.Join(walked, "secret.txt"), filepath.Join(walked, "apps", "a", "data")); err != nil {
		t.Logf("no symlink on disk here (%v) — the junction probe covers Windows", err)
		return
	}
	// the same link where git has a file: the working tree replaced it, and git still says 100644
	tracked := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/a/data": "x", "secret.txt": "TOKEN=1"})
	git(t, tracked, "", "init", "-q")
	git(t, tracked, "", "add", "apps/a/app.json", "apps/a/data")
	if err := os.Remove(filepath.Join(tracked, "apps", "a", "data")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(tracked, "secret.txt"), filepath.Join(tracked, "apps", "a", "data")); err != nil {
		t.Fatal(err)
	}
	for what, src := range map[string]string{"outside git": walked, "where git has a file": tracked} {
		p := both(t, src, nil)
		if got := members(t, filepath.Join(p.out, artifactsDir, "a-0.0.0.zip")); got != "a/app.json 644" || !p.links["a/data"] || len(p.links) != 1 {
			t.Errorf("a symlink on disk, %s: members %s, links %v", what, got, sortedKeys(p.links))
		}
		agree(t, p) // catalog.py leaves it out and names it too
	}
}

// ── what this build refuses, where catalog.py would publish ───────────────────────────────────────

func TestBuildRefusesWhatItCannotPublishHonestly(t *testing.T) {
	t.Parallel()
	ok := map[string]string{"apps/a/app.json": manifest("a", "")}
	cases := []struct {
		name  string
		files map[string]string
		opts  Options
		want  string
	}{
		{"a manifest the compiler refuses", map[string]string{"apps/a/app.json": manifest("a", `"bogus":1`)}, Options{}, "unknown field 'bogus'"},
		{"a version that is not SemVer", map[string]string{"apps/a/app.json": manifest("a", `"version":"1.0"`)}, Options{}, `version "1.0" is not SemVer`},
		{"a version that walks out of the tree", map[string]string{"apps/a/app.json": manifest("a", `"version":"../../x"`)}, Options{}, "is not SemVer"},
		{"a compose file outside yamlish", map[string]string{
			"apps/a/app.json": manifest("a", `"compose":"c.yml"`),
			"apps/a/c.yml":    "x: &anchor 1\nservices:\n  s:\n    image: *anchor\n",
		}, Options{}, "c.yml"},
		{"a long-syntax port", map[string]string{
			"apps/a/app.json": manifest("a", `"compose":"c.yml"`),
			"apps/a/c.yml":    "services:\n  s:\n    ports:\n      - target: 80\n        published: 8080\n",
		}, Options{}, "long-syntax"},
		{"service names of mixed YAML types", map[string]string{
			"apps/a/app.json": manifest("a", `"compose":"c.yml"`),
			"apps/a/c.yml":    "services:\n  web:\n    image: x\n  yes:\n    image: y\n",
		}, Options{}, "cannot sort them"},
		{"a compose path out of the app", map[string]string{
			"apps/a/app.json": manifest("a", `"compose":"../b/c.yml"`),
			"apps/b/app.json": manifest("b", ""),
			"apps/b/c.yml":    "services: {}\n",
		}, Options{}, "leaves the app's directory"},
		{"a blueprint directory out of the app", map[string]string{
			"apps/a/app.json": `{"id":"a","layer":3,"title":{"he":"x"},"kind":"blueprint","blueprints":{"n8n":"../wf"}}`,
		}, Options{}, "leaves the app's directory"},
		{"an id that is not portable", map[string]string{"apps/A_b/app.json": manifest("A_b", "")}, Options{}, "lower-case letters, digits and hyphens"},
		{"a source that is catalog.py's directory of app folders", ok, Options{Source: "apps"}, "holds no apps/"},
		{"a source without one app", map[string]string{"apps/README": "x"}, Options{}, "holds no app"},
		{"a signed index without its own version", ok, Options{Key: newKey(t)}, "needs --version"},
		{"a signed index at a pre-release, which no floor could order", ok, Options{Key: newKey(t), Keys: []byte("{}"), Version: "1.4.0-rc.1"}, "needs a release version"},
		{"a signed index without the key list that names its key", ok, Options{Key: newKey(t), Version: "1.4.0"}, "needs --keys"},
		{"a key list without a key to sign", ok, Options{Keys: []byte("{}")}, "--keys goes with --key"},
		{"an index version that is not SemVer", ok, Options{Version: "v1.0.0"}, "is not SemVer"},
		{"a base URL that is not https", ok, Options{BaseURL: "http://apps.example"}, "must be https"},
	}
	for _, c := range cases {
		o := c.opts
		src := tree(t, c.files)
		o.Root, o.Out = repoRoot(t), filepath.Join(t.TempDir(), "index")
		if o.Source != "" {
			o.Source = filepath.Join(src, o.Source)
		} else {
			o.Source = src
		}
		if _, err := Build(o); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: err = %v, want it to say %q", c.name, err, c.want)
		}
	}
}

// An id and a version name the artifact's file, and a third-party manifest writes both. One that
// walks out of artifacts/ is refused, naming the app and why, by this build and by catalog.py — which
// wrote it to <out>/../x.zip — and neither writes a byte, here or anywhere around its output.
func TestAnIdOrVersionThatWalksOutWritesNothing(t *testing.T) {
	t.Parallel()
	py := oracle(t)
	for _, c := range []struct{ name, manifest, says, pySays string }{
		{"version", manifest("a", `"version":"0/../../../x"`), `a: version "0/../../../x" is not SemVer`, `a: version '0/../../../x' is not SemVer`},
		{"id", manifest("../../x", ""), `id '../../x' != directory 'a'`, `a: id '../../x' is not an app id`},
	} {
		src, around := tree(t, map[string]string{"apps/a/app.json": c.manifest}), t.TempDir()
		if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: filepath.Join(around, "dgo", "index")}); err == nil || !strings.Contains(err.Error(), c.says) {
			t.Errorf("%s: err = %v, want it to say %q", c.name, err, c.says)
		}
		if py != nil {
			text, code, err := catalogPy(repoRoot(t), py, "build", "--out", filepath.Join(around, "py", "index"), "--unsigned", "--source", filepath.Join(src, "apps"))
			if err != nil {
				t.Fatal(err)
			}
			if code == 0 || !strings.Contains(text, c.pySays) {
				t.Errorf("%s: catalog.py exit %d, want a refusal that says %q:\n%s", c.name, code, c.pySays, text)
			}
		}
		filepath.Walk(around, func(p string, info os.FileInfo, err error) error {
			if err == nil && !info.IsDir() {
				t.Errorf("%s: a refused build wrote %s", c.name, p)
			}
			return nil
		})
	}
}

// The build replaces its output whole, so it refuses a directory it did not write; and two names
// that differ only in case are refused where the file system can hold both.
func TestBuildRefusesToTakeOtherFilesWithIt(t *testing.T) {
	t.Parallel()
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", "")})
	out := tree(t, map[string]string{"notes.md": "mine"})
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: out}); err == nil || !strings.Contains(err.Error(), "notes.md") {
		t.Errorf("a directory holding notes.md: err = %v", err)
	}
	if raw, _ := os.ReadFile(filepath.Join(out, "notes.md")); string(raw) != "mine" {
		t.Error("a refused build must leave the directory as it was")
	}
	cased := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/a/README": "x"})
	if err := os.WriteFile(filepath.Join(cased, "apps", "a", "readme"), []byte("y"), 0o644); err != nil {
		t.Fatal(err)
	}
	if raw, _ := os.ReadFile(filepath.Join(cased, "apps", "a", "README")); string(raw) != "x" {
		t.Log("a case-folding file system: README and readme are one file here")
		return
	}
	if _, err := Build(Options{Root: repoRoot(t), Source: cased, Out: t.TempDir()}); err == nil || !strings.Contains(err.Error(), "differ only in case") {
		t.Errorf("README and readme: err = %v", err)
	}
}

// The same tree, flags and key are the same bytes — every file of the tree, signature included — a
// rebuild replaces the tree whole (an app that went takes its artifact with it), and an unsigned
// rebuild leaves no signature naming other bytes.
func TestBuildIsByteReproducible(t *testing.T) {
	t.Parallel()
	src := tree(t, map[string]string{
		"apps/a/app.json":           manifest("a", `"version":"1.0.0","compose":"docker-compose.yml"`),
		"apps/a/docker-compose.yml": "services:\n  a:\n    image: x\n",
		"apps/a/hooks/run":          "echo",
		"apps/b/app.json":           manifest("b", `"capabilities":[{"name":"c","type":"protocol"}]`),
	})
	c := newChain(t)
	one, two := filepath.Join(t.TempDir(), "index"), filepath.Join(t.TempDir(), "index")
	for _, out := range []string{one, two} {
		if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: out, Key: c.key, Keys: c.keys, Version: "1.4.0"}); err != nil {
			t.Fatal(err)
		}
	}
	if a, b := snapshot(t, one), snapshot(t, two); a != b {
		t.Fatalf("two builds differ:\n%s\n---\n%s", a, b)
	}
	if err := os.RemoveAll(filepath.Join(src, "apps", "b")); err != nil {
		t.Fatal(err)
	}
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: one, Version: "1.4.0"}); err != nil {
		t.Fatal(err)
	}
	if got := snapshot(t, one); strings.Contains(got, "b-0.0.0.zip") || strings.Contains(got, sigName+" ") || strings.Contains(got, keysName+" ") ||
		!strings.Contains(got, draftName+" ") {
		t.Errorf("an unsigned rebuild without b must hold a's artifact and the draft only:\n%s", got)
	}
}

// snapshot is every file under dir with its sha256, sorted.
func snapshot(t *testing.T, dir string) string {
	t.Helper()
	var lines []string
	err := filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return err
		}
		raw, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, p)
		sum := sha256.Sum256(raw)
		lines = append(lines, filepath.ToSlash(rel)+" "+hex.EncodeToString(sum[:]))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n")
}

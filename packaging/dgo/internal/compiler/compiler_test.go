package compiler

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── the oracle: reconcile.py on the real checkout ─────────────────────────────────────────────────

// unprovable skips a test that cannot ask the oracle here — or fails it where DGO_ORACLE_REQUIRED=1
// (CI) says that a green run must have asked it: a suite that skipped its proof is not a proof.
func unprovable(t *testing.T, why string) {
	t.Helper()
	if os.Getenv("DGO_ORACLE_REQUIRED") == "1" {
		t.Fatal(why + " (DGO_ORACLE_REQUIRED=1)")
	}
	t.Skip(why)
}

// repoRoot is the checkout above the test: the directory that holds the compiler and bbox, as
// main.go's findRoot finds it — not the office's state file, which a fresh clone may lack.
func repoRoot(t *testing.T) string {
	t.Helper()
	d, _ := os.Getwd()
	for {
		if isFile(filepath.Join(d, "platform", "manager", "reconcile.py")) && isFile(filepath.Join(d, "bbox")) {
			return d
		}
		parent := filepath.Dir(d)
		if parent == d {
			unprovable(t, "not inside a checkout (no platform/manager/reconcile.py + bbox above here)")
		}
		d = parent
	}
}

// officeRoot is the checkout, for a test that asks reconcile.py about the office's OWN state — which
// it would otherwise create from the default, writing into the checkout.
func officeRoot(t *testing.T) string {
	t.Helper()
	root := repoRoot(t)
	if !isFile(filepath.Join(root, stateName)) {
		unprovable(t, "this checkout has no platform.state.yaml of its own")
	}
	return root
}

func isFile(p string) bool { fi, err := os.Stat(p); return err == nil && !fi.IsDir() }

// python is the interpreter the oracle runs, with PyYAML: python3, python, then the Windows launcher.
func python(t *testing.T) []string {
	t.Helper()
	for _, c := range [][]string{{"python3"}, {"python"}, {"py", "-3"}} {
		if _, err := exec.LookPath(c[0]); err != nil {
			continue
		}
		if exec.Command(c[0], append(c[1:], "-c", "import yaml")...).Run() == nil {
			return c
		}
	}
	unprovable(t, "no python with PyYAML on PATH")
	return nil
}

// TestEnabledAppsMatchesPython runs `reconcile.py enabled-apps` on this checkout and the Go verb on
// the same checkout: same stdout bytes, same exit code, same error lines (as a set — Python iterates
// a set to build its frontier, so its error ORDER is not stable across runs).
func TestEnabledAppsMatchesPython(t *testing.T) {
	py := python(t)
	root := officeRoot(t)
	cmd := exec.Command(py[0], append(py[1:], filepath.Join(root, "platform", "manager", "reconcile.py"), "enabled-apps")...)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	var pyOut, pyErr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &pyOut, &pyErr
	pyCode := 0
	if err := cmd.Run(); err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			pyCode = ee.ExitCode()
		} else {
			t.Fatalf("running reconcile.py: %v", err)
		}
	}
	// Python's text-mode stdout writes CRLF on Windows; the contract (and Linux) is LF.
	pyStdout := strings.ReplaceAll(pyOut.String(), "\r\n", "\n")
	pyStderr := strings.ReplaceAll(pyErr.String(), "\r\n", "\n")
	var goOut, goErr bytes.Buffer
	goCode := EnabledApps(root, &goOut, &goErr)
	if goCode != pyCode {
		t.Errorf("exit code: go %d, python %d\n--- go stderr ---\n%s\n--- python stderr ---\n%s", goCode, pyCode, goErr.String(), pyStderr)
	}
	if goOut.String() != pyStdout {
		t.Errorf("stdout differs\n--- go ---\n%s\n--- python ---\n%s", goOut.String(), pyStdout)
	}
	if e1, e2 := errorLines(goErr.String()), errorLines(pyStderr); strings.Join(e1, "\n") != strings.Join(e2, "\n") {
		t.Errorf("error lines differ\n--- go ---\n%s\n--- python ---\n%s", strings.Join(e1, "\n"), strings.Join(e2, "\n"))
	}
	t.Logf("%d enabled apps, identical to reconcile.py", strings.Count(goOut.String(), "\n"))
}

func errorLines(s string) []string {
	var out []string
	for _, l := range strings.Split(s, "\n") {
		if strings.HasPrefix(l, "  ERROR ") {
			out = append(out, l)
		}
	}
	sort.Strings(out)
	return out
}

// ── synthetic catalogs: every resolver rule, one case each ────────────────────────────────────────

// fixture writes manifests ("apps/x/app.json" → body) and a state file into a fresh repo that
// carries the REAL manifest schema, so every fixture is validated the way the office's are.
func fixture(t *testing.T, manifests map[string]string, state string) string {
	t.Helper()
	repo := t.TempDir()
	schema, err := os.ReadFile(filepath.Join(repoRoot(t), "platform", "schema", "app.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(repo, "platform", "schema"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(repo, "platform", "schema", "app.schema.json"), schema, 0o644); err != nil {
		t.Fatal(err)
	}
	for rel, body := range manifests {
		full := filepath.Join(repo, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if state != "" {
		if err := os.WriteFile(filepath.Join(repo, "platform.state.yaml"), []byte(state), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return repo
}

// manifest is a VALID minimal manifest (id, layer, a Hebrew title, kind service) plus extra JSON.
func manifest(id string, layer int, extra string) string {
	if extra != "" {
		extra = "," + extra
	}
	return fmt.Sprintf(`{"id":%q,"layer":%d,"title":{"he":"x"},"kind":"service"%s}`, id, layer, extra)
}

const stateHead = "schema_version: 1\napps:\n"

func run(t *testing.T, repo string) (string, string, int) {
	t.Helper()
	var out, errb bytes.Buffer
	code := EnabledApps(repo, &out, &errb)
	return out.String(), errb.String(), code
}

func TestPullsInProviderAndOrdersIt(t *testing.T) {
	repo := fixture(t, map[string]string{
		"apps/a/app.json":          manifest("a", 3, `"use":[{"capability":"db"}]`),
		"platform-base/p/app.json": manifest("p", 1, `"capabilities":[{"name":"db"}]`),
	}, stateHead+"  a: { enabled: true }\n")
	out, errb, code := run(t, repo)
	if code != 0 || out != "platform-base p\napps a\n" {
		t.Fatalf("code %d out %q err %q", code, out, errb)
	}
}

func TestWeakDependencyWantsButDoesNotOrder(t *testing.T) {
	repo := fixture(t, map[string]string{
		"apps/a/app.json":          manifest("a", 3, `"use":[{"capability":"db","dependency":"weak"}]`),
		"platform-base/p/app.json": manifest("p", 1, `"capabilities":[{"name":"db"}]`),
	}, stateHead+"  a: { enabled: true }\n")
	out, _, code := run(t, repo)
	if code != 0 || out != "apps a\nplatform-base p\n" {
		t.Fatalf("code %d out %q", code, out)
	}
}

func TestOpsNegotiationRefusesAProviderMissingAnOp(t *testing.T) {
	repo := fixture(t, map[string]string{
		"apps/a/app.json":          manifest("a", 3, `"use":[{"capability":"db","ops":["write"]}]`),
		"platform-base/p/app.json": manifest("p", 1, `"capabilities":[{"name":"db","required_ops":["read"]}]`),
	}, stateHead+"  a: { enabled: true }\n")
	_, errb, code := run(t, repo)
	if code != 1 || !strings.Contains(errb, "  ERROR a: provider 'p' lacks ops ['write'] for 'db'") {
		t.Fatalf("code %d err %q", code, errb)
	}
}

func TestProviderSelectionBindingDefaultAmbiguity(t *testing.T) {
	two := map[string]string{
		"apps/a/app.json":           manifest("a", 3, `"use":[{"capability":"db"}]`),
		"platform-base/p1/app.json": manifest("p1", 1, `"capabilities":[{"name":"db"}]`),
		"platform-base/p2/app.json": manifest("p2", 1, `"capabilities":[{"name":"db"}]`),
	}
	// no rule → a plan failure naming every candidate
	_, errb, code := run(t, fixture(t, two, stateHead+"  a: { enabled: true }\n"))
	if code != 1 || !strings.Contains(errb, "capability 'db' has 2 eligible providers (p1, p2) and no rule to choose") {
		t.Fatalf("ambiguity: code %d err %q", code, errb)
	}
	// a binding in the state file wins
	out, _, code := run(t, fixture(t, two, stateHead+"  a: { enabled: true }\nbindings:\n  db: { provider: p2 }\n"))
	if code != 0 || out != "platform-base p2\napps a\n" {
		t.Fatalf("binding: code %d out %q", code, out)
	}
	// a binding to a non-provider is an error
	_, errb, code = run(t, fixture(t, two, stateHead+"  a: { enabled: true }\nbindings:\n  db: p9\n"))
	if code != 1 || !strings.Contains(errb, "db: platform.state.yaml binds 'p9', which is not an eligible provider (p1, p2)") {
		t.Fatalf("bad binding: code %d err %q", code, errb)
	}
	// the consumer's default_provider is the second rule
	two["apps/a/app.json"] = manifest("a", 3, `"use":[{"capability":"db","default_provider":"p1"}]`)
	out, _, code = run(t, fixture(t, two, stateHead+"  a: { enabled: true }\n"))
	if code != 0 || out != "platform-base p1\napps a\n" {
		t.Fatalf("default_provider: code %d out %q", code, out)
	}
}

// The product's binding (platform.state.default.yaml `product_bindings:`) decides for an office whose
// own state binds nothing — one upgraded from before the second provider existed — and the plan says
// which rule chose. The office's binding, the consumer's default_provider and the one provider the
// office runs all win over it; and it never starts a provider the office switched off.
func TestProductDefaultBindingDecidesWhatTheOfficeLeftOpen(t *testing.T) {
	files := func(consumer string) map[string]string {
		return map[string]string{
			"apps/a/app.json":             manifest("a", 3, consumer),
			"platform-base/p1/app.json":   manifest("p1", 1, `"capabilities":[{"name":"db"}]`),
			"platform-base/p2/app.json":   manifest("p2", 1, `"capabilities":[{"name":"db"}]`),
			"platform.state.default.yaml": stateHead + "  a: { enabled: true }\nproduct_bindings:\n  db: p2\n",
		}
	}
	// said reports whether the resolver's notes for this repo hold msg
	said := func(repo, msg string) bool {
		t.Helper()
		cat, err := LoadCatalog(repo)
		if err != nil {
			t.Fatal(err)
		}
		st, err := LoadState(repo, io.Discard, io.Discard)
		if err != nil {
			t.Fatal(err)
		}
		_, diags, err := Resolve(repo, cat, st, nil)
		if err != nil {
			t.Fatal(err)
		}
		for _, d := range diags {
			if d.Level == "info" && d.Msg == msg {
				return true
			}
		}
		return false
	}
	plain := `"use":[{"capability":"db"}]`
	// an old state with no binding → the product's, and the plan's note says which rule chose
	repo := fixture(t, files(plain), stateHead+"  a: { enabled: true }\n")
	out, errb, code := run(t, repo)
	if code != 0 || out != "platform-base p2\napps a\n" {
		t.Fatalf("product binding: code %d out %q err %q", code, out, errb)
	}
	if !said(repo, "db: bound to 'p2' by platform.state.default.yaml (this office's platform.state.yaml binds none)") {
		t.Fatalf("product binding: the note is missing")
	}
	// the one provider the office runs wins, and says so
	repo = fixture(t, files(plain), stateHead+"  a: { enabled: true }\n  p1: { enabled: true }\n")
	if out, _, code = run(t, repo); code != 0 || strings.Contains(out, "p2") || !strings.Contains(out, "platform-base p1\n") {
		t.Fatalf("the one it runs over product: code %d out %q", code, out)
	}
	if !said(repo, "db: 'p1' is the one eligible provider this office runs") {
		t.Fatalf("the one it runs: the note is missing")
	}
	// a provider that names the capability twice is still one provider
	twice := files(plain)
	twice["platform-base/p1/app.json"] = manifest("p1", 1, `"capabilities":[{"name":"db"},{"name":"db"}]`)
	if !said(fixture(t, twice, stateHead+"  a: { enabled: true }\n  p1: { enabled: true }\n"), "db: 'p1' is the one eligible provider this office runs") {
		t.Fatalf("a capability named twice: the note is missing")
	}
	// running both, the product's choice decides between them
	if !said(fixture(t, files(plain), stateHead+"  a: { enabled: true }\n  p1: { enabled: true }\n  p2: { enabled: true }\n"),
		"db: bound to 'p2' by platform.state.default.yaml (this office's platform.state.yaml binds none)") {
		t.Fatalf("running both: the product's note is missing")
	}
	// the product never starts a provider the office switched off: running neither, it is refused
	_, errb, code = run(t, fixture(t, files(plain), stateHead+"  a: { enabled: true }\n  p2: { enabled: false }\n"))
	if code != 1 || !strings.Contains(errb, "capability 'db' has 2 eligible providers (p1, p2) and no rule to choose") {
		t.Fatalf("switched-off product provider: code %d err %q", code, errb)
	}
	// an office binding that cannot be met is refused, never replaced by the product's
	_, errb, code = run(t, fixture(t, files(plain), stateHead+"  a: { enabled: true }\nbindings:\n  db: p9\n"))
	if code != 1 || !strings.Contains(errb, "db: platform.state.yaml binds 'p9', which is not an eligible provider (p1, p2)") {
		t.Fatalf("unmeetable office binding: code %d err %q", code, errb)
	}
	// the office's own binding wins
	out, _, code = run(t, fixture(t, files(plain), stateHead+"  a: { enabled: true }\nbindings:\n  db: { provider: p1 }\n"))
	if code != 0 || out != "platform-base p1\napps a\n" {
		t.Fatalf("office binding over product: code %d out %q", code, out)
	}
	// the consumer's default_provider wins
	out, _, code = run(t, fixture(t, files(`"use":[{"capability":"db","default_provider":"p1"}]`), stateHead+"  a: { enabled: true }\n"))
	if code != 0 || out != "platform-base p1\napps a\n" {
		t.Fatalf("default_provider over product: code %d out %q", code, out)
	}
	// a product binding that names no eligible provider decides nothing: the ambiguity is refused
	bad := files(plain)
	bad["platform.state.default.yaml"] = stateHead + "  a: { enabled: true }\nproduct_bindings:\n  db: p9\n"
	_, errb, code = run(t, fixture(t, bad, stateHead+"  a: { enabled: true }\n"))
	if code != 1 || !strings.Contains(errb, "capability 'db' has 2 eligible providers (p1, p2) and no rule to choose") {
		t.Fatalf("bad product binding: code %d err %q", code, errb)
	}
}

func TestConflictNamesBoth(t *testing.T) {
	repo := fixture(t, map[string]string{
		"apps/a/app.json":          manifest("a", 3, `"use":[{"capability":"db","strength":"conflicts"}]`),
		"platform-base/p/app.json": manifest("p", 1, `"capabilities":[{"name":"db"}]`),
	}, stateHead+"  a: { enabled: true }\n  p: { enabled: true }\n")
	_, errb, code := run(t, repo)
	if code != 1 || !strings.Contains(errb, "  ERROR conflict: 'a' and 'p' cannot both be enabled (a declares conflicts with 'db') — disable one in platform.state.yaml") {
		t.Fatalf("code %d err %q", code, errb)
	}
}

func TestCycleIsNamed(t *testing.T) {
	repo := fixture(t, map[string]string{
		"apps/a/app.json": manifest("a", 3, `"use":[{"capability":"cb"}],"capabilities":[{"name":"ca"}]`),
		"apps/b/app.json": manifest("b", 3, `"use":[{"capability":"ca"}],"capabilities":[{"name":"cb"}]`),
	}, stateHead+"  a: { enabled: true }\n")
	_, errb, code := run(t, repo)
	if code != 1 || !strings.Contains(errb, "  ERROR dependency CYCLE: a -> b -> a (break it with dependency:'weak')") {
		t.Fatalf("code %d err %q", code, errb)
	}
}

func TestMissingCapabilityAndTheLegacyBridge(t *testing.T) {
	files := map[string]string{"apps/a/app.json": manifest("a", 3, `"use":[{"capability":"mail"}]`)}
	_, errb, code := run(t, fixture(t, files, stateHead+"  a: { enabled: true }\n"))
	if code != 1 || !strings.Contains(errb, "  ERROR a: requires capability 'mail' — no provider in catalog and not declared in platform/legacy-capabilities.yaml") {
		t.Fatalf("missing: code %d err %q", code, errb)
	}
	files["platform/legacy-capabilities.yaml"] = "mail: mailserver\n"
	out, errb, code := run(t, fixture(t, files, stateHead+"  a: { enabled: true }\n"))
	if code != 0 || out != "apps a\n" || strings.Contains(errb, "ERROR") {
		t.Fatalf("bridged: code %d out %q err %q", code, out, errb)
	}
}

func TestDispositionShapes(t *testing.T) {
	cases := []struct {
		yaml, want string
	}{
		{"x:", "disabled"},
		{"x: {}", "disabled"},
		{"x: { enabled: true }", "enabled"},
		{"x: { enabled: false }", "disabled"},
		{"x: { state: enabled, by: cli }", "enabled"},
		{"x: { state: ' Archived ' }", "archived"},
		{"x: { state: bogus, enabled: true }", "enabled"},
		{"x: { enabled: 'false' }", "enabled"}, // Python truth: a non-empty string is true
		{"x: { enabled: 0 }", "disabled"},
		{"x: yes", "disabled"}, // not a mapping: no `state`, no `enabled`
		{"x: { state: '', enabled: true }", "enabled"},
		{"x: { state: \"\\x1cenabled\" }", "enabled"}, // str.strip() takes \x1c-\x1f too
		{"x: { state: yes }", ""},                     // .strip() of a bool: where Python raises
		{"x: { state: [enabled] }", ""},
	}
	for _, c := range cases {
		v, err := yamlish.Unmarshal([]byte(c.yaml))
		if err != nil {
			t.Fatal(err)
		}
		e, _ := v.(*yamlish.Map).Get("x")
		got, err := Disposition(e)
		if got != c.want || (err != nil) != (c.want == "") {
			t.Errorf("%s: disposition %q (%v), want %q", c.yaml, got, err, c.want)
		}
	}
}

func TestLegacyAppIDIsNormalised(t *testing.T) {
	repo := fixture(t, map[string]string{"apps/dgo-extend/app.json": manifest("dgo-extend", 3, "")},
		stateHead+"  offices: { enabled: true }\n")
	out, errb, code := run(t, repo)
	if code != 0 || out != "apps dgo-extend\n" || !strings.Contains(errb, "legacy app id 'offices' is 'dgo-extend' now") {
		t.Fatalf("code %d out %q err %q", code, out, errb)
	}
}

func TestStateRefusals(t *testing.T) {
	files := map[string]string{"apps/a/app.json": manifest("a", 3, "")}
	_, errb, code := run(t, fixture(t, files, "schema_version: 2\napps: {}\n"))
	if code != 1 || !strings.Contains(errb, "FATAL platform.state.yaml schema_version 2 unsupported (expected 1)") {
		t.Fatalf("schema: code %d err %q", code, errb)
	}
	// missing on a checkout that has compiled before → refused (a temp dir is no git repo, so no ORIG_HEAD)
	repo := fixture(t, files, "")
	os.Mkdir(filepath.Join(repo, ".generated"), 0o755)
	_, errb, code = run(t, repo)
	if code != 1 || !strings.Contains(errb, "FATAL platform.state.yaml is missing on a checkout that has compiled before") {
		t.Fatalf("compiled-before: code %d err %q", code, errb)
	}
	// a real first run → created from the tracked default, said on stdout
	repo = fixture(t, files, "")
	os.WriteFile(filepath.Join(repo, "platform.state.default.yaml"), []byte(stateHead+"  a: { enabled: true }\n"), 0o644)
	out, _, code := run(t, repo)
	if code != 0 || !strings.HasPrefix(out, "  info  platform.state.yaml: created from platform.state.default.yaml (this checkout's first run)\n") || !strings.HasSuffix(out, "apps a\n") {
		t.Fatalf("first run: code %d out %q", code, out)
	}
	if _, err := os.Stat(filepath.Join(repo, "platform.state.yaml")); err != nil {
		t.Fatal("the state file must have been created")
	}
}

func TestCatalogRefusals(t *testing.T) {
	// the manifest's path as Python's relative_to prints it: in this OS's separators
	app, base := filepath.Join("apps", "a", "app.json"), filepath.Join("platform-base", "a", "app.json")
	_, errb, code := run(t, fixture(t, map[string]string{"apps/a/app.json": manifest("b", 3, "")}, stateHead))
	if code != 1 || !strings.Contains(errb, "FATAL "+app+": id 'b' != directory 'a'") {
		t.Fatalf("id: code %d err %q", code, errb)
	}
	_, errb, code = run(t, fixture(t, map[string]string{"platform-base/a/app.json": manifest("a", 3, "")}, stateHead))
	if code != 1 || !strings.Contains(errb, "FATAL "+base+": layer 3 manifest is in platform-base/, which holds layer(s) 1, 2 — move it to apps/") {
		t.Fatalf("layer: code %d err %q", code, errb)
	}
	_, errb, code = run(t, fixture(t, map[string]string{"apps/a/app.json": "{not json"}, stateHead))
	if code != 1 || !strings.Contains(errb, "FATAL "+app+": invalid JSON") {
		t.Fatalf("json: code %d err %q", code, errb)
	}
}

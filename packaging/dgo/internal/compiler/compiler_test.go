package compiler

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── the oracle: reconcile.py on the real checkout ─────────────────────────────────────────────────

func repoRoot(t *testing.T) string {
	d, _ := os.Getwd()
	for {
		if _, err := os.Stat(filepath.Join(d, "platform", "manager", "reconcile.py")); err == nil {
			if _, err := os.Stat(filepath.Join(d, "platform.state.yaml")); err == nil {
				return d
			}
		}
		parent := filepath.Dir(d)
		if parent == d {
			t.Skip("not inside the checkout")
		}
		d = parent
	}
}

func python(t *testing.T) []string {
	for _, c := range [][]string{{"python3"}, {"python"}, {"py", "-3"}} {
		if _, err := exec.LookPath(c[0]); err != nil {
			continue
		}
		if exec.Command(c[0], append(c[1:], "-c", "import yaml")...).Run() == nil {
			return c
		}
	}
	return nil
}

// TestEnabledAppsMatchesPython runs `reconcile.py enabled-apps` on this checkout and the Go verb on
// the same checkout: same stdout bytes, same exit code, same error lines (as a set — Python iterates
// a set to build its frontier, so its error ORDER is not stable across runs).
func TestEnabledAppsMatchesPython(t *testing.T) {
	py := python(t)
	if py == nil {
		t.Skip("no python with PyYAML on PATH")
	}
	root := repoRoot(t)
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
	}
	for _, c := range cases {
		v, err := yamlish.Unmarshal([]byte(c.yaml))
		if err != nil {
			t.Fatal(err)
		}
		e, _ := v.(*yamlish.Map).Get("x")
		if got := Disposition(e); got != c.want {
			t.Errorf("%s: disposition %s, want %s", c.yaml, got, c.want)
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
	_, errb, code := run(t, fixture(t, map[string]string{"apps/a/app.json": manifest("b", 3, "")}, stateHead))
	if code != 1 || !strings.Contains(errb, "FATAL apps/a/app.json: id 'b' != directory 'a'") {
		t.Fatalf("id: code %d err %q", code, errb)
	}
	_, errb, code = run(t, fixture(t, map[string]string{"platform-base/a/app.json": manifest("a", 3, "")}, stateHead))
	if code != 1 || !strings.Contains(errb, "FATAL platform-base/a/app.json: layer 3 manifest is in platform-base/, which holds layer(s) 1, 2 — move it to apps/") {
		t.Fatalf("layer: code %d err %q", code, errb)
	}
	_, errb, code = run(t, fixture(t, map[string]string{"apps/a/app.json": "{not json"}, stateHead))
	if code != 1 || !strings.Contains(errb, "FATAL apps/a/app.json: invalid JSON") {
		t.Fatalf("json: code %d err %q", code, errb)
	}
}

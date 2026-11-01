package compiler

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// TestValidateMatchesPython: `reconcile.py validate` and the Go verb on this checkout — same stdout
// (the OK line names every provided capability, sorted), same exit code.
func TestValidateMatchesPython(t *testing.T) {
	py := python(t)
	if py == nil {
		t.Skip("no python with PyYAML on PATH")
	}
	root := repoRoot(t)
	cmd := exec.Command(py[0], append(py[1:], filepath.Join(root, "platform", "manager", "reconcile.py"), "validate")...)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	var pyOut bytes.Buffer
	cmd.Stdout = &pyOut
	pyCode := 0
	if err := cmd.Run(); err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			pyCode = ee.ExitCode()
		} else {
			t.Fatal(err)
		}
	}
	var goOut, goErr bytes.Buffer
	goCode := ValidateVerb(root, &goOut, &goErr)
	pyStdout := strings.ReplaceAll(pyOut.String(), "\r\n", "\n")
	if goCode != pyCode || goOut.String() != pyStdout {
		t.Fatalf("go (%d):\n%s\npython (%d):\n%s\ngo stderr: %s", goCode, goOut.String(), pyCode, pyStdout, goErr.String())
	}
	t.Logf("%s", strings.TrimSpace(goOut.String())[:60])
}

// validation runs a fixture and returns the "  - …" error lines (empty when valid).
func validation(t *testing.T, manifests map[string]string) []string {
	t.Helper()
	repo := fixture(t, manifests, stateHead)
	var out, errb bytes.Buffer
	code := ValidateVerb(repo, &out, &errb)
	var errs []string
	for _, l := range strings.Split(out.String(), "\n") {
		if strings.HasPrefix(l, "  - ") {
			errs = append(errs, strings.TrimPrefix(l, "  - "))
		}
	}
	if (code != 0) != (len(errs) > 0) {
		t.Fatalf("exit %d with %d errors: %s %s", code, len(errs), out.String(), errb.String())
	}
	if code != 0 && !strings.HasPrefix(out.String(), "MANIFEST VALIDATION FAILED:\n") {
		t.Fatalf("a failure must start with the FAILED line: %q", out.String())
	}
	return errs
}

func expectErrs(t *testing.T, got []string, want ...string) {
	t.Helper()
	for _, w := range want {
		found := false
		for _, g := range got {
			if g == w {
				found = true
			}
		}
		if !found {
			t.Errorf("missing error %q\n got: %s", w, strings.Join(got, "\n      "))
		}
	}
	if len(got) != len(want) {
		t.Errorf("%d errors, want %d:\n      %s", len(got), len(want), strings.Join(got, "\n      "))
	}
}

func TestValidateAcceptsAValidManifest(t *testing.T) {
	errs := validation(t, map[string]string{"apps/a/app.json": manifest("a", 3, `"capabilities":[{"name":"x"}]`)})
	expectErrs(t, errs)
}

func TestValidateRequiredUnknownAndTopLevelTypes(t *testing.T) {
	errs := validation(t, map[string]string{"apps/a/app.json": `{"id":"a","layer":3,"kind":"service","title":"plain","colour":"#fff","system":1}`})
	expectErrs(t, errs,
		"a: unknown field 'colour'",
		"a: field 'system' must be boolean, got int",
		"a: field 'title' must be object, got str")
	errs = validation(t, map[string]string{"apps/a/app.json": `{"id":"a","layer":3,"kind":"service"}`})
	expectErrs(t, errs, "a: missing required field 'title'")
}

func TestValidateSubObjectRequiredKeyAndNestedEnumAndType(t *testing.T) {
	errs := validation(t, map[string]string{"apps/a/app.json": manifestRaw("a", 3, `"title":{"en":"A"},"kind":"service","routing":[{"host":"a.localhost","auth":"SSO"},{"host":"b.localhost","auth":null},{"host":12}]`)})
	// an explicit null fails BOTH walks in Python (the enum's and the type's) — two lines, as there
	expectErrs(t, errs,
		"a: field 'title' is missing required key 'he'",
		"a: field 'routing'[0].auth must be one of sso|none, got 'SSO'",
		"a: field 'routing'[1].auth must be one of sso|none, got None",
		"a: field 'routing'[1].auth must be string, got NoneType",
		"a: field 'routing'[2].host must be string, got int")
}

// A layer outside its root never reaches validate: load_catalog refuses it first (TestCatalogRefusals),
// so the validator's own "layer must be 1|2|3" is unreachable on a real tree — kind and strength are not.
func TestValidateKindAndStrength(t *testing.T) {
	errs := validation(t, map[string]string{"apps/a/app.json": manifestRaw("a", 3, `"title":{"he":"א"},"kind":"widget","use":[{"capability":"db","strength":"maybe"}]`)})
	expectErrs(t, errs,
		"a: field 'kind' must be one of service|domain|adapter|blueprint|library|tool, got 'widget'",
		"a: invalid kind 'widget'",
		"a: field 'use'[0].strength must be one of requires|wants|requisite|binds_to|conflicts, got 'maybe'",
		"a: use[db] bad strength 'maybe'")
}

func TestValidateRouteAndTileConflicts(t *testing.T) {
	errs := validation(t, map[string]string{
		"apps/a/app.json": manifest("a", 3, `"routing":[{"host":"x.localhost","module":{"id":"m"}}]`),
		"apps/b/app.json": manifest("b", 3, `"routing":[{"host":"x.localhost","module":{"id":"m"}}]`),
	})
	expectErrs(t, errs,
		"route conflict: host 'x.localhost' claimed by a, b — only one app can own an edge route",
		"tile conflict: console module 'm' claimed by a, b — the shell would route one app's tile to the other")
}

func TestValidateAgentBrief(t *testing.T) {
	big := strings.Repeat("x", maxBriefBytes+1)
	errs := validation(t, map[string]string{
		"apps/a/app.json": manifest("a", 3, `"agent":{"context":""}`),
		"apps/b/app.json": manifest("b", 3, `"agent":{"context":"../secret.md"}`),
		"apps/c/app.json": manifest("c", 3, `"agent":{"context":"AGENT.md"}`),
		"apps/d/app.json": manifest("d", 3, `"agent":{"context":"AGENT.md"}`),
		"apps/d/AGENT.md": big,
		"apps/e/app.json": manifest("e", 3, `"agent":{"context":"AGENT.md"}`),
		"apps/e/AGENT.md": "short brief\n",
	})
	expectErrs(t, errs,
		"a: agent.context must name the brief file (convention: AGENT.md)",
		"b: agent.context must be a path INSIDE apps/b/, got '../secret.md'",
		"c: agent.context 'AGENT.md' does not exist — the agent would never learn how to operate this app",
		"d: agent.context 'AGENT.md' is 6001 bytes, over the 6000 budget — this file is injected into EVERY agent session, so it buys its size from every other app's brief. Cut it to what a caller cannot read off the manifest (what the app is FOR, its vocabulary, its traps).")
}

func TestValidateCompose(t *testing.T) {
	errs := validation(t, map[string]string{
		"apps/a/app.json":           manifest("a", 3, `"compose":"docker-compose.yml"`),
		"apps/b/app.json":           manifest("b", 3, `"compose":"docker-compose.yml"`),
		"apps/b/docker-compose.yml": "services: {}\n",
		"apps/c/app.json":           manifestRaw("c", 3, `"title":{"he":"ג"},"kind":"blueprint","compose":"docker-compose.yml"`),
		"apps/c/docker-compose.yml": "services: {}\n",
	})
	expectErrs(t, errs,
		"a: compose 'docker-compose.yml' not found",
		"c: kind=blueprint must not declare compose")
}

func TestValidateKeepsPythonsBoolIsIntQuirk(t *testing.T) {
	// isinstance(True, int) is True in Python, so a boolean where the schema says integer passes
	// there — and must pass here, or the two validators disagree on a real manifest one day.
	errs := validation(t, map[string]string{"apps/a/app.json": manifest("a", 3, `"progress_deadline_seconds":true`)})
	expectErrs(t, errs)
	errs = validation(t, map[string]string{"apps/a/app.json": manifest("a", 3, `"progress_deadline_seconds":1.5`)})
	expectErrs(t, errs, "a: field 'progress_deadline_seconds' must be integer, got float")
}

func TestEnabledAppsRefusesAnInvalidManifestFirst(t *testing.T) {
	repo := fixture(t, map[string]string{"apps/a/app.json": `{"id":"a","layer":3,"kind":"service"}`}, stateHead+"  a: { enabled: true }\n")
	out, _, code := run(t, repo)
	if code != 1 || !strings.HasPrefix(out, "MANIFEST VALIDATION FAILED:\n  - a: missing required field 'title'\n") {
		t.Fatalf("code %d out %q", code, out)
	}
}

// manifestRaw builds a manifest from id, layer and raw extra JSON; a key repeated in extra (layer,
// kind, title) wins, as the last key does in both json libraries.
func manifestRaw(id string, layer int, extra string) string {
	return `{"id":"` + id + `","layer":` + strconv.Itoa(layer) + `,` + extra + `}`
}

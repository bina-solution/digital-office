package store

// Second-reader probes (review of core-store.patch, scratchpad/rvstore-probe). Each test asserts the
// behaviour the reviewer expected; each failed before the review round and passes after it. Changed
// from the reviewer's copy only where the fix changed an interface or turned parity into a refusal:
// verify() takes the channel (its base URL) — "" for this store's; F10 passes the --version a signed
// build now requires; F7 and F12 assert the deliberate divergence from catalog.py — a refusal, or a
// link left out — where the reviewer's copy demanded parity with what catalog.py does wrong (F6 did
// too, until catalog.py counted workflows by exact suffix: DGO-609, parity again). Since
// the index became a document of the trust chain (packaging/trust), a signed build takes the chain — a
// root, its keys.json and the key it lists (newChain) — where the reviewer's copy took one key.

import (
	"archive/zip"
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// F1: an older index, still validly signed, replayed by a mirror after the office has locked a
// newer one — and an index signed for another channel's URL. verify and install accept both.
func TestProbeReplayOfAnOlderIndexIsRefused(t *testing.T) {
	c := newChain(t)
	root := c.rootFile
	src := func(v string) string {
		return tree(t, map[string]string{"apps/a/app.json": manifest("a", `"version":"`+v+`"`)})
	}
	newer, older, other := t.TempDir(), t.TempDir(), t.TempDir()
	if _, err := Build(Options{Root: repoRoot(t), Source: src("1.1.0"), Out: newer, Key: c.key, Keys: c.keys, Version: "2.0.0"}); err != nil {
		t.Fatal(err)
	}
	if _, err := Build(Options{Root: repoRoot(t), Source: src("1.0.0"), Out: older, Key: c.key, Keys: c.keys, Version: "1.0.0"}); err != nil {
		t.Fatal(err)
	}
	if _, err := Build(Options{Root: repoRoot(t), Source: src("0.0.1"), Out: other, Key: c.key, Keys: c.keys, Version: "9.0.0",
		BaseURL: "https://staging.example.org/some-test-channel"}); err != nil {
		t.Fatal(err)
	}
	lock := filepath.Join(t.TempDir(), "dgo.lock")
	if so, se, code := dryRun(t, newer, root, "--lock", lock, "a"); code != 0 {
		t.Fatalf("newer: %d\n%s%s", code, so, se)
	}
	before, _ := os.ReadFile(lock)
	var out, errb bytes.Buffer
	vcode := verify(older, root, "", &out, &errb)
	so, se, icode := dryRun(t, older, root, "--lock", lock, "a")
	after, _ := os.ReadFile(lock)
	if vcode == 0 || icode == 0 {
		t.Errorf("index 1.0.0 replayed after 2.0.0 was locked: verify exit %d, install exit %d\n%s%s\nlock before:\n%s\nlock after:\n%s",
			vcode, icode, so, se, before, after)
	}
	out.Reset()
	errb.Reset()
	if code := verify(other, root, "", &out, &errb); code == 0 {
		t.Errorf("an index signed for https://staging.example.org/some-test-channel/index.json verifies as this store's: exit 0\n%s", out.String())
	}
}

// F2: MVS — the selected version of an app needs a capability that only an OLDER version of the
// same app provides. Nothing provides it to a@2.0.0; the plan must refuse.
func TestProbeASelfProvidedCapabilityTheSelectedVersionDropped(t *testing.T) {
	t.Parallel()
	dir, root := signedIndex(t, `{}`, ent("a@1.0.0", "x", ""), ent("a@2.0.0", "", "x"))
	so, se, code := dryRun(t, dir, root, "a")
	if code == 0 {
		t.Errorf("a@2.0.0 requires x, which only a@1.0.0 provides — planned anyway (exit 0):\n%s%s", so, se)
	}
	// the same reached through another app: r needs y and w; b (for w) needs y2, which only a@2.0.0
	// provides, so MVS raises a to 2.0.0 — and a@2.0.0 requires x, which only a@1.0.0 provides.
	dir, root = signedIndex(t, `{}`, ent("r@1.0.0", "", "y w"), ent("a@1.0.0", "x y", ""), ent("a@2.0.0", "y y2", "x"),
		ent("b@1.0.0", "w", "y2"))
	so, se, code = dryRun(t, dir, root, "r")
	if code == 0 {
		t.Errorf("r: a@2.0.0 is selected and requires x, which only a@1.0.0 provides — planned anyway (exit 0):\n%s%s", so, se)
	}
}

// F3 (design): the synthesized minimum is "the lowest version that provides the capability" — so a
// pre-release (or the oldest release ever published) is installed although a release exists.
func TestProbeAPreReleaseIsChosenOverItsRelease(t *testing.T) {
	t.Parallel()
	dir, root := signedIndex(t, `{}`, ent("a@1.0.0", "", "c"), ent("p@1.0.0-alpha.1", "c", ""), ent("p@1.0.0", "c", ""), ent("p@3.2.0", "c", ""))
	so, se, code := dryRun(t, dir, root, "a")
	if code != 0 || strings.Contains(so, "1.0.0-alpha.1") {
		t.Errorf("the plan installs a pre-release of p although p 1.0.0 and 3.2.0 are in the index (exit %d):\n%s%s", code, so, se)
	}
	dir, root = signedIndex(t, `{}`, ent("p@3.2.0", "c", ""), ent("p@3.3.0-rc.1", "c", ""))
	so, se, code = dryRun(t, dir, root, "p")
	if strings.Contains(so, "3.3.0-rc.1") {
		t.Errorf("an unpinned request installs the release candidate over the release 3.2.0 (exit %d):\n%s%s", code, so, se)
	}
}

// F4: compose service keys PyYAML reads as non-strings (YAML 1.1 bool / int keys) — catalog.py
// publishes True / 8080 (and "(built from source: True)"), this build "true" / "8080".
func TestProbeComposeServiceKeysThatAreNotStrings(t *testing.T) {
	t.Parallel()
	for name, compose := range map[string]string{
		"bool key": "services:\n  yes:\n    build: .\n",
		"int key":  "services:\n  8080:\n    image: x\n",
	} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			built(t, tree(t, map[string]string{
				"apps/a/app.json": manifest("a", `"compose":"c.yml"`),
				"apps/a/c.yml":    compose,
			}))
		})
	}
}

// F5: the MISSING line — the one per-entry line entryLines() does not compare.
func TestProbeMissingLinesAreCatalogPys(t *testing.T) {
	t.Parallel()
	py := oracle(t)
	if py == nil {
		t.Skip("DGO_SKIP_ORACLE=1")
	}
	dir, c := signedTree(t)
	root := c.rootFile
	if err := os.Remove(filepath.Join(dir, artifactsDir, "a-0.0.0.zip")); err != nil {
		t.Fatal(err)
	}
	pyText, pyCode, err := catalogPy(repoRoot(t), py, "verify", "--insecure", filepath.Join(dir, indexName))
	if err != nil {
		t.Fatal(err)
	}
	var goText, goErr bytes.Buffer
	goCode := verify(dir, root, "", &goText, &goErr)
	pick := func(s string) string {
		var out []string
		for _, l := range strings.Split(s, "\n") {
			if strings.HasPrefix(l, "  MISSING") {
				out = append(out, l)
			}
		}
		return strings.Join(out, "\n")
	}
	if a, b := pick(pyText), pick(goText.String()); a != b || pyCode != goCode {
		t.Errorf("MISSING lines differ (exit py %d, dgo %d)\n catalog.py: %s\n dgo:        %s", pyCode, goCode, a, b)
	}
}

// F6: workflows — catalog.py's pathlib glob is case-insensitive on Windows, so its count of an
// upper-case .JSON depended on the OS that builds, and this build refused the name. Both now match
// exact suffixes (DGO-609): an upper-case .JSON or .WORKFLOW.TS is no workflow, on either side, on
// every OS.
func TestProbeWorkflowCountOfAnUpperCaseJSON(t *testing.T) {
	t.Parallel()
	p := built(t, tree(t, map[string]string{
		"apps/a/app.json":           `{"id":"a","layer":3,"title":{"he":"x"},"kind":"blueprint","blueprints":{"n8n":"wf"}}`,
		"apps/a/wf/ONE.JSON":        "{}",
		"apps/a/wf/TWO.WORKFLOW.TS": "export {}",
	}))
	if got := field(t, p.ix, "a", "automations"); got != `{"n8n":true,"requires_stdlib":null,"workflows":0}` {
		t.Errorf("automations = %s", got)
	}
}

// F7: an absolute blueprints.n8n — catalog.py's pathlib join reads OUTSIDE the app dir. This build
// refuses the path (a deliberate divergence, with the links and the git failure: nothing outside an
// app is read); catalog.py's count of the files outside is asserted.
func TestProbeAnAbsoluteBlueprintDir(t *testing.T) {
	t.Parallel()
	ext := t.TempDir()
	for _, n := range []string{"w1.json", "w2.json"} {
		if err := os.WriteFile(filepath.Join(ext, n), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	src := tree(t, map[string]string{
		"apps/a/app.json": fmt.Sprintf(`{"id":"a","layer":3,"title":{"he":"x"},"kind":"blueprint","blueprints":{"n8n":%q}}`, filepath.ToSlash(ext)),
	})
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: filepath.Join(t.TempDir(), "index")}); err == nil || !strings.Contains(err.Error(), "leaves the app's directory") {
		t.Errorf("an absolute blueprints.n8n: err = %v", err)
	}
	if py := oracle(t); py != nil {
		pyOut := t.TempDir()
		if err := pyIndex(repoRoot(t), py, filepath.Join(src, "apps"), pyOut); err != nil {
			t.Fatal(err)
		}
		if got := field(t, readJSON(t, filepath.Join(pyOut, "index-v1.json")), "a", "automations"); !strings.Contains(got, `"workflows":2`) {
			t.Errorf("catalog.py counts %s — the two files outside the app were expected", got)
		}
	}
}

func gitIn(t *testing.T, dir string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir, "-c", "core.autocrlf=false"}, args...)...)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
}

func zipNames(t *testing.T, p string) []string {
	t.Helper()
	r, err := zip.OpenReader(p)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	var out []string
	for _, f := range r.File {
		out = append(out, f.Name)
	}
	return out
}

// F8: "byte-reproducible" — the same tree, flags and key, but the builder's git config differs
// (core.quotepath=false, common for anyone with non-ASCII names): a different artifact and index.
func TestProbeTheArtifactDoesNotDependOnGitConfig(t *testing.T) {
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/a/שלום.txt": "x"})
	gitIn(t, src, "init", "-q")
	gitIn(t, src, "add", ".")
	c := newChain(t)
	one, two := t.TempDir(), t.TempDir()
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: one, Key: c.key, Keys: c.keys, Version: "1.0.0"}); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_CONFIG_COUNT", "1")
	t.Setenv("GIT_CONFIG_KEY_0", "core.quotepath")
	t.Setenv("GIT_CONFIG_VALUE_0", "false")
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: two, Key: c.key, Keys: c.keys, Version: "1.0.0"}); err != nil {
		t.Fatal(err)
	}
	if a, b := snapshot(t, one), snapshot(t, two); a != b {
		t.Errorf("same tree, flags, key — different bytes:\n%s\n---\n%s\nmembers: %v vs %v", a, b,
			zipNames(t, filepath.Join(one, artifactsDir, "a-0.0.0.zip")), zipNames(t, filepath.Join(two, artifactsDir, "a-0.0.0.zip")))
	}
}

// F9: any git failure (here: git's own "dubious ownership" refusal, as on a checkout owned by
// another user) silently becomes a directory walk that packs what git does NOT track.
func TestProbeAGitFailureDoesNotPublishUntrackedFiles(t *testing.T) {
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/a/.env": "API_TOKEN=secret", "apps/a/key.pem": "PRIVATE"})
	gitIn(t, src, "init", "-q")
	gitIn(t, src, "add", "apps/a/app.json")
	out := t.TempDir()
	t.Setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
	if o, err := exec.Command("git", "-C", filepath.Join(src, "apps", "a"), "ls-files").CombinedOutput(); err == nil {
		t.Skipf("git did not refuse: %s", o)
	} else {
		t.Logf("git says: %s", strings.TrimSpace(string(o)))
	}
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: out}); err != nil {
		t.Logf("build refused: %v", err)
		return
	}
	names := zipNames(t, filepath.Join(out, artifactsDir, "a-0.0.0.zip"))
	if len(names) != 1 {
		t.Errorf("git failed and the build published the untracked files: %v", names)
	}
	if py := python(t); py != nil {
		pyOut := t.TempDir()
		if err := pyIndex(repoRoot(t), py, filepath.Join(src, "apps"), pyOut); err != nil {
			t.Fatal(err)
		}
		t.Logf("catalog.py under the same git refusal packs: %v", zipNames(t, filepath.Join(pyOut, "artifacts", "a-0.0.0.zip")))
	}
}

// F10: a build writes artifacts in place, in the published directory: a build that fails (here: a
// second app's compose is refused) has already rewritten the first app's artifact under the still
// published, still signed index — which now fails its own verify.
func TestProbeAFailedRebuildLeavesThePublishedTreeIntact(t *testing.T) {
	t.Parallel()
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/a/notes.txt": "v1"})
	c := newChain(t)
	out := t.TempDir()
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: out, Key: c.key, Keys: c.keys, Version: "1.0.0"}); err != nil {
		t.Fatal(err)
	}
	var o1, e1 bytes.Buffer
	if code := verify(out, c.rootFile, "", &o1, &e1); code != 0 {
		t.Fatalf("first build does not verify: %s%s", o1.String(), e1.String())
	}
	// the next release: a's notes change, and a new app b has a compose this build refuses
	os.WriteFile(filepath.Join(src, "apps", "a", "notes.txt"), []byte("v2"), 0o644)
	os.MkdirAll(filepath.Join(src, "apps", "b"), 0o755)
	os.WriteFile(filepath.Join(src, "apps", "b", "app.json"), []byte(manifest("b", `"compose":"c.yml"`)), 0o644)
	os.WriteFile(filepath.Join(src, "apps", "b", "c.yml"), []byte("services:\n  s:\n    ports:\n      - target: 80\n"), 0o644)
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: out, Key: c.key, Keys: c.keys, Version: "1.1.0"}); err == nil {
		t.Fatal("expected the second build to fail")
	} else {
		t.Logf("second build: %v", err)
	}
	var o2, e2 bytes.Buffer
	if code := verify(out, c.rootFile, "", &o2, &e2); code != 0 {
		t.Errorf("a FAILED build broke the published index: verify exit %d\n%s%s", code, o2.String(), e2.String())
	}
}

// F12 (Windows): a directory junction inside an app dir (no privilege needed to make one), outside
// git — catalog.py's os.walk descends into it (Python 3.12's islink() is False for a junction) and
// packs files from OUTSIDE the app. This build leaves the junction out and names it (a deliberate
// divergence, filed against catalog.py); catalog.py's packing of the outside file is asserted.
func TestProbeAJunctionInAnAppDir(t *testing.T) {
	t.Parallel()
	if _, err := exec.LookPath("cmd"); err != nil {
		t.Skip("windows only")
	}
	outside := t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "secret.txt"), []byte("TOKEN=1"), 0o644); err != nil {
		t.Fatal(err)
	}
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", "")})
	if out, err := exec.Command("cmd", "/c", "mklink", "/J", filepath.Join(src, "apps", "a", "ext"), outside).CombinedOutput(); err != nil {
		t.Skipf("mklink /J: %v %s", err, out)
	}
	p := both(t, src, nil)
	if goNames := zipNames(t, filepath.Join(p.out, artifactsDir, "a-0.0.0.zip")); strings.Join(goNames, ",") != "a/app.json" || !p.links["a/ext"] {
		t.Errorf("a junction: this build packs %v and left out %v", goNames, p.links)
	}
	if p.pyIx != nil {
		if pyNames := zipNames(t, filepath.Join(p.pyOut, "artifacts", "a-0.0.0.zip")); !strings.Contains(strings.Join(pyNames, ","), "a/ext/secret.txt") {
			t.Errorf("catalog.py was expected to follow the junction (the finding filed against it): %v", pyNames)
		}
	}
}

// F13: `--source` is catalog.py's flag name with another meaning. catalog.py: "directory of app
// folders to publish"; here: a tree that holds apps/. Given catalog.py's meaning, the build signs and
// publishes an EMPTY index and exits 0.
func TestProbeSourceAsCatalogPyMeansIt(t *testing.T) {
	t.Parallel()
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/b/app.json": manifest("b", "")})
	out := t.TempDir()
	var so, se bytes.Buffer
	code := indexVerb(repoRoot(t), []string{"build", out, "--source", filepath.Join(src, "apps")}, &so, &se)
	if code == 0 && strings.Contains(so.String(), "0 entry(ies)") {
		t.Errorf("--source <dir of app folders> (catalog.py's meaning): exit 0, an empty index:\n%s%s", so.String(), se.String())
	}
	if py := python(t); py != nil {
		pyOut := t.TempDir()
		if err := pyIndex(repoRoot(t), py, filepath.Join(src, "apps"), pyOut); err != nil {
			t.Fatal(err)
		}
		t.Logf("catalog.py build --source %s publishes %d entries", filepath.Join(src, "apps"), len(entries(readJSON(t, filepath.Join(pyOut, "index-v1.json")))))
	}
}

package store

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSemverPrecedence(t *testing.T) {
	t.Parallel()
	// SemVer 2.0.0 §11's own chain, numbers past one digit, and build metadata that does not order
	chain := []string{"1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
		"1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.9.0", "1.10.0", "1.11.0", "2.0.0", "10.0.0", "99999999999999999999.0.0"}
	for i := 1; i < len(chain); i++ {
		a, _ := parseSemver(chain[i-1])
		b, ok := parseSemver(chain[i])
		if !ok || a.compare(b) >= 0 || b.compare(a) <= 0 {
			t.Errorf("%s must order before %s", chain[i-1], chain[i])
		}
	}
	a, _ := parseSemver("1.0.0+build.1")
	b, _ := parseSemver("1.0.0+build.2")
	if a.compare(b) != 0 {
		t.Error("build metadata must not order")
	}
	for _, bad := range []string{"", "1.0", "1.0.0.0", "v1.0.0", "01.0.0", "1.0.0-01", "1.0.0-", "1.0.0+", "1.0.0-a..b", "1.0.0-a_b", "../x", "1.0.0/x"} {
		if _, ok := parseSemver(bad); ok {
			t.Errorf("%q is not SemVer", bad)
		}
	}
}

// ent is an index entry: "id@version", what it provides, what it uses ("c" requires c, "c?" only wants it).
func ent(idv, provides, uses string) string {
	id, v, _ := strings.Cut(idv, "@")
	var ps, us []string
	for _, p := range strings.Fields(provides) {
		ps = append(ps, fmt.Sprintf(`{"name":%q}`, p))
	}
	for _, u := range strings.Fields(uses) {
		strength := "requires"
		if strings.HasSuffix(u, "?") {
			strength, u = "wants", strings.TrimSuffix(u, "?")
		}
		us = append(us, fmt.Sprintf(`{"capability":%q,"strength":%q,"ops":[]}`, u, strength))
	}
	sum := sha256.Sum256([]byte(idv))
	return fmt.Sprintf(`{"id":%q,"version":%q,"provides":[%s],"uses":[%s],"artifact":{"url":"artifacts/%s-%s.zip","sha256":%q}}`,
		id, v, strings.Join(ps, ","), strings.Join(us, ","), id, v, hex.EncodeToString(sum[:]))
}

// signedIndex writes and signs an index of the entries — one that may hold several versions of an
// app, which a build of one tree never does — and returns its directory and root.
func signedIndex(t *testing.T, platform string, ents ...string) (string, string) {
	t.Helper()
	c := newChain(t)
	dir := t.TempDir()
	doc := fmt.Sprintf(`{"format":%q,"version":"1.0.0","platform":%s,"entries":[%s]}`, indexFormat, platform, strings.Join(ents, ","))
	if err := os.WriteFile(filepath.Join(dir, indexName), []byte(doc), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, keysName), c.keys, 0o644); err != nil {
		t.Fatal(err)
	}
	resign(t, dir, c.key, "1.0.0", defaultBaseURL)
	return dir, c.rootFile
}

// dryRun is `dgo index install --dry-run` as the CLI parses it.
func dryRun(t *testing.T, dir, root string, args ...string) (string, string, int) {
	t.Helper()
	var out, errb bytes.Buffer
	code := indexVerb(repoRoot(t), append([]string{"install", "--dry-run", "--index", dir, "--root", root}, args...), &out, &errb)
	return out.String(), errb.String(), code
}

// planLines are the plan's app lines, squeezed: "id version why".
func planLines(out string) string {
	var lines []string
	for _, l := range strings.Split(out, "\n") {
		if strings.HasPrefix(l, "  ") && !strings.HasPrefix(l, "  signature") && !strings.HasPrefix(l, "  platform") && !strings.Contains(l, "entry(ies)") {
			lines = append(lines, strings.Join(strings.Fields(l), " "))
		}
	}
	return strings.Join(lines, "\n")
}

// A built index, end to end: the request's hard uses pull their providers in, transitively; a weak
// one does not; what layers 1–2 provide is named, not installed.
func TestPlanPullsInProvidersAndLeavesThePlatformAlone(t *testing.T) {
	t.Parallel()
	out := filepath.Join(t.TempDir(), "index")
	c := newChain(t)
	_, err := Build(Options{Root: repoRoot(t), Out: out, Key: c.key, Keys: c.keys, Version: signedVersion, Source: tree(t, map[string]string{
		"platform-base/db/app.json":    `{"id":"db","layer":1,"title":{"he":"x"},"kind":"service","capabilities":[{"name":"sql","type":"protocol"}]}`,
		"platform-base/cache/app.json": `{"id":"cache","layer":1,"title":{"he":"x"},"kind":"service","capabilities":[{"name":"kv","type":"protocol"}]}`,
		"apps/a/app.json":              manifest("a", `"version":"1.0.0","use":[{"capability":"c"},{"capability":"sql"},{"capability":"w","strength":"wants"}]`),
		"apps/p/app.json":              manifest("p", `"version":"2.1.0","capabilities":[{"name":"c","type":"protocol"}],"use":[{"capability":"kv","strength":"binds_to"}]`),
		"apps/q/app.json":              manifest("q", `"version":"0.3.0","capabilities":[{"name":"w","type":"protocol"}]`),
	})})
	if err != nil {
		t.Fatal(err)
	}
	stdout, stderr, code := dryRun(t, out, c.rootFile, "a")
	if code != 0 {
		t.Fatalf("exit %d\n%s%s", code, stdout, stderr)
	}
	if got, want := planLines(stdout), "a v1.0.0 requested\np v2.1.0 c (a)"; got != want {
		t.Errorf("plan:\n%s\nwant:\n%s", got, want)
	}
	if !strings.Contains(stdout, "  platform: kv (cache), sql (db)\n") || !strings.HasSuffix(stdout, "dry run — nothing was written\n") {
		t.Errorf("output:\n%s", stdout)
	}
}

// Two providers that are both layers 1–2 refuse nothing: the plan installs neither and relies on the
// platform, and the office's compiler picks the one it runs when the app is placed (identity:
// authentik and forward-auth). An index app beside a platform provider is still refused.
func TestTwoPlatformProvidersAreThePlatforms(t *testing.T) {
	t.Parallel()
	dir, root := signedIndex(t, `{"identity":["authentik","forward-auth"]}`, ent("a@1.0.0", "", "identity"))
	stdout, stderr, code := dryRun(t, dir, root, "a")
	if code != 0 || planLines(stdout) != "a v1.0.0 requested" || !strings.Contains(stdout, "  platform: identity (authentik, forward-auth)\n") {
		t.Errorf("exit %d\n%s%s", code, stdout, stderr)
	}
}

// MVS: each app at the highest version the requirement graph reaches — and only what the selected
// versions need is installed (q is required by p@1.0.0 alone, which r@1.0.0's plan passes over).
func TestMVSSelectsTheHighestVersionReached(t *testing.T) {
	t.Parallel()
	dir, root := signedIndex(t, `{}`,
		ent("r@1.0.0", "", "ra rb"), ent("r@2.0.0", "", "ra"),
		ent("a@1.0.0", "ra", "c"), ent("b@1.0.0", "rb", "d"),
		ent("p@1.0.0", "c", "e"), ent("p@1.1.0", "c d", ""),
		ent("q@1.0.0", "e", ""))
	for req, want := range map[string]string{
		"r@1.0.0": "a v1.0.0 ra (r)\nb v1.0.0 rb (r)\np v1.1.0 c (a), d (b)\nr v1.0.0 requested",
		"r":       "a v1.0.0 ra (r)\np v1.0.0 c (a)\nq v1.0.0 e (p)\nr v2.0.0 requested",
	} {
		stdout, stderr, code := dryRun(t, dir, root, req)
		if got := planLines(stdout); code != 0 || got != want {
			t.Errorf("%s: exit %d\n%s\nwant:\n%s\n%s", req, code, got, want, stderr)
		}
	}
}

func TestPlanRefusesWhatItCannotResolve(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name, platform string
		ents           []string
		req, want      string
	}{
		{"no such app", `{}`, []string{ent("a@1.0.0", "", "")}, "zz", "no app 'zz' in the index (have: a)"},
		{"no such version", `{}`, []string{ent("a@1.0.0", "", ""), ent("a@2.0.0", "", "")}, "a@3.0.0", "a@3.0.0 is not in the index (versions: 1.0.0, 2.0.0)"},
		{"no provider anywhere", `{}`, []string{ent("a@1.0.0", "", "nope")}, "a", "a: requires capability 'nope' — no app in the index provides it, and the platform does not"},
		{"two index providers", `{}`, []string{ent("a@1.0.0", "", "c"), ent("p1@1.0.0", "c", ""), ent("p2@1.0.0", "c", "")}, "a", "capability 'c' has 2 providers (p1, p2)"},
		{"the platform and an app", `{"c":["db"]}`, []string{ent("a@1.0.0", "", "c"), ent("p@1.0.0", "c", "")}, "a", "capability 'c' has 2 providers (db, p)"},
		{"a pinned request MVS would raise", `{}`, []string{ent("x@1.0.0", "", "yc"), ent("x@2.0.0", "xc", "yc"), ent("y@1.0.0", "yc", "xc")}, "x@1.0.0", "x@1.0.0 was asked for, but what it requires needs x@2.0.0"},
		{"a selected version that dropped a capability", `{}`, []string{ent("r@1.0.0", "", "ra rb"), ent("a@1.0.0", "ra", "c"), ent("b@1.0.0", "rb", "d"),
			ent("p@1.0.0", "c", ""), ent("p@2.0.0", "d", "")}, "r", "a: requires capability 'c', which p@2.0.0 — the version selected — does not provide"},
		{"a version that is not SemVer", `{}`, []string{ent("a@1.0", "", "")}, "a", `a: version "1.0" in the index is not SemVer`},
		{"one version twice", `{}`, []string{ent("a@1.0.0", "", ""), ent("a@1.0.0", "", "")}, "a", "a@1.0.0 is in the index twice"},
		{"only pre-releases, not asked for", `{}`, []string{ent("a@1.0.0-rc.1", "", "")}, "a", "a has only pre-releases (1.0.0-rc.1) — ask for one by version"},
		{"a provider only in a pre-release", `{}`, []string{ent("a@1.0.0", "", "c"), ent("p@2.0.0-beta.1", "c", "")}, "a", "a: requires capability 'c', which only pre-releases of p provide"},
		{"a capability the selected version of the app itself dropped", `{}`, []string{ent("a@1.0.0", "x", ""), ent("a@2.0.0", "", "x")}, "a", "a: requires capability 'x', which a@2.0.0 — the version selected — does not provide"},
	}
	for _, c := range cases {
		dir, root := signedIndex(t, c.platform, c.ents...)
		stdout, stderr, code := dryRun(t, dir, root, c.req)
		if code != 1 || !strings.Contains(stderr, c.want) {
			t.Errorf("%s: exit %d, want 1 and %q\n%s%s", c.name, code, c.want, stdout, stderr)
		}
	}
}

// The lock pins the build list by version and artifact sha256; the same plan is the same bytes, and
// the dry run writes nothing else — not into the index, not beside the lock.
func TestTheLockIsDeterministicAndTheDryRunWritesNothingElse(t *testing.T) {
	t.Parallel()
	dir, root := signedIndex(t, `{"sql":["db"]}`, ent("a@1.0.0", "", "c sql"), ent("p@1.1.0", "c", ""), ent("z@0.1.0", "", ""))
	before := snapshot(t, dir)
	locks := t.TempDir()
	var got []string
	for _, name := range []string{"one.lock", "two.lock"} {
		stdout, stderr, code := dryRun(t, dir, root, "--lock", filepath.Join(locks, name), "a@1.0.0")
		if code != 0 || !strings.Contains(stdout, "nothing was written but the lock") {
			t.Fatalf("exit %d\n%s%s", code, stdout, stderr)
		}
		raw, err := os.ReadFile(filepath.Join(locks, name))
		if err != nil {
			t.Fatal(err)
		}
		got = append(got, string(raw))
	}
	if got[0] != got[1] {
		t.Fatalf("two locks of one plan differ:\n%s\n%s", got[0], got[1])
	}
	idx, _ := os.ReadFile(filepath.Join(dir, indexName))
	isum := sha256.Sum256(idx)
	asum, psum := sha256.Sum256([]byte("a@1.0.0")), sha256.Sum256([]byte("p@1.1.0"))
	want := fmt.Sprintf(`{
  "format": "dgo.lock/v1",
  "request": "a@1.0.0",
  "index": {
    "version": "1.0.0",
    "url": "https://apps.net.digital-office.co.il/v1/index.json",
    "sha256": "%x"
  },
  "apps": [
    {
      "id": "a",
      "version": "1.0.0",
      "sha256": "%x"
    },
    {
      "id": "p",
      "version": "1.1.0",
      "sha256": "%x"
    }
  ],
  "platform": [
    "sql"
  ]
}
`, isum, asum, psum)
	if got[0] != want {
		t.Errorf("lock:\n%s\nwant:\n%s", got[0], want)
	}
	if after := snapshot(t, dir); after != before {
		t.Errorf("the dry run changed the index directory:\n%s\n---\n%s", before, after)
	}
	if ents, _ := os.ReadDir(locks); len(ents) != 2 {
		t.Errorf("%d files beside the locks, want only the two locks", len(ents))
	}
}

// Without --dry-run the verb refuses rather than pretend: placing an app is still appinstall.py's.
func TestInstallWithoutDryRunDoesNotPretend(t *testing.T) {
	t.Parallel()
	var out, errb bytes.Buffer
	if code := indexVerb(repoRoot(t), []string{"install", "--index", "x", "--root", "y", "a"}, &out, &errb); code != 2 || !strings.Contains(errb.String(), "bbox app install") {
		t.Fatalf("exit %d, stderr %q", code, errb.String())
	}
}

// A pre-release is installed when it is asked for by name — as the request — and its own
// requirements resolve as any version's do.
func TestAPreReleaseIsInstalledWhenAskedFor(t *testing.T) {
	t.Parallel()
	dir, root := signedIndex(t, `{}`, ent("p@3.2.0", "c", ""), ent("p@3.3.0-rc.1", "c", "d"), ent("q@1.0.0", "d", ""))
	if stdout, stderr, code := dryRun(t, dir, root, "p@3.3.0-rc.1"); code != 0 || planLines(stdout) != "p v3.3.0-rc.1 requested\nq v1.0.0 d (p)" {
		t.Errorf("p@3.3.0-rc.1: exit %d\n%s%s", code, stdout, stderr)
	}
	if stdout, _, code := dryRun(t, dir, root, "p"); code != 0 || planLines(stdout) != "p v3.2.0 requested" {
		t.Errorf("p: exit %d\n%s", code, stdout)
	}
}

// A lock never goes back: an existing dgo.lock refuses an index older than the one it was resolved
// against, another index under that version, another channel's, and a file that is no lock; a
// newer index moves it on.
func TestALockNeverGoesBack(t *testing.T) {
	t.Parallel()
	dir, root := signedIndex(t, `{}`, ent("a@1.0.0", "", ""))
	locks := t.TempDir()
	n := 0
	lockOf := func(version, url, sha string) string {
		n++
		p := filepath.Join(locks, fmt.Sprintf("%d.lock", n))
		body := fmt.Sprintf(`{"format":%q,"request":"a","index":{"version":%q,"url":%q,"sha256":%q},"apps":[],"platform":[]}`, lockFormat, version, url, sha)
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		return p
	}
	url := defaultBaseURL + "/" + indexName
	raw, _ := os.ReadFile(filepath.Join(dir, indexName))
	sum := sha256.Sum256(raw)
	notALock := filepath.Join(locks, "notes.txt")
	os.WriteFile(notALock, []byte("mine"), 0o644)
	for _, c := range []struct {
		name, lock string
		code       int
		want       string
	}{
		{"a lock resolved against a newer index", lockOf("2.0.0", url, ""), 1, "a lock never goes back"},
		{"a lock resolved against another index of this version", lockOf("1.0.0", url, strings.Repeat("0", 64)), 1, "one version, one index"},
		{"a lock from another channel", lockOf("1.0.0", "https://staging.example.org/v1/index.json", ""), 1, "was resolved against https://staging.example.org"},
		{"a file that is no lock", notALock, 1, "refusing to overwrite it"},
		{"a lock of this very index", lockOf("1.0.0", url, hex.EncodeToString(sum[:])), 0, ""},
		{"a lock of an older index", lockOf("0.9.0", url, ""), 0, ""},
	} {
		before, _ := os.ReadFile(c.lock)
		stdout, stderr, code := dryRun(t, dir, root, "--lock", c.lock, "a")
		after, _ := os.ReadFile(c.lock)
		if code != c.code || !strings.Contains(stderr, c.want) {
			t.Errorf("%s: exit %d (want %d)\n%s%s", c.name, code, c.code, stdout, stderr)
		}
		if c.code != 0 && !bytes.Equal(before, after) {
			t.Errorf("%s: a refused dry run rewrote the lock", c.name)
		}
		if c.code == 0 && !strings.Contains(string(after), `"version": "1.0.0"`) {
			t.Errorf("%s: the lock was not moved on to index 1.0.0:\n%s", c.name, after)
		}
	}
}

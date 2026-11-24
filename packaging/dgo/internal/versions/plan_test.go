package versions

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// planRepo: an office at «batch 1», a green line one batch ahead (batch 2), and the line's red tip above it (batch 3,
// pushed before its proof, as batch 99 was). Batch 2 changes lib.sh, apps/esign/x.py, platform.state.yaml and a
// Hebrew-named file. Here, uncommitted: lib.sh untouched for 7 h (kept), x.py and the Hebrew file just now (they stop
// the take), platform.state.yaml (the office's own), and a.txt (batch 2 does not change it).
func planRepo(t *testing.T) (string, Git) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("no git here")
	}
	dir := t.TempDir()
	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t.invalid",
			"-c", "commit.gpgsign=false"}, args...)...)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	write := func(rel, text string) {
		t.Helper()
		p := filepath.Join(dir, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	he := "docs/מסמך.md"
	run("init", "-q", "-b", "office")
	for _, f := range []string{"a.txt", "lib.sh", "apps/esign/x.py", "platform.state.yaml", he, "carried.txt", "staged.txt"} {
		write(f, "one\n")
	}
	run("add", "-A")
	run("commit", "-q", "-m", "batch 1: the first")
	run("checkout", "-q", "-b", "line")
	for _, f := range []string{"lib.sh", "apps/esign/x.py", "platform.state.yaml", he, "carried.txt"} {
		write(f, "two\n")
	}
	write("apps/esign/new.py", "new\n") // the take ADDS these two
	write("added-same.txt", "same\n")
	run("add", "-A")
	run("commit", "-q", "-m", "batch 2: the green one")
	run("update-ref", "refs/remotes/origin-green/dgo-stable", "HEAD")
	write("a.txt", "three\n")
	run("commit", "-q", "-am", "batch 3: pushed, not yet proven")
	run("update-ref", "refs/remotes/origin/dgo-stable", "HEAD")
	run("checkout", "-q", "office")
	for _, f := range []string{"a.txt", "lib.sh", "apps/esign/x.py", "platform.state.yaml", he} {
		write(f, "here\n")
	}
	write("carried.txt", "two\n")        // fresh, but already the target's own text: carried
	write("staged.txt", "staged here\n") // fresh and staged; the take does not touch it
	run("add", "staged.txt")
	write("apps/esign/new.py", "other\n") // untracked where the take adds a file, other bytes: stops
	write("added-same.txt", "same\n")     // untracked, the very bytes the take adds: kept
	old := time.Now().Add(-7 * time.Hour)
	if err := os.Chtimes(filepath.Join(dir, "lib.sh"), old, old); err != nil {
		t.Fatal(err)
	}
	t.Setenv("DGO_BRANCH", "mac-dgo")
	t.Setenv("DGO_FOLLOW_KEEP_AFTER", "")
	return dir, RealGit(dir)
}

// namedImages writes refs/images/dgo-stable in dir as the proof's green job does: a commit of one file, images.json,
// naming the images built for target — one well formed, one with a digest that is not sha256, one with no name.
func namedImages(t *testing.T, dir, target string) {
	t.Helper()
	doc := `{"green":"` + target + `","built":["x"],"images":{` +
		`"x":{"digest":"sha256:` + strings.Repeat("a", 64) + `","name":"ghcr.io/bina-solution/digital-office/x"},` +
		`"bad":{"digest":"md5:00","name":"n"},` +
		`"nameless":{"digest":"sha256:` + strings.Repeat("b", 64) + `","name":""}}}`
	run := func(stdin string, args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t.invalid"}, args...)...)
		cmd.Stdin = strings.NewReader(stdin)
		out, err := cmd.Output()
		if err != nil {
			t.Fatalf("git %v: %v", args, err)
		}
		return strings.TrimSpace(string(out))
	}
	blob := run(doc, "hash-object", "-w", "--stdin")
	tree := run("100644 blob "+blob+"\timages.json\n", "mktree")
	commit := run("", "commit-tree", tree, "-m", "the images")
	run("", "update-ref", "refs/images/dgo-stable", commit)
}

func TestThePlanNamesTheImagesTheLineBuiltForItsTarget(t *testing.T) {
	dir, git := planRepo(t)
	green, err := git("rev-parse", "refs/remotes/origin-green/dgo-stable")
	if err != nil {
		t.Fatal(err)
	}
	namedImages(t, dir, green)
	p, err := MakePlan(dir, git, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if p.ImagesFrom != "images/dgo-stable" || len(p.Images) != 1 || p.Images[0].ID != "x" ||
		p.Images[0].Digest != "sha256:"+strings.Repeat("a", 64) || p.Images[0].Name != "ghcr.io/bina-solution/digital-office/x" {
		t.Fatalf("the one well-formed image named for the green target: %+v from %q", p.Images, p.ImagesFrom)
	}
	var b bytes.Buffer
	PrintPlan(&b, p)
	if !strings.Contains(b.String(), "  x  sha256:aaaaaaaaaaaa…\n") {
		t.Fatalf("the plan says the image and its digest, short: %s", b.String())
	}
	// a list made for another commit names nothing for this one
	namedImages(t, dir, strings.Repeat("c", 40))
	p, err = MakePlan(dir, git, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Images) != 0 || p.ImagesFrom != "" {
		t.Fatalf("another version's images are no answer for this one: %+v", p.Images)
	}
	out, err := json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(out), `"images":[]`) {
		t.Fatalf("an empty list, never null: %s", out)
	}
}

func TestThePlanTakesTheGreenLineAndNamesItsLeftWork(t *testing.T) {
	dir, git := planRepo(t)
	p, err := MakePlan(dir, git, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if p.Target.Label != "batch 2" || p.From != "remotes/origin-green/dgo-stable" || p.Behind != 1 || p.Holds != "batch 1" || p.Nothing {
		t.Fatalf("the GREEN line's batch 2, one commit, never the red tip: %+v", p)
	}
	got := map[string]string{}
	for _, l := range p.Left {
		got[l.Path] = l.Why + "/" + strconv.FormatBool(l.Keep)
	}
	want := map[string]string{ // follow.sh's take, case by case
		"apps/esign/x.py":   "changed/false",   // fresh, the take changes it: stops
		"lib.sh":            "changed/true",    // untouched 7 h: kept
		"docs/מסמך.md":      "changed/false",   // a Hebrew name, read whole (-z)
		"carried.txt":       "changed/true",    // fresh, but the target's own text
		"staged.txt":        "staged/false",    // fresh and staged: a merge would refuse
		"apps/esign/new.py": "untracked/false", // where the take adds a file, other bytes
		"added-same.txt":    "untracked/true",  // the very bytes the take adds
	}
	if len(got) != len(want) {
		t.Fatalf("exactly follow.sh's files, never the office's state or a file the take leaves alone (a.txt): %+v", p.Left)
	}
	for f, w := range want {
		if got[f] != w {
			t.Errorf("%s: %s, want %s (in %+v)", f, got[f], w, p.Left)
		}
	}
	if !p.Stop || strings.Join(p.Rebuild, " ") != "esign" {
		t.Errorf("a fresh edit stops the take, and esign is the one app it changes: stop=%v rebuild=%v", p.Stop, p.Rebuild)
	}
	var out, errb bytes.Buffer
	if code := Main(dir, []string{"plan"}, &out, &errb); code != 0 || !strings.Contains(out.String(), "STOPS the take") ||
		!strings.Contains(out.String(), "docs/מסמך.md") {
		t.Fatalf("the text says it, Hebrew path and all: exit %d\n%s%s", code, out.String(), errb.String())
	}
	out.Reset()
	var j Plan
	if code := Main(dir, []string{"plan", "--json"}, &out, &errb); code != 0 || json.Unmarshal(out.Bytes(), &j) != nil || !j.Stop {
		t.Fatalf("--json is the same plan: %d %s", code, out.String())
	}
}

func TestKeepAfterZeroKeepsEveryChangeButNotAForeignFile(t *testing.T) {
	dir, git := planRepo(t)
	t.Setenv("DGO_FOLLOW_KEEP_AFTER", "0") // follow.sh honours 0: every changed or staged file is left work
	p, err := MakePlan(dir, git, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range p.Left {
		if (l.Why == "changed" || l.Why == "staged") != l.Keep && l.Path != "added-same.txt" {
			t.Errorf("KEEP_AFTER=0: %s [%s] keep=%v", l.Path, l.Why, l.Keep)
		}
	}
	if !p.Stop {
		t.Error("an untracked file with other bytes where the take adds one still stops it")
	}
}

func TestAnOfficeThatHoldsTheGreenLineHasNothingToTake(t *testing.T) {
	dir, git := planRepo(t)
	cmd := exec.Command("git", "-C", dir, "-c", "user.name=t", "-c", "user.email=t@t.invalid", "update-ref", "HEAD", "refs/remotes/origin-green/dgo-stable")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, out)
	}
	p, err := MakePlan(dir, git, time.Now())
	if err != nil || !p.Nothing || p.Behind != 0 || p.Holds != "batch 2" {
		t.Fatalf("holding the green line: nothing to take: %v %+v", err, p)
	}
}

func TestNoGreenLineIsSaid(t *testing.T) {
	dir := t.TempDir()
	if err := exec.Command("git", "-C", dir, "init", "-q").Run(); err != nil {
		t.Fatal(err)
	}
	var out, errb bytes.Buffer
	if code := Main(dir, []string{"plan"}, &out, &errb); code != 1 || !strings.Contains(errb.String(), "no green line here") {
		t.Fatalf("no green line: exit 1 and why, got %d %q", code, errb.String())
	}
}

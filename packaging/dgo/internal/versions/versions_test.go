package versions

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// repo builds a checkout with real git: a remote `dgo` with a line of batches and three office branches, a stale remote
// `origin` left from an older setup (the Dell's, measured 2026-11-20), and a local mac-dgo that merged batch 3 back.
//
//	line (first parent):  b1 «batch 1» ── b2 «mac-dgo → dgo-stable, batch 2» ── b3 «batch 3: …» (2nd parent: m1)
//	dgo/mac-dgo:  b2 ── m1             (its own commit, taken by batch 3, but batch 3 itself not merged back)
//	dgo/hp-dgo:   b1 ── h1 ── h2       (two commits of its own, two behind b3)
//	dgo/vps1-dgo: b3                   (exactly the line)
//	dgo/feature:  b3 ── f1             (not an office: no «-dgo»)
//	origin/dgo-stable = b1, origin/hp-dgo = h1   (older copies: never the line, never an office's tip)
//	local mac-dgo:  m1 ── m2 (merges b3)          (this office's own truth, when it is this office)
func repo(t *testing.T) (string, Git) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("no git here")
	}
	dir := t.TempDir()
	run := func(args ...string) string {
		cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t.invalid",
			"-c", "commit.gpgsign=false"}, args...)...)
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	day := 0
	commit := func(msg string, parents ...string) string {
		day++ // each commit a day after the one before, so «newest» is a fact of the history, not of the clock
		tree := run("write-tree")
		args := []string{"commit-tree", tree, "-m", msg}
		for _, p := range parents {
			args = append(args, "-p", p)
		}
		t.Setenv("GIT_COMMITTER_DATE", fmt.Sprintf("2026-11-%02dT00:00:00Z", day))
		return run(args...)
	}
	run("init", "-q")
	b1 := commit("batch 1: the first")
	b2 := commit("mac-dgo → dgo-stable, batch 2: the second", b1)
	m1 := commit("console: a change of the MacBook's", b2)
	b3 := commit("batch 3: dgo-stable takes mac-dgo", b2, m1)
	h1 := commit("hp: one", b1)
	h2 := commit("hp: two", h1)
	f1 := commit("feature: x", b3)
	m2 := commit("merge dgo-stable batch 3 into mac-dgo", m1, b3)
	for ref, sha := range map[string]string{
		"remotes/dgo/dgo-stable": b3, "remotes/dgo/mac-dgo": m1, "remotes/dgo/hp-dgo": h2, "remotes/dgo/vps1-dgo": b3,
		"remotes/dgo/feature": f1, "remotes/origin/dgo-stable": b1, "remotes/origin/hp-dgo": h1, "heads/mac-dgo": m2,
	} {
		run("update-ref", "refs/"+ref, sha)
	}
	return dir, RealGit(dir)
}

func offices(t *testing.T, st Status) (map[string]Office, string) {
	t.Helper()
	got := map[string]Office{}
	var order []string
	for _, o := range st.Offices {
		got[o.Branch] = o
		order = append(order, o.Branch)
	}
	return got, strings.Join(order, " ")
}

func TestEachOfficeHoldsTheNewestLineCommitInItsBranch(t *testing.T) {
	_, git := repo(t)
	st, err := Read(git, "hp-dgo")
	if err != nil {
		t.Fatal(err)
	}
	if st.Remote != "dgo" || st.Line.Label != "batch 3" {
		t.Fatalf("the line is dgo's batch 3, never the stale origin's: %q %+v", st.Remote, st.Line)
	}
	got, order := offices(t, st)
	if order != "hp-dgo mac-dgo vps1-dgo" {
		t.Fatalf("this office first, then by name, only «-dgo» branches, each once: %v", order)
	}
	// the newest copy of hp-dgo (dgo's h2), not origin's older h1
	if o := got["hp-dgo"]; !o.Here || o.From != "dgo" || o.Holds != "batch 1" || o.Behind != 2 || o.Ahead != 2 {
		t.Errorf("hp-dgo: here, from dgo, holds batch 1, two behind, two of its own ahead: %+v", o)
	}
	// the MacBook's own commit went into batch 3 as its second parent: batch 3 is not held until it merges it back
	if o := got["mac-dgo"]; o.From != "dgo" || o.Holds != "batch 2" || o.Behind != 1 || o.Ahead != 0 {
		t.Errorf("mac-dgo (another office: its remote copy): holds batch 2, one behind, nothing ahead: %+v", o)
	}
	if o := got["vps1-dgo"]; o.Holds != "batch 3" || o.Behind != 0 || o.Ahead != 0 {
		t.Errorf("vps1-dgo: exactly the line: %+v", o)
	}
}

func TestThisOfficeIsReadFromItsOwnBranch(t *testing.T) {
	_, git := repo(t)
	st, err := Read(git, "mac-dgo")
	if err != nil {
		t.Fatal(err)
	}
	got, _ := offices(t, st)
	if o := got["mac-dgo"]; !o.Here || o.From != "local" || o.Holds != "batch 3" || o.Behind != 0 || o.Ahead != 1 {
		t.Errorf("mac-dgo here: its local branch merged batch 3 back, one merge commit ahead: %+v", o)
	}
}

func TestTheTextAndTheJSONSayTheSame(t *testing.T) {
	dir, git := repo(t)
	// as the office-branch guard reads it: `export`, spaces, quotes, and the LAST assignment wins
	if err := os.WriteFile(filepath.Join(dir, ".env"), []byte("A=1\nDGO_BRANCH=mac-dgo\nexport DGO_BRANCH = \"hp-dgo\"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("DGO_BRANCH", "")
	if b := HereBranch(dir, git); b != "hp-dgo" {
		t.Fatalf("DGO_BRANCH in .env names this office: %q", b)
	}
	var out, errb bytes.Buffer
	if code := Main(dir, []string{"status"}, &out, &errb); code != 0 {
		t.Fatalf("exit %d: %s", code, errb.String())
	}
	text := out.String()
	for _, want := range []string{"the line: dgo/dgo-stable", "batch 3", "never fetched here", "* hp-dgo", "batch 1 ("} {
		if !strings.Contains(text, want) {
			t.Errorf("the text lacks %q:\n%s", want, text)
		}
	}
	out.Reset()
	if code := Main(dir, []string{"--json"}, &out, &errb); code != 0 {
		t.Fatalf("--json exit %d: %s", code, errb.String())
	}
	var st Status
	if err := json.Unmarshal(out.Bytes(), &st); err != nil || len(st.Offices) != 3 || !st.Offices[0].Here || st.Offices[0].Branch != "hp-dgo" {
		t.Fatalf("the JSON is the same status, this office first: %v %+v", err, st)
	}
}

func TestAWrongWordIsRefusedInWords(t *testing.T) {
	dir, _ := repo(t)
	var out, errb bytes.Buffer
	if code := Main(dir, []string{"take"}, &out, &errb); code != 2 || !strings.Contains(errb.String(), "usage:") {
		t.Fatalf("an unknown verb: exit 2 with the usage, got %d %q", code, errb.String())
	}
	if code := Main(dir, []string{"-h"}, &out, &errb); code != 0 || !strings.Contains(out.String(), "usage:") {
		t.Fatalf("-h: the usage on stdout, exit 0, got %d", code)
	}
	empty := t.TempDir() // a repository of its own, so git never walks up into a checkout around the test (the runner's)
	if err := exec.Command("git", "-C", empty, "init", "-q").Run(); err != nil {
		t.Fatal(err)
	}
	if code := Main(empty, nil, &out, &errb); code != 1 || !strings.Contains(errb.String(), "fetch the line first") {
		t.Fatalf("no line here: exit 1 saying to fetch, got %d %q", code, errb.String())
	}
}

// The HP's take of batch 103 stopped on a merge conflict (2026-11-20): hp-dgo and the line had both changed follow.sh.
// The status names such an office and its files before any take tries; an office whose work merges cleanly has none.
//
//	base «batch 1» (f.txt a, «חוזה א.txt» a, g.txt a) ── line «batch 2» (f.txt and «חוזה א.txt» line)
//	dgo/hp-dgo:   base ── hp (f.txt and «חוזה א.txt» hp) → conflicts in both, the Hebrew name as it is, unquoted
//	dgo/vps1-dgo: base ── vp (g.txt vps1)                → merges cleanly
func TestAnOfficeWhoseMergeWouldStopIsNamedWithItsFiles(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("no git here")
	}
	dir := t.TempDir()
	run := func(args ...string) string {
		cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t.invalid",
			"-c", "commit.gpgsign=false"}, args...)...)
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	day := 0
	commit := func(msg string, files map[string]string, parents ...string) string {
		day++
		for name, body := range files {
			if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o600); err != nil {
				t.Fatal(err)
			}
		}
		run("add", "-A")
		args := []string{"commit-tree", run("write-tree"), "-m", msg}
		for _, p := range parents {
			args = append(args, "-p", p)
		}
		t.Setenv("GIT_COMMITTER_DATE", fmt.Sprintf("2026-11-%02dT00:00:00Z", day))
		return run(args...)
	}
	run("init", "-q")
	const he = "חוזה א.txt" // a Hebrew name with a space: git quotes it unless -z
	base := commit("batch 1: base", map[string]string{"f.txt": "a\n", he: "a\n", "g.txt": "a\n"})
	if exec.Command("git", "-C", dir, "merge-tree", "--write-tree", base, base).Run() != nil {
		t.Skip("this git has no `merge-tree --write-tree` (2.38+): the status then says no list, never «clean»")
	}
	line := commit("batch 2: the line", map[string]string{"f.txt": "line\n", he: "line\n", "g.txt": "a\n"}, base)
	hp := commit("hp: its own f", map[string]string{"f.txt": "hp\n", he: "hp\n", "g.txt": "a\n"}, base)
	vp := commit("vps1: its own g", map[string]string{"f.txt": "a\n", he: "a\n", "g.txt": "vps1\n"}, base)
	for ref, sha := range map[string]string{"dgo/dgo-stable": line, "dgo/hp-dgo": hp, "dgo/vps1-dgo": vp} {
		run("update-ref", "refs/remotes/"+ref, sha)
	}
	st, err := Read(RealGit(dir), "vps1-dgo")
	if err != nil {
		t.Fatal(err)
	}
	got, _ := offices(t, st)
	if o := got["hp-dgo"]; o.Ahead != 1 || o.Behind != 1 || o.Merge != "conflicts" || strings.Join(o.Conflicts, "|") != "f.txt|"+he {
		t.Errorf("hp-dgo: one ahead, one behind, its merge stops in f.txt and %s: %+v", he, o)
	}
	if o := got["vps1-dgo"]; o.Ahead != 1 || o.Behind != 1 || o.Merge != "clean" || len(o.Conflicts) != 0 {
		t.Errorf("vps1-dgo: one ahead, one behind, and a merge was read clean: %+v", o)
	}
	var out bytes.Buffer
	Print(&out, st)
	if !strings.Contains(out.String(), "hp-dgo conflicts with the line in f.txt, "+he) || strings.Contains(out.String(), "vps1-dgo conflicts") {
		t.Errorf("the text names the office whose take would stop, and only it:\n%s", out.String())
	}
}

func TestLabel(t *testing.T) {
	if l := Label("batch 98: dgo-stable takes …", "bd3d4b114001"); l != "batch 98" {
		t.Error(l)
	}
	if l := Label("mac-dgo → dgo-stable, batch 52: Examplex's live work", "43d533c1f000"); l != "batch 52" {
		t.Error(l)
	}
	if l := Label("issues: two files take the schema's category — and batch 92 went red on it", "599a9c72b000"); l != "599a9c72b" {
		t.Errorf("a commit that only mentions a batch is no batch: %s", l)
	}
	if l := Label("merge of x", "0123456789abcdef"); l != "012345678" {
		t.Error(l)
	}
}

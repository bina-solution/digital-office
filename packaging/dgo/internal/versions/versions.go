// Package versions is «ניהול גרסאות», the office's one owner of versions (DGO-2138), starting at step M0 of its
// migration (research_notes/DGO-2138 version management 2026-11-20/research.md §7.5): `dgo versions status`, which
// version of the line each office's branch holds, read from git alone and changing nothing.
//
// WHY THIS IS THE FIRST STEP. The owner, 2026-11-20: «כל מה שקשור לעדכוני גרסה ללשכה עצמה ולישומים הכל צריך להיות
// מנוהל מישום ליבה אחד שכולו בgo בשם "ניהול גרסאות"». Today the answer to «which office runs what» is spread over
// `git log` on four machines, the batch subjects on dgo-stable and the coordinator's notes. This verb gives that answer
// on one screen, from the facts every checkout already has. The take, the rings and the release come later (M1–M6),
// on top of the same reading.
//
// THE FACTS, AND ONLY THEM:
//   - the line is <remote>/dgo-stable, on the remote where it is newest; its FIRST-PARENT chain is the batches, each
//     subject naming its «batch NN»;
//   - an office's line is a branch `<name>-dgo` (AGENTS.md's table: mac-dgo, hp-dgo, vps1-dgo, dell-dgo, claude-dgo);
//   - an office HOLDS the newest first-parent commit of the line that is an ancestor of its branch. A batch that merged
//     one of the office's own commits as its second parent is not held until the office merges the batch itself;
//   - behind = the line's first-parent commits after the one it holds; ahead = its commits not on the line yet.
//
// It reads the refs as they were at the last fetch and says when that was. It never fetches.
package versions

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"text/tabwriter"
	"time"
)

// LineBranch is the line every office takes from (AGENTS.md: proven work is merged into dgo-stable). Which remote
// carries it is not assumed: the Dell's is named `dgo`, and its stale `origin` still held 11-13's line (measured
// 2026-11-20). The line is the remote whose dgo-stable is the NEWEST commit (lineRemote).
const LineBranch = "dgo-stable"

// depth bounds the line's chain read: an office further back than this holds «none read», which says what it is.
const depth = 400

// Commit is one first-parent commit of the line.
type Commit struct {
	SHA     string `json:"sha"`
	Label   string `json:"label"` // «batch 98», or the short sha of a commit that names no batch
	Subject string `json:"subject"`
}

// Office is one office's line.
type Office struct {
	Branch   string `json:"branch"`
	From     string `json:"from"` // "local" for this office's own branch, else the remote its newest copy came from
	Tip      string `json:"tip"`
	Here     bool   `json:"here"`      // this checkout's office (DGO_BRANCH, else the branch HEAD is on)
	Holds    string `json:"holds"`     // the label of the newest line commit it holds; "" when none was read
	HoldsSHA string `json:"holds_sha"` // …and its short sha
	Behind   int    `json:"behind"`    // the line's first-parent commits after it; -1 when it holds none read
	Ahead    int    `json:"ahead"`     // its commits not on the line yet

	// Merge is a trial merge of this branch and the line, read by `git merge-tree` (no working tree or index touched):
	// "clean", or "conflicts" with the files it would stop on — as the HP's take of batch 103 stopped on 2026-11-20.
	// "" when none was read: the branch is not both ahead and behind, or this git is older than 2.38. Never «clean».
	Merge     string   `json:"merge,omitempty"`
	Conflicts []string `json:"conflicts,omitempty"`
}

// Status is the whole answer.
type Status struct {
	Remote    string   `json:"remote"` // the remote whose dgo-stable is the line, and whose «-dgo» branches are listed
	Line      Commit   `json:"line"`
	Offices   []Office `json:"offices"`
	FetchedAt string   `json:"fetched_at,omitempty"` // when this checkout last fetched (FETCH_HEAD's time), UTC
}

// Git runs git in the checkout and returns its trimmed stdout.
type Git func(args ...string) (string, error)

// RealGit is git itself, in root.
func RealGit(root string) Git {
	return func(args ...string) (string, error) {
		// --no-optional-locks: a read never refreshes the shared checkout's index (other writers share it)
		out, err := exec.Command("git", append([]string{"--no-optional-locks", "-C", root}, args...)...).Output()
		return strings.TrimSpace(string(out)), err
	}
}

// a batch's number where a batch's subject puts it: «batch 98: …», or the older «mac-dgo → dgo-stable, batch 52: …».
// Anchored: a line commit that only MENTIONS a batch («issues: … and batch 92 …», 599a9c72b) is no batch (the reader).
var batchRE = regexp.MustCompile(`^(?:\S+ → dgo-stable, )?batch (\d+)\b`)

// envKey is the guard's own reading of DGO_BRANCH (.claude/hooks/office-branch.py `declared_branch`): `export` and
// spaces allowed, the last assignment wins, quotes dropped.
var envKey = regexp.MustCompile(`^\s*(?:export\s+)?DGO_BRANCH\s*=\s*(.*?)\s*$`)

// Label names a line commit as a person reads it: its batch, else its short sha.
func Label(subject, sha string) string {
	if m := batchRE.FindStringSubmatch(subject); m != nil {
		return "batch " + m[1]
	}
	return short(sha)
}

func short(sha string) string {
	if len(sha) > 9 {
		return sha[:9]
	}
	return sha
}

// lineRemote is the remote whose dgo-stable is the newest commit (a tie goes to the remote with more «-dgo» branches,
// then by name), so a remote left from an older setup never stands for the line. The branches are read from every
// remote (officeTips): the line may arrive by one remote and the offices by another.
func lineRemote(git Git) (string, error) {
	out, err := git("for-each-ref", "--format=%(refname)%09%(committerdate:unix)", "refs/remotes/")
	if err != nil {
		return "", fmt.Errorf("the remotes could not be listed: %v", err)
	}
	when, offices := map[string]int64{}, map[string]int{}
	for _, ln := range strings.Split(out, "\n") {
		ref, t, ok := strings.Cut(ln, "\t")
		rest, isRemote := strings.CutPrefix(ref, "refs/remotes/")
		remote, branch, nested := strings.Cut(rest, "/")
		if !ok || !isRemote || !nested || strings.Contains(branch, "/") {
			continue
		}
		if branch == LineBranch {
			when[remote], _ = strconv.ParseInt(t, 10, 64)
		} else if strings.HasSuffix(branch, "-dgo") {
			offices[remote]++
		}
	}
	best := ""
	for r := range when {
		if best == "" || when[r] > when[best] || (when[r] == when[best] && (offices[r] > offices[best] ||
			(offices[r] == offices[best] && r < best))) {
			best = r
		}
	}
	if best == "" {
		return "", errors.New("no remote here carries dgo-stable: fetch the line first")
	}
	return best, nil
}

type tip struct{ branch, sha, from string }

// officeTips is every office's line: each «-dgo» branch on any remote, the newest copy of it (a line can reach an
// office by another remote, or by bundle: the Dell's newest line came as `bundle/dgo-stable` with no office branch
// beside it, 2026-11-20), and THIS office from its own local branch, which is its truth.
func officeTips(git Git, here string) ([]tip, error) {
	out, err := git("for-each-ref", "--format=%(refname)%09%(objectname)%09%(committerdate:unix)", "refs/remotes/", "refs/heads/")
	if err != nil {
		return nil, fmt.Errorf("the branches could not be listed: %v", err)
	}
	best, when := map[string]tip{}, map[string]int64{}
	for _, ln := range strings.Split(out, "\n") {
		f := strings.Split(ln, "\t")
		if len(f) != 3 {
			continue
		}
		var from, branch string
		if rest, ok := strings.CutPrefix(f[0], "refs/heads/"); ok {
			if rest != here || here == "" {
				continue // a local branch speaks only for this office
			}
			from, branch = "local", rest
		} else if rest, ok := strings.CutPrefix(f[0], "refs/remotes/"); ok {
			r, b, nested := strings.Cut(rest, "/")
			if !nested {
				continue
			}
			from, branch = r, b
		}
		if !strings.HasSuffix(branch, "-dgo") || strings.Contains(branch, "/") {
			continue
		}
		t, _ := strconv.ParseInt(f[2], 10, 64)
		cur, seen := best[branch]
		if !seen || (cur.from != "local" && (from == "local" || t > when[branch])) {
			best[branch], when[branch] = tip{branch: branch, sha: f[1], from: from}, t
		}
	}
	tips := make([]tip, 0, len(best))
	for _, t := range best {
		tips = append(tips, t)
	}
	return tips, nil
}

// Read gathers the status. here is this office's branch name ("" when unknown).
func Read(git Git, here string) (Status, error) {
	remote, err := lineRemote(git)
	if err != nil {
		return Status{}, err
	}
	lineRef := "refs/remotes/" + remote + "/" + LineBranch
	out, err := git("log", "--first-parent", "--format=%H%x09%s", "-n", strconv.Itoa(depth), lineRef)
	if err != nil {
		return Status{}, fmt.Errorf("the line %s could not be read: %v", lineRef, err)
	}
	var chain []Commit
	for _, ln := range strings.Split(out, "\n") {
		sha, subject, ok := strings.Cut(ln, "\t")
		if !ok || len(sha) < 9 {
			continue
		}
		chain = append(chain, Commit{SHA: sha, Subject: subject, Label: Label(subject, sha)})
	}
	if len(chain) == 0 {
		return Status{}, errors.New("the line has no commits")
	}
	st := Status{Remote: remote, Line: chain[0], Offices: []Office{}}
	tips, err := officeTips(git, here)
	if err != nil {
		return Status{}, err
	}
	for _, t := range tips {
		branch, sha := t.branch, t.sha
		o := Office{Branch: branch, From: t.from, Tip: short(sha), Here: branch == here, Behind: -1}
		// ONE call per office (the reader: 400 ancestry checks took 9.7 s for one tip 1,607 behind). The line's
		// first-parent commits the tip cannot reach are exactly the ones after the newest it holds, so their count
		// is `behind`, and the commit at that depth is the one it holds.
		if n, err := git("rev-list", "--first-parent", "--count", lineRef, "^"+sha); err == nil {
			k, _ := strconv.Atoi(n)
			held := Commit{}
			if k < len(chain) {
				held = chain[k]
			} else if ln, err := git("log", "--first-parent", "--skip="+n, "-n", "1", "--format=%H%x09%s", lineRef); err == nil {
				if s, subject, ok := strings.Cut(ln, "\t"); ok {
					held = Commit{SHA: s, Subject: subject, Label: Label(subject, s)}
				}
			}
			if held.SHA != "" {
				o.Holds, o.HoldsSHA, o.Behind = held.Label, short(held.SHA), k
			}
		}
		if n, err := git("rev-list", "--count", lineRef+".."+sha); err == nil {
			o.Ahead, _ = strconv.Atoi(n)
		}
		if o.Ahead > 0 && o.Behind > 0 {
			if files, ok := conflicts(git, lineRef, sha); ok {
				o.Merge, o.Conflicts = "clean", files
				if len(files) > 0 {
					o.Merge = "conflicts"
				}
			}
		}
		st.Offices = append(st.Offices, o)
	}
	sort.SliceStable(st.Offices, func(i, j int) bool {
		if st.Offices[i].Here != st.Offices[j].Here {
			return st.Offices[i].Here
		}
		return st.Offices[i].Branch < st.Offices[j].Branch
	})
	if p, err := git("rev-parse", "--git-path", "FETCH_HEAD"); err == nil {
		st.FetchedAt = p // resolved to a time by the caller, which knows the checkout's directory
	}
	return st, nil
}

// conflicts are the files a merge of tip and the line would conflict on, and whether a merge was read at all.
// `git merge-tree --write-tree` (git 2.38+) merges in memory, touching no working tree or index: exit 0 is clean; exit 1
// prints the tree's id and then each conflicted file. -z ends each with a NUL and quotes nothing, so a Hebrew name or one
// with a space comes back as it is (without -z, git prints `"\327\251…"`; the second reader, 2026-11-20). An older git
// prints only its usage: no list, and not read — never «clean».
func conflicts(git Git, lineRef, tip string) ([]string, bool) {
	out, err := git("merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", lineRef, tip)
	if err == nil {
		return nil, true
	}
	recs := strings.Split(out, "\x00") // the tree's id, then one file per record
	var files []string
	for _, f := range recs[1:] {
		if f != "" {
			files = append(files, f)
		}
	}
	return files, len(files) > 0
}

// HereBranch is this office's branch, read as the office-branch guard reads it: DGO_BRANCH from the environment, else
// the checkout's .env (the last assignment wins), else the branch HEAD is on. Only that one key is read from .env.
func HereBranch(root string, git Git) string {
	if v := strings.TrimSpace(os.Getenv("DGO_BRANCH")); v != "" {
		return v
	}
	if raw, err := os.ReadFile(filepath.Join(root, ".env")); err == nil {
		v := ""
		for _, ln := range strings.Split(string(raw), "\n") {
			if m := envKey.FindStringSubmatch(ln); m != nil {
				v = strings.Trim(strings.TrimSpace(m[1]), `"'`)
			}
		}
		if v != "" {
			return v
		}
	}
	b, _ := git("rev-parse", "--abbrev-ref", "HEAD")
	if b == "HEAD" {
		return ""
	}
	return b
}

const usage = `usage:
  dgo versions status [--json]    which version of the line (dgo-stable) each office's branch holds, from git alone
  dgo versions plan [--json]      what a take of the green line would do here: its commits, left work, apps to rebuild
`

// Main is `dgo versions …`.
func Main(root string, args []string, stdout, stderr io.Writer) int {
	verb, rest := "status", args
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		verb, rest = args[0], args[1:]
	}
	asJSON := false
	for _, a := range rest {
		switch a {
		case "--json":
			asJSON = true
		case "-h", "--help":
			fmt.Fprint(stdout, usage)
			return 0
		default:
			fmt.Fprintf(stderr, "dgo versions %s: unknown argument %q\n%s", verb, a, usage)
			return 2
		}
	}
	if verb == "plan" {
		return planMain(root, asJSON, stdout, stderr)
	}
	if verb != "status" {
		fmt.Fprintf(stderr, "dgo versions: unknown verb %q\n%s", verb, usage)
		return 2
	}
	git := RealGit(root)
	st, err := Read(git, HereBranch(root, git))
	if err != nil {
		fmt.Fprintln(stderr, "dgo versions:", err)
		return 1
	}
	st.FetchedAt = fetchedAt(root, st.FetchedAt)
	if asJSON {
		enc := json.NewEncoder(stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(st)
		return 0
	}
	Print(stdout, st)
	return 0
}

func fetchedAt(root, gitPath string) string {
	if gitPath == "" {
		return ""
	}
	if !filepath.IsAbs(gitPath) {
		gitPath = filepath.Join(root, gitPath)
	}
	fi, err := os.Stat(gitPath)
	if err != nil {
		return ""
	}
	return fi.ModTime().UTC().Format(time.RFC3339)
}

// Print writes the status as a person reads it.
func Print(w io.Writer, st Status) {
	when := "never fetched here"
	if st.FetchedAt != "" {
		when = "as of the last fetch, " + st.FetchedAt
	}
	fmt.Fprintf(w, "the line: %s/dgo-stable %s · %s (%s)\n\n", st.Remote, short(st.Line.SHA), st.Line.Label, when)
	tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
	fmt.Fprintln(tw, "  branch\tfrom\ttip\tholds\tbehind\tahead")
	for _, o := range st.Offices {
		mark, holds, behind := " ", "none of the last "+strconv.Itoa(depth), "?"
		if o.Here {
			mark = "*"
		}
		if o.Behind >= 0 {
			holds, behind = o.Holds+" ("+o.HoldsSHA+")", strconv.Itoa(o.Behind)
		}
		fmt.Fprintf(tw, "%s %s\t%s\t%s\t%s\t%s\t%d\n", mark, o.Branch, o.From, o.Tip, holds, behind, o.Ahead)
	}
	_ = tw.Flush()
	for _, o := range st.Offices {
		if len(o.Conflicts) > 0 {
			fmt.Fprintf(w, "\n%s conflicts with the line in %s: its next take stops there until the line takes its work",
				o.Branch, strings.Join(o.Conflicts, ", "))
		}
	}
	fmt.Fprintln(w, "\n* this office · behind: the line's commits after the one it holds · ahead: its commits not on the line yet")
}

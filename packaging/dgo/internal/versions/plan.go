package versions

// plan.go — `dgo versions plan`: what a take would do HERE, read from git and the working tree, changing nothing
// (DGO-2138, the read-only half of M1). It judges a take as scripts/follow.sh's `take` does (its oracle until M1's
// second half moves the take itself here), and every rule below is that function's, line for line:
//   - the target is the GREEN line, never dgo-stable's tip: batch 99 was pushed red at 14:46Z on top of a green 98;
//   - changed = `git diff --no-renames HEAD...target`; dirty = `git diff --no-renames HEAD`; their overlap, without
//     platform.state.yaml (always the office's own), is the files a merge would refuse on;
//   - each is LEFT WORK when it is here and untouched for KEEP_AFTER (6 h), or already holds the target's own text
//     («carried»): kept in a commit of its own. Anything else stops the take — the HP's take of 94 stopped three times;
//   - a staged file the take does not touch stops it too unless it is left work (then it is unstaged);
//   - a file the take ADDS that sits here untracked stops it, unless it holds the very bytes the take adds;
//   - an index mid-conflict (`git ls-files -u`) makes nothing left work.
// Git runs with --no-optional-locks: reading never refreshes the shared checkout's index (RealGit).

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// KeepAfter is the follow's own rule (scripts/follow.sh KEEP_AFTER, DGO_FOLLOW_KEEP_AFTER, default 21600 s): seconds a
// changed file must be untouched before it counts as left work. 0 is honoured (every changed file is left work).
func KeepAfter() time.Duration {
	if s, err := strconv.Atoi(strings.TrimSpace(os.Getenv("DGO_FOLLOW_KEEP_AFTER"))); err == nil && s >= 0 {
		return time.Duration(s) * time.Second
	}
	return 6 * time.Hour
}

// Left is one file of this office's that the take meets.
type Left struct {
	Path string `json:"path"`
	Why  string `json:"why"`  // "changed" (uncommitted, the take changes it), "staged", or "untracked" (the take adds it)
	Age  string `json:"age"`  // how long it has been untouched; "carried" when it already holds the target's text
	Keep bool   `json:"keep"` // left work the take keeps (or unstages); false stops the take
}

// Plan is what a take would do here.
type Plan struct {
	Branch   string   `json:"branch"`
	Holds    string   `json:"holds"`  // the line commit HEAD holds (its label)
	Target   Commit   `json:"target"` // the green line's commit
	From     string   `json:"from"`   // the ref the green line was read from
	Behind   int      `json:"behind"` // the green line's first-parent commits HEAD does not hold
	Nothing  bool     `json:"nothing_to_take"`
	Unmerged bool     `json:"unmerged"` // an index left mid-conflict: nothing is left work
	Left     []Left   `json:"left_work"`
	Stop     bool     `json:"stop"` // the take would stop before it merges anything
	Rebuild  []string `json:"rebuild"`

	// Images: the ready-made images the line's proof named for this very target (refs/images/<line>, DGO-2123), which
	// a take pulls instead of building where this office runs the image store and opted in (scripts/follow.sh
	// images_pull); ImagesFrom is the ref they were read from, "" when none names this target.
	Images     []Image `json:"images"`
	ImagesFrom string  `json:"images_from,omitempty"`
}

// Image is one ready-made image: built once by the line's proof, pushed to the image store by digest
// (research_notes/CICD 2026-11/images.md).
type Image struct {
	ID     string `json:"id"`
	Digest string `json:"digest"`
	Name   string `json:"name"` // the image name its compose file gives it, the tag a take sets after the pull
}

// imagesFor reads the images the line's proof named for target: the follow's own fetch of refs/images/<line>, or the
// ref itself. A list made for another commit names nothing for this one; a digest that is not sha256, or an image with
// no name, is not counted.
func imagesFor(git Git, target string) ([]Image, string) {
	for _, ref := range []string{"refs/follow/images/" + LineBranch, "refs/images/" + LineBranch} {
		out, err := git("show", ref+":images.json")
		if err != nil {
			continue
		}
		var doc struct {
			Green  string `json:"green"`
			Images map[string]struct {
				Digest string `json:"digest"`
				Name   string `json:"name"`
			} `json:"images"`
		}
		if json.Unmarshal([]byte(out), &doc) != nil || doc.Green != target {
			continue
		}
		imgs := []Image{}
		for id, e := range doc.Images {
			if strings.HasPrefix(e.Digest, "sha256:") && e.Name != "" {
				imgs = append(imgs, Image{ID: id, Digest: e.Digest, Name: e.Name})
			}
		}
		sort.Slice(imgs, func(i, j int) bool { return imgs[i].ID < imgs[j].ID })
		return imgs, strings.TrimPrefix(ref, "refs/")
	}
	return []Image{}, ""
}

// shortDigest is a digest as a person reads it: its algorithm and first twelve hex digits.
func shortDigest(d string) string {
	if len(d) > len("sha256:")+12 {
		return d[:len("sha256:")+12] + "…"
	}
	return d
}

// greenRef is the newest commit any green ref of the line names: the follow's own fetch of it
// (`refs/follow/green/dgo-stable`), the ref itself (`refs/green/dgo-stable`), or a remote tracking it whose name says
// green (`green/dgo-stable`, `origin-green/dgo-stable` on the MacBook). A line never proven here has none.
func greenRef(git Git) (string, error) {
	out, err := git("for-each-ref", "--sort=-committerdate", "--format=%(refname)", "refs/follow/green/", "refs/green/", "refs/remotes/")
	if err != nil {
		return "", fmt.Errorf("the refs could not be listed: %v", err)
	}
	for _, ref := range strings.Split(out, "\n") {
		if ref == "refs/follow/green/"+LineBranch || ref == "refs/green/"+LineBranch {
			return ref, nil
		}
		if rest, ok := strings.CutPrefix(ref, "refs/remotes/"); ok {
			if remote, branch, _ := strings.Cut(rest, "/"); branch == LineBranch && strings.Contains(remote, "green") {
				return ref, nil
			}
		}
	}
	return "", fmt.Errorf("no green line here (refs/green/%s, or a remote of it): fetch it first", LineBranch)
}

func names(out string) []string {
	var r []string
	for _, f := range strings.Split(out, "\x00") {
		if f != "" {
			r = append(r, f)
		}
	}
	return r
}

// MakePlan reads what a take of the green line would do in root.
func MakePlan(root string, git Git, now time.Time) (Plan, error) {
	ref, err := greenRef(git)
	if err != nil {
		return Plan{}, err
	}
	p := Plan{Branch: HereBranch(root, git), From: strings.TrimPrefix(ref, "refs/"), Left: []Left{}, Rebuild: []string{}}
	tip, err := git("log", "-1", "--format=%H%x09%s", ref)
	if err != nil {
		return Plan{}, fmt.Errorf("the green line could not be read: %v", err)
	}
	sha, subject, _ := strings.Cut(tip, "\t")
	p.Target = Commit{SHA: sha, Subject: subject, Label: Label(subject, sha)}
	p.Images, p.ImagesFrom = imagesFor(git, sha)
	if n, err := git("rev-list", "--first-parent", "--count", ref, "^HEAD"); err == nil {
		p.Behind, _ = strconv.Atoi(n)
	}
	if held, err := git("log", "--first-parent", "--skip="+strconv.Itoa(p.Behind), "-n", "1", "--format=%H%x09%s", ref); err == nil {
		if s, subj, ok := strings.Cut(held, "\t"); ok {
			p.Holds = Label(subj, s)
		}
	}
	if p.Behind == 0 {
		p.Nothing = true
		return p, nil
	}
	// -z everywhere: git quotes a path that is not plain ASCII, and this checkout is full of Hebrew ones
	out, err := git("diff", "-z", "--name-only", "--no-renames", "HEAD..."+ref)
	if err != nil {
		return Plan{}, fmt.Errorf("what the take changes could not be read: %v", err)
	}
	changed := map[string]bool{}
	apps := map[string]bool{}
	for _, f := range names(out) {
		changed[f] = true
		if parts := strings.SplitN(f, "/", 3); len(parts) == 3 && (parts[0] == "apps" || parts[0] == "platform-base") {
			apps[parts[1]] = true
		}
	}
	for a := range apps {
		p.Rebuild = append(p.Rebuild, a)
	}
	sort.Strings(p.Rebuild)
	if u, err := git("ls-files", "-u"); err == nil && u != "" {
		p.Unmerged = true // follow.sh's mine=0: an index mid-conflict keeps nothing
	}
	keep := KeepAfter()
	carried := func(path string) bool { // here_carried: the file's text HERE is the target's own text for it
		if path == "platform.state.yaml" {
			return false
		}
		if fi, err := os.Lstat(filepath.Join(root, path)); err != nil || !fi.Mode().IsRegular() {
			return false
		}
		blob, err := git("hash-object", "--", path)
		if err != nil {
			return false
		}
		want, err := git("rev-parse", "-q", "--verify", ref+":"+path)
		return err == nil && want == blob
	}
	judge := func(path, why string) Left { // left_work: here, and untouched for KEEP_AFTER, or carried
		l := Left{Path: path, Why: why, Age: "gone"}
		fi, err := os.Lstat(filepath.Join(root, path))
		if err != nil { // a deletion is a session's call to make: never left work
			return l
		}
		age := now.Sub(fi.ModTime())
		l.Age = age.Round(time.Minute).String()
		switch {
		case p.Unmerged:
		case age >= keep:
			l.Keep = true
		case carried(path):
			l.Age, l.Keep = "carried", true
		}
		return l
	}
	out, err = git("diff", "-z", "--name-only", "--no-renames", "HEAD")
	if err != nil {
		return Plan{}, fmt.Errorf("the working tree could not be read: %v", err)
	}
	rest := map[string]bool{}
	for _, f := range names(out) {
		if f == "platform.state.yaml" || !changed[f] {
			continue
		}
		rest[f] = true
		p.Left = append(p.Left, judge(f, "changed"))
	}
	if out, err = git("diff", "--cached", "-z", "--name-only", "--no-renames"); err == nil {
		for _, f := range names(out) {
			if rest[f] || (f == "platform.state.yaml" && changed[f]) {
				continue // in the commit of left work above, or the office's own state's own commit
			}
			p.Left = append(p.Left, judge(f, "staged"))
		}
	}
	if out, err = git("diff", "-z", "--name-only", "--no-renames", "--diff-filter=A", "HEAD..."+ref); err == nil {
		for _, f := range names(out) {
			if _, err := git("cat-file", "-e", "HEAD:"+f); err == nil {
				continue // tracked here already: it merges
			}
			if _, err := os.Lstat(filepath.Join(root, f)); err != nil {
				continue // not on disk: nothing in its way
			}
			l := Left{Path: f, Why: "untracked", Age: "-"}
			if !p.Unmerged && carried(f) { // the very bytes the take adds (follow.sh also checks the mode git stages)
				l.Age, l.Keep = "carried", true
			}
			p.Left = append(p.Left, l)
		}
	}
	for _, l := range p.Left {
		if !l.Keep {
			p.Stop = true
		}
	}
	sort.Slice(p.Left, func(i, j int) bool { return p.Left[i].Path < p.Left[j].Path })
	return p, nil
}

// PrintPlan writes the plan as a person reads it.
func PrintPlan(w io.Writer, p Plan) {
	fmt.Fprintf(w, "%s holds %s; the green line (%s) is %s %s\n", p.Branch, p.Holds, p.From, short(p.Target.SHA), p.Target.Label)
	if p.Nothing {
		fmt.Fprintln(w, "nothing to take: this office holds the green line")
		return
	}
	fmt.Fprintf(w, "a take would bring %d of the line's commits\n", p.Behind)
	if p.Unmerged {
		fmt.Fprintln(w, "the index is mid-conflict here: nothing counts as left work")
	}
	if len(p.Left) > 0 {
		fmt.Fprintf(w, "this office's files the take meets (left work when untouched for %s, or holding the target's text):\n", KeepAfter())
		for _, l := range p.Left {
			verdict := "STOPS the take: someone may still be writing it"
			if l.Keep {
				verdict = "left work: kept (or unstaged)"
			}
			fmt.Fprintf(w, "  %s  [%s] untouched %s · %s\n", l.Path, l.Why, l.Age, verdict)
		}
	}
	if len(p.Rebuild) > 0 {
		fmt.Fprintf(w, "apps it changes (rebuilt if they run here): %s\n", strings.Join(p.Rebuild, " "))
	}
	if len(p.Images) > 0 {
		fmt.Fprintf(w, "ready-made images the line named for it (%s), pulled instead of built where this office runs the image store and opted in:\n", p.ImagesFrom)
		for _, im := range p.Images {
			fmt.Fprintf(w, "  %s  %s\n", im.ID, shortDigest(im.Digest))
		}
	}
	if p.Stop {
		fmt.Fprintln(w, "verdict: the take would STOP before it merges anything")
	} else {
		fmt.Fprintln(w, "verdict: the take can run")
	}
}

func planMain(root string, asJSON bool, stdout, stderr io.Writer) int {
	git := RealGit(root)
	p, err := MakePlan(root, git, time.Now())
	if err != nil {
		fmt.Fprintln(stderr, "dgo versions plan:", err)
		return 1
	}
	if asJSON {
		enc := json.NewEncoder(stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(p)
		return 0
	}
	PrintPlan(stdout, p)
	return 0
}

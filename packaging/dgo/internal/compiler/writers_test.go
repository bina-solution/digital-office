package compiler

import (
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── the oracle for the writers: reconcile.py and dgo on two copies of one fixture tree ───────────

const noState = "\x00no state file"

// writerCase is one command line of a writer verb, the state file it meets, and anything else the
// tree needs. crash marks a case Python answers with a traceback, where dgo prints one FATAL line (the
// read verbs' rule): the exit status, stdout and the state file are compared, and where dgo's line
// names the exception Python raised, it ends with the traceback's last line.
type writerCase struct {
	name, verb string
	args       []string
	stdin      string
	state      string // "" is the checkout's own platform.state.yaml; noState removes it
	setup      func(dir string)
	crash      bool
	// again: reconcile.py has written this very stdin once already, on both trees — the next pass of
	// a `remote-get | remote-set`, or of the projection.
	again bool
	// refused: where dgo refuses on purpose and Python writes (or, with crash, crashes): exit 1,
	// nothing on stdout, one line on stderr that holds this text, the state file as it was. readerGap:
	// the refusal is the reader's gap (it reads the value otherwise than PyYAML does) — answering as
	// Python does, as a reader without the gap would, passes too.
	refused   string
	readerGap bool
	// warning: dgo answers as Python does, with one more line on stderr: a warning holding this text.
	warning string
}

type outcome struct {
	stdout, stderr string
	code           int
	state          []byte // nil: no state file
}

// writerTree is a checkout the writers can run on: reconcile.py and serve.py side by side (the
// compiler takes its checkout from its own path), every manifest of this checkout, the icon set and
// the palette office-set checks against, and the case's state file.
func writerTree(t *testing.T, c writerCase, realState string) string {
	t.Helper()
	src, dir := repoRoot(t), t.TempDir()
	// a case may leave a file read-only, which Windows will not remove
	t.Cleanup(func() {
		filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
			if err == nil && !d.IsDir() {
				os.Chmod(p, 0o644)
			}
			return nil
		})
	})
	files := []string{"platform/manager/reconcile.py", "platform/manager/serve.py",
		"platform-base/bina-ui/bina-icons.js", "platform-base/bina-ui/theme-tokens.css"}
	for _, root := range []string{"apps", "platform-base"} {
		ms, _ := filepath.Glob(filepath.Join(src, root, "*", "app.json"))
		for _, m := range ms {
			rel, _ := filepath.Rel(src, m)
			files = append(files, filepath.ToSlash(rel))
		}
	}
	for _, f := range files {
		raw, err := os.ReadFile(filepath.Join(src, filepath.FromSlash(f)))
		if err != nil {
			t.Fatal(err)
		}
		put(t, dir, f, string(raw))
	}
	switch c.state {
	case noState:
	case "":
		put(t, dir, stateName, realState)
	default:
		put(t, dir, stateName, c.state)
	}
	if c.setup != nil {
		c.setup(dir)
	}
	return dir
}

func put(t *testing.T, dir, rel, body string) {
	t.Helper()
	p := filepath.Join(dir, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func stateOf(dir string) []byte {
	raw, err := os.ReadFile(filepath.Join(dir, stateName))
	if err != nil {
		return nil
	}
	return raw
}

func runPython(t *testing.T, py []string, dir string, c writerCase) outcome {
	t.Helper()
	argv := append(append(append([]string{}, py[1:]...), filepath.Join(dir, "platform", "manager", "reconcile.py"), c.verb), c.args...)
	cmd := exec.Command(py[0], argv...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	cmd.Stdin = strings.NewReader(c.stdin)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	code := 0
	if err := cmd.Run(); err != nil {
		ee, ok := err.(*exec.ExitError)
		if !ok {
			t.Fatalf("running reconcile.py: %v", err)
		}
		code = ee.ExitCode()
	}
	// Python's text-mode stdout writes CRLF on Windows; the contract (and Linux) is LF.
	return outcome{strings.ReplaceAll(out.String(), "\r\n", "\n"), strings.ReplaceAll(errb.String(), "\r\n", "\n"), code, stateOf(dir)}
}

func runGo(dir string, c writerCase) outcome {
	var out, errb bytes.Buffer
	var code int
	switch c.verb {
	case "set-state":
		code = SetStateCmd(dir, c.args, &out, &errb)
	case "office-set":
		code = OfficeSetCmd(dir, c.args, strings.NewReader(c.stdin), &out, &errb)
	case "remote-set":
		code = RemoteSetCmd(dir, c.args, strings.NewReader(c.stdin), &out, &errb)
	}
	return outcome{out.String(), errb.String(), code, stateOf(dir)}
}

// legacyChoices is argparse's invalid-choice wording before Python 3.12.8, which quoted each choice;
// dgo answers in today's wording, so an older oracle's line is read in today's.
var legacyChoices = regexp.MustCompile(`\(choose from ('[^']*'(?:, '[^']*')*)\)`)

var fatalPath = regexp.MustCompile(`(?m)^FATAL \S+`)

func modernChoices(s string) string {
	return legacyChoices.ReplaceAllStringFunc(s, func(m string) string { return strings.ReplaceAll(m, "'", "") })
}

func lastLine(s string) string {
	lines := strings.Split(strings.TrimRight(s, "\n"), "\n")
	return lines[len(lines)-1]
}

// sameOutcome holds dgo's run to Python's (differences), or — for a case dgo refuses on purpose — to
// its refusal; either way, nothing may be left beside the state file.
func sameOutcome(t *testing.T, c writerCase, py, gr outcome, pyDir, goDir string, before []byte) {
	t.Helper()
	if left, _ := filepath.Glob(filepath.Join(goDir, "."+stateName+".*")); len(left) > 0 {
		t.Errorf("left beside the state file: %v", left)
	}
	diffs := differences(c, py, gr, pyDir, goDir)
	if c.refused == "" || c.readerGap && len(diffs) == 0 {
		for _, d := range diffs {
			t.Error(d)
		}
		return
	}
	t.Logf("python: exit %d, %q", py.code, lastLine(py.stdout+py.stderr))
	if gr.code != 1 || gr.stdout != "" || strings.Count(gr.stderr, "\n") != 1 || !strings.Contains(gr.stderr, c.refused) {
		t.Errorf("dgo must refuse with one line holding %q:\n exit %d\n--- stdout ---\n%s--- stderr ---\n%s", c.refused, gr.code, gr.stdout, gr.stderr)
	}
	if !bytes.Equal(gr.state, before) {
		t.Errorf("dgo refused, yet the state file changed")
	}
	if c.crash && (py.code != 1 || !strings.Contains(py.stderr, "Traceback") || !bytes.Equal(py.state, before)) {
		t.Errorf("python did not crash leaving the file as it was, as the case says:\n%s", py.stderr)
	}
}

// differences compares the two runs: the state file's bytes, the exit status, stdout, and stderr —
// for a crash, dgo's one FATAL line against the traceback — each run's own tree named <repo>.
func differences(c writerCase, py, gr outcome, pyDir, goDir string) []string {
	var out []string
	norm := func(s, dir string) string {
		dirs := []string{dir}
		if real, err := filepath.EvalSymlinks(dir); err == nil && real != dir {
			dirs = append(dirs, real) // an OSError names the checkout resolved, as reconcile.py's REPO is
		}
		for _, d := range dirs {
			s = strings.ReplaceAll(s, strings.ReplaceAll(d, `\`, `\\`), "<repo>")
		}
		// load_catalog prints a manifest's path with the OS's separator, LoadCatalog always with `/`:
		// the same line on Linux, where the office runs (a difference of the catalog port, not of these
		// writers)
		s = fatalPath.ReplaceAllStringFunc(s, func(m string) string { return strings.ReplaceAll(m, `\`, "/") })
		for _, d := range dirs {
			s = strings.ReplaceAll(s, d, "<repo>")
		}
		return modernChoices(s)
	}
	if py.code != gr.code {
		out = append(out, fmt.Sprintf("exit status: python %d, go %d\n--- python stderr ---\n%s--- go stderr ---\n%s", py.code, gr.code, py.stderr, gr.stderr))
	}
	stderr := gr.stderr
	if c.warning != "" {
		var kept []string
		warned := false
		for _, ln := range strings.SplitAfter(stderr, "\n") {
			if !warned && strings.HasPrefix(ln, "warning: ") && strings.Contains(ln, c.warning) {
				warned = true
				continue
			}
			kept = append(kept, ln)
		}
		if !warned {
			out = append(out, fmt.Sprintf("no warning holding %q:\n%s", c.warning, stderr))
		}
		stderr = strings.Join(kept, "")
	}
	if c.crash {
		if py.code != 1 || !strings.Contains(py.stderr, "Traceback") {
			out = append(out, "python did not crash as the case says:\n"+py.stderr)
		}
		g := norm(stderr, goDir)
		if !strings.HasPrefix(g, "FATAL ") || strings.Count(g, "\n") != 1 || py.stdout != gr.stdout {
			out = append(out, fmt.Sprintf("dgo must stop with one FATAL line and python's stdout:\n--- go ---\n%s%s", gr.stdout, g))
		}
		exception := norm(lastLine(py.stderr), pyDir)
		if name, _, ok := strings.Cut(exception, ": "); ok && strings.Contains(g, " "+name+": ") && !strings.HasSuffix(strings.TrimSuffix(g, "\n"), exception) {
			out = append(out, fmt.Sprintf("the exception differs:\n python %s\n go     %s", exception, g))
		}
	} else {
		if p, g := norm(py.stdout, pyDir), norm(gr.stdout, goDir); p != g {
			out = append(out, fmt.Sprintf("stdout differs:\n--- python ---\n%s--- go ---\n%s", p, g))
		}
		if p, g := norm(py.stderr, pyDir), norm(stderr, goDir); p != g {
			out = append(out, fmt.Sprintf("stderr differs:\n--- python ---\n%s--- go ---\n%s", p, g))
		}
	}
	if !bytes.Equal(py.state, gr.state) {
		at := firstDiffBytes(py.state, gr.state)
		out = append(out, fmt.Sprintf("platform.state.yaml differs at byte %d:\n--- python ---\n%s\n--- go ---\n%s", at, around(py.state, at), around(gr.state, at)))
	}
	return out
}

func firstDiffBytes(a, b []byte) int {
	for i := 0; i < len(a) && i < len(b); i++ {
		if a[i] != b[i] {
			return i
		}
	}
	return min(len(a), len(b))
}

func around(b []byte, at int) string {
	return string(b[max(0, at-200):min(len(b), at+200)])
}

func runWriterCases(t *testing.T, cases []writerCase) {
	py := python(t)
	if py == nil {
		t.Skip("no python with PyYAML on PATH")
	}
	real, err := os.ReadFile(filepath.Join(repoRoot(t), stateName))
	if err != nil {
		t.Skip("this checkout has no platform.state.yaml")
	}
	t.Setenv("COLUMNS", "80") // argparse wraps its usage at the terminal's width; both sides read this one
	for _, c := range cases {
		c := c
		t.Run(c.name, func(t *testing.T) {
			t.Parallel()
			pyDir, goDir := writerTree(t, c, string(real)), writerTree(t, c, string(real))
			if c.again {
				for _, d := range []string{pyDir, goDir} {
					if o := runPython(t, py, d, c); o.code != 0 {
						t.Fatalf("reconcile.py's first write failed:\n%s", o.stderr)
					}
				}
			}
			before := stateOf(goDir)
			sameOutcome(t, c, runPython(t, py, pyDir, c), runGo(goDir, c), pyDir, goDir, before)
		})
	}
}

// ── set-state ─────────────────────────────────────────────────────────────────────────────────────

func TestSetStateMatchesPython(t *testing.T) {
	const small = "schema_version: 1\n\napps:\n  # base\n  traefik:   { enabled: true }\n  ollama:    { enabled: false }   # gallery\n  axb:       { state: disabled, by: user }\n\ninstances:\n  drive:\n    active: x\n"
	nonUTF8 := "schema_version: 1\napps:\n  a: { enabled: true }   # \xff\n"
	cases := []writerCase{
		{name: "enable an app written the legacy way", verb: "set-state", args: []string{"--app", "ollama", "--state", "enabled"}},
		{name: "already so", verb: "set-state", args: []string{"--app", "app-management", "--state", "enabled", "--by", "dgo-extend"}},
		{name: "the same state by someone else is a change", verb: "set-state", args: []string{"--app", "app-management", "--state", "enabled"}},
		{name: "archive", verb: "set-state", args: []string{"--app", "browser42", "--state", "archived", "--by", "cli"}},
		{name: "not found", verb: "set-state", args: []string{"--app", "nosuch", "--state", "enabled"}},
		{name: "create", verb: "set-state", args: []string{"--app", "nosuch", "--state", "enabled", "--create", "--by", "cli"}},
		{name: "create an id longer than the column", verb: "set-state", args: []string{"--app", "a-very-long-app-identifier", "--state", "disabled", "--create"}},
		{name: "create a Hebrew id", verb: "set-state", args: []string{"--app", "שלום", "--state", "enabled", "--create"}},
		{name: "create where the entry exists replaces it", verb: "set-state", args: []string{"--app", "drive", "--state", "enabled", "--create"}},
		{name: "an empty by", verb: "set-state", args: []string{"--app", "ollama", "--state", "enabled", "--by", ""}},
		{name: "a negative number is a value", verb: "set-state", args: []string{"--app", "ollama", "--state", "enabled", "--by", "-5"}},
		{name: "a value with a space may start with a dash", verb: "set-state", args: []string{"--app", "ollama", "--state", "enabled", "--by", "-x y"}},
		{name: "flags of other verbs are ignored", verb: "set-state", args: []string{"--for", "a", "--app", "ollama", "--exclude", "b", "--state", "enabled", "--capability", "c", "--json"}},
		{name: "abbreviations", verb: "set-state", args: []string{"--ap", "ollama", "--st", "enabled", "--cr", "--b", "me"}},
		{name: "values after =", verb: "set-state", args: []string{"--app=ollama", "--state=disabled", "--by=x=y"}},
		{name: "a regex character in an id is literal", verb: "set-state", args: []string{"--app", "a.b", "--state", "enabled"}, state: small},
		{name: "small file", verb: "set-state", args: []string{"--app", "traefik", "--state", "disabled"}, state: small},
		{name: "small file create after the last entry", verb: "set-state", args: []string{"--app", "new", "--state", "enabled", "--create"}, state: small},
		{name: "a top-level key after a blank line is matched too", verb: "set-state", args: []string{"--app", "foo", "--state", "enabled"},
			state: "schema_version: 1\napps:\n  a: { enabled: true }\n\nfoo: { x: 1 }\n"},
		{name: "CRLF file", verb: "set-state", args: []string{"--app", "ollama", "--state", "enabled"}, state: strings.ReplaceAll(small, "\n", "\r\n")},
		{name: "line separators split the file on create", verb: "set-state", args: []string{"--app", "zz", "--state", "enabled", "--create"},
			state: "schema_version: 1\napps:\n  a: { enabled: true }   # one\u2028two\u0085three\n  b: { enabled: true }\n"},
		{name: "no apps block to extend", verb: "set-state", args: []string{"--app", "x", "--state", "enabled", "--create"}, state: "schema_version: 1\ninstances: {}\n"},
		{name: "a state file that is not UTF-8", verb: "set-state", args: []string{"--app", "a", "--state", "enabled"}, state: nonUTF8},
		{name: "no state file", verb: "set-state", args: []string{"--app", "a", "--state", "enabled"}, state: noState, crash: true},
		{name: "needs app and state", verb: "set-state", args: []string{"--app", "ollama"}},
		{name: "needs anything", verb: "set-state"},
		{name: "an invalid state", verb: "set-state", args: []string{"--app", "x", "--state", "bogus"}},
		{name: "an unknown flag", verb: "set-state", args: []string{"--app", "x", "--state", "enabled", "--bogus"}},
		{name: "an extra positional", verb: "set-state", args: []string{"extra", "--app", "x", "--state", "enabled"}},
		{name: "an ambiguous abbreviation", verb: "set-state", args: []string{"--c"}},
		{name: "a flag without its value", verb: "set-state", args: []string{"--app"}},
		{name: "a flag whose value is a flag", verb: "set-state", args: []string{"--by", "--create"}},
		{name: "a value for a switch", verb: "set-state", args: []string{"--create=yes"}},
		{name: "an empty value for a switch", verb: "set-state", args: []string{"--json="}},
		{name: "a single-dash unknown", verb: "set-state", args: []string{"-x"}},
		{name: "a lone dash", verb: "set-state", args: []string{"-"}},
		{name: "after -- nothing is a flag", verb: "set-state", args: []string{"--", "--app", "x"}},
		{name: "help", verb: "set-state", args: []string{"-h"}},
		{name: "help glued", verb: "set-state", args: []string{"-hx"}},
		{name: "help after an error is too late", verb: "set-state", args: []string{"--state", "bogus", "--help"}},
		{name: "help with a value", verb: "set-state", args: []string{"--help=1"}},
	}
	// main() prints str(UnicodeDecodeError) for a state file that is not UTF-8: the bytes CPython's
	// decoder blames — a lead byte and the good continuations after it, or all of a sequence the file's
	// end cuts short — named by value when one, as a range when more
	for _, bad := range []string{"\xe2\x82A", "\xf0\x9f\x98", "\xf0\x9f\x98A", "\xe2\x82", "\xc3", "\xe0\x80\x80",
		"\xed\xa0\x80", "\xf4\x90\x80\x80", "\xc0\x80", "\x80"} {
		cases = append(cases, writerCase{name: fmt.Sprintf("not UTF-8: % x", bad), verb: "set-state",
			args: []string{"--app", "a", "--state", "enabled"}, state: "schema_version: 1\napps:\n  a: { enabled: true }   # " + bad})
	}
	cases = append(cases,
		// reconcile.py takes no lock: one dgo cannot take stops nothing (it says so when it writes), and
		// a lock file it may not write is locked through a read handle
		writerCase{name: "a lock file that is read-only", verb: "set-state", args: []string{"--app", "ollama", "--state", "enabled"},
			setup: func(dir string) {
				put(t, dir, "data/.locks/platform.state", "")
				os.Chmod(filepath.Join(dir, "data", ".locks", "platform.state"), 0o444)
			}},
		writerCase{name: "no lock to be had: nothing to change", verb: "set-state", args: []string{"--app", "nosuch", "--state", "enabled"}, setup: lockless(t)},
		writerCase{name: "no lock to be had: a change", verb: "set-state", args: []string{"--app", "ollama", "--state", "enabled"}, setup: lockless(t),
			warning: "is written without its lock"},
	)
	if os.Geteuid() != 0 { // root may write a read-only file, Python and dgo alike
		cases = append(cases, writerCase{name: "a read-only state file", verb: "set-state", args: []string{"--app", "ollama", "--state", "enabled"},
			crash: true, setup: readOnly})
	}
	runWriterCases(t, cases)
}

// A state file another process holds open while dgo writes it. On Windows a handle that does not
// share deletion (Go's own os.Open, most editors) refuses the rename over the file — not a write into
// it, which is how Python's write succeeds: dgo writes in place, then, and says so. Elsewhere a rename
// is not refused for that.
func TestAStateFileHeldOpenIsStillWritten(t *testing.T) {
	const state = "schema_version: 1\napps:\n  a: { enabled: true }\n"
	dir := t.TempDir()
	put(t, dir, stateName, state)
	f, err := os.Open(filepath.Join(dir, stateName))
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out, errb bytes.Buffer
	code := SetStateCmd(dir, []string{"--app", "a", "--state", "disabled"}, &out, &errb)
	inPlace := strings.Contains(errb.String(), "— written in place")
	if code != 0 || out.String() != "a -> disabled (by user)\n" || inPlace != (runtime.GOOS == "windows") ||
		string(stateOf(dir)) != strings.Replace(state, "{ enabled: true }", "{ state: disabled, by: user }", 1) {
		t.Errorf("exit %d, stdout %q, stderr %q\nstate file:\n%s", code, out.String(), errb.String(), stateOf(dir))
	}
	if left, _ := filepath.Glob(filepath.Join(dir, "."+stateName+".*")); len(left) > 0 {
		t.Errorf("left beside the state file: %v", left)
	}
}

// ── office-set ────────────────────────────────────────────────────────────────────────────────────

const record = `{"name": "הלשכה של חיים", "animal": "elephant", "hue": "muted", "terms_version": "1", "terms_accepted_at": "2026-10-09T10:00:00Z", "installed_at": "2026-10-09T10:00:00Z"}`

func TestOfficeSetMatchesPython(t *testing.T) {
	real, err := os.ReadFile(filepath.Join(repoRoot(t), stateName))
	if err != nil {
		t.Skip("this checkout has no platform.state.yaml")
	}
	header := officeHeader + "  (by wizard)\n"
	withOffice := string(real) + "\n" + header + "office:\n  name: הלשכה של חיים\n  animal: elephant\n  hue: muted\n  terms_version: '1'\n" +
		"  terms_accepted_at: '2026-10-09T10:00:00Z'\n  installed_at: '2026-10-09T10:00:00Z'\n"
	middle := "schema_version: 1\napps:\n  a: { enabled: true }\n\n" + header + "office:\n  name: old\n  hue: sky\n\n# a comment at column 0\nremote:\n- office: x\n  apps: []\n"
	cases := []writerCase{
		{name: "the wizard's record", verb: "office-set", args: []string{"--by", "wizard"}, stdin: record},
		{name: "by defaults to user", verb: "office-set", stdin: `{"name": "x"}`},
		{name: "the same record again", verb: "office-set", args: []string{"--by", "wizard"}, stdin: record, state: withOffice},
		{name: "one field changes, the rest keep their values", verb: "office-set", stdin: `{"animal": "deer", "hue": "lime"}`, state: withOffice},
		{name: "the block moves to the end", verb: "office-set", stdin: `{"name": "new"}`, state: middle},
		{name: "an empty record changes nothing", verb: "office-set", stdin: `{}`, state: middle},
		{name: "whitespace collapses, empty and null are skipped", verb: "office-set", stdin: `{"name": "  a\t b \n c ", "hue": null, "animal": ""}`},
		{name: "numbers and lists are written as str()", verb: "office-set", stdin: `{"name": 5, "terms_version": 1.5, "installed_at": "2026-10-09T10:00:00Z"}`},
		{name: "a list as a name", verb: "office-set", stdin: `{"name": [1, "a", null, true]}`},
		{name: "quotes and a colon", verb: "office-set", stdin: `{"name": "ה: 'x' #1"}`},
		{name: "Unicode digits are digits", verb: "office-set", stdin: `{"installed_at": "٢٠٢٦-١٠-٠٩T١٠:٠٠:٠٠Z"}`},
		{name: "unknown field", verb: "office-set", stdin: `{"colour": "red", "name": "x"}`},
		{name: "a name too long", verb: "office-set", stdin: `{"name": "` + strings.Repeat("א", 61) + `"}`},
		{name: "an animal that is no word", verb: "office-set", stdin: `{"animal": "Dog"}`},
		{name: "an animal that is no glyph", verb: "office-set", stdin: `{"animal": "dragon"}`},
		{name: "a hue outside the palette", verb: "office-set", stdin: `{"hue": "red"}`},
		{name: "a time in another form", verb: "office-set", stdin: `{"installed_at": "2026-10-09 10:00"}`},
		{name: "terms accepted without a version", verb: "office-set", stdin: `{"terms_accepted_at": "2026-10-09T10:00:00Z"}`},
		{name: "every refusal at once", verb: "office-set", stdin: `{"x": 1, "name": "` + strings.Repeat("n", 70) + `", "animal": "Q", "hue": "q", "installed_at": "now", "terms_accepted_at": "then"}`},
		{name: "not an object", verb: "office-set", stdin: `[1]`},
		{name: "nothing on stdin", verb: "office-set", stdin: ""},
		{name: "only whitespace on stdin", verb: "office-set", stdin: "  \n\t"},
		{name: "not JSON", verb: "office-set", stdin: `{"name": }`},
		{name: "a byte order mark", verb: "office-set", stdin: "\ufeff{}"},
		{name: "no icon set", verb: "office-set", stdin: `{"animal": "deer"}`,
			setup: func(dir string) { os.Remove(filepath.Join(dir, "platform-base", "bina-ui", "bina-icons.js")) }},
		{name: "no palette", verb: "office-set", stdin: `{"hue": "sky"}`,
			setup: func(dir string) { os.Remove(filepath.Join(dir, "platform-base", "bina-ui", "theme-tokens.css")) }},
		{name: "no state file and nothing to change", verb: "office-set", stdin: `{}`, state: noState},
		{name: "no state file and a change", verb: "office-set", stdin: `{"name": "x"}`, state: noState, crash: true},
		{name: "a state file that is not UTF-8", verb: "office-set", stdin: `{"name": "x"}`, state: "schema_version: 1\n# \xff\n", crash: true},
		{name: "a flow office block is not cut", verb: "office-set", stdin: `{"name": "x"}`, state: "schema_version: 1\noffice: {}\n"},
		{name: "help", verb: "office-set", args: []string{"--help"}},
		{name: "a bad flag", verb: "office-set", args: []string{"--by"}},
		// long values, folded at width 1000 in each style, read back as the record the file then holds
		{name: "a long terms_version, folded plain", verb: "office-set", stdin: `{"terms_version": "` + longPlain + `"}`},
		{name: "a long terms_version, folded single-quoted", verb: "office-set", stdin: `{"terms_version": "` + longQuoted + `"}`},
		{name: "a long terms_version, folded double-quoted", verb: "office-set", stdin: `{"terms_version": "\u0007` + longPlain + `"}`},
		{name: "a long terms_version with colons", verb: "office-set", stdin: `{"terms_version": "` + longColons + `"}`},
		{name: "a long terms_version of emoji", verb: "office-set", stdin: `{"terms_version": "` + longAstral + `"}`},
		{name: "a terms_version nested 2000 deep is str()'d", verb: "office-set", stdin: `{"terms_version": ` + strings.Repeat("[", 2000) + strings.Repeat("]", 2000) + `}`},
		{name: "no lock to be had: nothing to change", verb: "office-set", stdin: `{}`, setup: lockless(t)},
		// a file holding a block the reader cannot read (set_remote wrote a `? key`): dgo stops there
		{name: "a block of the file the reader cannot read", verb: "office-set", stdin: `{"name": "x"}`, state: string(real) + "\n" + keyBlock,
			refused: unreadable, readerGap: true},
	}
	if os.Geteuid() != 0 {
		cases = append(cases, writerCase{name: "a read-only state file", verb: "office-set", stdin: `{"name": "x"}`, crash: true, setup: readOnly})
	}
	runWriterCases(t, cases)
}

// ── remote-set ────────────────────────────────────────────────────────────────────────────────────

func TestRemoteSetMatchesPython(t *testing.T) {
	root := repoRoot(t)
	realText, err := readText(filepath.Join(root, stateName))
	if err != nil {
		t.Skip("this checkout has no platform.state.yaml")
	}
	v, err := yamlish.Unmarshal([]byte(realText))
	if err != nil {
		t.Fatal(err)
	}
	doc, err := mapping(v, stateName)
	if err != nil {
		t.Fatal(err)
	}
	have, _ := doc.Get("remote")
	block, _ := have.([]any)
	asJSON := func(v any) string { return yamlish.DumpsJSON(v) }
	// fresh copies of this checkout's block, changed by edit
	realBlock := func(edit func(entry *yamlish.Map)) string {
		v, err := yamlish.LoadJSON(asJSON(block))
		if err != nil {
			t.Fatal(err)
		}
		if l, _ := v.([]any); len(l) > 0 && edit != nil {
			edit(l[0].(*yamlish.Map))
		}
		return asJSON(v)
	}
	entry := func(extra string) string {
		return `{"office": "peer", "address": "10.79.5.2", "apps": [{"app": "bina", "port": 3080` + extra + `}]}`
	}
	small := "schema_version: 1\napps:\n  a: { enabled: true }\n"
	cases := []writerCase{
		{name: "the same block: nothing to change", verb: "remote-set", stdin: realBlock(nil)},
		{name: "a new fetched time is no change", verb: "remote-set", stdin: realBlock(func(e *yamlish.Map) { e.Set("fetched", int64(1)) })},
		{name: "an app fewer", verb: "remote-set", stdin: realBlock(func(e *yamlish.Map) {
			apps, _ := e.Get("apps")
			l := apps.([]any)
			e.Set("apps", l[:len(l)-1])
		})},
		{name: "json answer", verb: "remote-set", args: []string{"--json"}, stdin: realBlock(func(e *yamlish.Map) { e.Set("commit", "abc") })},
		{name: "json answer, nothing to change", verb: "remote-set", args: []string{"--json"}, stdin: realBlock(nil)},
		{name: "an empty block removes it", verb: "remote-set", stdin: `[]`},
		{name: "an empty block where there is none", verb: "remote-set", stdin: `[]`, state: small},
		{name: "a first block", verb: "remote-set", stdin: `[` + entry(`, "identity": {"to": 5, "from": "alice"}, "name": "בינה", "icon": "🏠", "x": [1.5, -0.0, null, {"y": NaN}], "long": "`+strings.Repeat("word ", 250)+`"`) + `]`, state: small},
		{name: "identity is rewritten as strings", verb: "remote-set", stdin: `[` + entry(`, "identity": {"to": "bob", "from": ["a", null, "", 7]}`) + `]`, state: small},
		{name: "a legacy serve block goes with it", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small + "serve:\n- office: old\n  apps: []\nnext: 1\n"},
		{name: "a flow remote line stays", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small + "remote: []\n"},
		{name: "not a list", verb: "remote-set", stdin: `{"office": "x"}`},
		{name: "nothing on stdin", verb: "remote-set", stdin: "\n"},
		{name: "not JSON", verb: "remote-set", stdin: `[{"office": "x",]`},
		{name: "every entry refused", verb: "remote-set", stdin: `["x", {"office": "A b"}, {"office": null}, {"office": true}, {"office": "dup", "address": "10.79.1.2"}, {"office": "dup"},
			{"office": "o1", "address": "93.184.216.7"}, {"office": "o2", "address": "10.79.1.0"}, {"office": "o3", "address": "10.79.1.255"}, {"office": "o4", "address": "10.79.1.256"},
			{"office": "o5", "address": "::1"}, {"office": "o6", "address": "10.079.1.2"}, {"office": "o7", "address": "fe80::1%eth0"}, {"office": "o8", "address": " 10.79.1.9 ", "apps": []},
			{"office": "o9", "address": "10.79.1.9", "apps": "x"}]`},
		{name: "every app refused", verb: "remote-set", stdin: `[{"office": "peer", "address": "10.79.5.2", "label": 5, "apps": ["x", {"app": "Bad_ID"}, {"app": "a", "alias": "B B"},
			{"app": "b", "port": "x"}, {"app": "c", "port": 70000}, {"app": "d", "port": 80, "agent_api_port": "x"}, {"app": "e", "port": 80, "agent_api_port": 80},
			{"app": "f", "port": 80, "identity": "x"}, {"app": "g", "port": 80, "identity": {"to": "a b"}}, {"app": "h", "port": 80, "identity": {"from": ["ok", "no way"]}},
			{"app": "i", "port": 80, "host": "Bad Host"}, {"app": "j", "port": "8080", "alias": "k"}, {"app": "k", "port": 8080.9}]}]`},
		{name: "a taken alias", verb: "remote-set", stdin: `[{"office": "peer", "address": "10.79.5.2", "apps": [{"app": "a", "port": 1}, {"app": "b", "alias": "a", "port": 2}]}]`},
		{name: "two identities on one link", verb: "remote-set", stdin: `[{"office": "peer", "address": "10.79.5.2", "apps": [{"app": "a", "port": 1, "identity": {"to": "x"}}, {"app": "b", "port": 2, "identity": {"to": "y"}}]}]`},
		{name: "a door out of range", verb: "remote-set", stdin: `[` + strings.TrimSuffix(entry(""), "}") + `, "link_port": "x"}, ` + strings.TrimSuffix(strings.Replace(entry(""), "peer", "peer2", 1), "}") + `, "link_port": 0}]`},
		{name: "a label that is a list", verb: "remote-set", stdin: `[` + strings.TrimSuffix(entry(""), "}") + `, "label": ["x"]}]`},
		{name: "header characters and a trailing newline", verb: "remote-set", stdin: `[` + entry(`, "identity": {"to": "alice\n", "from": "bob\n"}`) + `]`, state: small},
		{name: "ports as Python reads them", verb: "remote-set", stdin: `[` + entry(`, "agent_api_port": " 8_0 "`) + `, ` + strings.Replace(entry(`, "agent_api_port": true`), "peer", "peer2", 1) + `]`, state: small},
		{name: "int() strips no \\x1c around a port", verb: "remote-set", stdin: `[` + strings.Replace(entry(""), `"port": 3080`, `"port": "\u001c3080\u3000"`, 1) + `]`, state: small},
		{name: "this office's own address, from the link's record", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small,
			setup: func(dir string) { put(t, dir, ".dgo/addressing.json", `{"self": " 10.79.5.2 "}`) }},
		{name: "this office's own address, from a pair", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small,
			setup: func(dir string) { put(t, dir, ".dgo/addressing.json", `{"pairs": [null, {"self": "10.79.5.2"}]}`) }},
		{name: "this office's own address, from wg0.conf", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small,
			setup: func(dir string) { put(t, dir, ".dgo/wg0.conf", "[Interface]\n  Address = 10.79.5.2/24\n") }},
		{name: "this office's own address, from a pair's conf", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small,
			setup: func(dir string) { put(t, dir, ".dgo/pairs/wg1.conf", "Address=10.79.5.2\n") }},
		{name: "an unreadable link record says nothing", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small,
			setup: func(dir string) { put(t, dir, ".dgo/addressing.json", `{"self": `) }},
		{name: "a link record that is a list", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small, crash: true,
			setup: func(dir string) { put(t, dir, ".dgo/addressing.json", `[1]`) }},
		{name: "pairs that are an object", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small, crash: true,
			setup: func(dir string) { put(t, dir, ".dgo/addressing.json", `{"pairs": {"a": 1}}`) }},
		{name: "a module that is not an object", verb: "remote-set", stdin: `[` + entry(`, "module": "x"`) + `]`, crash: true},
		{name: "an infinite port", verb: "remote-set", stdin: `[` + entry(``) + `, {"office": "p2", "address": "10.79.6.2", "apps": [{"app": "a", "port": Infinity}]}]`, crash: true},
		{name: "a manifest the catalog refuses", verb: "remote-set", stdin: `[]`,
			setup: func(dir string) { put(t, dir, "apps/zz-bad/app.json", `{"id": "other", "layer": 3}`) }},
		{name: "no state file", verb: "remote-set", stdin: `[]`, state: noState, crash: true},
		{name: "help", verb: "remote-set", args: []string{"-h"}},
		// Past EVERY 3.12's limit, not 3.12.10's alone: 3.12.3 and 3.12.14 load 2998 levels and 5,000 (measured
		// 2026-10-30, DGO-1040) and refuse 20,000, so the old 2998 failed on whatever 3.12 the runner had.
		{name: "JSON nested past json.loads' limit", verb: "remote-set", stdin: strings.Repeat("[", 30000) + strings.Repeat("]", 30000), crash: true},
		{name: "no lock to be had: nothing to change", verb: "remote-set", stdin: realBlock(nil), setup: lockless(t)},
	}
	// A linked office's catalog reaches the block with `order`, `module` and `label` unchecked. PyYAML
	// cannot write a block nested past about 330 levels (reconcile.py crashes in safe_dump and writes
	// nothing) nor read one past about 500; dgo writes none deeper than 100.
	order := func(n int) string {
		return `[` + entry(`, "order": `+strings.Repeat("[", n)+"1"+strings.Repeat("]", n)) + `]`
	}
	deep := "remote: the block nests %d levels deep, more than the 100 a state file takes — nothing written"
	cases = append(cases,
		writerCase{name: "a block nested 150 deep", verb: "remote-set", stdin: order(150), state: small, refused: fmt.Sprintf(deep, 154)},
		writerCase{name: "a block nested 400 deep", verb: "remote-set", stdin: order(400), state: small, crash: true, refused: fmt.Sprintf(deep, 404)},
		writerCase{name: "a block nested 600 deep", verb: "remote-set", stdin: order(600), state: small, crash: true, refused: fmt.Sprintf(deep, 604)},
	)
	// What the next native read would not read back as written is not written: a key PyYAML writes as
	// `? key` and an integer beyond 64 bits (the reader's design), a non-ASCII space at a value's edge,
	// a line separator inside one, int64's minimum (its gaps, until it reads them as PyYAML does).
	const unread = "dgo's YAML reader would not read it back as written"
	for _, v := range []struct{ name, extra string }{
		{"a key YAML writes as ? key", `, "": "x"`},
		{"a 130-character key", `, "` + strings.Repeat("k", 130) + `": 1`},
		{"an integer beyond 64 bits", `, "order": 123456789012345678901234567890`},
		{"an NBSP at a name's edge", `, "name": "בינה\u00a0"`},
		{"an ideographic space at a name's edge", `, "name": "\u3000ב"`},
		{"a line separator inside a value", `, "desc": "שורה\u2028שנייה"`},
		{"int64's minimum", `, "order": -9223372036854775808`},
	} {
		cases = append(cases, writerCase{name: "first write: " + v.name, verb: "remote-set", stdin: `[` + entry(v.extra) + `]`, state: small,
			refused: unread, readerGap: true})
	}
	// What reconcile.py wrote, sent again (the next `remote-get | remote-set`): Python changes nothing,
	// nor does dgo — or, where its reader reads the file's block otherwise or not at all, it stops
	// rather than rewrite the file on every pass.
	for _, v := range []struct{ name, extra, refused string }{
		{"a long plain desc", `, "desc": "` + longPlain + `"`, ""},
		{"a long single-quoted desc", `, "desc": "` + longQuoted + `"`, ""},
		{"a long double-quoted desc", `, "desc": "\u0007` + longPlain + `"`, ""},
		{"a multi-line desc", `, "desc": "line one\nline two\n\n  indented\n"`, ""},
		{"tab and CR", `, "desc": "a\tb\r\nc"`, ""},
		{"a float order", `, "order": 1e16`, ""},
		{"an identity rewritten as strings", `, "identity": {"to": 5, "from": ["a", null, 7]}`, ""},
		{"an NBSP at a name's edge", `, "name": "בינה\u00a0"`, unread},
		{"an ideographic space at a name's edge", `, "name": "\u3000ב"`, unread},
		{"a line separator inside a value", `, "desc": "שורה\u2028שנייה"`, unread},
		{"a 130-character key", `, "` + strings.Repeat("k", 130) + `": 1`, unreadable},
		{"int64's minimum", `, "order": -9223372036854775808`, unreadable},
	} {
		cases = append(cases, writerCase{name: "again: " + v.name, verb: "remote-set", stdin: `[` + entry(v.extra) + `]`, state: small, again: true,
			refused: v.refused, readerGap: v.refused != ""})
	}
	timestamped := strings.Replace(entry(""), `"address"`, `"commit": "2026-10-09", "address"`, 1)
	nbspJSON := `[` + entry(`, "name": "בינה\u00a0"`) + `]`
	nbspYAML := "remote:\n- office: peer\n  address: 10.79.5.2\n  apps:\n  - app: bina\n    port: 3080\n    name: בינה\u00a0\n"
	keyJSON := `[` + entry(`, "": "x"`) + `]`
	cases = append(cases,
		writerCase{name: "again: a commit that reads as a date", verb: "remote-set", stdin: `[` + timestamped + `]`, state: small, again: true},
		writerCase{name: "again, before another key: an NBSP at a name's edge", verb: "remote-set", stdin: nbspJSON, state: small + "\n" + nbspYAML + "next: 1\n",
			refused: unread, readerGap: true},
		writerCase{name: "again, --json: an NBSP at a name's edge", verb: "remote-set", args: []string{"--json"}, stdin: nbspJSON, state: small + "\n" + nbspYAML,
			refused: unread, readerGap: true},
		// a file holding a block the reader cannot read: dgo stops there, and changes nothing
		writerCase{name: "a block the reader cannot read: the same block", verb: "remote-set", stdin: keyJSON, state: small + "\n" + keyBlock,
			refused: unreadable, readerGap: true},
		writerCase{name: "a block the reader cannot read: taken away", verb: "remote-set", stdin: `[]`, state: small + "\n" + keyBlock,
			refused: unreadable, readerGap: true},
	)
	if os.Geteuid() != 0 {
		// A block that CHANGES the file, whatever this checkout's own state holds: `[]` over a state with
		// no remote block is "nothing to change" for both, nothing is written, and nothing can crash — so
		// the case failed on a clean CI checkout and passed where the office's state had a block (DGO-1040).
		cases = append(cases, writerCase{name: "a read-only state file", verb: "remote-set", stdin: `[` + entry("") + `]`, state: small, crash: true, setup: readOnly})
	}
	runWriterCases(t, cases)
}

// long values the emitter folds at width 1000, one per style
var (
	longPlain  = strings.Repeat("word ", 260) + "end"
	longQuoted = "#" + longPlain                      // single-quoted for its leading #
	longColons = strings.Repeat("a: b ", 220) + "end" // single-quoted for its ": "
	longAstral = strings.Repeat("😀 x ", 200) + "end"
)

// keyBlock is what set_remote writes for an app with an empty key: PyYAML's `? key` form, which the
// reader does not read — where a native verb meets it, it stops, with unreadable.
const (
	keyBlock   = "remote:\n- office: peer\n  address: 10.79.5.2\n  apps:\n  - app: bina\n    port: 3080\n    ? ''\n    : x\n"
	unreadable = "FATAL platform.state.yaml: yaml: "
)

// lockless is a tree where the lock's directory cannot be made: a file stands where it would be.
func lockless(t *testing.T) func(dir string) {
	return func(dir string) { put(t, dir, "data/.locks", "a file where the lock's directory would be") }
}

// readOnly freezes a tree's state file.
func readOnly(dir string) { os.Chmod(filepath.Join(dir, stateName), 0o444) }

// ── Python's words, one rule each ─────────────────────────────────────────────────────────────────

func TestPythonHelpersMatchPython(t *testing.T) {
	py := python(t)
	if py == nil {
		t.Skip("no python on PATH")
	}
	strs := []string{"", "a", "it's", `say "hi"`, `both ' and "`, "back\\slash", "tab\tnl\ncr\r", "\x00\x1f\x7f", "é ש 🏠",
		"\u00a0\u00ad\u200f\u2028\ufeff", "\U0001f600", " \t x \u3000\u2003", "a\x1cb\x1dc\x1ed\x1fe\vf\fg\u0085h\u2029i\r\nj\rk",
		"İstanbul KELVIN\u212a", "1_000", " 42 ", "+7", "-0", "٤٢", "1__0", "_1", "1_", "0x10", "", "4.0", "007", "１２",
		"\x1c42", "42\x1f", "\u3000 42\u2028", "\u008542\u00a0", "\u200b42"}
	const script = `import sys, json
strs = json.load(sys.stdin)
def num(s):
    try:
        return str(int(s))
    except ValueError:
        return None
out = [[s.strip(), s.split(), s.lower(), s.splitlines(), s.splitlines(True), num(s)] for s in strs]
digits = [c for c in map(chr, range(0x110000)) if c.isdecimal()]
sys.stdout.write(json.dumps([out, [[ord(c), int(c)] for c in digits]]))`
	var want []any
	raw := pyRun(t, py, script, strs)
	v, err := yamlish.LoadJSON(string(raw))
	if err != nil {
		t.Fatal(err)
	}
	want = v.([]any)
	for i, s := range strs {
		w := want[0].([]any)[i].([]any)
		lower := pyLower(s)
		got := []any{pyval.Strip(s), strsAny(pySplit(s)), lower, strsAny(pySplitLines(s, false)), strsAny(pySplitLines(s, true))}
		for k, g := range got {
			if yamlish.CanonicalJSON(g) != yamlish.CanonicalJSON(w[k]) {
				t.Errorf("%q, rule %d: go %s, python %s", s, k, yamlish.CanonicalJSON(g), yamlish.CanonicalJSON(w[k]))
			}
		}
		n, ok := pyval.Int(s)
		if ok != (w[5] != nil) || (ok && n.Text != w[5]) {
			t.Errorf("int(%q): go %v %v, python %v", s, n.Text, ok, w[5])
		}
	}
	for _, d := range want[1].([]any) {
		pair := d.([]any)
		r, v := rune(pair[0].(int64)), int(pair[1].(int64))
		if n, ok := pyval.Int(string(r)); !ok || n.Text != strconv.Itoa(v) { // int(c) of one digit is its value
			t.Errorf("decimal value of U+%04X: go %q %v, python %d", r, n.Text, ok, v)
		}
	}
	t.Logf("%d strings and %d decimal digits agree with Python", len(strs), len(want[1].([]any)))
}

func strsAny(xs []string) []any {
	out := make([]any, len(xs))
	for i, x := range xs {
		out[i] = x
	}
	return out
}

func pyRun(t *testing.T, py []string, script string, input any) []byte {
	t.Helper()
	cmd := exec.Command(py[0], append(py[1:], "-c", script)...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	cmd.Stdin = strings.NewReader(yamlish.DumpsJSON(toAny(input)))
	var errb bytes.Buffer
	cmd.Stderr = &errb
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("python: %v\n%s", err, errb.String())
	}
	return out
}

func toAny(v any) any {
	if xs, ok := v.([]string); ok {
		return strsAny(xs)
	}
	return v
}

// A byte that is not UTF-8 in a value the writers put in the file is refused before anything is
// touched: on Linux Python takes such argv as surrogates and empties the file when it fails to encode
// them (this host's argv cannot carry one, so the rule is held here against its own sentence).
func TestNonUTF8ArgumentsAreRefusedBeforeAnyWrite(t *testing.T) {
	const state = "schema_version: 1\napps:\n  a: { enabled: true }\n"
	for _, c := range []struct {
		name string
		run  func(dir string, out, errb *bytes.Buffer) int
	}{
		{"set-state --app", func(dir string, out, errb *bytes.Buffer) int {
			return SetStateCmd(dir, []string{"--app", "x\xff", "--state", "enabled", "--create"}, out, errb)
		}},
		{"set-state --by", func(dir string, out, errb *bytes.Buffer) int {
			return SetStateCmd(dir, []string{"--app", "a", "--state", "disabled", "--by", "\xff"}, out, errb)
		}},
		{"office-set --by", func(dir string, out, errb *bytes.Buffer) int {
			return OfficeSetCmd(dir, []string{"--by", "\xff"}, strings.NewReader(`{"name": "x"}`), out, errb)
		}},
	} {
		dir := t.TempDir()
		put(t, dir, stateName, state)
		var out, errb bytes.Buffer
		if code := c.run(dir, &out, &errb); code != 1 || out.Len() != 0 || !strings.Contains(errb.String(), "must be UTF-8 text — nothing written") {
			t.Errorf("%s: exit %d, stdout %q, stderr %q", c.name, code, out.String(), errb.String())
		}
		if got := string(stateOf(dir)); got != state {
			t.Errorf("%s: the state file changed:\n%s", c.name, got)
		}
	}
}

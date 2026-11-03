package compiler

import (
	"bytes"
	"encoding/json"
	"io"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// parseDriver is the driver with argparse's parse_args answering by raising the Namespace it parsed,
// so main() never does a verb's work: any verb can be asked any command line, and what argparse
// parsed — every option's value — is compared, not only what it refused or printed.
const parseDriver = `import argparse, contextlib, io, json, os, sys
script = sys.argv[1]
sys.path.insert(0, os.path.dirname(script))
import reconcile
class Parsed(Exception):
    pass
parse = argparse.ArgumentParser.parse_args
def parsed(self, args=None, namespace=None):
    raise Parsed(vars(parse(self, args, namespace)))
argparse.ArgumentParser.parse_args = parsed
answers = []
for case in json.load(sys.stdin):
    if case["cols"] is None:
        os.environ.pop("COLUMNS", None)
    else:
        os.environ["COLUMNS"] = case["cols"]
    sys.argv = [script] + case["argv"]
    out, err = io.StringIO(), io.StringIO()
    ns, code = None, -1
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            reconcile.main()
        except Parsed as p:
            ns, code = p.args[0], 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    answers.append({"ns": ns, "stdout": out.getvalue(), "stderr": err.getvalue(), "code": code})
sys.stdout.write(json.dumps(answers))`

// namespace is argparse's Namespace as vars() gives it.
type namespace struct {
	Verb                       string
	Capability, App, State, By *string
	Create, JSON               bool
	Roots, Exclude             []string
}

type parseAnswer struct {
	NS             *namespace `json:"ns"`
	Stdout, Stderr string
	Code           int
}

func pythonParses(t *testing.T, root string, calls []call) []parseAnswer {
	t.Helper()
	py := python(t)
	type wire struct {
		Argv []string `json:"argv"`
		Cols *string  `json:"cols"`
	}
	in := make([]wire, len(calls))
	for i, c := range calls {
		in[i] = wire{c.argv, c.cols}
	}
	body, _ := json.Marshal(in)
	cmd := exec.Command(py[0], append(py[1:], "-c", parseDriver, filepath.Join(root, "platform", "manager", "reconcile.py"))...)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONHASHSEED=0")
	cmd.Stdin = bytes.NewReader(body)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	raw, err := cmd.Output()
	if err != nil {
		t.Fatalf("the driver: %v\n%s", err, stderr.String())
	}
	var out []parseAnswer
	if err := json.Unmarshal(raw, &out); err != nil || len(out) != len(calls) {
		t.Fatalf("the driver answered %d of %d: %v", len(out), len(calls), err)
	}
	return out
}

// parsesAgree holds parseArgs against argparse on every call: the same Namespace where argparse
// parsed (an option not given is None there and "" here — main() only ever asks whether it is
// truthy), the same exit code, stdout and stderr where it answered by itself.
func parsesAgree(t *testing.T, calls []call, want []parseAnswer) {
	t.Helper()
	old, had := os.LookupEnv("COLUMNS")
	defer func() {
		if had {
			os.Setenv("COLUMNS", old)
		} else {
			os.Unsetenv("COLUMNS")
		}
	}()
	str := func(p *string) string {
		if p == nil {
			return ""
		}
		return *p
	}
	same := func(a, b []string) bool {
		return (a == nil) == (b == nil) && strings.Join(a, "\x00") == strings.Join(b, "\x00")
	}
	bad := 0
	for i, c := range calls {
		if c.cols == nil {
			os.Unsetenv("COLUMNS")
		} else {
			os.Setenv("COLUMNS", *c.cols)
		}
		var out, errb bytes.Buffer
		a, code, done := parseArgs(c.argv[0], c.argv[1:], &out, &errb)
		w, problem := want[i], ""
		switch {
		case w.NS != nil && done:
			problem = "argparse parsed it; dgo answered by itself"
		case w.NS == nil && !done:
			problem = "argparse answered by itself; dgo parsed it"
		case w.NS == nil:
			if code != w.Code || out.String() != w.Stdout || errb.String() != w.Stderr {
				problem = "the answers differ"
			}
		default:
			ns := w.NS
			if ns.Verb != c.argv[0] || str(ns.Capability) != a.Capability || str(ns.App) != a.App || str(ns.State) != a.State ||
				str(ns.By) != a.By || ns.Create != a.Create || ns.JSON != a.JSON || !same(ns.Roots, a.Roots) || !same(ns.Exclude, a.Exclude) {
				problem = "the parsed values differ"
			}
		}
		if problem != "" {
			if bad++; bad <= 25 {
				var parsed any = a
				if a != nil {
					parsed = *a
				}
				cols := "unset"
				if c.cols != nil {
					cols = strconv.Quote(*c.cols)
				}
				t.Errorf("%q (COLUMNS %s): %s\n--- argparse: %+v exit %d\nstdout %q\nstderr %q\n--- dgo: %+v exit %d\nstdout %q\nstderr %q",
					c.argv, cols, problem, w.NS, w.Code, w.Stdout, w.Stderr, parsed, code, out.String(), errb.String())
			}
		}
	}
	if bad > 0 {
		t.Errorf("%d of %d command lines differ", bad, len(calls))
	}
	t.Logf("%d command lines: parsed, refused and helped as argparse does", len(calls))
}

// nativeNames are the verbs dgo answers natively — the ones a native parse can be asked under.
var nativeNames = []string{"validate", "enabled-apps", "services", "required-by", "compose-services",
	"capability-provider", "blueprints", "generations", "office-get", "remote-get"}

// TestArgparseMatchesPython: the command line read by dgo and by reconcile.py's own parser, under every
// verb dgo answers — every shape argparse treats differently (abbreviations, values after "=", "--",
// one-dash bundles, negative numbers, values with a space, the order refusals and -h are met in, each
// refusal's words and repr), the usage and the help at every width from 1 to 260 columns and at every
// $COLUMNS int() reads its own way (huge, underscores, other scripts' digits, whitespace) — and then
// the reviewer's fuzz: 6000 random command lines of up to five words, and 4000 random code points
// through --state and as unknown options.
func TestArgparseMatchesPython(t *testing.T) {
	root := repoRoot(t)
	shapes := [][]string{
		{}, {"--app", "x"},
		{"--app=x", "--json", "--create", "--by", "", "--for", "a", "--for=b,c", "--exclude", "x", "--state", "archived"},
		{"--bogus"}, {"extra"}, {"x", "--bogus", "y"},
		{"--app"}, {"--app", "--json"}, {"--app", "-x"}, {"--for"},
		{"--app", "-1"}, {"--app", "-1.5"}, {"--app", "-.5"}, {"--app", "-1."}, {"--app", "-5\n"}, {"-5"}, {"--app", "-٣"},
		{"--app", "-x y"}, {"--app", "-"}, {"--app", ""}, {"--app=", "--state=enabled"}, {"--app", "x", "--app", "y"},
		{"--c", "x"}, {"--c=x"}, {"--ca", "x"}, {"--cap=x"}, {"--cr"}, {"--j"}, {"--=x"}, {"---"}, {"--ap=", "--fo=a,b", "--ex", "s"},
		{"--json=1"}, {"--json="}, {"--create=yes"}, {"--help=x"}, {"--by", "--by"}, {"--by=--app"}, {"--for", "-x y", "--exclude=-"},
		{"-h=x"}, {"-h="}, {"-hh"}, {"-h-"}, {"-h-x"},
		{"-h"}, {"--help"}, {"--he"}, {"--h"},
		{"-x"}, {"-app"}, {"-é"},
		{"--"}, {"--", "x"}, {"--", "--app"}, {"--app", "x", "--", "y"}, {"--app", "--", "x"},
		{"--for", "a", "extra", "--json"},
		{"--bogus", "-h"}, {"-h", "--state", "bogus"}, {"--c", "-h"},
	}
	var calls []call
	for _, verb := range nativeNames {
		for _, s := range shapes {
			calls = append(calls, argv(append([]string{verb}, s...)...))
		}
	}
	for w := 1; w <= 260; w++ {
		cols := strconv.Itoa(w)
		calls = append(calls, call{argv: []string{"office-get", "-h"}, cols: &cols},
			call{argv: []string{"services", "--bogus"}, cols: &cols})
	}
	for _, v := range []string{"", "0", "-5", "abc", " 100 ", "+90", "99999999999999999999", "9223372036854775808",
		"1_00", "_100", "100_", "1__00", "١٢٠", "\x1c100\x1c", "100\n", "0x50", "+0100", " -1 ", "1e3", "-99999999999999999999"} {
		cols := v
		calls = append(calls, call{argv: []string{"office-get", "-h"}, cols: &cols}, call{argv: []string{"office-get", "--bogus"}, cols: &cols})
	}
	stable := len(calls)
	// What argparse itself answers differently from one Python release to the next (measured: 3.12.2
	// and 3.12.10 disagree on exactly these shapes, and 3.11 on more of the fuzz below): an invalid
	// --state's choices were quoted, "-hx" and "-h --c" were refused before the help, "-=" was left
	// over. dgo answers as the newer argparse; the first shape tells which one the oracle has, and an
	// older one is said, not failed.
	changed := [][]string{
		{"-h", "--c"},
		{"--state", "bogus"}, {"--state", "it's"}, {"--state", `a\b`}, {"--state", "שלום"}, {"--state", "tab\there"},
		{"--state", "x'\"y"}, {"--state", " "}, {"--state", "😀"}, {"--state", "\U000e0001"}, {"--state="},
		{"--state", "bogus", "-h"},
		{"-hx"}, {"-hé"}, {"-hhx"}, {"-hh=x"}, {"-hh="}, {"-="}, {"-=x"},
	}
	for _, s := range changed {
		calls = append(calls, argv(append([]string{"services"}, s...)...))
	}
	calls = append(calls, fuzz(6000, 20261015)...)
	want := pythonParses(t, root, calls)
	if want[stable].Code != 0 {
		t.Logf("%d command lines not compared: this python's argparse is the older one (it refuses `-h --c`)", len(calls)-stable)
		calls, want = calls[:stable], want[:stable]
	}
	parsesAgree(t, calls, want)
}

// fuzz is the reviewer's: random command lines under random native verbs, from a pool of every
// option, abbreviation, "=" form, bundle, number and odd value, sometimes under an odd $COLUMNS — and
// random code points through --state (argparse's repr of an invalid choice) and as unknown options.
func fuzz(n int, seed int64) []call {
	pool := []string{
		"-h", "--help", "--capability", "--app", "--state", "--by", "--create", "--json", "--for", "--exclude",
		"--c", "--ca", "--cap", "--cr", "--a", "--ap", "--s", "--st", "--b", "--j", "--js", "--f", "--fo", "--e", "--ex",
		"--h", "--he", "--hel", "--app=x", "--ap=", "--a=y", "--for=a,b", "--f=", "--state=enabled", "--st=archived",
		"--s=bogus", "--json=", "--json=1", "--create=x", "--help=", "--h=x", "--c=x", "--=x", "--=", "-h=", "-h=x", "-=",
		"-=x", "--by=", "--by=me", "--e=s1", "--ex=a=b", "--app==", "--for=--", "--app=-h", "-hh", "-hx", "-h-", "-hé",
		"-x", "-é", "-", "-1", "-1.5", "-.5", "-1.", "-5\n", "-٣", "-x y", "- x", "-app", "-for", "-h-x", "-hh=x", "-h=-",
		"-happ", "-\t", "x", "a,b", "", " ", "enabled", "disabled", "archived", "é", "שלום", "it's", "😀", "tab\there",
		"x=y", "=", "--x", "ENABLED", "a b", "\x00", "-0", "-1e5", "-inf", "-nan", "+1", "--", "--", "--", "---", "----",
	}
	cols := []string{"80", "40", "120", "1", "300"}
	r := rand.New(rand.NewSource(seed))
	var calls []call
	for i := 0; i < n; i++ {
		words := []string{nativeNames[r.Intn(len(nativeNames))]}
		for k := r.Intn(6); k > 0; k-- {
			words = append(words, pool[r.Intn(len(pool))])
		}
		c := call{argv: words}
		if r.Intn(8) == 0 {
			v := cols[r.Intn(len(cols))]
			c.cols = &v
		}
		calls = append(calls, c)
	}
	ranges := [][2]int{{0x01, 0x7f}, {0x80, 0x2ff}, {0x300, 0x36f}, {0x370, 0x1fff}, {0x2000, 0x206f}, {0x2070, 0xd7ff},
		{0xe000, 0xf8ff}, {0xf900, 0xfffd}, {0x10000, 0x1ffff}, {0x20000, 0x10ffff}, {0xfff0, 0xffff}, {0xe0000, 0xe01ff}}
	for i := 0; i < 4000; i++ {
		var b strings.Builder
		for j := 1 + r.Intn(3); j > 0; j-- {
			rg := ranges[r.Intn(len(ranges))]
			c := rg[0] + r.Intn(rg[1]-rg[0]+1)
			if c >= 0xd800 && c <= 0xdfff {
				c = 'A'
			}
			b.WriteRune(rune(c))
		}
		s := b.String()
		switch i % 3 {
		case 0:
			calls = append(calls, argv("office-get", "--state", s))
		case 1:
			calls = append(calls, argv("office-get", "-"+s))
		default:
			calls = append(calls, argv("office-get", "--state="+s+"'\""))
		}
	}
	return calls
}

const wrapOracle = `import sys, json, textwrap
texts = json.load(sys.stdin)
sys.stdout.write(json.dumps([[textwrap.wrap(t, w) for w in range(1, 41)] for t in texts]))`

// TestWrapMatchesTextwrap: wrap against textwrap.wrap at every width from 1 to 40, on the help texts
// and on text that reaches each of textwrap's rules — the hyphen breaks, the em-dashes of its own
// docstring, a word longer than the line with and without a hyphen in reach, spaces at the ends.
func TestWrapMatchesTextwrap(t *testing.T) {
	py := python(t)
	texts := []string{
		"Hello there -- you goof-ball, use the -b option!",
		"Look, goof-ball -- use the -b option!",
		"a-b-c ab-cd-ef x--y well-known--really e.g.--this --flag a-- -- ---- a---b _a-_b",
		"long-hyphenated-compound-word-here and-another-one-at-the-end",
		"supercalifragilisticexpialidocious-and-more antidisestablishmentarianism --------x",
		"  leading and trailing spaces  ", "two  spaces  between",
	}
	for _, o := range options {
		texts = append(texts, o.help)
	}
	in, _ := json.Marshal(texts)
	cmd := exec.Command(py[0], append(py[1:], "-c", wrapOracle)...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	cmd.Stdin = strings.NewReader(string(in))
	raw, err := cmd.Output()
	if err != nil {
		t.Fatalf("python: %v", err)
	}
	var want [][][]string
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatal(err)
	}
	for i, text := range texts {
		for w := 1; w <= 40; w++ {
			got := wrap(text, w)
			if strings.Join(got, "|") != strings.Join(want[i][w-1], "|") || len(got) != len(want[i][w-1]) {
				t.Errorf("wrap(%q, %d):\n go     %q\n python %q", text, w, got, want[i][w-1])
			}
		}
	}
	t.Logf("%d texts × 40 widths: textwrap's lines", len(texts))
}

func TestTheParserTakesWhatMainReads(t *testing.T) {
	a, code, done := parseArgs("services", []string{"--for", "a,b", "--fo=c", "--exclude", "x", "--by", "",
		"--state=archived", "--cr", "--json", "--capability", "-1", "--app", "-x y"}, io.Discard, io.Discard)
	if done || code != 0 {
		t.Fatalf("refused: %d", code)
	}
	want := Args{Capability: "-1", App: "-x y", State: "archived", By: "", Create: true, JSON: true,
		Roots: []string{"a,b", "c"}, Exclude: []string{"x"}}
	if strings.Join(a.Roots, "|") != "a,b|c" || strings.Join(a.Exclude, "|") != "x" ||
		a.Capability != want.Capability || a.App != want.App || a.State != want.State || a.By != want.By ||
		a.Create != want.Create || a.JSON != want.JSON {
		t.Fatalf("got %+v\nwant %+v", *a, want)
	}
	if got := strings.Join(csv(a.Roots), " "); got != "a b c" {
		t.Fatalf("csv(--for) = %s", got)
	}
	if a, _, _ := parseArgs("services", nil, io.Discard, io.Discard); a.By != "user" || a.Roots != nil {
		t.Fatalf("defaults: %+v", *a)
	}
}

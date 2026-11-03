package yamlish

import (
	"encoding/json"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf8"
)

// pyAnswers asks PyYAML's safe_load each source, in one process: the answer as json.dumps(sort_keys=True,
// ensure_ascii=True, separators=(",", ":")) — FlaskJSON's format, which carries a surrogate PyYAML keeps —
// or "!ERR <type>" where it refuses, or "!UNDUMPABLE <type>" where it reads a value JSON cannot hold (a
// date). Keys pass through JSON first, as they do on their way to every caller (remote-get's own round
// trip): 14 sorts after 2 as an int and before it as the string this reader keeps, and only the content
// is the question here.
func pyAnswers(t *testing.T, sources []string) []string {
	t.Helper()
	py := python(t)
	if py == nil {
		t.Skip("no python with PyYAML on PATH")
	}
	const prog = `import sys, json, yaml
out = []
for item in json.load(sys.stdin):
    try:
        v = yaml.safe_load(item)
    except Exception as e:
        out.append("!ERR " + type(e).__name__)
        continue
    try:
        d = json.loads(json.dumps(v))
    except Exception as e:
        out.append("!UNDUMPABLE " + type(e).__name__)
        continue
    out.append(json.dumps(d, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
json.dump(out, sys.stdout)`
	in, _ := json.Marshal(sources)
	cmd := exec.Command(py[0], append(py[1:], "-c", prog)...)
	cmd.Stdin = strings.NewReader(string(in))
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("PyYAML: %v", err)
	}
	var answers []string
	if err := json.Unmarshal(out, &answers); err != nil || len(answers) != len(sources) {
		t.Fatalf("PyYAML answered %d of %d: %v", len(answers), len(sources), err)
	}
	return answers
}

// TestEdgesAgreeWithPyYAML asks PyYAML and this reader the corners of the subset — what PyYAML's scanner
// refuses in a plain scalar, keys Python's dict makes one, escapes, line breaks in comments — and
// requires: where PyYAML refuses, this reader refuses as PyYAML does (not OutsideSubset); where both
// read, the same answer; where only PyYAML reads, a refusal OutsideSubset — a caller stops on it, and
// answers the other as Python answers a YAMLError; and where a case is marked `read`, this reader reads it.
func TestEdgesAgreeWithPyYAML(t *testing.T) {
	bs, tab := string(rune(92)), string(rune(9))
	ls, ps, nel, cr := string(rune(0x2028)), string(rune(0x2029)), string(rune(0x85)), string(rune(13))
	cases := []struct {
		name, src string
		read      bool
	}{
		// a plain scalar PyYAML's scanner refuses (the second reader's cases first)
		{"eq", "a: =\n", false}, {"at", "a: @deer\n", false}, {"backtick", "a: `x\n", false},
		{"pct", "a: %x\n", false}, {"colon", "a: b: c\n", false}, {"dash", "a: - x\n", false},
		{"rbracket", "a: ]x\n", false}, {"comma", "a: ,x\n", false}, {"rbrace", "a: }x\n", false},
		{"pipe", "a: |x\n", false}, {"question", "a: ? x\n", false}, {"tab after colon", "a:" + tab + "b\n", false},
		{"merge as a value", "a: <<\n", false}, {"a lone dash", "a: -\n", false}, {"a lone ?", "a: ?\n", false},
		{"a lone :", "a: :\n", false}, {"ends with :", "a: b:\n", false}, {"colon tab", "a: b:" + tab + "c\n", false},
		{"space colon", "a: b : c\n", false}, {"key @", "@k: v\n", false}, {"indented key %", "m:\n  %k: v\n", false},
		{"key with an anchor", "&a k: v\n", false}, {"item @", "- @x\n", false}, {"item ,", "- ,x\n", false},
		{"item =", "- =\n", false}, {"flow @", "a: [@x]\n", false}, {"flow - x", "a: [- x]\n", false},
		{"flow :x", "a: [:x]\n", false}, {"flow ?x", "a: [?x]\n", false}, {"flow a?b", "a: [a?b]\n", false},
		{"flow =", "a: [=]\n", false}, {"flow key @", "a: {@k: v}\n", false}, {"flow value %", "a: {k: %v}\n", false},
		{"remote value: x", "remote:\n- office: vps1: x\n", false}, {"remote value %", "remote:\n- office: %vps1\n", false},
		// escapes: past Unicode PyYAML fails; a surrogate it keeps as half a character, which is refused here
		{"beyond U+10FFFF", "a: \"" + bs + "U00110000\"\n", false},
		{"a lone surrogate", "a: \"" + bs + "ud800\"\n", false},
		{"a surrogate pair", "a: \"" + bs + "ud83d" + bs + "ude00\"\n", false},
		{"U+10FFFF", "a: \"" + bs + "U0010FFFF\"\n", true}, {"NUL", "a: \"" + bs + "u0000\"\n", true},
		{"x1c", "a: \"" + bs + "x1cenabled\"\n", true},
		// keys Python's dict makes one: refused here, unless they are spelled alike
		{"1 and true", "a: {1: x, true: y}\n", false}, {"1 and 1.0", "a: {1: x, 1.0: y}\n", false},
		{"0 and false", "a: {0: x, false: y}\n", false}, {"-0.0 and 0", "a: {-0.0: x, 0: y}\n", false},
		{"block 1 and true", "a:\n  1: x\n  true: y\n", false},
		{"1 and 0x1", "a: {1: x, 0x1: y}\n", true}, {"NaN twice", "a: {.nan: x, .nan: y}\n", true},
		// read alike
		{"bang inside", "a: x!\n", true}, {"amp inside", "a: x &y\n", true}, {"-x", "a: -x\n", true},
		{"?x", "a: ?x\n", true}, {":x", "a: :x\n", true}, {"url", "a: http://x:80/y\n", true},
		{"a default", "a: ${A:-}\n", true}, {"a drive", "a: C:" + bs + "x\n", true}, {"key -k", "-k: v\n", true},
		{"key ?k", "?k: v\n", true}, {"key :k", ":k: v\n", true}, {"key =", "=: v\n", true},
		{"flow -x", "a: [-x]\n", true}, {"sexagesimal", "a: 1:1:0.1\n", false},
		// every line break PyYAML reads: a lone CR and NEL as "\n", U+2028 and U+2029 kept where a scalar
		// folds — in comments, in plain and quoted scalars, and as Python's own writer puts them
		{"LS then key", "a: 1 # x" + ls + "b: 2\n", true}, {"LS then tab", "a: 1 # x" + ls + tab + "# y\n", false},
		{"LS then spaces", "a: 1 # x" + ls + "   \n", true},
		{"NEL in a block scalar", "k: |\n  t # c" + nel + "# d\nz: 1\n", true},
		{"LS ending a block scalar line", "k: |\n  t" + ls + "\nz: 1\n", false},
		{"CR in a quoted continuation", "k: \"a\n  b # c" + cr + "\"\n", true},
		{"a CR-only file", "office:" + cr + "  name: cr" + cr, true},
		{"CR, CR LF and LF together", "a: 1" + cr + "b: 2" + cr + "\nc: 3\n", true},
		{"NEL ending a plain value", "office:\n  name: a" + nel + "b\n", false},
		{"LS ending a plain value", "office:\n  name: a" + ls + "b\n", false},
		{"LS folding a plain value", "a: x" + ls + "  y\n", true},
		{"PS in a flow collection", "a: [x," + ps + " y]\n", false},
		{"python's own writer", "schema_version: 1\nremote:\n- office: peer\n  label:\n    he: 'a" + ls + "      b'\n" +
			"    en: 'c" + ps + "      d'\n  apps:\n  - app: x\n    alias: y\n    desc: 'one" + ls + "      two'\n" +
			"    n: 'p" + nel + "      q'\n    both: 'x" + ls + ps + "      y'\n    nl: 'm\n\n      n'\n" +
			"    lsnl: 'u" + ls + "\n      v'\n", true},
		{"an escaped break alone on a line", "a: \"x\n  " + bs + "\n  y\"\n", true},
		{"a leading tab", "a: " + tab + "b\n", false},
		// block scalars where the source ends without a break, and with blank lines only
		{"literal at the end", "k: |\n  text", true}, {"strip at the end", "k: |-\n  a", true},
		{"folded at the end", "k: >\n  a\n  b", true}, {"keep with no text", "k: |+\n\nz: 1\n", true},
		{"clip with no text", "k: |\n\nz: 1\n", true},
		// the document's end marker
		{"... at the end", "a: 1\n...\n", true}, {"--- then ...", "---\n...\n", true},
		{"... then a comment", "a: 1\n...\n# c\n", true}, {"... then a document", "a: 1\n...\nb: 2\n", false},
		{"... twice", "a: 1\n...\n...\n", true}, {"... comment ...", "a: 1\n...\n# c\n...\n", true},
		{"... then a directive", "a: 1\n...\n%YAML 1.1\n", false}, {"a --- after the document", "a: 1\n---\n", false},
		{"--- twice", "---\n---\na: 1\n", false}, {"--- inside a quoted scalar", "a: \"x\n---\n y\"\n", false},
		// a `%` starting a line: text where it continues a scalar, else a directive inside the document
		{"% continuing a quoted scalar", "a: \"x\n%y\"\n", true}, {"% mid-document", "a: 1\n%x\nb: 2\n", false},
		{"% after ---", "---\n%x\na: 1\n", false}, {"% inside a flow collection", "a: [1,\n%x]\n", false},
		{"% continuing a top-level plain scalar", "text\n%more\n", true},
		// aliases: one naming no anchor above it, or with more after it, PyYAML refuses; a comment it reads
		{"an undefined alias", "a: *nope\n", false}, {"more after an alias", "a: &x []\nb: *x y\n", false},
		{"a comment after an alias", "a: &x [1]\nb: *x # c\n", true},
		// a block scalar's header, as PyYAML's scanner reads the rest of its line
		{"header |0", "a: |0\n  x\n", false}, {"header |--", "a: |--\n  x\n", false}, {"header |12", "a: |12\n  x\n", false},
		{"header |+-", "a: |+-\n  x\n", false}, {"header |1 2", "a: |1 2\n  x\n", false}, {"header |#c", "a: |#c\n  x\n", false},
		{"header | tab", "a: |" + tab + "\n  x\n", false}, {"header |  tab", "a: |  " + tab + "\n  x\n", false},
		{"header |1-", "a: |1-\n  x\n", true}, {"header |-1", "a: |-1\n  x\n", true}, {"header >2-", "a: >2-\n   x\n", true},
		{"header | # c", "a: | # c\n  x\n", true}, {"header |- # c", "a: |- # c\n  x\n", true},
		{"item header | tab", "- |" + tab + "\n  x\n", false}, {"item header |- # c", "- |- # c\n  x\n", true},
		{"flow ? x", "a: [? x]\n", false},
		// a plain scalar continues on any more-indented line — one that starts like structure too — and
		// ends at a comment, after which a more-indented line is one PyYAML refuses
		{"a continuation that starts with a dash", "a: b\n  - c\n", true},
		{"an item's continuation that starts with a dash", "- a\n  - b\n", true},
		{"a continuation that starts with [", "a: b\n  [c]\n", true}, {"a continuation that starts with {", "a: b\n  {c}\n", true},
		{"a continuation that is a lone dash", "a: b\n  -\n", true}, {"a dash continuation holding a key", "a: b\n  - c: d\n", false},
		{"a comment line, then more text", "a: b\n  # c\n  d\n", false},
		{"a blank line and a comment line, then more text", "a: b\n\n  # c\n  d\n", false},
		{"a trailing comment, then more text", "a: b # c\n  d\n", false},
		{"a continuation's comment, then more text", "a: b\n  c # x\n  d\n", false},
		{"an item's trailing comment, then more text", "- a # c\n  b\n", false},
		{"a comment line ends the scalar", "a: b\n  c\n  # x\nz: 1\n", true},
		{"a blank line inside the scalar", "a: b\n\n  c\n", true},
		// tags: safe_load's own (`!`, YAML's twelve `!!`) it reads, outside this subset; any other it refuses
		{"a !!str value", "a: !!str 1\n", false}, {"a ! value", "a: ! x\n", false},
		{"a verbatim str tag", "a: !<tag:yaml.org,2002:str> x\n", false},
		{"a !!js value", "a: !!js x\n", false}, {"a local tag", "a: !local x\n", false},
		{"a tag and a tab", "a: !!str" + tab + "x\n", false}, {"a tagged item", "- !!js x\n", false},
		{"a tagged key", "!!js k: v\n", false}, {"a tagged !!str key", "!!str 1: v\n", false},
		{"a tagged flow item", "a: [!!js x]\n", false}, {"a tagged flow key", "a: {!!str 1: x}\n", false},
		{"an anchored flow key", "a: {&k x: y}\n", false}, {"a tagged block node", "a:\n  !!map\n  b: 1\n", false},
		// tabs: PyYAML's scanner skips only spaces between tokens — a tab anywhere but inside a quoted
		// scalar, a block scalar's content or a comment it refuses
		{"a trailing tab", "a: b" + tab + "\n", false}, {"a tab before a comment", "a: b" + tab + "# c\n", false},
		{"a tab inside a plain scalar", "a: b" + tab + "c\n", false}, {"a space and a tab in a plain scalar", "a: b " + tab + "c\n", false},
		{"a tab after an empty value", "a:" + tab + "\n", false}, {"a tab after a flow collection", "a: [b]" + tab + "\n", false},
		{"a tab after a quoted scalar", "a: \"b\"" + tab + "\n", false}, {"a tab after the end marker", "k: v\n..." + tab + "\n", false},
		{"a tab-only line between entries", "a: 1\n" + tab + "\nb: 2\n", false},
		{"spaces and a tab between entries", "a: 1\n  " + tab + "\nb: 2\n", false},
		{"a tab-indented comment line", "a: 1\n" + tab + "# c\nb: 2\n", false},
		{"a tab in a comment", "a: b # c" + tab + "d\n", true}, {"a tab between flow items", "a: [b," + tab + "c]\n", false},
		{"a tab after [", "a: [" + tab + "b]\n", false}, {"a tab inside a quoted scalar", "a: \"b" + tab + "c\"\n", true},
		{"a tab after a dash", "-" + tab + "x\n", false}, {"a tab inside a key", "a" + tab + "b: c\n", false},
		{"a tab before the colon", "a" + tab + ": c\n", false},
		{"a tab in block content", "a: |\n  line1\n  " + tab + "x\n", true},
		{"a tab-only line in block content", "a: |\n  x\n  " + tab + "\n  y\n", true},
		{"a tab at column 0 in block content", "a: |\n  x\n" + tab + "\n  y\n", false},
		{"a tab leading a quoted continuation", "a: \"x\n  " + tab + "y\"\n", true},
		{"a tab-only line in a quoted scalar", "a: \"x\n" + tab + "\n  y\"\n", true},
		{"a heredoc's tab in a command", "c:\n  command: |\n    cat <<-EOF\n    " + tab + "line\n    EOF\n", true},
		// a block scalar's indentation: the deepest of its leading blank lines counts too
		{"a deep blank line before a block's content", "a: |\n      \n  x\n", false},
		{"a blank line as deep as the content", "a: |\n    \n    x\n", true},
		{"a whitespace line deeper than the block, inside it", "a: |\n  x\n      \n  y\n", true},
		{"an explicit indentation under a deeper blank line", "a: |2\n      \n  x\n", true},
		{"a block at the top", "|\n x\n", true}, {"a block at the top, at column 0", "|\nx\n", false},
		{"a block at the top, |1", "|1\n  x\n", true},
		{"a double quote inside a plain scalar, then a comment", "a: b\"c # d\n", true},
		// folding: a break next to an indented line is kept, blank lines and all — the leading ones too
		{"folded: an indented line, a blank, text", "a: >\n  x\n    y\n\n  z\n", true},
		{"folded: a tab-led line, a blank, text", "a: >\n  x\n  " + tab + "y\n\n  z\n", true},
		{"folded, stripped: an indented line, a blank, text", "a: >-\n  x\n    y\n\n  z\n", true},
		{"folded: a leading blank line", "a: >\n\n  x\n", true}, {"folded: two leading blank lines", "a: >\n\n\n  x\n  y\n", true},
		// a quoted scalar spanning lines inside a flow collection: PyYAML folds it, outside this subset
		{"in flow, a quoted scalar spanning a tab", "a: [\"x\n  y" + tab + "z\"]\n", false},
		{"in flow, a quoted scalar continued by a tab", "a: [\"x\n" + tab + "y\"]\n", false},
		{"in flow, a quoted scalar spanning ' #'", "a: [\"x\n  y # z\"]\n", false},
		{"in flow, a quoted scalar spanning a blank line", "a: [\"x\n\n  y\"]\n", false},
		{"in flow, a quoted scalar spanning an escaped break", "a: [\"x" + bs + "\n  y\"]\n", false},
		// a `#` right after a token is a comment; inside a plain scalar it is text
		{"a comment glued to a flow sequence", "a: [x]# c\n", true}, {"a comment glued to a flow mapping", "a: {b: 1}# c\n", true},
		{"a comment glued to an item's flow", "- [x]# c\n", true}, {"a comment glued to a quoted scalar", "a: \"x\"# c\n", true},
		{"a tab in a comment glued to a flow", "a: [x]# c" + tab + "d\n", true},
		{"a bracket and a hash inside a plain scalar", "a: x]#y\n", true},
		// a quote opens a scalar only where a token may start
		{"a quote after a colon, then a tab, in block context", "a:\"x" + tab + "y\"\n", false},
		{"a quote after a colon, then a comment, in block context", "a:\"b # c\"\n", true},
		{"JSON's style in a flow mapping", "a: {\"b\":\"c # d\"}\n", true},
		{"a bracket inside a plain scalar, then a comment", "a: x[1,\"y # z\"]\n", true},
		{"an apostrophe in a flow item", "a: [it's]\n", true},
		// a scalar's lines are measured from its parent's indentation — for an item, from the dash
		{"an item's block scalar, |2", "a:\n  - |2\n     x\n", true}, {"an item's block scalar at column 1", "- |\n x\n", true},
		{"an item's block scalar, |1", "- |1\n  x\n", true}, {"an item's plain scalar continued at column 1", "- a\n b\n", true},
		{"a scalar below a key, continued at column 1", "a:\n  b\n c\n", true}, {"a block scalar below a key", "a:\n  |\n   x\n", true},
		// an item's complex key PyYAML reads; outside the subset, as everywhere
		{"an item's complex key", "- ? x\n", false}, {"an item's bare ?", "- ?\n", false}, {"a nested item's complex key", "- - ? x\n", false},
		// what PyYAML's parser wants around a document
		{"a directive without ---", "%YAML 1.1\na: 1\n", false}, {"only ...", "...\n", false},
		{"a comment, then ...", "# c\n...\n", false}, {"... then ---", "...\n---\na: 1\n", false},
		// an alias naming no anchor, wherever it stands, PyYAML refuses; one that does, it reads
		{"an undefined alias in flow", "a: [*nope]\n", false}, {"an undefined alias on its own line", "a:\n  *nope\n", false},
		{"a defined alias in flow", "a: &x [1]\nb: [*x]\n", false},
	}
	for _, br := range []struct{ name, s string }{{"LS", ls}, {"PS", ps}, {"NEL", nel}, {"CR", cr}} {
		cases = append(cases,
			struct {
				name, src string
				read      bool
			}{br.name + " comment then comment", "a: 1 # x" + br.s + "# y\n", true},
			struct {
				name, src string
				read      bool
			}{br.name + " comment then blank", "a: 1 # x" + br.s + "\n", true},
			struct {
				name, src string
				read      bool
			}{br.name + " full-line comment", "# note" + br.s + "# more\nschema_version: 1\n", true})
	}
	srcs := make([]string, len(cases))
	for i, c := range cases {
		srcs[i] = c.src
	}
	want := pyAnswers(t, srcs)
	for i, c := range cases {
		v, err := Unmarshal([]byte(c.src))
		pyRefuses := strings.HasPrefix(want[i], "!ERR")
		switch {
		case err == nil && pyRefuses:
			t.Errorf("%s: read as %s, where PyYAML refuses (%s)", c.name, FlaskJSON(v), want[i])
		case err == nil && FlaskJSON(v) != want[i]:
			t.Errorf("%s: read as %s, PyYAML reads %s", c.name, FlaskJSON(v), want[i])
		case err != nil && c.read:
			t.Errorf("%s: refused (%v), where PyYAML reads %s", c.name, err, want[i])
		case err != nil && pyRefuses && OutsideSubset(err):
			t.Errorf("%s: refused as outside the subset (%v), where PyYAML refuses it too (%s) — a caller would stop where Python goes on", c.name, err, want[i])
		case err != nil && !pyRefuses && !OutsideSubset(err):
			t.Errorf("%s: refused as PyYAML refuses (%v), yet PyYAML reads %s — a caller would answer where Python reads", c.name, err, want[i])
		}
	}
	t.Logf("%d corners: each refused where PyYAML refuses, read alike where both read", len(cases))
}

// TestTheTreeIsReadAsPyYAMLReadsIt sweeps every YAML file of this checkout. Where PyYAML reads a file,
// this reader reads it alike or refuses it as outside its subset (OutsideSubset) — never as a refusal
// PyYAML makes — and never reads it otherwise: no guess anywhere in the tree. Where PyYAML refuses a
// file, this reader refuses it too, and says it is PyYAML's refusal (not OutsideSubset).
func TestTheTreeIsReadAsPyYAMLReadsIt(t *testing.T) {
	root := repoRoot(t)
	// each file read once, and both readers asked the same text: a live checkout rewrites .generated/
	// under the test and holds files this user may not read (skipped, as is text that is not UTF-8,
	// which the reader refuses whole)
	var files, srcs []string
	_ = filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() && (d.Name() == ".git" || d.Name() == "node_modules" || d.Name() == ".claude") {
			return filepath.SkipDir
		}
		if d.IsDir() || !strings.HasSuffix(p, ".yml") && !strings.HasSuffix(p, ".yaml") {
			return nil
		}
		if raw, err := os.ReadFile(p); err == nil && utf8.Valid(raw) {
			files, srcs = append(files, p), append(srcs, string(raw))
		}
		return nil
	})
	want := pyAnswers(t, srcs)
	agree, refused, both := 0, 0, 0
	for i, f := range files {
		v, err := Unmarshal([]byte(srcs[i]))
		rel, _ := filepath.Rel(root, f)
		switch pyRefuses := strings.HasPrefix(want[i], "!ERR"); {
		case pyRefuses && err == nil:
			t.Errorf("%s: read, where PyYAML refuses it (%s)", rel, want[i])
		case pyRefuses && OutsideSubset(err):
			t.Errorf("%s: refused as outside the subset (%v), where PyYAML refuses it too (%s)", rel, err, want[i])
		case pyRefuses:
			both++
		case err == nil && FlaskJSON(v) != want[i]:
			t.Errorf("%s: read otherwise than PyYAML reads it", rel)
		case err == nil:
			agree++
		case !OutsideSubset(err):
			t.Errorf("%s: refused as PyYAML would refuse it, yet PyYAML reads it: %v", rel, err)
		default:
			refused++
			t.Logf("outside the subset: %s — %v", rel, err)
		}
	}
	t.Logf("%d YAML files: %d read as PyYAML reads them, %d outside this reader's subset (refused, never guessed), %d refused by both",
		len(files), agree, refused, both)
}

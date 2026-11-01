package yamlish

import (
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// known-answer cases: what PyYAML's safe_load answers, written as the canonical JSON the oracle
// test compares — so a reader of this file sees both sides on one line.
func TestKnownAnswers(t *testing.T) {
	cases := []struct{ name, yaml, want string }{
		{"empty document", "", "null"},
		{"comment only", "# nothing\n", "null"},
		{"scalar document", "hello", `"hello"`},
		{"map", "a: 1\nb: two\n", `{"a":1,"b":"two"}`},
		{"nested", "a:\n  b:\n    c: 3\n", `{"a":{"b":{"c":3}}}`},
		{"sequence", "- a\n- b\n", `["a","b"]`},
		{"indentless sequence", "k:\n- a\n- b\nz: 1\n", `{"k":["a","b"],"z":1}`},
		{"indented sequence", "k:\n  - a\n  - b\n", `{"k":["a","b"]}`},
		{"compact map in sequence", "- name: x\n  value: y\n- name: z\n", `[{"name":"x","value":"y"},{"name":"z"}]`},
		{"nested sequence in sequence", "- - a\n  - b\n- c\n", `[["a","b"],"c"]`},
		{"null item and null value", "- \nk:\n", `["k"]`}, // placeholder, replaced below
		{"flow map", "apps:\n  x:   { enabled: true }   # c\n", `{"apps":{"x":{"enabled":true}}}`},
		{"flow map two keys", "n8n: { state: disabled, by: cli }", `{"n8n":{"by":"cli","state":"disabled"}}`},
		{"flow seq", `test: ["CMD", "curl", "-f", "http://x"]`, `{"test":["CMD","curl","-f","http://x"]}`},
		{"flow seq multi-line", "test: [\"CMD\",\n  \"curl\"]\nz: 1", `{"test":["CMD","curl"],"z":1}`},
		{"flow nested", "a: [1, {b: [2, 3]}, []]", `{"a":[1,{"b":[2,3]},[]]}`},
		{"flow trailing comma", "a: [1, 2, ]", `{"a":[1,2]}`},
		{"empty flow", "a: {}\nb: []", `{"a":{},"b":[]}`},
		{"bools 1.1", "- yes\n- No\n- ON\n- off\n- true\n- False", `[true,false,true,false,true,false]`},
		{"ints", "- 0\n- 42\n- -7\n- 0755\n- 0x1F\n- 0b101\n- 1_000\n- 1:20", `[0,42,-7,493,31,5,1000,80]`},
		{"floats", "- 1.5\n- -0.25\n- 1.\n- .5\n- 1.0e+3\n- 2.0", `[1.5,-0.25,1.0,0.5,1000.0,2.0]`},
		{"strings that look numeric", "- 1e5\n- 1.5e5\n- 08\n- 0o17\n- +\n- 12abc", `["1e5","1.5e5","08","0o17","+","12abc"]`},
		{"nulls", "- ~\n- null\n- NULL\n-\n- Null", `[null,null,null,null,null]`},
		{"quoted keep strings", `- "yes"` + "\n- 'no'\n- '0755'\n- \"1\"", `["yes","no","0755","1"]`},
		{"double-quoted escapes", `s: "a\tb\n\"q\" \\ \u00e9 \x41"`, `{"s":"a\tb\n\"q\" \\ é A"}`},
		{"single-quoted doubles", `s: 'it''s # not a comment'`, `{"s":"it's # not a comment"}`},
		{"comment rules", "a: b#c # real\nu: http://h/#frag\n", `{"a":"b#c","u":"http://h/#frag"}`},
		{"url value is not a key", "u: http://h:8080/x\n", `{"u":"http://h:8080/x"}`},
		{"compose-ish", "services:\n  web:\n    image: nginx:1.25\n    ports:\n      - \"80:80\"\n      - 443:443\n    environment:\n      - KEY=v\n      - DSN=${X:-a:b}\n    labels:\n      traefik.http.routers.web.rule: Host(`web.localhost`)\n",
			`{"services":{"web":{"environment":["KEY=v","DSN=${X:-a:b}"],"image":"nginx:1.25","labels":{"traefik.http.routers.web.rule":"Host(` + "`web.localhost`" + `)"},"ports":["80:80","443:443"]}}}`},
		{"multi-line plain scalar", "k: one\n  two\n   three\nz: 1", `{"k":"one two three","z":1}`},
		{"plain scalar blank line folds to newline", "k: one\n\n  two\n", `{"k":"one\ntwo"}`},
		{"literal block", "k: |\n  line1\n  line2\n\nz: 1", `{"k":"line1\nline2\n","z":1}`},
		{"literal strip", "k: |-\n  a\n  b\n", `{"k":"a\nb"}`},
		{"literal keep", "k: |+\n  a\n\n", `{"k":"a\n\n"}`},
		{"folded block", "k: >\n  a\n  b\n\n  c\n", `{"k":"a b\nc\n"}`},
		{"folded more-indented", "k: >-\n  a\n    b\n  c\n", `{"k":"a\n  b\nc"}`},
		{"folded blank then more-indented", "k: >\n  a\n\n    b\n  c\n", `{"k":"a\n\n  b\nc\n"}`},
		{"folded two blanks", "k: >\n  a\n\n\n  b\n", `{"k":"a\n\nb\n"}`},
		{"folded keep trailing", "k: >+\n  a\n\n\n", `{"k":"a\n\n\n"}`},
		{"dq multi-line", "k: \"one\n  two\n\n  three\"\n", `{"k":"one two\nthree"}`},
		{"dq escaped break", "k: \"one \\\n  two\"\n", `{"k":"one two"}`},
		{"dq escaped break then escaped space", "k: \"one\\\n  \\ two\"\n", `{"k":"one two"}`},
		{"dq escaped backslash at line end", "k: \"one\\\\\n  two\"\n", `{"k":"one\\ two"}`},
		{"sq multi-line", "k: 'one\n  two'\n", `{"k":"one two"}`},
		{"dq multi-line in sequence", "- \"a\n  b\"\n- c\n", `["a b","c"]`},
		{"hash inside multi-line quotes", "k: \"a\n  # not a comment\"\n", `{"k":"a # not a comment"}`},
		{"document marker", "---\na: 1\n", `{"a":1}`},
		{"unicode", "שם: בינה\n", `{"שם":"בינה"}`},
		{"numeric key", "80: x\ntrue: y\n", `{"80":"x","true":"y"}`},
		{"duplicate key keeps first place last value", "a: 1\nb: 2\na: 3\n", `{"a":3,"b":2}`},
		{"empty value then sibling", "a:\nb: 1\n", `{"a":null,"b":1}`},
		{"deep sequence of maps with nested lists", "x:\n  - n: a\n    l:\n      - 1\n      - 2\n  - n: b\n", `{"x":[{"l":[1,2],"n":"a"},{"n":"b"}]}`},
		{"windows newlines", "a: 1\r\nb:\r\n  - x\r\n", `{"a":1,"b":["x"]}`},
		{"bom", string(rune(0xFEFF)) + "a: 1\n", `{"a":1}`},
	}
	cases[10] = struct{ name, yaml, want string }{"null item and null value", "- \n- k:\n", `[null,{"k":null}]`}
	for _, c := range cases {
		v, err := Unmarshal([]byte(c.yaml))
		if err != nil {
			t.Errorf("%s: %v", c.name, err)
			continue
		}
		if got := CanonicalJSON(v); got != c.want {
			t.Errorf("%s:\n got  %s\n want %s", c.name, got, c.want)
		}
	}
}

func TestRefusesWhatItDoesNotSpeak(t *testing.T) {
	cases := []struct{ name, yaml, wantErr string }{
		{"anchor", "a: &x 1\nb: *x\n", "anchors"},
		{"alias", "a: *x\n", "anchors"},
		{"tag", "a: !!str 1\n", "anchors, aliases and tags"},
		{"merge key", "a:\n  <<: {b: 1}\n", "merge key"},
		{"two documents", "a: 1\n---\nb: 2\n", "more than one document"},
		{"directive", "%YAML 1.1\n---\na: 1\n", "directive"},
		{"complex key", "? a\n: b\n", "complex key"},
		{"tab indent", "a:\n\tb: 1\n", "tab"},
		{"timestamp", "t: 2026-10-10\n", "timestamp"},
		{"bad indent", "a:\n  b: 1\n c: 2\n", "indent"},
		{"colon in plain continuation", "a: b\n  c: d\n", "mapping values"},
		{"int overflow", "n: 99999999999999999999\n", "64 bits"},
	}
	for _, c := range cases {
		_, err := Unmarshal([]byte(c.yaml))
		if err == nil {
			t.Errorf("%s: parsed without error, must refuse", c.name)
			continue
		}
		if !strings.Contains(err.Error(), c.wantErr) {
			t.Errorf("%s: error %q does not name %q", c.name, err, c.wantErr)
		}
	}
}

func TestMapKeepsInsertionOrder(t *testing.T) {
	v, err := Unmarshal([]byte("z: 1\na: 2\nm: 3\n"))
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(v.(*Map).Keys(), ","); got != "z,a,m" {
		t.Fatalf("keys in order = %s, want z,a,m", got)
	}
}

func TestPythonFloatRepr(t *testing.T) {
	cases := map[float64]string{
		1.5: "1.5", 2: "2.0", 0.1: "0.1", 100: "100.0", 1e16: "1e+16", 1234567.0: "1234567.0",
		1e-5: "1e-05", 0.0001: "0.0001", 123456789012345680.0: "1.2345678901234568e+17", -0.5: "-0.5",
		1e15: "1000000000000000.0", 3.0e-7: "3e-07",
	}
	for f, want := range cases {
		if got := pythonFloat(f); got != want {
			t.Errorf("repr(%v) = %s, want %s", f, got, want)
		}
	}
}

// ── the oracle: PyYAML on every file the compiler reads ───────────────────────────────────────────

// python finds an interpreter with PyYAML the way each OS has it, or "" (the test then skips).
func python(t *testing.T) []string {
	for _, c := range [][]string{{"python3"}, {"python"}, {"py", "-3"}} {
		if _, err := exec.LookPath(c[0]); err != nil {
			continue
		}
		cmd := exec.Command(c[0], append(c[1:], "-c", "import yaml")...)
		if cmd.Run() == nil {
			return c
		}
	}
	return nil
}

func repoRoot(t *testing.T) string {
	d, _ := os.Getwd()
	for {
		if st, err := os.Stat(filepath.Join(d, "platform.state.yaml")); err == nil && !st.IsDir() {
			return d
		}
		parent := filepath.Dir(d)
		if parent == d {
			t.Skip("not inside the checkout (no platform.state.yaml above)")
		}
		d = parent
	}
}

// corpus is every YAML the compiler reads: the state file and each app's compose files and overlays.
func corpus(t *testing.T, root string) []string {
	var files []string
	for _, g := range []string{
		"platform.state.yaml",
		"apps/*/docker-compose*.yml", "platform-base/*/docker-compose*.yml",
		"apps/*/*.yml", "platform-base/*/*.yml",
		".generated/*.yml",
	} {
		m, _ := filepath.Glob(filepath.Join(root, g))
		files = append(files, m...)
	}
	sort.Strings(files)
	out := files[:0]
	seen := map[string]bool{}
	for _, f := range files {
		if !seen[f] {
			seen[f] = true
			out = append(out, f)
		}
	}
	return out
}

const oracle = `import sys, json, yaml
d = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
sys.stdout.write(json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":")))`

func TestCorpusMatchesPyYAML(t *testing.T) {
	py := python(t)
	if py == nil {
		t.Skip("no python with PyYAML on PATH")
	}
	root := repoRoot(t)
	files := corpus(t, root)
	if len(files) < 20 {
		t.Fatalf("only %d corpus files found under %s — the globs are wrong", len(files), root)
	}
	for _, f := range files {
		rel, _ := filepath.Rel(root, f)
		src, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command(py[0], append(py[1:], "-c", oracle, f)...)
		cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
		want, err := cmd.Output()
		if err != nil {
			t.Errorf("%s: PyYAML itself failed: %v", rel, err)
			continue
		}
		v, err := Unmarshal(src)
		if err != nil {
			t.Errorf("%s: %v", rel, err)
			continue
		}
		if got := CanonicalJSON(v); got != string(want) {
			t.Errorf("%s: differs from PyYAML at byte %d:\n got  …%s\n want …%s", rel, firstDiff(got, string(want)),
				window(got, firstDiff(got, string(want))), window(string(want), firstDiff(got, string(want))))
		}
	}
	t.Logf("%d files agree with PyYAML", len(files))
}

func firstDiff(a, b string) int {
	n := len(a)
	if len(b) < n {
		n = len(b)
	}
	for i := 0; i < n; i++ {
		if a[i] != b[i] {
			return i
		}
	}
	return n
}

func window(s string, at int) string {
	lo, hi := at-60, at+120
	if lo < 0 {
		lo = 0
	}
	if hi > len(s) {
		hi = len(s)
	}
	return s[lo:hi]
}

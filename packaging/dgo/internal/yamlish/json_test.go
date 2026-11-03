package yamlish

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

// jsonCases are documents for json.loads — the values it answers and the refusals it words — and, for
// every value, the two json.dumps spellings the compiler uses (CanonicalJSON, DumpsJSON).
var jsonCases = []string{
	// values
	`{"a":1}`, ` [ ] `, `{}`, `true`, `null`, `0`, `-1`, `1.0`, `"x"`, "\n\t{ \"a\" : 1 , \"b\" : [ 2 ] }\r\n",
	`[1, 2.5, -0, -0.0, 1e5, 1E-5, 1.5e+300, 1e400, -1e400, 1e-400, 123456789012345678901234567890, -98765432109876543210]`,
	`"\ud83c\udfe0"`, `"\u00e9\u05e9"`, `"\/\b\f\n\r\t\"\\"`, `"a\u0000b\u001f"`, `"שלום 🏠"`, `"\u007f\u0080\uffff"`,
	`{"a":1,"a":2,"b":3,"a":4}`, `{"z":1,"a":{"y":[],"b":{}}}`, `NaN`, `[Infinity,-Infinity,NaN]`,
	`{"k": {"n": [[], {}, [[[]]]]}}`, `["` + strings.Repeat("9", 4300) + `"]`, strings.Repeat("9", 4300),
	// refusals
	``, ` `, `[`, `]`, `{`, `{"a"`, `{"a":`, `{"a":1`, `{"a":1,`, `{"a":1,}`, `{"a" 1}`, `{1:2}`, `[1,]`,
	`[1 2]`, `[,1]`, `"abc`, `"a\`, `"a\x"`, `"\u0012"`, `"\u12G4"`, `"\u12"x`, `"\ud83c\uZZZZ"`, "\"a\x01b\"",
	`nul`, `[nul]`, `tru`, `fals`, `-`, `-a`, `01`, `1.`, `1e`, `1e+`, `.5`, `+1`, `[1]x`, `{"a":1}}`,
	"\ufeff[1]", "\"tab\there\"", "[\n1,\n2,\n]", "{\n\"a\":\n}", `-Inf`, `NaNx`, `Infinit`, `[1,,2]`,
	strings.Repeat("9", 4301), "-" + strings.Repeat("1", 4302), `{"a":1,"b"}`, `{"a":1 "b":2}`,
	`[` + strings.Repeat("[", 50) + strings.Repeat("]", 50), "\"\u2028\"x", `"\u12`, `"\u123`,
}

const pyLoads = `import sys, json
out = []
for text in json.load(sys.stdin):
    try:
        v = json.loads(text)
    except ValueError as e:
        out.append(["err", str(e)])
        continue
    out.append(["ok", json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":")), json.dumps(v)])
sys.stdout.write(json.dumps(out))`

func TestLoadJSONMatchesPython(t *testing.T) {
	py := python(t)
	if py == nil {
		noPython(t)
	}
	var want [][]string
	if err := json.Unmarshal(pyRun(t, py, pyLoads, jsonCases), &want); err != nil {
		t.Fatal(err)
	}
	for i, c := range jsonCases {
		show := c
		if len(show) > 60 {
			show = show[:60] + "…"
		}
		v, err := LoadJSON(c)
		if want[i][0] == "err" {
			if err == nil || err.Error() != want[i][1] {
				t.Errorf("%q: error %v, python %q", show, err, want[i][1])
			}
			continue
		}
		if err != nil {
			t.Errorf("%q: %v, python accepted it", show, err)
			continue
		}
		got := []string{CanonicalJSON(v), DumpsJSON(v)}
		for k, g := range got {
			if g != want[i][k+1] {
				t.Errorf("%q: dump %d\n got  %s\n want %s", show, k, g, want[i][k+1])
			}
		}
	}
	t.Logf("%d documents: same values and same refusals as json.loads", len(jsonCases))
}

// Where this decoder's answer is not simply json.loads': a lone surrogate escape (Python keeps it in a
// str; a Go string cannot hold it), and the nesting limit, which is Python's own but a measured one —
// CPython 3.12.10, these tests' oracle, decodes 2997 levels and raises RecursionError at the 2998th,
// naming what it was decoding. Other releases stop elsewhere (measured: 3.12.2 at the 1498th, 3.11.9
// near the 988th — its 1000 frames less those in use — and 3.14 past the 14,000th, by stack size).
func TestLoadJSONRefusesWhatGoCannotHold(t *testing.T) {
	for _, c := range []string{`"\ud800"`, `"\udc00"`, `"\ud800\u0041"`, `["x\ud800"]`} {
		var je *JSONError
		if _, err := LoadJSON(c); !errors.As(err, &je) || !strings.HasPrefix(je.Msg, "Unpaired surrogate") {
			t.Errorf("%s: %v, want the unpaired-surrogate refusal", c, err)
		}
	}
	nest := map[string]func(n int) string{
		"array":  func(n int) string { return strings.Repeat("[", n) + strings.Repeat("]", n) },
		"object": func(n int) string { return strings.Repeat(`{"a":`, n) + "1" + strings.Repeat("}", n) },
	}
	for kind, doc := range nest {
		if _, err := LoadJSON(doc(2997)); err != nil {
			t.Errorf("%s, 2997 levels: %v", kind, err)
		}
		want := "maximum recursion depth exceeded while decoding a JSON " + kind + " from a unicode string"
		if _, err := LoadJSON(doc(2998)); !errors.Is(err, ErrJSONTooDeep) || err.Error() != want {
			t.Errorf("%s, 2998 levels: %v, want RecursionError: %s", kind, err, want)
		}
	}
}

// TestLoadJSONMatchesPythonOnRandomDocuments holds LoadJSON to json.loads on a seeded random corpus
// (testdata/json_corpus.py): strings of JSON tokens, documents json.dumps writes in each of its
// spellings and each of them mutated once, and corners — the same value, or the same refusal word for
// word. What may differ is what TestLoadJSONRefusesWhatGoCannotHold names: a document whose one fault,
// to Go, is a lone surrogate escape, and nesting deeper than the oracle's own release decodes.
func TestLoadJSONMatchesPythonOnRandomDocuments(t *testing.T) {
	t.Parallel()
	py := python(t)
	if py == nil {
		noPython(t)
	}
	var cases []struct {
		Doc string  `json:"doc"`
		OK  *string `json:"ok"`
		Err *string `json:"err"`
	}
	pyCorpus(t, py, "json_corpus.py", 5000, &cases)
	surrogates, deeper, bad := 0, 0, 0
	for _, c := range cases {
		v, err := LoadJSON(c.Doc)
		got := "ok " + CanonicalJSON(v)
		if errors.Is(err, ErrJSONTooDeep) {
			got = "err RecursionError: " + err.Error()
		} else if err != nil {
			got = "err " + err.Error()
		}
		want := "ok "
		if c.OK != nil {
			want += *c.OK
		} else {
			want = "err " + *c.Err
		}
		var je *JSONError
		switch {
		case got == want:
		case c.OK != nil && errors.As(err, &je) && strings.HasPrefix(je.Msg, "Unpaired surrogate"):
			surrogates++
		case err == nil && strings.HasPrefix(want, "err RecursionError: "):
			deeper++
		default:
			if bad++; bad <= 10 {
				t.Errorf("%q:\n python %s\n go     %s", c.Doc, want, got)
			}
		}
	}
	t.Logf("%d documents answered as json.loads answers them, but %d holding a lone surrogate and %d deeper than this Python decodes",
		len(cases)-surrogates-deeper-bad, surrogates, deeper)
}

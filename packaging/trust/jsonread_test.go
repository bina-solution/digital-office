package trust

// encoding/json is the ORACLE for jsonread.go: on every input below — and on every input the fuzzer
// invents — the stub's reader must accept exactly what encoding/json accepts and return the same
// value, except where one of its four documented rules is stricter, and there it must refuse.

import (
	"bytes"
	"encoding/json"
	"errors"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"unicode/utf8"
)

// oracle decodes with encoding/json the way jsonread represents values: numbers as their text.
func oracle(b []byte) (any, error) {
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var v any
	if err := d.Decode(&v); err != nil {
		return nil, err
	}
	if rest := bytes.TrimLeft(b[d.InputOffset():], " \t\r\n"); len(rest) > 0 {
		return nil, errors.New("data after the document") // as json.Unmarshal says
	}
	return withJSONNumbers(v), nil
}

func withJSONNumbers(v any) any {
	switch t := v.(type) {
	case json.Number:
		return jsonNumber(t)
	case map[string]any:
		for k, e := range t {
			t[k] = withJSONNumbers(e)
		}
	case []any:
		for i, e := range t {
			t[i] = withJSONNumbers(e)
		}
	}
	return v
}

// stricter reports whether a document encoding/json accepts breaks one of jsonread's four extra
// rules: invalid UTF-8, a \u escape of a surrogate, a duplicate key, nesting past maxJSONDepth.
func stricter(b []byte) bool {
	if !utf8.Valid(b) || surrogateEscape(b) {
		return true
	}
	type frame struct {
		keys    map[string]bool // nil for an array
		wantKey bool
	}
	var stack []*frame
	valueDone := func() {
		if n := len(stack); n > 0 && stack[n-1].keys != nil {
			stack[n-1].wantKey = true
		}
	}
	d := json.NewDecoder(bytes.NewReader(b))
	for {
		tok, err := d.Token()
		if err != nil {
			return false
		}
		if n := len(stack); n > 0 && stack[n-1].wantKey {
			if k, ok := tok.(string); ok {
				if stack[n-1].keys[k] {
					return true
				}
				stack[n-1].keys[k], stack[n-1].wantKey = true, false
				continue
			}
		}
		if tok == json.Delim('}') || tok == json.Delim(']') {
			stack = stack[:len(stack)-1]
			valueDone()
			continue
		}
		if len(stack) > maxJSONDepth { // this value's depth: the containers around it
			return true
		}
		switch tok {
		case json.Delim('{'):
			stack = append(stack, &frame{keys: map[string]bool{}, wantKey: true})
		case json.Delim('['):
			stack = append(stack, &frame{})
		default:
			valueDone()
		}
	}
}

// surrogateEscape finds a \u escape in D800–DFFF inside a string (an escaped backslash is skipped).
func surrogateEscape(b []byte) bool {
	in := false
	for i := 0; i < len(b); i++ {
		switch {
		case b[i] == '"':
			in = !in
		case in && b[i] == '\\' && i+1 < len(b):
			if b[i+1] == 'u' && i+6 <= len(b) {
				if r, err := strconv.ParseUint(string(b[i+2:i+6]), 16, 16); err == nil && 0xD800 <= r && r <= 0xDFFF {
					return true
				}
			}
			i++
		}
	}
	return false
}

var jsonCases = []string{
	// accepted by both
	`{}`, `[]`, `""`, `0`, `-0`, `1`, `-1`, `123456789012345678901234567890`, `1.5`, `-0.25`, `1e3`, `1E+3`,
	`2.5e-3`, `true`, `false`, `null`, ` { "a" : [ 1 , 2 , { "b" : null } ] } `, "\t\r\n[\n1\n]\n",
	`{"payloadType":"application/vnd.dgo.manifest+json","payload":"eyJ2IjoxfQ==","signatures":[{"keyid":"00ff","sig":"AA=="}]}`,
	`"\"\\\/\b\f\n\r\t"`, `"Ω emoji 😀 raw UTF-8"`, `"` + u("0000") + `"`,
	`"` + u("0026") + u("003c") + u("003e") + u("00e9") + u("00E9") + u("20ac") + u("ffff") + u("d7ff") + u("e000") + `"`,
	`{"a":{"b":{"c":[[[[]]]]}}}`, `{"":""}`, `[1,"two",3.0,true,null,{},[]]`, "\"\x7f\"", `"\\ud800 is text"`,
	`{"a":1,"b":{"a":2}}`, `[{"a":1},{"a":2}]`, strings.Repeat("[", 32) + "1" + strings.Repeat("]", 32),
	// refused by both
	``, ` `, `{`, `}`, `[`, `]`, `[1,]`, `{"a":1,}`, `{,}`, `[,1]`, `{"a"}`, `{"a" 1}`, `{a:1}`, `{'a':1}`,
	`01`, `-`, `1.`, `.5`, `+1`, `1e`, `1e+`, `0x10`, `NaN`, `Infinity`, `-Infinity`, `tru`, `nul`, `True`,
	`"unterminated`, `"bad \x escape"`, `"` + u("12") + `"`, `"` + u("12g4") + `"`, "\"tab\tinside\"", "\"nl\ninside\"",
	`{} {}`, `[] x`, `1 2`, `"a" "b"`, `{"a":1}}`, `[1]]`, `nulll`, `truefalse`, `"\`, "\xef\xbb\xbf{}",
	// stricter: refused here although encoding/json accepts them
	`{"a":1,"a":2}`, `[{"x":{"a":1,"a":1}}]`, "\"\xff\xfe\"", `"` + u("d83d") + u("de00") + `"`, `"` + u("dc00") + `"`, `"` + u("D800") + `"`,
	strings.Repeat("[", 33) + "1" + strings.Repeat("]", 33), strings.Repeat(`{"a":`, 40) + "1" + strings.Repeat("}", 40),
}

// u spells JSON's escape backslash-u-XXXX for the cases above. The backslash is \x5c on purpose: an
// escape typed literally into this file can be turned into its character by an editor, and the case
// would then test raw UTF-8 instead of the escape (it happened once, invisibly).
func u(hex string) string { return "\x5cu" + hex }

func TestJSONReaderMatchesEncodingJSON(t *testing.T) {
	for _, c := range jsonCases {
		checkAgainstOracle(t, []byte(c))
	}
}

func checkAgainstOracle(t *testing.T, b []byte) {
	t.Helper()
	got, gotErr := parseJSON(b)
	want, wantErr := oracle(b)
	switch {
	case wantErr != nil && gotErr == nil:
		t.Errorf("%q: encoding/json refuses it (%v), jsonread accepted %#v", b, wantErr, got)
	case wantErr == nil && stricter(b) && gotErr == nil:
		t.Errorf("%q: one of the four stricter rules must refuse it", b)
	case wantErr == nil && !stricter(b) && gotErr != nil:
		t.Errorf("%q: encoding/json accepts it, jsonread refused: %v", b, gotErr)
	case wantErr == nil && gotErr == nil && !reflect.DeepEqual(got, want):
		t.Errorf("%q: jsonread = %#v, encoding/json = %#v", b, got, want)
	}
}

// FuzzJSONReaderMatchesEncodingJSON keeps the oracle running on inputs nobody wrote down
// (go test -fuzz=FuzzJSONReader); without -fuzz it runs the cases above as its seeds.
func FuzzJSONReaderMatchesEncodingJSON(f *testing.F) {
	for _, c := range jsonCases {
		f.Add([]byte(c))
	}
	f.Fuzz(checkAgainstOracle)
}

func TestObjectGettersNameTheFieldTheyRefuse(t *testing.T) {
	v, err := parseJSON([]byte(`{"s":"x","empty":"","n":42,"neg":-1,"frac":1.5,"t":"2026-10-15T12:00:00Z","l":[1],"nl":[]}`))
	if err != nil {
		t.Fatal(err)
	}
	o, _ := asObj(v, "doc")
	if s, err := o.text("s"); s != "x" || err != nil {
		t.Errorf("text: %q %v", s, err)
	}
	if n, err := o.natural("n"); n != 42 || err != nil {
		t.Errorf("natural: %d %v", n, err)
	}
	if tm, err := o.instant("t"); err != nil || tm.Year() != 2026 {
		t.Errorf("instant: %v %v", tm, err)
	}
	if l, err := o.list("l"); len(l) != 1 || err != nil {
		t.Errorf("list: %v %v", l, err)
	}
	for _, refused := range []error{
		errOf(o.text("empty")), errOf(o.text("missing")), errOf(o.text("n")),
		errOf(o.natural("neg")), errOf(o.natural("frac")), errOf(o.natural("s")),
		errOf(o.instant("s")), errOf(o.list("nl")), errOf(o.list("s")),
	} {
		if refused == nil || !strings.Contains(refused.Error(), `field "`) {
			t.Errorf("a getter must refuse by the field's name, got %v", refused)
		}
	}
	if _, err := asObj([]any{}, "the envelope"); err == nil {
		t.Error("an array is not an object")
	}
}

func errOf[T any](_ T, err error) error { return err }

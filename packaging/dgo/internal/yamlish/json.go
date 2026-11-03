package yamlish

import (
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
)

// The compiler's write verbs read JSON as well as YAML — `office-set` and `remote-set` take a JSON
// document on stdin — and their refusals of a bad one are part of their contract. So LoadJSON is
// Python's json.loads on the same values as the YAML side (its writers, CanonicalJSON and DumpsJSON,
// are in scalar.go).

// BigInt is an integer beyond int64, kept as its decimal digits. Python's int has no bound, so
// json.loads answers one for any number of digits; it travels unchanged and is written by Marshal,
// DumpsJSON and Repr exactly as Python writes it. (The YAML reader still refuses such a number — see parseInt —
// so a state file holding one is read back by PyYAML only.)
type BigInt string

// JSONError is a JSONDecodeError: the message, and where — the position counted in characters, as
// Python counts them, with its line and column. It prints as Python's str() of the exception does.
type JSONError struct {
	Msg             string
	Pos, Line, Col  int
	positionUnknown bool // a ValueError that is not a JSONDecodeError (the integer digit limit)
	unpaired        bool // the one refusal that is not Python's (ErrUnpairedSurrogate)
}

// ErrUnpairedSurrogate is LoadJSON's one refusal that is not Python's: a \u escape of half a UTF-16
// surrogate pair, which Python keeps and a Go string cannot hold. errors.Is finds it on the JSONError,
// so a reader that must answer as Python does — the console's — can tell it from Python's own refusals.
var ErrUnpairedSurrogate = errors.New("unpaired surrogate escape")

// Is makes the unpaired-surrogate refusal ErrUnpairedSurrogate to errors.Is.
func (e *JSONError) Is(target error) bool { return e.unpaired && target == ErrUnpairedSurrogate }

func (e *JSONError) Error() string {
	if e.positionUnknown {
		return e.Msg
	}
	return fmt.Sprintf("%s: line %d column %d (char %d)", e.Msg, e.Line, e.Col, e.Pos)
}

// ErrJSONTooDeep is Python's RecursionError while decoding: nesting deeper than the interpreter lets
// its C scanner recurse. It is not a ValueError — reconcile.py does not catch it — so a verb treats it
// as the crash it is in Python. (errors.Is finds it; the message names an array or an object.)
var ErrJSONTooDeep = errors.New("maximum recursion depth exceeded")

type tooDeep string // "array" or "object": what was being decoded when the limit was reached

func (k tooDeep) Error() string {
	return "maximum recursion depth exceeded while decoding a JSON " + string(k) + " from a unicode string"
}
func (tooDeep) Is(target error) bool { return target == ErrJSONTooDeep }

// maxJSONDepth is the deepest nesting CPython 3.12.10 decodes — the oracle these tests run against:
// measured, 2997 levels load and the 2998th raises (its C recursion limit). There is no one Python
// answer: 3.12.2 loads 1497, 3.11.9 about 987 (the interpreter's 1000 frames, less those in use),
// 3.12.3 and 3.12.14 over 5,000 and under 20,000 (measured 2026-10-30), and 3.14 over 14,000 (by stack
// size) — so between 2998 and the running Python's own limit the two answer differently, and the
// parity test nests past every 3.12 instead. The bound also keeps a hostile input from exhausting this
// process's stack.
const maxJSONDepth = 2997

// maxIntDigits is sys.get_int_max_str_digits(): Python refuses to convert a longer decimal integer.
const maxIntDigits = 4300

// LoadJSON is json.loads(s) for a str: Python's values — an object keeps its key order and a repeated
// key keeps its first place and its last value; NaN, Infinity and -Infinity are floats; an integer has
// no bound (BigInt) — and Python's refusals, worded as CPython 3.12's C scanner words them
// ("Expecting value: line 1 column 1 (char 0)").
//
// The one divergence, on purpose: a \u escape naming one half of a UTF-16 surrogate pair without the
// other is refused here (a Go string is UTF-8 and cannot hold it), where Python keeps it in the str.
// The refusal waits for the end of the document, so that wherever Python refuses the text, it is
// Python's own refusal that is answered.
func LoadJSON(text string) (any, error) {
	d := &jsonDecoder{s: []rune(text), lone: -1}
	if len(d.s) > 0 && d.s[0] == 0xFEFF {
		return nil, d.fail("Unexpected UTF-8 BOM (decode using utf-8-sig)", 0)
	}
	v, end, err := d.value(d.skipSpace(0))
	if err != nil {
		var stop stopAt
		if errors.As(err, &stop) {
			return nil, d.fail("Expecting value", int(stop))
		}
		return nil, err
	}
	if end = d.skipSpace(end); end != len(d.s) {
		return nil, d.fail("Extra data", end)
	}
	if d.lone >= 0 {
		err := d.fail("Unpaired surrogate escape (a Go string is UTF-8 and cannot hold it)", d.lone)
		err.(*JSONError).unpaired = true
		return nil, err
	}
	return v, nil
}

type jsonDecoder struct {
	s     []rune
	depth int
	lone  int // where the first unpaired surrogate escape is (its `u`), or -1
}

// stopAt is the scanner's StopIteration(idx): no JSON value starts at idx. json.loads turns it into
// "Expecting value" at that index, wherever in the document it happened.
type stopAt int

func (stopAt) Error() string { return "no JSON value here" }

func (d *jsonDecoder) fail(msg string, pos int) error {
	line, col := 1, pos+1
	for i := 0; i < pos && i < len(d.s); i++ {
		if d.s[i] == '\n' {
			line, col = line+1, pos-i
		}
	}
	return &JSONError{Msg: msg, Pos: pos, Line: line, Col: col}
}

func (d *jsonDecoder) skipSpace(i int) int {
	for i < len(d.s) && (d.s[i] == ' ' || d.s[i] == '\t' || d.s[i] == '\n' || d.s[i] == '\r') {
		i++
	}
	return i
}

// lit reports whether the constant `word` is spelled at i (a truncated one is no constant: `[nul` is
// "Expecting value", as in the C scanner).
func (d *jsonDecoder) lit(i int, word string) bool {
	w := []rune(word)
	if i+len(w)-1 >= len(d.s) {
		return false
	}
	for k, r := range w {
		if d.s[i+k] != r {
			return false
		}
	}
	return true
}

// value is scan_once: the JSON term that starts at i, and the index after it.
func (d *jsonDecoder) value(i int) (any, int, error) {
	if i >= len(d.s) {
		return nil, 0, stopAt(i)
	}
	switch d.s[i] {
	case '"':
		return d.str(i + 1)
	case '{', '[':
		if d.depth >= maxJSONDepth {
			if d.s[i] == '{' {
				return nil, 0, tooDeep("object")
			}
			return nil, 0, tooDeep("array")
		}
		d.depth++
		defer func() { d.depth-- }()
		if d.s[i] == '{' {
			return d.object(i + 1)
		}
		return d.array(i + 1)
	case 'n':
		if d.lit(i, "null") {
			return nil, i + 4, nil
		}
	case 't':
		if d.lit(i, "true") {
			return true, i + 4, nil
		}
	case 'f':
		if d.lit(i, "false") {
			return false, i + 5, nil
		}
	case 'N':
		if d.lit(i, "NaN") {
			return math.NaN(), i + 3, nil
		}
	case 'I':
		if d.lit(i, "Infinity") {
			return math.Inf(1), i + 8, nil
		}
	case '-':
		if d.lit(i, "-Infinity") {
			return math.Inf(-1), i + 9, nil
		}
	}
	return d.number(i)
}

func isDigit(r rune) bool { return r >= '0' && r <= '9' }

// number is _match_number_unicode: an integer unless a fraction or an exponent follows, and an
// exponent without digits is not part of the number (`1e` is the integer 1 and "Extra data").
func (d *jsonDecoder) number(start int) (any, int, error) {
	s, last, i := d.s, len(d.s)-1, start
	if s[i] == '-' {
		if i++; i > last {
			return nil, 0, stopAt(start)
		}
	}
	switch {
	case s[i] >= '1' && s[i] <= '9':
		for i++; i <= last && isDigit(s[i]); i++ {
		}
	case s[i] == '0':
		i++
	default:
		return nil, 0, stopAt(start)
	}
	isFloat := false
	if i < last && s[i] == '.' && isDigit(s[i+1]) {
		isFloat = true
		for i += 2; i <= last && isDigit(s[i]); i++ {
		}
	}
	if i < last && (s[i] == 'e' || s[i] == 'E') {
		eStart := i
		if i++; i < last && (s[i] == '-' || s[i] == '+') {
			i++
		}
		for ; i <= last && isDigit(s[i]); i++ {
		}
		if isDigit(s[i-1]) {
			isFloat = true
		} else {
			i = eStart
		}
	}
	text := string(s[start:i])
	if isFloat {
		f, err := strconv.ParseFloat(text, 64)
		if err != nil && !errors.Is(err, strconv.ErrRange) { // out of range is ±Inf or 0, as float() answers
			return nil, 0, err
		}
		return f, i, nil
	}
	if digits := len(strings.TrimPrefix(text, "-")); digits > maxIntDigits {
		return nil, 0, &JSONError{positionUnknown: true, Msg: fmt.Sprintf(
			"Exceeds the limit (%d digits) for integer string conversion: value has %d digits; use sys.set_int_max_str_digits() to increase the limit",
			maxIntDigits, digits)}
	}
	if n, err := strconv.ParseInt(text, 10, 64); err == nil {
		return n, i, nil
	}
	return BigInt(text), i, nil
}

// str is scanstring_unicode: the string whose content starts at end (after the opening quote).
func (d *jsonDecoder) str(end int) (string, int, error) {
	s, begin := d.s, end-1
	var b strings.Builder
	for {
		next := end
		for ; next < len(s) && s[next] != '"' && s[next] != '\\'; next++ {
			if s[next] <= 0x1f {
				return "", 0, d.fail("Invalid control character at", next)
			}
		}
		if next == len(s) {
			return "", 0, d.fail("Unterminated string starting at", begin)
		}
		b.WriteString(string(s[end:next]))
		if s[next] == '"' {
			return b.String(), next + 1, nil
		}
		if next++; next == len(s) {
			return "", 0, d.fail("Unterminated string starting at", begin)
		}
		c := s[next]
		if c != 'u' {
			end = next + 1
			switch c {
			case '"', '\\', '/':
			case 'b':
				c = '\b'
			case 'f':
				c = '\f'
			case 'n':
				c = '\n'
			case 'r':
				c = '\r'
			case 't':
				c = '\t'
			default:
				return "", 0, d.fail("Invalid \\escape", end-2)
			}
			b.WriteRune(c)
			continue
		}
		u := next
		next++
		if end = next + 4; end >= len(s) {
			return "", 0, d.fail("Invalid \\uXXXX escape", next-1)
		}
		c, ok := hex4(s[next:end])
		if !ok {
			return "", 0, d.fail("Invalid \\uXXXX escape", end-5)
		}
		if c >= 0xD800 && c <= 0xDBFF && end+6 < len(s) && s[end] == '\\' && s[end+1] == 'u' {
			c2, ok := hex4(s[end+2 : end+6])
			if !ok {
				return "", 0, d.fail("Invalid \\uXXXX escape", end+1)
			}
			if c2 >= 0xDC00 && c2 <= 0xDFFF {
				c = 0x10000 + (c-0xD800)<<10 + (c2 - 0xDC00)
				end += 6
			}
		}
		if c >= 0xD800 && c <= 0xDFFF && d.lone < 0 {
			d.lone = u // refused once the whole document has parsed (see LoadJSON)
		}
		b.WriteRune(c)
	}
}

func hex4(rs []rune) (rune, bool) {
	var c rune
	for _, r := range rs {
		switch {
		case r >= '0' && r <= '9':
			c = c<<4 | (r - '0')
		case r >= 'a' && r <= 'f':
			c = c<<4 | (r - 'a' + 10)
		case r >= 'A' && r <= 'F':
			c = c<<4 | (r - 'A' + 10)
		default:
			return 0, false
		}
	}
	return c, true
}

// object is _parse_object_unicode; idx is just after `{`.
func (d *jsonDecoder) object(idx int) (any, int, error) {
	s, m := d.s, NewMap()
	if idx = d.skipSpace(idx); idx >= len(s) || s[idx] != '}' {
		for {
			if idx >= len(s) || s[idx] != '"' {
				return nil, 0, d.fail("Expecting property name enclosed in double quotes", idx)
			}
			key, next, err := d.str(idx + 1)
			if err != nil {
				return nil, 0, err
			}
			if idx = d.skipSpace(next); idx >= len(s) || s[idx] != ':' {
				return nil, 0, d.fail("Expecting ':' delimiter", idx)
			}
			v, next, err := d.value(d.skipSpace(idx + 1))
			if err != nil {
				return nil, 0, err
			}
			m.Set(key, v)
			if idx = d.skipSpace(next); idx < len(s) && s[idx] == '}' {
				break
			}
			if idx >= len(s) || s[idx] != ',' {
				return nil, 0, d.fail("Expecting ',' delimiter", idx)
			}
			idx = d.skipSpace(idx + 1)
		}
	}
	return m, idx + 1, nil
}

// array is _parse_array_unicode; idx is just after `[`.
func (d *jsonDecoder) array(idx int) (any, int, error) {
	s, out := d.s, []any{}
	if idx = d.skipSpace(idx); idx >= len(s) || s[idx] != ']' {
		for {
			v, next, err := d.value(idx)
			if err != nil {
				return nil, 0, err
			}
			out = append(out, v)
			if idx = d.skipSpace(next); idx < len(s) && s[idx] == ']' {
				break
			}
			if idx >= len(s) || s[idx] != ',' {
				return nil, 0, d.fail("Expecting ',' delimiter", idx)
			}
			idx = d.skipSpace(idx + 1)
		}
	}
	return out, idx + 1, nil
}

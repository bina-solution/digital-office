// Package pyval is dgo's one copy of Python's value rules that more than one port needs: how
// reconcile.py, app.py and catalog.py spell a value they read — repr() and str() — what str.isspace()
// and str.strip() call whitespace, and what int() reads in a str. Each port's own policy stays its own
// (the console and the store refuse to publish what str() would spell as Python syntax); the rule is
// this one, oracle-tested by the compiler (TestValuesSpelledAsPythonSpellsThem,
// TestPythonHelpersMatchPython, TestArgparseMatchesPython) and the console.
//
// It serves both kinds of value dgo reads: what encoding/json decodes (UseNumber: json.Number,
// map[string]any) and what yamlish decodes (*yamlish.Map, int64, float64 — and yamlish.LoadJSON's
// yamlish.BigInt, an integer beyond 64 bits).
package pyval

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// Repr is repr(). One limit, by construction: a map[string]any's keys are listed sorted (the decode
// it comes from keeps no order). A *yamlish.Map's keys are shown as YAML typed them (`1:` is 1).
func Repr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case bool:
		if t {
			return "True"
		}
		return "False"
	case int64:
		return strconv.FormatInt(t, 10)
	case yamlish.BigInt:
		return string(t)
	case float64:
		return reprFloat(t)
	case json.Number:
		return reprNumber(t)
	case string:
		return reprString(t)
	case []string:
		parts := make([]string, len(t))
		for i, s := range t {
			parts[i] = reprString(s)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case []any:
		parts := make([]string, len(t))
		for i, e := range t {
			parts[i] = Repr(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case *yamlish.Map:
		keys := t.Keys()
		parts := make([]string, len(keys))
		for i, k := range keys {
			e, _ := t.Get(k)
			parts[i] = Repr(t.TypedKey(k)) + ": " + Repr(e)
		}
		return "{" + strings.Join(parts, ", ") + "}"
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		parts := make([]string, len(keys))
		for i, k := range keys {
			parts[i] = reprString(k) + ": " + Repr(t[k])
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	panic(fmt.Sprintf("pyval: no Python value is a %T", v))
}

// Str is str(): a string is itself, anything else its repr.
func Str(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return Repr(v)
}

// reprFloat is repr(float): the JSON spelling, but for the three values JSON has words of its own for.
func reprFloat(f float64) string {
	switch {
	case math.IsNaN(f):
		return "nan"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	}
	return yamlish.CanonicalJSON(f)
}

// reprNumber is repr() of what json.loads makes of a number: an int for a literal without a point or
// an exponent ("-0" is 0), else a float (one too large for a double is inf, as float() makes it).
func reprNumber(n json.Number) string {
	s := n.String()
	if !strings.ContainsAny(s, ".eE") {
		if strings.TrimLeft(s, "-0") == "" {
			return "0"
		}
		return s
	}
	f, _ := strconv.ParseFloat(s, 64)
	return reprFloat(f)
}

// reprString is repr(str): single quotes unless the text has one and no double quote; the quote and
// `\` escaped; \t \n \r by name, other controls as \xHH; printable characters as themselves, the
// rest as \xHH, \uHHHH or \UHHHHHHHH. A byte that is not UTF-8 is shown the way Python holds it
// after decoding argv with surrogateescape: \udcHH.
func reprString(s string) string {
	quote := byte('\'')
	if strings.IndexByte(s, '\'') >= 0 && strings.IndexByte(s, '"') < 0 {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		if r == utf8.RuneError && size == 1 {
			fmt.Fprintf(&b, `\udc%02x`, s[i])
			i++
			continue
		}
		i += size
		switch {
		case r == rune(quote) || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\t':
			b.WriteString(`\t`)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r < ' ' || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r < 0x7f || strconv.IsPrint(r): // unicode.IsPrint's definition, in tables fmt already links
			b.WriteRune(r)
		case r <= 0xff:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r <= 0xffff:
			fmt.Fprintf(&b, `\u%04x`, r)
		default:
			fmt.Fprintf(&b, `\U%08x`, r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// IsSpace is str.isspace() for one character: unicode.IsSpace plus \x1c-\x1f, which Python counts
// as whitespace (their bidirectional class is a separator) and Go does not.
func IsSpace(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }

// SpaceClass is IsSpace's set as a regular-expression class: what `\s` matches in a Python str
// pattern, for the ports of reconcile.py's regexes.
const SpaceClass = `[\t\n\v\f\r \x1c-\x1f\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]`

// Strip is str.strip().
func Strip(s string) string { return strings.TrimFunc(s, IsSpace) }

// Integer is what int() answers: its decimal text, and the value when it fits 64 bits (Python's int
// has no bound).
type Integer struct {
	Text string
	N    int64
	Fits bool
}

// IntegerOf is the Integer of a 64-bit value.
func IntegerOf(n int64) Integer { return Integer{Text: strconv.FormatInt(n, 10), N: n, Fits: true} }

// InRange is `lo <= n <= hi` on the Python int.
func (i Integer) InRange(lo, hi int64) bool { return i.Fits && i.N >= lo && i.N <= hi }

// Int is int(s) for a str, in base 10: the whitespace around it int() strips, a sign, decimal digits
// of any script with single underscores between them — at most 4300 of them, Python's
// sys.get_int_max_str_digits(); false where int() raises ValueError.
func Int(s string) (Integer, bool) {
	rs := []rune(strings.TrimFunc(s, intSpace))
	neg := false
	if len(rs) > 0 && (rs[0] == '+' || rs[0] == '-') {
		neg, rs = rs[0] == '-', rs[1:]
	}
	var digits []byte
	for i, r := range rs {
		if r == '_' && i > 0 && i < len(rs)-1 && rs[i-1] != '_' && rs[i+1] != '_' {
			continue
		}
		d := decimalValue(r)
		if d < 0 {
			return Integer{}, false
		}
		digits = append(digits, byte('0'+d))
	}
	if len(digits) == 0 || len(digits) > 4300 {
		return Integer{}, false
	}
	text := strings.TrimLeft(string(digits), "0")
	if text == "" {
		return IntegerOf(0), true
	}
	if neg {
		text = "-" + text
	}
	if n, err := strconv.ParseInt(text, 10, 64); err == nil {
		return IntegerOf(n), true
	}
	return Integer{Text: text}, true
}

// intSpace is the whitespace int() strips around a number: ASCII's six and Unicode's — not \x1c-\x1f,
// which str.isspace() counts but int() reads as characters (int("\x1c42") is a ValueError).
func intSpace(r rune) bool {
	return strings.ContainsRune(" \t\n\v\f\r", r) || r > 127 && unicode.IsSpace(r)
}

// decimalValue is a character's decimal digit value (category Nd, which int() and `\d` accept in
// every script), or -1. Every run of Nd characters starts at a zero, ten to a block.
func decimalValue(r rune) int {
	if r >= '0' && r <= '9' {
		return int(r - '0')
	}
	if !unicode.Is(unicode.Nd, r) {
		return -1
	}
	for _, rg := range unicode.Nd.R16 {
		if r >= rune(rg.Lo) && r <= rune(rg.Hi) {
			return int(r-rune(rg.Lo)) % 10
		}
	}
	for _, rg := range unicode.Nd.R32 {
		if r >= rune(rg.Lo) && r <= rune(rg.Hi) {
			return int(r-rune(rg.Lo)) % 10
		}
	}
	return -1
}

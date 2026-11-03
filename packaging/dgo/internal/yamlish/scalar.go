package yamlish

import (
	"errors"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

// PyYAML's implicit resolvers (yaml/resolver.py, YAML 1.1), verbatim — the reason `on` is a bool,
// `0755` an int, `1e5` a string (no `.` — PyYAML's float wants one) and `1.5e5` a string too (the
// exponent's sign is mandatory). A value a config author would call a number is whatever these say.
var (
	reBool  = regexp.MustCompile(`^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$`)
	reInt   = regexp.MustCompile(`^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$`)
	reFloat = regexp.MustCompile(`^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$`)
	reNull  = regexp.MustCompile(`^(?:~|null|Null|NULL|)$`)
	// a date alone has two-digit month and day (2026-1-5 is a string to PyYAML); only the form with
	// a time allows one digit
	reTime = regexp.MustCompile(`^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$`)
)

// plainIsString answers the question the emitter asks before writing a string without quotes: would
// PyYAML read this text back as a string? Not if one of its implicit resolvers claims it — including
// the two whose types the reader never meets: `<<` (merge) and `=` (value).
func plainIsString(s string) bool {
	return !(reNull.MatchString(s) || reBool.MatchString(s) || reInt.MatchString(s) ||
		reFloat.MatchString(s) || reTime.MatchString(s) || s == "<<" || s == "=")
}

// scalar resolves one scalar token: quoted → the string; plain → PyYAML's implicit type.
func scalar(tok string) (any, error) {
	if tok == "" {
		return nil, nil
	}
	if tok[0] == '"' || tok[0] == '\'' {
		return unquote(tok)
	}
	switch {
	case reNull.MatchString(tok):
		return nil, nil
	case reBool.MatchString(tok):
		return tok[0] == 'y' || tok[0] == 'Y' || tok[0] == 't' || tok[0] == 'T' || strings.EqualFold(tok, "on"), nil
	case reInt.MatchString(tok):
		return parseInt(tok)
	case reFloat.MatchString(tok):
		return parseFloat(tok)
	case reTime.MatchString(tok):
		// PyYAML gives a datetime.date / datetime.datetime here. The compiler never reads one unquoted
		// (its own writer quotes timestamps), so this is refused rather than silently mistyped.
		return nil, fmt.Errorf("unsupported: an unquoted timestamp %q (quote it)", tok)
	}
	return tok, nil
}

func parseInt(tok string) (any, error) {
	s := strings.ReplaceAll(tok, "_", "")
	sign := int64(1)
	if s[0] == '-' || s[0] == '+' {
		if s[0] == '-' {
			sign = -1
		}
		s = s[1:]
	}
	var v int64
	var err error
	switch {
	case s == "0":
		v = 0
	case strings.HasPrefix(s, "0b"):
		v, err = strconv.ParseInt(s[2:], 2, 64)
	case strings.HasPrefix(s, "0x"):
		v, err = strconv.ParseInt(s[2:], 16, 64)
	case strings.Contains(s, ":"):
		// sexagesimal: 1:20 → 80
		for _, part := range strings.Split(s, ":") {
			d, e := strconv.ParseInt(part, 10, 64)
			if e != nil {
				return nil, fmt.Errorf("bad sexagesimal int %q", tok)
			}
			v = v*60 + d
		}
	case s[0] == '0':
		v, err = strconv.ParseInt(s[1:], 8, 64)
	default:
		v, err = strconv.ParseInt(s, 10, 64)
	}
	if err != nil {
		return nil, fmt.Errorf("unsupported: int %q does not fit 64 bits (PyYAML would answer a Python long)", tok)
	}
	return sign * v, nil
}

func parseFloat(tok string) (any, error) {
	s := strings.ReplaceAll(tok, "_", "")
	lower := strings.ToLower(s)
	switch {
	case strings.HasSuffix(lower, ".inf"):
		if strings.HasPrefix(s, "-") {
			return math.Inf(-1), nil
		}
		return math.Inf(1), nil
	case strings.HasSuffix(lower, ".nan"):
		return math.NaN(), nil
	case strings.Contains(s, ":"):
		// sexagesimal float: 190:20:30.15 → 685230.15
		sign := 1.0
		if s[0] == '-' || s[0] == '+' {
			if s[0] == '-' {
				sign = -1
			}
			s = s[1:]
		}
		parts := strings.Split(s, ":")
		v := 0.0
		for _, part := range parts {
			d, err := strconv.ParseFloat(part, 64)
			if err != nil {
				return nil, fmt.Errorf("bad sexagesimal float %q", tok)
			}
			v = v*60 + d
		}
		return sign * v, nil
	}
	if strings.HasSuffix(s, ".") {
		s += "0"
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return nil, fmt.Errorf("bad float %q", tok)
	}
	return v, nil
}

// unquote resolves a quoted scalar: '…' doubles its quote; "…" has the YAML escapes.
func unquote(tok string) (string, error) {
	if len(tok) < 2 || tok[0] != tok[len(tok)-1] {
		return "", fmt.Errorf("bad quoted scalar %q", tok)
	}
	body := tok[1 : len(tok)-1]
	if tok[0] == '\'' {
		return strings.ReplaceAll(body, "''", "'"), nil
	}
	var b strings.Builder
	for i := 0; i < len(body); i++ {
		c := body[i]
		if c != '\\' {
			b.WriteByte(c)
			continue
		}
		i++
		if i >= len(body) {
			return "", errors.New("a double-quoted scalar ends in a backslash")
		}
		switch body[i] {
		case '0':
			b.WriteByte(0)
		case 'a':
			b.WriteByte('\a')
		case 'b':
			b.WriteByte('\b')
		case 't', '\t':
			b.WriteByte('\t')
		case 'n':
			b.WriteByte('\n')
		case 'v':
			b.WriteByte('\v')
		case 'f':
			b.WriteByte('\f')
		case 'r':
			b.WriteByte('\r')
		case 'e':
			b.WriteByte(0x1b)
		case ' ':
			b.WriteByte(' ')
		case '"':
			b.WriteByte('"')
		case '/':
			b.WriteByte('/')
		case '\\':
			b.WriteByte('\\')
		case 'N':
			b.WriteString("\u0085")
		case '_':
			b.WriteString(" ")
		case 'L':
			b.WriteString(" ")
		case 'P':
			b.WriteString(" ")
		case 'x', 'u', 'U':
			n := map[byte]int{'x': 2, 'u': 4, 'U': 8}[body[i]]
			if i+n >= len(body) {
				return "", errors.New("truncated \\x/\\u/\\U escape")
			}
			code, err := strconv.ParseUint(body[i+1:i+1+n], 16, 32)
			if err != nil {
				return "", fmt.Errorf("bad escape in %q", tok)
			}
			// PyYAML keeps a surrogate as half a character, which a Go string cannot hold; a code point
			// beyond U+10FFFF it fails on (chr() raises ValueError)
			if code >= 0xD800 && code <= 0xDFFF {
				return "", fmt.Errorf("unsupported: the escape of U+%X in %q (a surrogate)", code, tok)
			}
			if code > 0x10FFFF {
				return "", fmt.Errorf("the escape of U+%X in %q is beyond Unicode (PyYAML fails on it too)", code, tok)
			}
			b.WriteRune(rune(code))
			i += n
		default:
			return "", fmt.Errorf("unknown escape \\%c in %q", body[i], tok)
		}
	}
	return b.String(), nil
}

// ── JSON — what Python's json.dumps writes for the same value, in the spellings the office's outputs
// use: one writer, a style per spelling. The oracle tests compare them byte for byte; the compiler's
// own JSON outputs and the control plane's and the console's answers go through it. ──────────────

// CanonicalJSON is json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":")).
func CanonicalJSON(v any) string {
	var b strings.Builder
	writeJSON(&b, v, canonicalJSON)
	return b.String()
}

// DumpsJSON is what Python's json.dumps(v) writes with its defaults — the spelling of every JSON line
// the compiler prints (`remote-get`, `office-get`, `required-by`): keys in insertion order, ", " and
// ": " between items, and every character outside printable ASCII as a \u escape (ensure_ascii; an
// astral character as its surrogate pair), so the line survives any stdout encoding.
func DumpsJSON(v any) string {
	var b strings.Builder
	writeJSON(&b, v, dumpsJSON)
	return b.String()
}

// FlaskJSON is what Flask's jsonify writes outside debug mode — json.dumps(sort_keys=True,
// ensure_ascii=True, separators=(",", ":")) — so a route of the control plane or the console answered
// in Go can equal app-management's or app.py's byte for byte (the trailing newline is jsonify's, not
// json's).
func FlaskJSON(v any) string {
	var b strings.Builder
	writeJSON(&b, v, flaskJSON)
	return b.String()
}

// SortedJSON is json.dumps(v, sort_keys=True, ensure_ascii=False): Python's default separators.
func SortedJSON(v any) string {
	var b strings.Builder
	writeJSON(&b, v, sortedJSON)
	return b.String()
}

// IndentJSON is json.dumps(v, indent=2, ensure_ascii=False) — the spelling of the compiler's JSON
// files under .generated/ (the registries, resolved.json) and of `serve-plan`: keys in insertion
// order, one item per line two spaces deeper than its container, "," at a line's end and ": " after
// a key, an empty list or object as [] or {}, characters as themselves.
func IndentJSON(v any) string {
	var b strings.Builder
	writeJSON(&b, v, indentJSON)
	return b.String()
}

// jsonStyle is the part of json.dumps's arguments the spellings differ in. With an indent every item
// of a list or an object stands on a line of its own, one indent deeper per level (json's separators
// are "," and ": " then).
type jsonStyle struct {
	sortKeys, ascii bool
	item, key       string
	indent          string
}

var (
	canonicalJSON = jsonStyle{sortKeys: true, item: ",", key: ":"}
	dumpsJSON     = jsonStyle{ascii: true, item: ", ", key: ": "}
	flaskJSON     = jsonStyle{sortKeys: true, ascii: true, item: ",", key: ":"}
	sortedJSON    = jsonStyle{sortKeys: true, item: ", ", key: ": "}
	indentJSON    = jsonStyle{item: ",", key: ": ", indent: "  "}
)

func writeJSON(b *strings.Builder, v any, s jsonStyle) { writeJSONAt(b, v, s, 0) }

// startItem starts the i-th item of a non-empty container `level` deep: the separator after the one
// before it and, with an indent, the item's own line.
func (s jsonStyle) startItem(b *strings.Builder, i, level int) {
	if i > 0 {
		b.WriteString(s.item)
	}
	if s.indent != "" {
		b.WriteString("\n" + strings.Repeat(s.indent, level+1))
	}
}

// close ends a non-empty container `level` deep: with an indent, its bracket on a line of its own.
func (s jsonStyle) close(b *strings.Builder, level int, bracket byte) {
	if s.indent != "" {
		b.WriteString("\n" + strings.Repeat(s.indent, level))
	}
	b.WriteByte(bracket)
}

func writeJSONAt(b *strings.Builder, v any, s jsonStyle, level int) {
	switch t := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if t {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case int64:
		b.WriteString(strconv.FormatInt(t, 10))
	case int:
		b.WriteString(strconv.Itoa(t))
	case BigInt:
		b.WriteString(string(t))
	case float64:
		b.WriteString(pythonFloat(t))
	case string:
		writeJSONString(b, t, s.ascii)
	case []any:
		if len(t) == 0 {
			b.WriteString("[]")
			break
		}
		b.WriteByte('[')
		for i, e := range t {
			s.startItem(b, i, level)
			writeJSONAt(b, e, s, level+1)
		}
		s.close(b, level, ']')
	case *Map:
		keys := t.Keys()
		if len(keys) == 0 {
			b.WriteString("{}")
			break
		}
		if s.sortKeys {
			sort.Strings(keys)
		}
		b.WriteByte('{')
		for i, k := range keys {
			s.startItem(b, i, level)
			writeJSONString(b, k, s.ascii)
			b.WriteString(s.key)
			writeJSONAt(b, t.vals[k], s, level+1)
		}
		s.close(b, level, '}')
	default:
		panic(fmt.Sprintf("yamlish: no JSON for %T", v))
	}
}

// writeJSONString escapes as Python's json does: `"` `\` and the controls, short forms for
// \n \r \t \b \f, \u00XX for the rest; with ascii (ensure_ascii) everything past `~` as \uXXXX too,
// else as the character itself.
func writeJSONString(b *strings.Builder, s string, ascii bool) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			if r < 0x20 {
				fmt.Fprintf(b, `\u%04x`, r)
			} else if ascii && r > '~' {
				if hi, lo := utf16.EncodeRune(r); hi != utf8.RuneError {
					fmt.Fprintf(b, `\u%04x\u%04x`, hi, lo)
				} else {
					fmt.Fprintf(b, `\u%04x`, r)
				}
			} else if r == utf8.RuneError {
				b.WriteString(`�`)
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}

// FloatRepr is pythonFloat for another package: the console spells a file's st_mtime in its ETag as
// Python's f"{mtime}" does (a finite float; the non-finite ones are spelled as JSON spells them).
func FloatRepr(f float64) string { return pythonFloat(f) }

// pythonFloat is repr(float): the shortest round-trip digits, fixed notation when the decimal
// exponent is in [-4, 16), else `d.ddde±XX`; an integral value keeps a `.0`.
func pythonFloat(f float64) string {
	switch {
	case math.IsNaN(f):
		return "NaN"
	case math.IsInf(f, 1):
		return "Infinity"
	case math.IsInf(f, -1):
		return "-Infinity"
	}
	e := strconv.FormatFloat(f, 'e', -1, 64) // d.ddddde±XX, shortest digits
	mant, expStr, _ := strings.Cut(e, "e")
	exp, _ := strconv.Atoi(expStr)
	neg := strings.HasPrefix(mant, "-")
	mant = strings.TrimPrefix(mant, "-")
	digits := strings.Replace(mant, ".", "", 1)
	var out string
	if exp >= -4 && exp < 16 {
		switch {
		case exp < 0:
			out = "0." + strings.Repeat("0", -exp-1) + digits
		case exp+1 >= len(digits):
			out = digits + strings.Repeat("0", exp+1-len(digits)) + ".0"
		default:
			out = digits[:exp+1] + "." + digits[exp+1:]
		}
	} else {
		m := digits[:1]
		if len(digits) > 1 {
			m += "." + digits[1:]
		}
		sign := "+"
		if exp < 0 {
			sign = "-"
			exp = -exp
		}
		out = fmt.Sprintf("%se%s%02d", m, sign, exp)
	}
	if neg {
		out = "-" + out
	}
	return out
}

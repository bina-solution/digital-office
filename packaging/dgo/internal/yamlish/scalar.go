package yamlish

import (
	"errors"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
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
	reTime  = regexp.MustCompile(`^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$`)
)

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
		return nil, fmt.Errorf("int %q does not fit 64 bits (PyYAML would answer a Python long; refusing)", tok)
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
			b.WriteRune(rune(code))
			i += n
		default:
			return "", fmt.Errorf("unknown escape \\%c in %q", body[i], tok)
		}
	}
	return b.String(), nil
}

// ── canonical JSON — what Python's json.dumps(sort_keys=True, ensure_ascii=False,
// separators=(",", ":")) writes for the same value. The oracle test compares two of these byte for
// byte, and the compiler's own JSON outputs will go through it. ───────────────────────────────────

func CanonicalJSON(v any) string {
	var b strings.Builder
	writeJSON(&b, v)
	return b.String()
}

func writeJSON(b *strings.Builder, v any) {
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
	case float64:
		b.WriteString(pythonFloat(t))
	case string:
		writeJSONString(b, t)
	case []any:
		b.WriteByte('[')
		for i, e := range t {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSON(b, e)
		}
		b.WriteByte(']')
	case *Map:
		keys := t.Keys()
		sort.Strings(keys)
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSONString(b, k)
			b.WriteByte(':')
			writeJSON(b, t.vals[k])
		}
		b.WriteByte('}')
	default:
		panic(fmt.Sprintf("yamlish: no JSON for %T", v))
	}
}

// writeJSONString escapes as Python's json does with ensure_ascii=False: `"` `\` and the controls,
// short forms for \n \r \t \b \f, \u00XX for the rest; everything else as the character itself.
func writeJSONString(b *strings.Builder, s string) {
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
			} else if r == utf8.RuneError {
				b.WriteString(`�`)
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}

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

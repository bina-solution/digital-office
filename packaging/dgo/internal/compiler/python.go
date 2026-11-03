package compiler

import (
	"bytes"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// Python's own words for text, as the write verbs need them: the compiler's text surgery and its
// refusals are made of str(), int(), str.strip/split/lower/splitlines, Path.read_text and `re` with its
// Unicode \s and its `$`. Each helper is the one CPython behaviour a ported line depends on, so a
// refusal reads the same and the same bytes land in the file. (repr(), str(), str.isspace(),
// str.strip(), `\s` and int() of a str are internal/pyval's, the one copy the other ports read with.)

// dies is a place where reconcile.py raises instead of answering — a traceback and exit 1. The verb
// stops there too: exit 1, nothing more on stdout, and one FATAL line naming what Python raised, as
// the read verbs do (died makes one).
type dies struct {
	what  string
	codec string // a UnicodeDecodeError's str(e), which main() prints where it catches a ValueError
}

func (d *dies) Error() string { return "FATAL " + d.what }

func pySplit(s string) []string { return strings.FieldsFunc(s, pyval.IsSpace) } // str.split()
func pyLen(s string) int        { return utf8.RuneCountInString(s) }

func pyLjust(s string, n int) string {
	if k := pyLen(s); k < n {
		return s + strings.Repeat(" ", n-k)
	}
	return s
}

// pyLower is str.lower() where it matters here: the one character whose full lowercase differs from
// Go's simple mapping in a way an ASCII-only pattern could notice is U+0130, which Python lowers to
// two characters (i and a combining dot), not to the ASCII "i".
func pyLower(s string) string {
	return strings.ToLower(strings.ReplaceAll(s, "\u0130", "i\u0307"))
}

// pySplitLines is str.splitlines(keepends): a line ends at \n, \r\n, \r, \v, \f, \x1c, \x1d, \x1e,
// \x85, U+2028 or U+2029 — not only at \n.
func pySplitLines(s string, keepEnds bool) []string {
	var out []string
	start := 0
	for i, r := range s {
		if i < start {
			continue
		}
		switch r {
		case '\n', '\r', '\v', '\f', 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029:
		default:
			continue
		}
		end := i + utf8.RuneLen(r)
		if r == '\r' && strings.HasPrefix(s[end:], "\n") {
			end++
		}
		if keepEnds {
			out = append(out, s[start:end])
		} else {
			out = append(out, s[start:i])
		}
		start = end
	}
	if start < len(s) {
		out = append(out, s[start:])
	}
	return out
}

// pyMatch is re.match(pattern, s) for a pattern anchored as `^…$`, compiled here as `^…\z`: Python's
// `$` also matches just before a newline that ends the string, so "akadmin\n" passes `^[a-z]+$`.
// reconcile.py's own patterns are so; serve.py's end in `\Z` since DGO-615 and are matched as written.
func pyMatch(re *regexp.Regexp, s string) bool {
	return re.MatchString(s) || (strings.HasSuffix(s, "\n") && re.MatchString(strings.TrimSuffix(s, "\n")))
}

// readText is Path.read_text(encoding="utf-8"): the OS's error when the file cannot be read, a
// UnicodeDecodeError when it is not UTF-8, and universal newlines — "\r\n" and "\r" read as "\n".
func readText(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	if !utf8.Valid(raw) {
		return "", decodeError(filepath.Base(path), raw)
	}
	raw = bytes.ReplaceAll(raw, []byte("\r\n"), []byte("\n"))
	return string(bytes.ReplaceAll(raw, []byte("\r"), []byte("\n"))), nil
}

// decodeError is the UnicodeDecodeError Python raises for bytes that are not UTF-8, worded as
// str(e) words it: one byte by its value, a longer bad sequence by its range of positions.
func decodeError(name string, raw []byte) *dies {
	start, end, why := badUTF8(raw)
	codec := fmt.Sprintf("'utf-8' codec can't decode bytes in position %d-%d: %s", start, end-1, why)
	if end == start+1 {
		codec = fmt.Sprintf("'utf-8' codec can't decode byte 0x%02x in position %d: %s", raw[start], start, why)
	}
	return &dies{what: name + ": UnicodeDecodeError: " + codec, codec: codec}
}

// badUTF8 is where CPython's UTF-8 decoder (Objects/stringlib/codecs.h) stops on raw, which is not
// valid UTF-8: the bytes it blames, [start, end), and why. A lead byte with no room for its sequence
// is "unexpected end of data" up to the end; a continuation that is wrong blames the lead byte and the
// good continuations before it; an overlong form or a surrogate is wrong at the second byte.
func badUTF8(raw []byte) (int, int, string) {
	cont := func(i int) bool { return raw[i]&0xC0 == 0x80 }
	const (
		badStart = "invalid start byte"
		badCont  = "invalid continuation byte"
		cutShort = "unexpected end of data"
	)
	for i := 0; i < len(raw); {
		b, left := raw[i], len(raw)-i
		switch {
		case b < 0x80:
			i++
			continue
		case b < 0xC2 || b > 0xF4:
			return i, i + 1, badStart
		}
		size := 2
		if b >= 0xE0 {
			size = 3
		}
		if b >= 0xF0 {
			size = 4
		}
		// the second byte's range depends on the lead: no overlong form, no surrogate, nothing past U+10FFFF
		lo, hi := byte(0x80), byte(0xBF)
		switch b {
		case 0xE0:
			lo = 0xA0
		case 0xED:
			hi = 0x9F
		case 0xF0:
			lo = 0x90
		case 0xF4:
			hi = 0x8F
		}
		if left >= 2 && (raw[i+1] < lo || raw[i+1] > hi) {
			return i, i + 1, badCont
		}
		for k := 2; k < size; k++ {
			if k < left && !cont(i+k) {
				return i, i + k, badCont
			}
		}
		if left < size {
			return i, len(raw), cutShort
		}
		i += size
	}
	return len(raw), len(raw), "" // valid; callers only ask of invalid bytes
}

// errNotInt is the TypeError or ValueError int() raises for a value that is not a number — the two
// exceptions the remote block's checks catch.
var errNotInt = errors.New("not an integer")

// pyInt is int(v) for a decoded value: a bool is 0 or 1, a float is cut toward zero (NaN is a
// ValueError; an infinity is the OverflowError nobody catches), a str is read as int() reads one
// (pyval.Int) — surrounding whitespace, a sign, decimal digits of any script, `_` between digits.
func pyInt(v any) (pyval.Integer, error) {
	switch t := v.(type) {
	case bool:
		if t {
			return pyval.IntegerOf(1), nil
		}
		return pyval.IntegerOf(0), nil
	case int64:
		return pyval.IntegerOf(t), nil
	case yamlish.BigInt:
		return pyval.Integer{Text: string(t)}, nil
	case float64:
		switch {
		case math.IsNaN(t):
			return pyval.Integer{}, errNotInt
		case math.IsInf(t, 0):
			return pyval.Integer{}, &dies{what: "OverflowError: cannot convert float infinity to integer"}
		}
		tr := math.Trunc(t)
		if tr >= -9.2e18 && tr <= 9.2e18 {
			return pyval.IntegerOf(int64(tr)), nil
		}
		return pyval.Integer{Text: strconv.FormatFloat(tr, 'f', 0, 64)}, nil
	case string:
		if n, ok := pyval.Int(t); ok {
			return n, nil
		}
	}
	return pyval.Integer{}, errNotInt
}

// absent is `v in (None, "")`.
func absent(v any) bool { return v == nil || v == "" }

// orEmpty is `v or ""`.
func orEmpty(v any) any {
	if !truthy(v) {
		return ""
	}
	return v
}

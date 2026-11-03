package trust

// A strict reader for the small JSON documents this package reads — the signed envelope, keys.json, the
// core manifest and the index document. WHY NOT encoding/json: it costs 250,368 bytes of the installer
// stub (measured on windows/amd64 on 2026-10-15, on top of the TLS floor every build carries), a
// sixteenth of its 4 MiB budget, for a reflection-driven decoder the stub would use a sliver of.
//
// It reads exactly RFC 8259 JSON and is STRICTER than encoding/json in four places, each a refusal:
// a duplicate key, invalid UTF-8, a \u escape in the UTF-16 surrogate range (relsign never writes one),
// and nesting deeper than maxJSONDepth. Everything else — what it accepts, what it refuses and the values
// it returns — is encoding/json's answer: TestJSONReaderMatchesEncodingJSON (jsonread_test.go) runs
// encoding/json beside it as the oracle on every case.

import (
	"bytes"
	"errors"
	"strconv"
	"time"
	"unicode/utf8"
)

// maxJSONDepth bounds nesting; the deepest document read here is three levels (envelope → signatures → one).
const maxJSONDepth = 32

// jsonNumber is a number kept as its literal text (encoding/json's UseNumber), so an integer field is
// parsed once, by the getter that knows it wants an integer.
type jsonNumber string

// parseJSON reads one JSON text: an object becomes map[string]any, an array []any, a string string, a
// number jsonNumber, true/false bool and null nil.
func parseJSON(b []byte) (any, error) {
	p := jsonParser{b: b}
	v, err := p.value(0)
	if err == nil {
		if p.space(); p.i < len(p.b) {
			err = p.fail("data after the document")
		}
	}
	return v, err
}

type jsonParser struct {
	b []byte
	i int
}

func (p *jsonParser) fail(what string) error {
	return errors.New("JSON: " + what + " at byte " + strconv.Itoa(p.i))
}

func (p *jsonParser) space() {
	for p.i < len(p.b) && (p.b[p.i] == ' ' || p.b[p.i] == '\t' || p.b[p.i] == '\n' || p.b[p.i] == '\r') {
		p.i++
	}
}

// eat consumes c when it is the next byte after any whitespace.
func (p *jsonParser) eat(c byte) bool {
	if p.space(); p.i < len(p.b) && p.b[p.i] == c {
		p.i++
		return true
	}
	return false
}

func (p *jsonParser) value(depth int) (any, error) {
	if depth > maxJSONDepth {
		return nil, p.fail("nesting deeper than " + strconv.Itoa(maxJSONDepth))
	}
	if p.space(); p.i == len(p.b) {
		return nil, p.fail("unexpected end")
	}
	switch c := p.b[p.i]; {
	case c == '{':
		return p.object(depth)
	case c == '[':
		return p.array(depth)
	case c == '"':
		return p.text()
	case c == '-' || '0' <= c && c <= '9':
		return p.number()
	}
	for _, lit := range [...]struct {
		s string
		v any
	}{{"true", true}, {"false", false}, {"null", nil}} {
		if bytes.HasPrefix(p.b[p.i:], []byte(lit.s)) {
			p.i += len(lit.s)
			return lit.v, nil
		}
	}
	return nil, p.fail("unexpected character")
}

func (p *jsonParser) object(depth int) (any, error) {
	p.i++ // '{'
	m := map[string]any{}
	if p.eat('}') {
		return m, nil
	}
	for {
		if p.space(); p.i == len(p.b) || p.b[p.i] != '"' {
			return nil, p.fail("expected a quoted key")
		}
		k, err := p.text()
		if err != nil {
			return nil, err
		}
		if !p.eat(':') {
			return nil, p.fail("expected ':'")
		}
		v, err := p.value(depth + 1)
		if err != nil {
			return nil, err
		}
		if _, dup := m[k]; dup {
			return nil, p.fail("duplicate key " + strconv.Quote(k))
		}
		m[k] = v
		if p.eat(',') {
			continue
		}
		if p.eat('}') {
			return m, nil
		}
		return nil, p.fail("expected ',' or '}'")
	}
}

func (p *jsonParser) array(depth int) (any, error) {
	p.i++ // '['
	a := []any{}
	if p.eat(']') {
		return a, nil
	}
	for {
		v, err := p.value(depth + 1)
		if err != nil {
			return nil, err
		}
		a = append(a, v)
		if p.eat(',') {
			continue
		}
		if p.eat(']') {
			return a, nil
		}
		return nil, p.fail("expected ',' or ']'")
	}
}

func (p *jsonParser) text() (string, error) {
	p.i++ // the opening quote
	var out []byte
	for p.i < len(p.b) {
		c := p.b[p.i]
		p.i++
		switch {
		case c == '"':
			if !utf8.Valid(out) {
				return "", p.fail("invalid UTF-8 in a string")
			}
			return string(out), nil
		case c < 0x20:
			return "", p.fail("control character in a string")
		case c != '\\':
			out = append(out, c)
		case p.i == len(p.b):
			return "", p.fail("unterminated string")
		default:
			e := p.b[p.i]
			p.i++
			switch e {
			case '"', '\\', '/':
				out = append(out, e)
			case 'b':
				out = append(out, '\b')
			case 'f':
				out = append(out, '\f')
			case 'n':
				out = append(out, '\n')
			case 'r':
				out = append(out, '\r')
			case 't':
				out = append(out, '\t')
			case 'u':
				if p.i+4 > len(p.b) {
					return "", p.fail("short \\u escape")
				}
				r, err := strconv.ParseUint(string(p.b[p.i:p.i+4]), 16, 16)
				if err != nil {
					return "", p.fail("malformed \\u escape")
				}
				if 0xD800 <= r && r <= 0xDFFF {
					return "", p.fail("\\u escape of a UTF-16 surrogate")
				}
				out = utf8.AppendRune(out, rune(r))
				p.i += 4
			default:
				return "", p.fail("unknown escape")
			}
		}
	}
	return "", p.fail("unterminated string")
}

// number reads RFC 8259's grammar exactly: -?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?
func (p *jsonParser) number() (any, error) {
	start := p.i
	if p.b[p.i] == '-' {
		p.i++
	}
	if p.i < len(p.b) && p.b[p.i] == '0' {
		p.i++
	} else if p.digits() == 0 {
		return nil, p.fail("malformed number")
	}
	if p.i < len(p.b) && p.b[p.i] == '.' {
		if p.i++; p.digits() == 0 {
			return nil, p.fail("malformed number")
		}
	}
	if p.i < len(p.b) && (p.b[p.i] == 'e' || p.b[p.i] == 'E') {
		if p.i++; p.i < len(p.b) && (p.b[p.i] == '+' || p.b[p.i] == '-') {
			p.i++
		}
		if p.digits() == 0 {
			return nil, p.fail("malformed number")
		}
	}
	return jsonNumber(p.b[start:p.i]), nil
}

func (p *jsonParser) digits() int {
	n := 0
	for p.i < len(p.b) && '0' <= p.b[p.i] && p.b[p.i] <= '9' {
		p.i++
		n++
	}
	return n
}

// obj is a JSON object read for its fields. Each getter refuses a missing, empty or mistyped field by
// its name, so a refusal says which line of a document is wrong. Unknown fields are ignored: a later
// release may add one, and min_bootstrapper — not a parse error — is how it retires an older stub.
type obj map[string]any

func asObj(v any, what string) (obj, error) {
	if m, ok := v.(map[string]any); ok {
		return m, nil
	}
	return nil, errors.New(what + " is not a JSON object")
}

func (o obj) text(k string) (string, error) {
	if s, ok := o[k].(string); ok && s != "" {
		return s, nil
	}
	return "", errors.New("field " + strconv.Quote(k) + " is missing or not a non-empty string")
}

// natural is a whole number ≥ 0 (a version counter, a size in bytes).
func (o obj) natural(k string) (int64, error) {
	if s, ok := o[k].(jsonNumber); ok {
		if n, err := strconv.ParseInt(string(s), 10, 64); err == nil && n >= 0 {
			return n, nil
		}
	}
	return 0, errors.New("field " + strconv.Quote(k) + " is missing or not a whole number")
}

func (o obj) instant(k string) (time.Time, error) {
	s, err := o.text(k)
	if err != nil {
		return time.Time{}, err
	}
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		return time.Time{}, errors.New("field " + strconv.Quote(k) + " is not an RFC 3339 time")
	}
	return t, nil
}

func (o obj) list(k string) ([]any, error) {
	if a, ok := o[k].([]any); ok && len(a) > 0 {
		return a, nil
	}
	return nil, errors.New("field " + strconv.Quote(k) + " is missing or not a non-empty list")
}

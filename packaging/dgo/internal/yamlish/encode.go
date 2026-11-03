package yamlish

import (
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// Options mirrors the safe_dump keyword arguments the compiler passes. allow_unicode=True and
// default_flow_style=False are passed (or defaulted) by every call site, so they are not options:
// they are what this emitter is.
type Options struct {
	SortKeys bool // sort_keys
	Width    int  // width; 0 is PyYAML's default, 80
}

// Marshal is yaml.safe_dump(v, default_flow_style=False, allow_unicode=True, sort_keys=…, width=…),
// byte for byte, for the values the compiler writes — this package's own model: mappings (a *Map
// keeps its order unless SortKeys), sequences, strings, integers (BigInt included), floats, booleans
// and null.
//
// WHY A PORT AND NOT "AN EQUIVALENT". Every byte the compiler writes is read by something: write()
// leaves a generated file alone only while it says the same bytes (a rewrite is an event to the
// sign-in worker, the edge and the console that watch them), people and git read the state file, and
// a verb is answered natively only once its bytes equal reconcile.py's. So this is PyYAML's emitter
// itself — analyze_scalar, choose_scalar_style, the three scalar writers with their line folding,
// write_indent's column rules — driven by the walk its event state machine makes over a block-style
// document. Every shape the compiler writes is checked against safe_dump by TestMarshalMatchesPyYAML,
// and the checkout's own platform.state.yaml by TestTheStateFileRoundTrips.
//
// What it refuses rather than guesses: a document root that is not a mapping or a sequence (PyYAML
// ends such a document with `...`, and nothing in the compiler writes one), and a value of any other
// type.
//
// A mapping that appears twice in the document — the same *Map, as the same dict object does in
// Python (the console registry's tiles share their office's label and mark) — is written as PyYAML's
// serializer writes it: `&idNNN` where it first appears, `*idNNN` wherever it appears again, the
// names numbered in the order the repeats are met. A sequence is never shared by what the compiler
// writes, so only a mapping is anchored.
func Marshal(v any, o Options) ([]byte, error) {
	switch v.(type) {
	case *Map, []any:
	default:
		return nil, errors.New("yamlish.Marshal: the document root must be a mapping or a sequence")
	}
	e := &emitter{width: 80, sortKeys: o.SortKeys, indent: -1, whitespace: true, indention: true,
		anchors: map[*Map]string{}, written: map[*Map]bool{}}
	if o.Width > 2*bestIndent {
		e.width = o.Width
	}
	e.anchor(v, map[*Map]bool{})
	if err := e.node(v, false, false); err != nil {
		return nil, err
	}
	e.writeIndent() // the document's end: the last line is closed
	return []byte(e.b.String()), nil
}

// ErrNotReadBack is MarshalReadBack's refusal: the document is PyYAML's, but this package's reader would
// refuse it or read another value from it.
var ErrNotReadBack = errors.New("dgo's YAML reader would not read it back as written")

// MarshalReadBack is Marshal, and the proof that Unmarshal reads the document back as v. The state
// file's writers write only through it: the next native verb reads the file through Unmarshal, so a
// document it refuses would stop every native verb after this write, and one it misreads would be
// "changed" — and rewritten — on every pass. Which values those are is the reader's business (a key
// YAML writes as `? key` and an integer beyond 64 bits by its design; a non-ASCII space at a value's
// edge, a line separator inside one and int64's minimum until it reads them as PyYAML does); this
// only asks.
func MarshalReadBack(v any, o Options) ([]byte, error) {
	out, err := Marshal(v, o)
	if err != nil {
		return nil, err
	}
	back, err := Unmarshal(out)
	if err != nil {
		return nil, fmt.Errorf("%w (%v)", ErrNotReadBack, err)
	}
	if CanonicalJSON(back) != CanonicalJSON(v) {
		return nil, fmt.Errorf("%w (it reads another value)", ErrNotReadBack)
	}
	return out, nil
}

const bestIndent = 2

// emitter carries PyYAML's Emitter state that decides bytes: the column of the next character,
// whether the last thing written was whitespace or indentation, and the indentation stack (-1 stands
// for None, the indent before the root collection opens). flow_level is always 0 where a scalar is
// written: the only flow collections in a block document are the empty ones, `{}` and `[]`.
type emitter struct {
	b          strings.Builder
	width      int
	sortKeys   bool
	indent     int
	indents    []int
	column     int
	whitespace bool
	indention  bool
	anchors    map[*Map]string // a mapping met more than once, and its name
	written    map[*Map]bool   // an anchored mapping already written: the next time is its alias
}

// anchor is Serializer.anchor_node: the document walked in the order it is written, a mapping met a
// second time given the next name (id001, id002, …) and not walked again.
func (e *emitter) anchor(v any, seen map[*Map]bool) {
	switch t := v.(type) {
	case *Map:
		if seen[t] {
			if e.anchors[t] == "" {
				e.anchors[t] = fmt.Sprintf("id%03d", len(e.anchors)+1)
			}
			return
		}
		seen[t] = true
		for _, k := range e.keys(t) {
			x, _ := t.Get(k)
			e.anchor(x, seen)
		}
	case []any:
		for _, x := range t {
			e.anchor(x, seen)
		}
	}
}

// keys are a mapping's keys in the order they are written.
func (e *emitter) keys(m *Map) []string {
	keys := m.Keys()
	if e.sortKeys {
		sort.Strings(keys)
	}
	return keys
}

// node is expect_node. inMapping says the node is a key or value of a block mapping (a sequence
// there is written without extra indentation); simpleKey says it is a key written on its own line.
func (e *emitter) node(v any, inMapping, simpleKey bool) error {
	switch t := v.(type) {
	case *Map:
		if name := e.anchors[t]; name != "" { // process_anchor: `&name` the first time, `*name` after
			if e.written[t] {
				e.writeIndicator("*"+name, true, false, false)
				return nil
			}
			e.written[t] = true
			e.writeIndicator("&"+name, true, false, false)
		}
		if t.Len() == 0 {
			e.emptyFlow("{", "}")
			return nil
		}
		return e.mapping(t)
	case []any:
		if len(t) == 0 {
			e.emptyFlow("[", "]")
			return nil
		}
		return e.sequence(t, inMapping)
	}
	text, isString, err := represent(v)
	if err != nil {
		return err
	}
	// A non-string's text always reads back as its own type (that is how the representer spells it);
	// a string is plain only if no resolver would read the plain text as something else.
	e.scalar(text, !isString || plainIsString(text), simpleKey)
	return nil
}

// represent is SafeRepresenter: the scalar's text, and whether it is a string.
func represent(v any) (string, bool, error) {
	switch t := v.(type) {
	case nil:
		return "null", false, nil
	case bool:
		return strconv.FormatBool(t), false, nil
	case int:
		return strconv.Itoa(t), false, nil
	case int64:
		return strconv.FormatInt(t, 10), false, nil
	case BigInt:
		return string(t), false, nil
	case float64:
		return pyYAMLFloat(t), false, nil
	case string:
		return t, true, nil
	}
	return "", false, fmt.Errorf("yamlish.Marshal: no YAML for a value of type %T", v)
}

// pyYAMLFloat is represent_float: repr() in lower case, with .inf/.nan, and a ".0" put before an
// exponent whose mantissa has no point (repr's 1e+16 is not a YAML 1.1 float; 1.0e+16 is).
func pyYAMLFloat(f float64) string {
	switch {
	case math.IsNaN(f):
		return ".nan"
	case math.IsInf(f, 1):
		return ".inf"
	case math.IsInf(f, -1):
		return "-.inf"
	}
	s := pythonFloat(f)
	if strings.Contains(s, "e") && !strings.Contains(s, ".") {
		s = strings.Replace(s, "e", ".0e", 1)
	}
	return s
}

// mapping is a block mapping: each key on its own line at the mapping's indentation — a simple key
// followed by `:`, or, for a key that cannot be one, the explicit `? key` / `: value` form. A simple
// key is not empty, has no line break, and is shorter than 128 characters counting its tag, which
// check_simple_key measures although the tag is never written: `!!str` (or `!!int` …), five more. A
// key is written as YAML typed it where it was read (TypedKey: `80:` stays the int 80, not '80').
func (e *emitter) mapping(m *Map) error {
	e.increaseIndent(false, false)
	for _, k := range e.keys(m) {
		e.writeIndent()
		text, isString, err := represent(m.TypedKey(k))
		if err != nil {
			return err
		}
		implicit := !isString || plainIsString(text)
		if n := len([]rune(text)); n > 0 && n+len("!!str") < 128 && !hasLineBreak(text) {
			e.scalar(text, implicit, true)
			e.writeIndicator(":", false, false, false)
		} else {
			e.writeIndicator("?", true, false, true)
			e.scalar(text, implicit, false)
			e.writeIndent()
			e.writeIndicator(":", true, false, true)
		}
		v, _ := m.Get(k)
		if err := e.node(v, true, false); err != nil {
			return err
		}
	}
	e.popIndent()
	return nil
}

// sequence is a block sequence. As a mapping's value it is "indentless" — its dashes stand at the
// mapping's own column — which is PyYAML's layout and the one every file here is written in.
func (e *emitter) sequence(items []any, inMapping bool) error {
	e.increaseIndent(false, inMapping && !e.indention)
	for _, it := range items {
		e.writeIndent()
		e.writeIndicator("-", true, false, true)
		if err := e.node(it, false, false); err != nil {
			return err
		}
	}
	e.popIndent()
	return nil
}

// emptyFlow is an empty collection, which PyYAML always writes in flow style.
func (e *emitter) emptyFlow(open, close string) {
	e.writeIndicator(open, true, true, false)
	e.writeIndicator(close, false, false, false)
}

func (e *emitter) increaseIndent(flow, indentless bool) {
	e.indents = append(e.indents, e.indent)
	switch {
	case e.indent < 0 && flow:
		e.indent = bestIndent
	case e.indent < 0:
		e.indent = 0
	case !indentless:
		e.indent += bestIndent
	}
}

func (e *emitter) popIndent() {
	e.indent = e.indents[len(e.indents)-1]
	e.indents = e.indents[:len(e.indents)-1]
}

// ── scalars ───────────────────────────────────────────────────────────────────────────────────────

func isBreak(r rune) bool { return r == '\n' || r == 0x85 || r == 0x2028 || r == 0x2029 }

func hasLineBreak(s string) bool { return strings.ContainsAny(s, "\n\u0085\u2028\u2029") }

// spaceOrEnd is the set analyze_scalar calls whitespace around an indicator.
func spaceOrEnd(r rune) bool { return r == 0 || r == ' ' || r == '\t' || r == '\r' || isBreak(r) }

// analysis is what analyze_scalar decides about a text, reduced to what a block document uses.
type analysis struct {
	empty, multiline, plain, singleQuoted bool
}

// analyze is analyze_scalar with allow_unicode=True: which styles can carry the text unchanged.
func analyze(s []rune) analysis {
	if len(s) == 0 {
		return analysis{empty: true, plain: true, singleQuoted: true}
	}
	indicators := strings.HasPrefix(string(s), "---") || strings.HasPrefix(string(s), "...")
	var lineBreaks, special, leadingSpace, leadingBreak, trailingSpace, trailingBreak, breakSpace, spaceBreak bool
	precededBySpace, followedBySpace := true, len(s) == 1 || spaceOrEnd(s[1])
	prevSpace, prevBreak := false, false
	for i, ch := range s {
		if i == 0 {
			if strings.ContainsRune("#,[]{}&*!|>'\"%@`", ch) ||
				((ch == '?' || ch == ':' || ch == '-') && followedBySpace) {
				indicators = true
			}
		} else if (ch == ':' && followedBySpace) || (ch == '#' && precededBySpace) {
			indicators = true
		}
		if isBreak(ch) {
			lineBreaks = true
		}
		if !(ch == '\n' || (ch >= 0x20 && ch <= 0x7E)) {
			printable := ch == 0x85 || (ch >= 0xA0 && ch <= 0xD7FF) || (ch >= 0xE000 && ch <= 0xFFFD) ||
				(ch >= 0x10000 && ch < 0x10FFFF)
			if !printable || ch == 0xFEFF {
				special = true
			}
		}
		switch {
		case ch == ' ':
			leadingSpace = leadingSpace || i == 0
			trailingSpace = trailingSpace || i == len(s)-1
			breakSpace = breakSpace || prevBreak
			prevSpace, prevBreak = true, false
		case isBreak(ch):
			leadingBreak = leadingBreak || i == 0
			trailingBreak = trailingBreak || i == len(s)-1
			spaceBreak = spaceBreak || prevSpace
			prevSpace, prevBreak = false, true
		default:
			prevSpace, prevBreak = false, false
		}
		precededBySpace = spaceOrEnd(ch)
		followedBySpace = i+2 >= len(s) || spaceOrEnd(s[i+2])
	}
	a := analysis{multiline: lineBreaks, plain: true, singleQuoted: true}
	if leadingSpace || leadingBreak || trailingSpace || trailingBreak || lineBreaks || indicators {
		a.plain = false
	}
	if breakSpace || spaceBreak || special {
		a.plain, a.singleQuoted = false, false
	}
	return a
}

// scalar is expect_scalar + choose_scalar_style + process_scalar. implicit says the plain text would
// read back as the same value; a simple key is never folded and never written plain when empty.
func (e *emitter) scalar(text string, implicit, simpleKey bool) {
	e.increaseIndent(true, false)
	s := []rune(text)
	a := analyze(s)
	switch {
	case implicit && !(simpleKey && (a.empty || a.multiline)) && a.plain:
		e.writePlain(s, !simpleKey)
	case a.singleQuoted && !(simpleKey && a.multiline):
		e.writeSingleQuoted(s, !simpleKey)
	default:
		e.writeDoubleQuoted(s, !simpleKey)
	}
	e.popIndent()
}

// ── the writers (PyYAML's Emitter, line for line) ─────────────────────────────────────────────────

func (e *emitter) put(s string) {
	e.b.WriteString(s)
	e.column += len([]rune(s))
}

func (e *emitter) writeIndicator(ind string, needWhitespace, whitespace, indention bool) {
	if !e.whitespace && needWhitespace {
		ind = " " + ind
	}
	e.whitespace = whitespace
	e.indention = e.indention && indention
	e.put(ind)
}

func (e *emitter) writeIndent() {
	indent := e.indent
	if indent < 0 {
		indent = 0
	}
	if !e.indention || e.column > indent || (e.column == indent && !e.whitespace) {
		e.writeLineBreak("\n")
	}
	if e.column < indent {
		e.whitespace = true
		e.put(strings.Repeat(" ", indent-e.column))
	}
}

func (e *emitter) writeLineBreak(br string) {
	e.whitespace, e.indention = true, true
	e.b.WriteString(br)
	e.column = 0
}

// lineBreaks writes the breaks of a quoted scalar's text: a `\n` that starts them is doubled (one
// newline folds away when the scalar is read back), any other break is written as itself.
func (e *emitter) lineBreaks(br []rune) {
	if br[0] == '\n' {
		e.writeLineBreak("\n")
	}
	for _, r := range br {
		e.writeLineBreak(string(r))
	}
	e.writeIndent()
}

// writePlain folds at a single space once the column has passed the width. The text never holds a
// line break here: analyze() does not allow a multi-line text to be plain.
func (e *emitter) writePlain(s []rune, split bool) {
	if len(s) == 0 {
		return
	}
	if !e.whitespace {
		e.put(" ")
	}
	e.whitespace, e.indention = false, false
	spaces, start := false, 0
	for end := 0; end <= len(s); end++ {
		atEnd := end == len(s)
		var ch rune
		if !atEnd {
			ch = s[end]
		}
		if spaces {
			if atEnd || ch != ' ' {
				if start+1 == end && e.column > e.width && split {
					e.writeIndent()
					e.whitespace, e.indention = false, false
				} else {
					e.put(string(s[start:end]))
				}
				start = end
			}
		} else if atEnd || ch == ' ' {
			e.put(string(s[start:end]))
			start = end
		}
		if !atEnd {
			spaces = ch == ' '
		}
	}
}

func (e *emitter) writeSingleQuoted(s []rune, split bool) {
	e.writeIndicator("'", true, false, false)
	spaces, breaks, start := false, false, 0
	for end := 0; end <= len(s); end++ {
		atEnd := end == len(s)
		var ch rune
		if !atEnd {
			ch = s[end]
		}
		switch {
		case spaces:
			if atEnd || ch != ' ' {
				if start+1 == end && e.column > e.width && split && start != 0 && end != len(s) {
					e.writeIndent()
				} else {
					e.put(string(s[start:end]))
				}
				start = end
			}
		case breaks:
			if atEnd || !isBreak(ch) {
				e.lineBreaks(s[start:end])
				start = end
			}
		default:
			if (atEnd || ch == ' ' || isBreak(ch) || ch == '\'') && start < end {
				e.put(string(s[start:end]))
				start = end
			}
		}
		if !atEnd && ch == '\'' {
			e.put("''")
			start = end + 1
		}
		if !atEnd {
			spaces, breaks = ch == ' ', isBreak(ch)
		}
	}
	e.writeIndicator("'", false, false, false)
}

// escapes is Emitter.ESCAPE_REPLACEMENTS, verbatim.
var escapes = map[rune]string{
	0: "0", 0x07: "a", 0x08: "b", 0x09: "t", 0x0A: "n", 0x0B: "v", 0x0C: "f", 0x0D: "r", 0x1B: "e",
	'"': "\"", '\\': "\\", 0x85: "N", 0xA0: "_", 0x2028: "L", 0x2029: "P",
}

// writeDoubleQuoted escapes what a YAML file cannot carry as itself and folds a long line with an
// escaped line break (`\` at the end, and `\ ` where the next line would begin with a space).
func (e *emitter) writeDoubleQuoted(s []rune, split bool) {
	e.writeIndicator("\"", true, false, false)
	start := 0
	for end := 0; end <= len(s); end++ {
		atEnd := end == len(s)
		var ch rune
		if !atEnd {
			ch = s[end]
		}
		if atEnd || ch == '"' || ch == '\\' || ch == 0x85 || ch == 0x2028 || ch == 0x2029 || ch == 0xFEFF ||
			!((ch >= 0x20 && ch <= 0x7E) || (ch >= 0xA0 && ch <= 0xD7FF) || (ch >= 0xE000 && ch <= 0xFFFD)) {
			if start < end {
				e.put(string(s[start:end]))
				start = end
			}
			if !atEnd {
				switch r, ok := escapes[ch]; {
				case ok:
					e.put("\\" + r)
				case ch <= 0xFF:
					e.put(fmt.Sprintf("\\x%02X", ch))
				case ch <= 0xFFFF:
					e.put(fmt.Sprintf("\\u%04X", ch))
				default:
					e.put(fmt.Sprintf("\\U%08X", ch))
				}
				start = end + 1
			}
		}
		if 0 < end && end < len(s)-1 && (ch == ' ' || start >= end) && e.column+(end-start) > e.width && split {
			pending := "" // right after an escape start is end+1, and Python's text[start:end] is ''
			if start < end {
				pending = string(s[start:end])
				start = end
			}
			e.put(pending + "\\")
			e.writeIndent()
			e.whitespace, e.indention = false, false
			if s[start] == ' ' {
				e.put("\\")
			}
		}
	}
	e.writeIndicator("\"", false, false, false)
}

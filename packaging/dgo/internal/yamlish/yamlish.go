// Package yamlish reads the YAML the office's compiler actually consumes — platform.state.yaml and
// every app's compose file — with PyYAML's answers, and refuses the rest of YAML out loud.
//
// WHY NOT A YAML LIBRARY. dgo is stdlib-only (CGO_ENABLED=0, nothing downloaded — the two binaries
// before it and the release lane are built on that), and the compiler it replaces reads YAML through
// PyYAML's safe_load: YAML 1.1 resolution, where `on` is true, `0755` is 493 and `1e5` is a string.
// A general YAML 1.2 library gives different answers for exactly the corners a config file hits, and
// carries ten thousand lines nobody here reads. The office's corpus, measured 2026-10-10 over the 63
// files the compiler reads: block and flow mappings and sequences, plain and quoted scalars, comments,
// one optional `---`. No anchors, aliases, merge keys, tags, multi-documents, complex keys or
// multi-line quoted scalars outside comments. So this is that subset with PyYAML's scalar rules, and
// an error — never a guess — for anything else. TestCorpusMatchesPyYAML (yamlish_test.go) runs PyYAML
// beside it on every file the compiler reads and compares the two canonical JSON renderings byte for
// byte; the day the corpus grows a construct this package lacks, that test says so by file name.
// The console's registry (.generated/registry/console.modules.yaml, read by the console's server)
// added one: safe_dump writes an object that appears twice — a linked office's label — as `&idNNN`
// before a collection and `*idNNN` where it repeats. Those two shapes are read; every other anchor,
// alias or tag is still refused.
//
// Values: *Map (insertion-ordered — a compose file's key order is meaning to a reader and to
// safe_dump(sort_keys=False)), []any, string, int64, float64, bool, nil.
package yamlish

import (
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Map is an insertion-ordered string-keyed mapping. A non-string YAML key (80:, true:) is kept under
// its canonical JSON spelling, as json.dumps would write it; TypedKey still has it as YAML typed it.
type Map struct {
	keys  []string
	vals  map[string]any
	typed map[string]any // the keys YAML did not type as strings, by their spelling
}

// TypedKey is a key as YAML typed it: the key itself for a string, else the bool, number or null a
// plain key resolved to — what a reader needs that must print a key as Python would (`yes:` is True).
func (m *Map) TypedKey(k string) any {
	if t, ok := m.typed[k]; ok {
		return t
	}
	return k
}

// keyed remembers the type of the key just set from raw, when YAML did not make it a string.
func (m *Map) keyed(k, raw string) {
	if t, err := scalar(strings.TrimSpace(raw)); err == nil {
		if _, isString := t.(string); !isString {
			if m.typed == nil {
				m.typed = map[string]any{}
			}
			m.typed[k] = t
		}
	}
}

func NewMap() *Map { return &Map{vals: map[string]any{}} }

// Set keeps the position of an existing key (a duplicate key keeps its first place and takes the
// last value, which is what a Python dict does under PyYAML).
func (m *Map) Set(k string, v any) {
	if _, ok := m.vals[k]; !ok {
		m.keys = append(m.keys, k)
	}
	m.vals[k] = v
}

func (m *Map) Get(k string) (any, bool) { v, ok := m.vals[k]; return v, ok }

// Delete removes a key (a no-op for one that is absent).
func (m *Map) Delete(k string) {
	if _, ok := m.vals[k]; !ok {
		return
	}
	delete(m.vals, k)
	delete(m.typed, k)
	for i, key := range m.keys {
		if key == k {
			m.keys = append(m.keys[:i], m.keys[i+1:]...)
			break
		}
	}
}
func (m *Map) Keys() []string { return append([]string(nil), m.keys...) }
func (m *Map) Len() int       { return len(m.keys) }

// Unmarshal parses one YAML document.
func Unmarshal(src []byte) (any, error) {
	p := &parser{}
	if err := p.split(string(src)); err != nil {
		return nil, err
	}
	all := p.lines // an end marker cuts p.lines short; the scanner still reads every line
	p.rawUsed = make([]bool, len(all))
	v, err := p.document()
	last := len(all) - 1
	if err != nil {
		last = p.at
	}
	if tabErr := p.tabUpTo(all, last); tabErr != nil {
		return nil, tabErr
	}
	return v, err
}

// document reads the one document the lines hold.
func (p *parser) document() (any, error) {
	// skip blank/comment lines before the body; allow one `---`
	i := 0
	for i < len(p.lines) && p.lines[i].blank() {
		i++
	}
	started := false // past the document's start: its `---`, or its first content
	if i < len(p.lines) && p.lines[i].indent == 0 && (p.lines[i].text == "---" || strings.HasPrefix(p.lines[i].text, "--- ")) {
		if strings.HasPrefix(p.lines[i].text, "--- ") {
			return nil, p.errAt(i, "unsupported: content on the `---` line")
		}
		i++
		started = true
	}
	for j := i; j < len(p.lines); j++ {
		t := p.lines[j].text
		if p.lines[j].indent == 0 && t == "..." && ended(p.lines[j+1:]) {
			if !started { // an implicit document must hold a node before it ends
				return nil, p.errAt(j, "an end marker with no document before it (PyYAML refuses it too)")
			}
			p.lines = p.lines[:j] // the document's end marker, with nothing after it but blanks and more of it
			break
		}
		if p.lines[j].indent == 0 && (t == "---" || t == "...") {
			// another document: a `---` anywhere past the first is one, and so is anything after a `...`
			// — inside a quoted scalar PyYAML refuses the separator itself
			return nil, p.errAt(j, "more than one document (PyYAML refuses it too: it expects a single document in the stream)")
		}
		if strings.HasPrefix(t, "%") && p.lines[j].indent == 0 && !started {
			// directives before the document: PyYAML reads them where a `---` follows (as far as this
			// reader goes, outside its subset) and refuses them where none does. One inside the document
			// is the parser's: text where it continues a quoted or a top-level plain scalar, as PyYAML
			// reads it, and else the line PyYAML refuses (a directive mid-document)
			k := j + 1
			for k < len(p.lines) && (p.lines[k].blank() || p.lines[k].indent == 0 && strings.HasPrefix(p.lines[k].text, "%")) {
				k++
			}
			if k == len(p.lines) || p.lines[k].indent != 0 || p.lines[k].text != "---" && !strings.HasPrefix(p.lines[k].text, "--- ") {
				return nil, p.errAt(j, "a directive with no `---` after it (PyYAML refuses it too)")
			}
			return nil, p.errAt(j, "unsupported: YAML directive")
		}
		started = started || t != ""
	}
	for i < len(p.lines) && p.lines[i].blank() {
		i++
	}
	if i >= len(p.lines) {
		return nil, nil // an empty document is None, as safe_load answers
	}
	v, next, err := p.node(i, p.lines[i].indent, -1)
	if err != nil {
		return nil, err
	}
	for next < len(p.lines) && p.lines[next].blank() {
		next++
	}
	if next < len(p.lines) {
		return nil, p.errAt(next, "unexpected content (is it indented less than its parent?)")
	}
	return v, nil
}

// ── lines ─────────────────────────────────────────────────────────────────────────────────────────

// line is one physical line: its indentation, its text with any trailing comment removed, the raw
// text (block scalars read raw: `#` is content there), and the break that ends it.
type line struct {
	indent  int
	text    string
	raw     string
	brk     string // "\n"; U+2028 or U+2029, which a folded scalar keeps; "" where the source ends
	n       int    // 1-based, for errors
	comment bool   // a comment was cut from text — where a plain scalar ends, as PyYAML's scanner ends it
	// tab: a tab stands outside quotes and before any comment. PyYAML's scanner skips only spaces
	// between tokens and ends a plain scalar at a tab, so it refuses the line — unless the line is
	// read raw, as a block scalar's content or a quoted scalar's continuation (parser.rawUsed).
	tab bool
}

func (l line) blank() bool { return l.text == "" }

// ended reports whether the lines after a `...` hold no other document: blanks, comments, and more
// end markers, which PyYAML's parser skips (parse_document_start).
func ended(lines []line) bool {
	for _, l := range lines {
		if !l.blank() && (l.indent != 0 || l.text != "...") {
			return false
		}
	}
	return true
}

type parser struct {
	lines   []line
	anchors map[string]any // `&name` → the collection it names, for each `*name` below it
	rawUsed []bool         // the lines read raw — a block scalar's content, a quoted scalar's continuation
	at      int            // the line of the last refusal
}

func (p *parser) errAt(i int, msg string) error {
	p.at = i
	if i >= 0 && i < len(p.lines) {
		return fmt.Errorf("yaml: line %d: %s", p.lines[i].n, msg)
	}
	return fmt.Errorf("yaml: %s", msg)
}

// tabUpTo is the refusal of the first line up to `last` with a tab that is no scalar's content: the
// tab PyYAML's scanner meets before anything else it might refuse, or read, after it.
func (p *parser) tabUpTo(lines []line, last int) error {
	for k := 0; k <= last && k < len(lines); k++ {
		if lines[k].tab && !p.rawUsed[k] {
			return fmt.Errorf("yaml: line %d: a tab where PyYAML reads only spaces (PyYAML refuses it too)", lines[k].n)
		}
	}
	return nil
}

// OutsideSubset reports whether Unmarshal refused a document by this reader's design — one PyYAML
// reads (an anchor, a tag, a merge key, keys Python's dict makes one, an integer past 64 bits) — and
// not one PyYAML refuses too. A caller answering as Python does needs the difference: on the first it
// cannot know Python's answer and must stop; the second is the YAMLError Python's own code handles.
// The reader words the first kind, and only it, "unsupported…" (TestEdgesAgreeWithPyYAML holds every
// corner to PyYAML's verdict).
func OutsideSubset(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.TrimPrefix(err.Error(), "yaml: ")
	if rest, ok := strings.CutPrefix(msg, "line "); ok {
		if _, after, ok := strings.Cut(rest, ": "); ok {
			msg = after
		}
	}
	return strings.HasPrefix(msg, "unsupported")
}

// The two line breaks PyYAML keeps as themselves where a scalar folds (scan_line_break). Every other
// break — \r\n, a lone \r, NEL — it reads as "\n", as Python's text mode reads the first two already.
const ls, ps = string(rune(0x2028)), string(rune(0x2029))

var toNewline = strings.NewReplacer("\r\n", "\n", "\r", "\n", string(rune(0x85)), "\n")

// split cuts the source into rows at every line break PyYAML reads, each row keeping the break that
// ends it; measures indentation; strips comments outside quotes.
func (p *parser) split(src string) error {
	if !utf8.ValidString(src) {
		return errors.New("yaml: not UTF-8 (PyYAML refuses it too)")
	}
	src = toNewline.Replace(strings.TrimPrefix(src, string(rune(0xFEFF))))
	for n := 1; n == 1 || src != ""; n++ { // the break that ends the source starts no row of its own
		raw, brk := src, ""
		if i := strings.IndexAny(src, "\n"+ls+ps); i >= 0 {
			r, size := utf8.DecodeRuneInString(src[i:])
			raw, brk, src = src[:i], string(r), src[i+size:]
		} else {
			src = ""
		}
		ind := 0
		for ind < len(raw) && raw[ind] == ' ' {
			ind++
		}
		if r, bad := unprintable(raw); bad {
			return fmt.Errorf("yaml: line %d: a character PyYAML refuses as not printable (U+%04X)", n, r)
		}
		cut, tab := scanLine(raw[ind:])
		l := line{text: strings.TrimRight(raw[ind:ind+cut], " \t"), raw: raw, brk: brk, n: n, comment: ind+cut < len(raw), tab: tab}
		if l.text != "" {
			l.indent = ind
		}
		p.lines = append(p.lines, l)
	}
	return nil
}

// unprintable finds a character PyYAML's reader refuses as not printable (Reader.check_printable).
func unprintable(row string) (rune, bool) {
	for _, r := range row {
		if !(r == '\t' || r >= 0x20 && r <= 0x7e || r >= 0xa0 && r <= 0xd7ff || r >= 0xe000 && r <= 0xfffd || r >= 0x10000) {
			return r, true
		}
	}
	return 0, false
}

// kept is U+2028 or U+2029 ending a row: a break PyYAML keeps in a folded scalar instead of folding it.
func kept(brk string) bool { return brk == ls || brk == ps }

// fold joins the lines of a folded flow or plain scalar as PyYAML does (scan_flow_scalar_spaces,
// scan_plain_spaces): a "\n" between two lines is one space, a kept break is itself, and each blank line
// between them adds its own break. brks[k] ends lines[k]; esc[k] says lines[k] ended in an escaped
// break (`\` at the end of a double-quoted line), which leaves nothing of the break itself. The lines
// arrive trimmed.
func fold(lines, brks []string, esc []bool) string {
	var b strings.Builder
	var blank []string
	last := 0
	for k, s := range lines {
		if k > 0 && s == "" && !esc[k] {
			blank = append(blank, brks[k])
			continue
		}
		if k > 0 {
			switch {
			case esc[last]:
			case brks[last] != "\n":
				b.WriteString(brks[last])
			case len(blank) == 0:
				b.WriteByte(' ')
			}
			b.WriteString(strings.Join(blank, ""))
			blank = nil
		}
		b.WriteString(s)
		last = k
	}
	return b.String()
}

// plainStart refuses what PyYAML's scanner refuses at the start of a plain scalar (check_plain): an
// indicator, or `-`, `?`, `:` followed by a blank — and in flow context `:` at all. A `?` in flow
// context is no refusal of PyYAML's: it is the key indicator there, always (`[?x]` is [{x: null}]),
// and a complex key is outside this subset.
func plainStart(s string, flow bool) error {
	if s == "" {
		return nil
	}
	c, blankNext := s[0], len(s) == 1 || s[1] == ' ' || s[1] == '\t'
	if c == '?' && flow {
		return errors.New("unsupported: a complex key (`?`) in a flow collection")
	}
	if strings.IndexByte("\t,[]{}#&*!|>'\"%@`", c) >= 0 || c == '-' && blankNext || c == '?' && blankNext || c == ':' && (flow || blankNext) {
		return fmt.Errorf("a plain scalar cannot start with %q (PyYAML refuses it too)", s[:1])
	}
	return nil
}

// propertyRefusal is why a node that starts with a property is refused where this reader does not read
// one: an anchor, or an alias of one above it, PyYAML reads (outside the subset); an alias of none it
// refuses. Of tags, safe_load constructs the non-specific `!` and YAML's twelve `!!` tags — a node so
// tagged may be one PyYAML reads; any other it refuses (ConstructorError, or the scanner's own error
// where no space follows the tag), and so does this.
func (p *parser) propertyRefusal(text string) string {
	switch text[0] {
	case '*':
		if name, _ := anchorName(text); name != "" {
			if _, ok := p.anchors[name]; !ok {
				return "*" + name + " names no anchor above it (PyYAML refuses the undefined alias too)"
			}
		}
	case '!':
		tag, _, _ := strings.Cut(text, " ")
		if !safeTags[tag] {
			return "the tag " + tag + " has no constructor in safe_load (PyYAML refuses it too)"
		}
		return "unsupported: the tag " + tag
	}
	return "unsupported: anchors, aliases and tags"
}

// anchorName is the name an `&` or `*` at rest[0] gives — the characters PyYAML's scan_anchor takes —
// and where it ends.
func anchorName(rest string) (string, int) {
	n := 1
	for n < len(rest) && (rest[n] == '-' || rest[n] == '_' || ('0' <= rest[n] && rest[n] <= '9') ||
		('a' <= rest[n] && rest[n] <= 'z') || ('A' <= rest[n] && rest[n] <= 'Z')) {
		n++
	}
	return rest[1:n], n
}

var safeTags = func() map[string]bool {
	tags := map[string]bool{"!": true}
	for _, n := range []string{"null", "bool", "int", "float", "binary", "timestamp", "omap", "pairs", "set", "str", "seq", "map"} {
		tags["!!"+n], tags["!<tag:yaml.org,2002:"+n+">"] = true, true
	}
	return tags
}()

// colonInPlain answers whether a line of a plain scalar holds a `:` that PyYAML reads as a mapping value
// in block context — one followed by a space, a tab or the end of the line — which it refuses there.
func colonInPlain(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] == ':' && (i+1 == len(s) || s[i+1] == ' ' || s[i+1] == '\t') {
			return true
		}
	}
	return false
}

// plainValue resolves a plain scalar in a value's place. `=` and `<<` resolve to tags PyYAML's safe
// loader has no constructor for (value, merge) — it fails on them, so this reader does too.
func plainValue(tok string) (any, error) {
	if tok == "=" || tok == "<<" {
		return nil, fmt.Errorf("a plain %q as a value (PyYAML fails on it too)", tok)
	}
	return scalar(tok)
}

// stripComment removes ` # …` (a hash at the start or after whitespace) outside quotes. A hash glued
// to text (`a#b`, a colour, an anchor in a URL) is content, as in PyYAML.
func stripComment(s string) string {
	c, _ := scanLine(s)
	return s[:c]
}

// scanLine reads a line, from its first character that is no space, as PyYAML's scanner meets it:
// where a comment starts (len(s) where none does) and whether a tab stands outside quotes before it.
// A `#` starts a comment where a token may end: at the start, after a blank, after a closing quote or
// a flow collection's indicator (`[x]# c`).
func scanLine(s string) (comment int, tab bool) {
	l, boundary := lineScan{s: s}, true
	for i := 0; i < len(s); {
		outside, ends, after := l.next(i)
		if outside && s[i] == '#' && boundary {
			return i, tab
		}
		tab = tab || outside && s[i] == '\t'
		boundary = ends || outside && (s[i] == ' ' || s[i] == '\t')
		i = after
	}
	return len(s), tab
}

// lineScan follows a line — or a flow collection's text, joined from its lines — as PyYAML's scanner
// meets it: its quoted scalars and its flow collections. A quote opens a scalar, and a `[` or `{` a
// collection, only where a token may start: at the beginning, after a space, or inside a collection
// after `[` `{` `,` `:` — so `b"c`, `it's`, `a:"b"` and `x[1]` are text.
type lineScan struct {
	s              string
	depth          int  // the flow collections open
	single, double bool // inside a quoted scalar
}

// next reads s[i]: whether it stands outside every quoted scalar, whether a token ends with it (a
// closing quote, a flow collection's indicator), and the index to read after it.
func (l *lineScan) next(i int) (outside, ends bool, after int) {
	s, c := l.s, l.s[i]
	if l.single || l.double {
		switch {
		case l.double && c == '\\':
			return false, false, i + 2
		case l.single && c == '\'' && i+1 < len(s) && s[i+1] == '\'':
			return false, false, i + 2
		case l.double && c == '"', l.single && c == '\'':
			l.single, l.double = false, false
			return false, true, i + 1
		}
		return false, false, i + 1
	}
	start := i == 0 || s[i-1] == ' ' || l.depth > 0 && strings.IndexByte("[{,:", s[i-1]) >= 0
	switch {
	case start && (c == '"' || c == '\''):
		l.single, l.double = c == '\'', c == '"'
		return false, false, i + 1
	case start && (c == '[' || c == '{'):
		l.depth++
		return true, true, i + 1
	case l.depth > 0 && (c == ']' || c == '}'):
		l.depth--
		return true, true, i + 1
	case l.depth > 0 && c == ',':
		return true, true, i + 1
	}
	return true, false, i + 1
}

// ── block structure ───────────────────────────────────────────────────────────────────────────────

// node parses the block node that starts at line i with the given indentation, inside a collection
// indented `parent` (-1 at the top) — what a scalar's further lines are measured from.
func (p *parser) node(i, indent, parent int) (any, int, error) {
	l := p.lines[i]
	if l.indent != indent {
		return nil, i, p.errAt(i, fmt.Sprintf("expected indentation %d, found %d", indent, l.indent))
	}
	if strings.IndexAny(l.text, "&*!") == 0 {
		return nil, i, p.errAt(i, p.propertyRefusal(l.text))
	}
	if l.text == "-" || strings.HasPrefix(l.text, "- ") {
		return p.sequence(i, indent)
	}
	if strings.HasPrefix(l.text, "? ") || l.text == "?" {
		return nil, i, p.errAt(i, "unsupported: complex key")
	}
	if _, _, ok := splitKey(l.text); ok {
		return p.mapping(i, indent)
	}
	return p.scalarNode(i, parent)
}

// sequence parses `- item` entries at this indentation.
func (p *parser) sequence(i, indent int) (any, int, error) {
	out := []any{}
	for i < len(p.lines) {
		l := p.lines[i]
		if l.blank() {
			i++
			continue
		}
		if l.indent < indent {
			break
		}
		if l.indent > indent {
			return nil, i, p.errAt(i, "unexpected indentation inside a sequence")
		}
		if l.text != "-" && !strings.HasPrefix(l.text, "- ") {
			break // a sibling mapping key at this indent ends the sequence (the caller decides)
		}
		rest := strings.TrimLeft(strings.TrimPrefix(l.text, "-"), " ")
		var v any
		var next int
		var err error
		switch {
		case rest == "":
			v, next, err = p.itemBelow(i, indent)
		case rest[0] == '&' || rest[0] == '*':
			v, next, err = p.anchored(i, rest, func() (any, int, error) { return p.itemBelow(i, indent) })
		default:
			// inline content after `- `: a compact mapping/sequence or a scalar. Re-base it at the
			// column where the content starts and parse the item as its own block.
			v, next, err = p.inlineItem(i, indent+(len(l.text)-len(rest)), indent, rest)
		}
		if err != nil {
			return nil, i, err
		}
		out = append(out, v)
		i = next
	}
	return out, i, nil
}

// itemBelow is a sequence item written as a block on the lines after its dash (more indented than
// it), or null.
func (p *parser) itemBelow(i, indent int) (any, int, error) {
	j := i + 1
	for j < len(p.lines) && p.lines[j].blank() {
		j++
	}
	if j < len(p.lines) && p.lines[j].indent > indent {
		return p.node(j, p.lines[j].indent, indent)
	}
	return nil, i + 1, nil
}

// anchored reads the node properties PyYAML's safe_dump writes for an object that appears twice:
// `&name` before a collection — on the lines below (read by below), or an empty `{}` / `[]` after
// it — and `*name` where the object appears again, which is that same object, as PyYAML's composer
// gives it. Everything else is refused: an anchor on a scalar or on a compact mapping (safe_dump
// writes neither), an alias before its anchor or with more after it, a second anchor of one name.
func (p *parser) anchored(i int, rest string, below func() (any, int, error)) (any, int, error) {
	name, n := anchorName(rest)
	after := strings.TrimLeft(rest[n:], " ")
	if name == "" || (n < len(rest) && rest[n] != ' ') {
		return nil, i, p.errAt(i, "unsupported: anchors, aliases and tags")
	}
	if rest[0] == '*' {
		v, ok := p.anchors[name]
		switch {
		case !ok: // every anchor this reader reads is kept, and one it does not read it refused above
			return nil, i, p.errAt(i, "*"+name+" names no anchor above it (PyYAML refuses the undefined alias too)")
		case after != "":
			return nil, i, p.errAt(i, "more after the alias *"+name+" (PyYAML refuses it too)")
		}
		return v, i + 1, nil
	}
	if _, dup := p.anchors[name]; dup {
		return nil, i, p.errAt(i, "a second anchor &"+name+" (PyYAML refuses it too)")
	}
	var v any
	var next int
	var err error
	switch {
	case after == "":
		v, next, err = below()
	case after[0] == '{' || after[0] == '[':
		v, next, err = p.flow(i, after)
	default:
		return nil, i, p.errAt(i, "unsupported: anchors on a scalar or a compact mapping (safe_dump writes neither)")
	}
	if err != nil {
		return nil, i, err
	}
	if p.anchors == nil {
		p.anchors = map[string]any{}
	}
	p.anchors[name] = v
	return v, next, nil
}

// inlineItem parses content that begins mid-line (after `- `) at column col, together with the more-
// indented lines that follow it, by substituting a synthetic first line. A scalar there is measured
// from its sequence's indentation, `parent` — the dash's column, as PyYAML measures it.
func (p *parser) inlineItem(i, col, parent int, rest string) (any, int, error) {
	if strings.IndexAny(rest, "&*!") == 0 {
		return nil, i, p.errAt(i, p.propertyRefusal(rest))
	}
	if rest == "?" || strings.HasPrefix(rest, "? ") {
		return nil, i, p.errAt(i, "unsupported: complex key")
	}
	saved := p.lines[i]
	// the same physical line with what precedes col blanked out — its comment kept (a block scalar's
	// header reads the line to its end)
	p.lines[i] = line{indent: col, text: rest, raw: strings.Repeat(" ", col) + saved.raw[col:], brk: saved.brk, n: saved.n,
		comment: saved.comment, tab: saved.tab}
	defer func() { p.lines[i] = saved }()
	if rest == "-" || strings.HasPrefix(rest, "- ") {
		return p.sequence(i, col)
	}
	if _, _, ok := splitKey(rest); ok {
		return p.mapping(i, col)
	}
	return p.scalarNode(i, parent)
}

// mapping parses `key: value` entries at this indentation.
func (p *parser) mapping(i, indent int) (any, int, error) {
	m, ids := NewMap(), map[string]string{}
	for i < len(p.lines) {
		l := p.lines[i]
		if l.blank() {
			i++
			continue
		}
		if l.indent < indent {
			break
		}
		if l.indent > indent {
			return nil, i, p.errAt(i, "unexpected indentation inside a mapping")
		}
		if l.text == "-" || strings.HasPrefix(l.text, "- ") {
			return nil, i, p.errAt(i, "a sequence entry where a mapping key was expected")
		}
		// An explicit key (`? key`, its value on the next line as `: value`) is outside the subset. Asked
		// BEFORE splitKey: a `?` key with no colon on its own line (pnpm-lock.yaml's long keys) failed as
		// a malformed mapping, which claims PyYAML would refuse it too — it does not (DGO-1040).
		if l.text == "?" || strings.HasPrefix(l.text, "? ") {
			return nil, i, p.errAt(i, "unsupported: complex key")
		}
		key, rest, ok := splitKey(l.text)
		if !ok {
			return nil, i, p.errAt(i, "expected `key: value`")
		}
		if key == "<<" {
			return nil, i, p.errAt(i, "unsupported: merge key `<<`")
		}
		if strings.IndexAny(key, "&*!") == 0 {
			return nil, i, p.errAt(i, p.propertyRefusal(key))
		}
		if key != "" && key[0] != '"' && key[0] != '\'' {
			if err := plainStart(key, false); err != nil {
				return nil, i, p.errAt(i, err.Error())
			}
		}
		k, id, err := keyString(key)
		if err == nil {
			err = oneKey(ids, id, k)
		}
		if err != nil {
			return nil, i, p.errAt(i, err.Error())
		}
		var v any
		var next int
		switch {
		case rest == "":
			v, next, err = p.valueBelow(i, indent)
		case rest[0] == '&' || rest[0] == '*':
			v, next, err = p.anchored(i, rest, func() (any, int, error) { return p.valueBelow(i, indent) })
		default:
			v, next, err = p.value(i, indent, rest)
		}
		if err != nil {
			return nil, i, err
		}
		m.Set(k, v)
		m.keyed(k, key)
		i = next
	}
	return m, i, nil
}

// valueBelow is a mapping value written as a block on the following, more-indented lines; a
// sequence may sit at the SAME indentation as the key (PyYAML's indentless sequence); otherwise null.
func (p *parser) valueBelow(i, indent int) (any, int, error) {
	j := i + 1
	for j < len(p.lines) && p.lines[j].blank() {
		j++
	}
	switch {
	case j < len(p.lines) && p.lines[j].indent > indent:
		return p.node(j, p.lines[j].indent, indent)
	case j < len(p.lines) && p.lines[j].indent == indent && (p.lines[j].text == "-" || strings.HasPrefix(p.lines[j].text, "- ")):
		return p.sequence(j, indent)
	}
	return nil, j, nil
}

// splitKey finds `key:` at the start of a line's text: a plain key up to the first `: ` or a trailing
// `:`, or a quoted key. A `:` inside a URL (`http://`) is not a key separator because no space follows.
func splitKey(text string) (key, rest string, ok bool) {
	if text == "" {
		return "", "", false
	}
	if text[0] == '"' || text[0] == '\'' {
		end := closingQuote(text)
		if end < 0 {
			return "", "", false
		}
		after := text[end+1:]
		if after == ":" {
			return text[:end+1], "", true
		}
		if strings.HasPrefix(after, ": ") {
			return text[:end+1], strings.TrimLeft(after[2:], " "), true
		}
		return "", "", false
	}
	if text[0] == '[' || text[0] == '{' {
		return "", "", false
	}
	for i := 0; i < len(text); i++ {
		if text[i] != ':' {
			continue
		}
		if i == len(text)-1 {
			return text[:i], "", true
		}
		if text[i+1] == ' ' {
			return text[:i], strings.TrimLeft(text[i+1:], " "), true
		}
	}
	return "", "", false
}

// closingQuote returns the index of the quote that closes the scalar starting at text[0], or -1.
func closingQuote(text string) int {
	q := text[0]
	for i := 1; i < len(text); i++ {
		c := text[i]
		if q == '"' && c == '\\' {
			i++
			continue
		}
		if c == q {
			if q == '\'' && i+1 < len(text) && text[i+1] == '\'' {
				i++
				continue
			}
			return i
		}
	}
	return -1
}

// keyString resolves a key the way PyYAML + json.dumps would spell it, and names the key Python's dict
// sees: there 1, 1.0 and true are one key (so are 0, 0.0, -0.0 and false), a string never equals a
// number, and every NaN is PyYAML's one NaN object.
func keyString(key string) (string, string, error) {
	v, err := scalar(strings.TrimSpace(key))
	if err != nil {
		return "", "", err
	}
	switch t := v.(type) {
	case string:
		return t, "s:" + t, nil
	case nil:
		return "null", "null", nil
	case bool:
		if t {
			return "true", "n:1", nil
		}
		return "false", "n:0", nil
	case int64:
		return CanonicalJSON(v), "n:" + strconv.FormatInt(t, 10), nil
	case float64:
		if t == math.Trunc(t) && math.Abs(t) < 1<<63 {
			return CanonicalJSON(v), "n:" + strconv.FormatInt(int64(t), 10), nil
		}
		return CanonicalJSON(v), "f:" + CanonicalJSON(v), nil
	default:
		return CanonicalJSON(v), "?" + CanonicalJSON(v), nil
	}
}

// oneKey refuses a key Python's dict holds as one with an earlier key spelled otherwise (1 and true):
// PyYAML keeps the first spelling and the last value, which this reader does not model.
func oneKey(ids map[string]string, id, spelling string) error {
	if seen, ok := ids[id]; ok && seen != spelling {
		return fmt.Errorf("unsupported: keys %s and %s are one key to Python (PyYAML keeps one; this reader will not guess which)", seen, spelling)
	}
	ids[id] = spelling
	return nil
}

// value parses what follows `key: ` on line i: a flow collection (possibly spanning lines), a block
// scalar, a quoted scalar, or a plain scalar that may continue on more-indented lines.
func (p *parser) value(i, indent int, rest string) (any, int, error) {
	switch {
	case rest[0] == '[' || rest[0] == '{':
		return p.flow(i, rest)
	case rest[0] == '|' || rest[0] == '>':
		return p.blockScalar(i, indent, rest)
	case rest[0] == '"' || rest[0] == '\'':
		// a quoted scalar may span lines; the continuation is read RAW (a `#` inside quotes is content),
		// each joined by the break that ended the line before it
		text, j := rest, i+1
		for closingQuote(text) < 0 && j < len(p.lines) {
			text += p.lines[j-1].brk + p.lines[j].raw
			p.rawUsed[j] = true
			j++
		}
		end := closingQuote(text)
		if end < 0 {
			return nil, i, p.errAt(i, "unterminated quoted scalar")
		}
		// after it, PyYAML's scanner skips spaces only: then a comment, or the line's end
		switch cut, tab := scanLine(text[end+1:]); {
		case tab:
			return nil, i, p.errAt(j-1, "a tab after a quoted scalar (PyYAML refuses it too)")
		case strings.Trim(text[end+1:end+1+cut], " ") != "":
			return nil, i, p.errAt(i, "unexpected text after a quoted scalar")
		}
		s, err := unquote(foldQuoted(text[:end+1]))
		if err != nil {
			return nil, i, p.errAt(i, err.Error())
		}
		return s, j, nil
	case rest[0] == '&' || rest[0] == '*' || rest[0] == '!':
		return nil, i, p.errAt(i, p.propertyRefusal(rest))
	}
	// plain scalar — what PyYAML's scanner refuses in one is refused here too; then gather continuation
	// lines: every line more indented than this mapping — one that starts like structure (`- `, `[`) is
	// text there, as scan_plain reads it — up to a comment, where scan_plain stops
	if err := plainStart(rest, false); err != nil {
		return nil, i, p.errAt(i, err.Error())
	}
	if colonInPlain(rest) {
		return nil, i, p.errAt(i, "mapping values are not allowed here (a `: ` inside a plain scalar)")
	}
	parts, brks := []string{rest}, []string{p.lines[i].brk}
	j := i + 1
	for open := !p.lines[i].comment; open && j < len(p.lines); {
		l := p.lines[j]
		if l.blank() {
			if l.comment {
				break
			}
			// a blank line inside a plain scalar folds to its break — only if more text follows
			k := j + 1
			for k < len(p.lines) && p.lines[k].blank() && !p.lines[k].comment {
				k++
			}
			if k < len(p.lines) && !p.lines[k].blank() && p.lines[k].indent > indent {
				parts, brks = append(parts, ""), append(brks, l.brk)
				j++
				continue
			}
			break
		}
		if l.indent <= indent {
			break
		}
		if colonInPlain(l.text) {
			return nil, j, p.errAt(j, "mapping values are not allowed here (a `: ` inside a plain scalar)")
		}
		parts, brks = append(parts, l.text), append(brks, l.brk)
		j++
		open = !l.comment
	}
	v, err := plainValue(fold(parts, brks, make([]bool, len(parts))))
	if err != nil {
		return nil, i, p.errAt(i, err.Error())
	}
	return v, j, nil
}

// scalarNode is a bare scalar standing as a whole node (a document that is one string, a sequence
// item, a value on the lines below its key), inside a collection indented `parent`.
func (p *parser) scalarNode(i, parent int) (any, int, error) {
	l := p.lines[i]
	if l.text[0] == '&' || l.text[0] == '*' || l.text[0] == '!' {
		return nil, i, p.errAt(i, p.propertyRefusal(l.text))
	}
	// the mapping-value parser does exactly the right thing: its lines are measured from the parent's
	return p.value(i, parent, l.text)
}

// blockScalar parses `|` / `>` with an optional chomping indicator and explicit indentation.
func (p *parser) blockScalar(i, indent int, header string) (any, int, error) {
	literal := header[0] == '|'
	// the header is the end of the line's text (every caller passes that), read with what the text
	// leaves out — the comment, the trailing blanks — as PyYAML's scanner reads the rest of the line
	l := p.lines[i]
	chomp, explicit, err := blockHeader(l.raw[l.indent+len(l.text)-len(header)+1:])
	if err != nil {
		return nil, i, p.errAt(i, err.Error())
	}
	// The block's indentation (scan_block_scalar): the parent's and the explicit indicator's, or else
	// that of its first line with more than spaces on it, the deepest of the blank lines before that
	// counting too — so a first line less indented than one of them ends the block before it.
	j := i + 1
	blockIndent := max(indent+1, 1)
	if explicit > 0 {
		blockIndent += explicit - 1
	} else {
		for k := j; k < len(p.lines); k++ {
			spaces := leadingSpaces(p.lines[k].raw)
			blockIndent = max(blockIndent, spaces)
			if spaces < len(p.lines[k].raw) {
				break
			}
		}
	}
	// its content: every line indented that far, read raw to its end (spaces and tabs are text), and
	// the blank lines among them, each with its break; the first line indented less ends it
	var body, brks []string
	for ; j < len(p.lines); j++ {
		raw := p.lines[j].raw
		spaces := leadingSpaces(raw)
		if spaces == len(raw) && spaces <= blockIndent {
			raw = "" // a blank line
		} else if spaces < blockIndent {
			break
		} else {
			raw = raw[blockIndent:]
		}
		if kept(p.lines[j].brk) {
			return nil, j, p.errAt(j, "unsupported: U+2028 or U+2029 inside a block scalar")
		}
		p.rawUsed[j] = true
		body, brks = append(body, raw), append(brks, p.lines[j].brk)
	}
	// trailing blank lines are the chomping's business, with the break that ends the text — none where
	// the source ends without one, as PyYAML adds none there
	var trailing []string
	for len(body) > 0 && body[len(body)-1] == "" {
		trailing = append([]string{brks[len(brks)-1]}, trailing...)
		body, brks = body[:len(body)-1], brks[:len(brks)-1]
	}
	end := ""
	if len(brks) > 0 {
		end = brks[len(brks)-1]
	}
	var text string
	if literal {
		text = strings.Join(body, "\n")
	} else {
		text = foldBlock(body)
	}
	switch chomp {
	case "clip":
		text += end
	case "keep":
		text += end + strings.Join(trailing, "")
	}
	return text, j, nil
}

func leadingSpaces(s string) int { return len(s) - len(strings.TrimLeft(s, " ")) }

// blockHeader reads what follows a block scalar's `|` or `>` on its line as PyYAML's scanner does
// (scan_block_scalar_indicators, then scan_block_scalar_ignored_line): at most one chomping indicator
// and one indentation digit 1-9, in either order; then a space or the line's end; then spaces and a
// comment only. PyYAML refuses anything else, and so does this.
func blockHeader(s string) (chomp string, explicit int, err error) {
	chomp = "clip"
	chomping := func() bool {
		if s == "" || s[0] != '+' && s[0] != '-' {
			return false
		}
		chomp, s = map[byte]string{'+': "keep", '-': "strip"}[s[0]], s[1:]
		return true
	}
	indentation := func() (bool, error) {
		if s == "" || s[0] < '0' || s[0] > '9' {
			return false, nil
		}
		if s[0] == '0' {
			return false, errors.New("a block scalar's indentation indicator of 0 (PyYAML refuses it too: 1-9)")
		}
		explicit, s = int(s[0]-'0'), s[1:]
		return true, nil
	}
	if chomping() {
		_, err = indentation()
	} else if digit, e := indentation(); e != nil {
		err = e
	} else if digit {
		chomping()
	}
	if err != nil {
		return "", 0, err
	}
	if r, _ := utf8.DecodeRuneInString(s); s != "" && r != ' ' {
		return "", 0, fmt.Errorf("%q after a block scalar's indicators (PyYAML refuses it too)", r)
	}
	if s = strings.TrimLeft(s, " "); s != "" && s[0] != '#' {
		r, _ := utf8.DecodeRuneInString(s)
		return "", 0, fmt.Errorf("%q where a block scalar's header ends (PyYAML refuses it too: a comment or the line's end)", r)
	}
	return chomp, explicit, nil
}

// foldBlock joins folded-scalar lines as PyYAML's scan_block_scalar does: the break after a line is
// kept unless that line and the next both start with text (not a space or a tab) — then it folds to a
// space, or to nothing where blank lines lie between them; and each blank line is a newline of its own,
// the ones before the first line too.
func foldBlock(body []string) string {
	var b strings.Builder
	indented := func(s string) bool { return strings.HasPrefix(s, " ") || strings.HasPrefix(s, "\t") }
	blanks, prev := 0, ""
	for _, s := range body {
		if s == "" {
			blanks++
			continue
		}
		if prev != "" { // a line before it: the break between the two
			switch {
			case indented(prev) || indented(s):
				b.WriteByte('\n')
			case blanks == 0:
				b.WriteByte(' ')
			}
		}
		b.WriteString(strings.Repeat("\n", blanks))
		b.WriteString(s)
		prev, blanks = s, 0
	}
	return b.String()
}

// foldQuoted turns a quoted scalar that spans lines into the single-line token unquote() reads, with
// PyYAML's flow folding (`fold`, measured 2026-10-10): leading indentation and trailing blanks of each
// line are dropped; in double quotes a `\` at the end of a line is an escaped break — the two lines join
// with nothing between them and the text before the backslash keeps its spaces.
func foldQuoted(tok string) string {
	var lines, brks []string
	for rest := tok; ; {
		i := strings.IndexAny(rest, "\n"+ls+ps)
		if i < 0 {
			lines, brks = append(lines, rest), append(brks, "")
			break
		}
		r, size := utf8.DecodeRuneInString(rest[i:])
		lines, brks, rest = append(lines, rest[:i]), append(brks, string(r)), rest[i+size:]
	}
	if len(lines) == 1 {
		return tok
	}
	esc := make([]bool, len(lines))
	for k, s := range lines {
		if k > 0 {
			s = strings.TrimLeft(s, " \t")
		}
		n := 0 // the backslashes that end the line: an odd count escapes its break
		for n < len(s) && s[len(s)-1-n] == '\\' {
			n++
		}
		switch last := k == len(lines)-1; {
		case !last && tok[0] == '"' && n%2 == 1:
			esc[k], s = true, s[:len(s)-1]
		case !last:
			s = strings.TrimRight(s, " \t")
		}
		lines[k] = s
	}
	return fold(lines, brks, esc)
}

// ── flow collections ──────────────────────────────────────────────────────────────────────────────

// flow parses `[…]` or `{…}` starting on line i, continuing onto following lines until it balances.
func (p *parser) flow(i int, first string) (any, int, error) {
	text := first
	j := i + 1
	for ; j < len(p.lines); j++ {
		balanced, quoted := flowBalanced(text)
		if balanced {
			break
		}
		if quoted { // its lines would be folded as a quoted scalar folds them, which joining them is not
			return nil, i, p.errAt(j-1, "unsupported: a quoted scalar spanning lines inside a flow collection")
		}
		if kept(p.lines[j-1].brk) { // a scalar spanning it would keep the break, not a space
			return nil, i, p.errAt(j-1, "unsupported: U+2028 or U+2029 inside a flow collection")
		}
		text += " " + strings.TrimSpace(p.lines[j].text)
	}
	if balanced, _ := flowBalanced(text); !balanced {
		return nil, i, p.errAt(i, "unbalanced flow collection")
	}
	fp := &flowParser{s: text, doc: p}
	v, err := fp.value()
	if err != nil {
		return nil, i, p.errAt(i, err.Error())
	}
	fp.skipSpace()
	if fp.pos != len(fp.s) && fp.s[fp.pos] != '#' { // a `#` straight after the collection starts a comment
		return nil, i, p.errAt(i, "unexpected text after a flow collection")
	}
	return v, j, nil
}

// flowBalanced reports whether a flow collection's text closes every collection it opens and every
// quoted scalar — and where it does not, whether it stops inside a quoted scalar.
func flowBalanced(s string) (balanced, quoted bool) {
	l := lineScan{s: s}
	for i := 0; i < len(s); {
		_, _, i = l.next(i)
	}
	quoted = l.single || l.double
	return l.depth == 0 && !quoted, quoted
}

type flowParser struct {
	s   string
	pos int
	doc *parser // the document around it: the anchors above the collection
}

func (f *flowParser) skipSpace() {
	for f.pos < len(f.s) && (f.s[f.pos] == ' ' || f.s[f.pos] == '\t') {
		f.pos++
	}
}

func (f *flowParser) value() (any, error) {
	f.skipSpace()
	if f.pos >= len(f.s) {
		return nil, errors.New("unexpected end of flow collection")
	}
	switch f.s[f.pos] {
	case '[':
		f.pos++
		out := []any{}
		for {
			f.skipSpace()
			if f.pos < len(f.s) && f.s[f.pos] == ']' {
				f.pos++
				return out, nil
			}
			v, err := f.value()
			if err != nil {
				return nil, err
			}
			// `[a: b]` — a single-pair mapping inside a sequence — is legal YAML; refuse it loudly
			f.skipSpace()
			if f.pos < len(f.s) && f.s[f.pos] == ':' {
				return nil, errors.New("unsupported: a `key: value` pair directly inside a flow sequence")
			}
			out = append(out, v)
			f.skipSpace()
			if f.pos < len(f.s) && f.s[f.pos] == ',' {
				f.pos++
				continue
			}
			if f.pos < len(f.s) && f.s[f.pos] == ']' {
				f.pos++
				return out, nil
			}
			return nil, errors.New("expected `,` or `]` in a flow sequence")
		}
	case '{':
		f.pos++
		m, ids := NewMap(), map[string]string{}
		for {
			f.skipSpace()
			if f.pos < len(f.s) && f.s[f.pos] == '}' {
				f.pos++
				return m, nil
			}
			kv, err := f.scalarToken(true)
			if err != nil {
				return nil, err
			}
			if kv == "<<" {
				return nil, errors.New("unsupported: merge key `<<`")
			}
			k, id, err := keyString(kv)
			if err == nil {
				err = oneKey(ids, id, k)
			}
			if err != nil {
				return nil, err
			}
			f.skipSpace()
			var v any
			if f.pos < len(f.s) && f.s[f.pos] == ':' {
				f.pos++
				f.skipSpace()
				if f.pos < len(f.s) && (f.s[f.pos] == ',' || f.s[f.pos] == '}') {
					v = nil
				} else {
					v, err = f.value()
					if err != nil {
						return nil, err
					}
				}
			}
			m.Set(k, v)
			m.keyed(k, kv)
			f.skipSpace()
			if f.pos < len(f.s) && f.s[f.pos] == ',' {
				f.pos++
				continue
			}
			if f.pos < len(f.s) && f.s[f.pos] == '}' {
				f.pos++
				return m, nil
			}
			return nil, errors.New("expected `,` or `}` in a flow mapping")
		}
	}
	tok, err := f.scalarToken(false)
	if err != nil {
		return nil, err
	}
	return plainValue(tok)
}

// scalarToken reads one scalar in flow context: quoted (returned with its quotes, for scalar() to
// resolve) or plain, which ends at `,` `]` `}` or a `: `/`:` before a separator.
func (f *flowParser) scalarToken(asKey bool) (string, error) {
	f.skipSpace()
	if f.pos >= len(f.s) {
		return "", errors.New("unexpected end of flow collection")
	}
	if c := f.s[f.pos]; c == '"' || c == '\'' {
		end := closingQuote(f.s[f.pos:])
		if end < 0 {
			return "", errors.New("unterminated quoted scalar in a flow collection")
		}
		tok := f.s[f.pos : f.pos+end+1]
		f.pos += end + 1
		return tok, nil
	}
	start := f.pos
	if c := f.s[f.pos]; c == '&' || c == '*' || c == '!' { // a node property — on a key as on a value
		return "", errors.New(f.doc.propertyRefusal(f.s[f.pos:]))
	}
	if err := plainStart(f.s[f.pos:], true); err != nil {
		return "", err
	}
	for f.pos < len(f.s) {
		c := f.s[f.pos]
		if c == ',' || c == ']' || c == '}' {
			break
		}
		if c == ':' && (f.pos+1 == len(f.s) || f.s[f.pos+1] == ' ' || f.s[f.pos+1] == ',' || f.s[f.pos+1] == ']' || f.s[f.pos+1] == '}') {
			break
		}
		if c == '[' || c == '{' || c == '?' { // PyYAML ends a flow plain scalar at each; what follows is no scalar
			return "", errors.New("unexpected `" + string(c) + "` inside a plain flow scalar")
		}
		f.pos++
	}
	return strings.TrimSpace(f.s[start:f.pos]), nil
}

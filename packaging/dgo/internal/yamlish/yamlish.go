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
//
// Values: *Map (insertion-ordered — a compose file's key order is meaning to a reader and to
// safe_dump(sort_keys=False)), []any, string, int64, float64, bool, nil.
package yamlish

import (
	"errors"
	"fmt"
	"strings"
)

// Map is an insertion-ordered string-keyed mapping. A non-string YAML key (80:, true:) is kept under
// its canonical JSON spelling, as json.dumps would write it.
type Map struct {
	keys []string
	vals map[string]any
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
	// skip blank/comment lines before the body; allow one `---`
	i := 0
	for i < len(p.lines) && p.lines[i].blank() {
		i++
	}
	if i < len(p.lines) && p.lines[i].indent == 0 && (p.lines[i].text == "---" || strings.HasPrefix(p.lines[i].text, "--- ")) {
		if strings.HasPrefix(p.lines[i].text, "--- ") {
			return nil, p.errAt(i, "unsupported: content on the `---` line")
		}
		i++
	}
	for j := i; j < len(p.lines); j++ {
		t := p.lines[j].text
		if p.lines[j].indent == 0 && (t == "---" || t == "...") {
			return nil, p.errAt(j, "unsupported: more than one document")
		}
		if strings.HasPrefix(t, "%") && p.lines[j].indent == 0 {
			return nil, p.errAt(j, "unsupported: YAML directive")
		}
	}
	for i < len(p.lines) && p.lines[i].blank() {
		i++
	}
	if i >= len(p.lines) {
		return nil, nil // an empty document is None, as safe_load answers
	}
	v, next, err := p.node(i, p.lines[i].indent)
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

// line is one physical line: its indentation, its text with any trailing comment removed, and the
// raw text (block scalars read raw: `#` is content there).
type line struct {
	indent int
	text   string
	raw    string
	n      int // 1-based, for errors
}

func (l line) blank() bool { return l.text == "" }

type parser struct {
	lines []line
}

func (p *parser) errAt(i int, msg string) error {
	if i >= 0 && i < len(p.lines) {
		return fmt.Errorf("yaml: line %d: %s", p.lines[i].n, msg)
	}
	return fmt.Errorf("yaml: %s", msg)
}

// split cuts the source into lines, measures indentation and strips comments outside quotes.
func (p *parser) split(src string) error {
	src = strings.TrimPrefix(src, string(rune(0xFEFF)))
	src = strings.ReplaceAll(src, "\r\n", "\n")
	rows := strings.Split(src, "\n")
	if len(rows) > 1 && rows[len(rows)-1] == "" {
		rows = rows[:len(rows)-1] // the newline that ends the file is not an extra blank line
	}
	for n, raw := range rows {
		ind := 0
		for ind < len(raw) && raw[ind] == ' ' {
			ind++
		}
		if ind < len(raw) && raw[ind] == '\t' {
			return fmt.Errorf("yaml: line %d: a tab in indentation (PyYAML refuses it too)", n+1)
		}
		text := strings.TrimRight(stripComment(raw[ind:]), " \t")
		if text == "" {
			ind = 0
		}
		p.lines = append(p.lines, line{indent: ind, text: text, raw: raw, n: n + 1})
	}
	return nil
}

// stripComment removes ` # …` (a hash at the start or after whitespace) outside quotes. A hash glued
// to text (`a#b`, a colour, an anchor in a URL) is content, as in PyYAML.
func stripComment(s string) string {
	inS, inD := false, false
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case inD:
			if c == '\\' {
				i++
			} else if c == '"' {
				inD = false
			}
		case inS:
			if c == '\'' {
				if i+1 < len(s) && s[i+1] == '\'' {
					i++
				} else {
					inS = false
				}
			}
		case c == '"':
			inD = true
		case c == '\'':
			// a quote opens a scalar only at the start of a token
			if i == 0 || s[i-1] == ' ' || s[i-1] == '[' || s[i-1] == '{' || s[i-1] == ',' || s[i-1] == ':' {
				inS = true
			}
		case c == '#':
			if i == 0 || s[i-1] == ' ' || s[i-1] == '\t' {
				return s[:i]
			}
		}
	}
	return s
}

// ── block structure ───────────────────────────────────────────────────────────────────────────────

// node parses the block node that starts at line i with the given indentation.
func (p *parser) node(i, indent int) (any, int, error) {
	l := p.lines[i]
	if l.indent != indent {
		return nil, i, p.errAt(i, fmt.Sprintf("expected indentation %d, found %d", indent, l.indent))
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
	return p.scalarNode(i, indent)
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
		if rest == "" {
			// the item is a block on the following, more-indented lines — or null
			j := i + 1
			for j < len(p.lines) && p.lines[j].blank() {
				j++
			}
			if j < len(p.lines) && p.lines[j].indent > indent {
				v, next, err := p.node(j, p.lines[j].indent)
				if err != nil {
					return nil, i, err
				}
				out = append(out, v)
				i = next
				continue
			}
			out = append(out, nil)
			i++
			continue
		}
		// inline content after `- `: a compact mapping/sequence or a scalar. Re-base it at the column
		// where the content starts and parse the item as its own block.
		col := indent + (len(l.text) - len(rest))
		v, next, err := p.inlineItem(i, col, rest)
		if err != nil {
			return nil, i, err
		}
		out = append(out, v)
		i = next
	}
	return out, i, nil
}

// inlineItem parses content that begins mid-line (after `- `) at column col, together with the more-
// indented lines that follow it, by substituting a synthetic first line.
func (p *parser) inlineItem(i, col int, rest string) (any, int, error) {
	saved := p.lines[i]
	p.lines[i] = line{indent: col, text: rest, raw: strings.Repeat(" ", col) + rest, n: saved.n}
	defer func() { p.lines[i] = saved }()
	if rest == "-" || strings.HasPrefix(rest, "- ") {
		return p.sequence(i, col)
	}
	if _, _, ok := splitKey(rest); ok {
		return p.mapping(i, col)
	}
	return p.scalarNode(i, col)
}

// mapping parses `key: value` entries at this indentation.
func (p *parser) mapping(i, indent int) (any, int, error) {
	m := NewMap()
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
		key, rest, ok := splitKey(l.text)
		if !ok {
			return nil, i, p.errAt(i, "expected `key: value`")
		}
		if strings.HasPrefix(l.text, "? ") {
			return nil, i, p.errAt(i, "unsupported: complex key")
		}
		if key == "<<" {
			return nil, i, p.errAt(i, "unsupported: merge key `<<`")
		}
		k, err := keyString(key)
		if err != nil {
			return nil, i, p.errAt(i, err.Error())
		}
		var v any
		var next int
		if rest == "" {
			// the value is a block on the following, more-indented lines; a sequence may sit at the
			// SAME indentation as the key (PyYAML's indentless sequence); otherwise null
			j := i + 1
			for j < len(p.lines) && p.lines[j].blank() {
				j++
			}
			switch {
			case j < len(p.lines) && p.lines[j].indent > indent:
				v, next, err = p.node(j, p.lines[j].indent)
			case j < len(p.lines) && p.lines[j].indent == indent && (p.lines[j].text == "-" || strings.HasPrefix(p.lines[j].text, "- ")):
				v, next, err = p.sequence(j, indent)
			default:
				v, next, err = nil, j, nil
			}
			if err != nil {
				return nil, i, err
			}
		} else {
			v, next, err = p.value(i, indent, rest)
			if err != nil {
				return nil, i, err
			}
		}
		m.Set(k, v)
		i = next
	}
	return m, i, nil
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

// keyString resolves a key the way PyYAML + json.dumps would spell it.
func keyString(key string) (string, error) {
	v, err := scalar(strings.TrimSpace(key))
	if err != nil {
		return "", err
	}
	switch t := v.(type) {
	case string:
		return t, nil
	case nil:
		return "null", nil
	case bool:
		if t {
			return "true", nil
		}
		return "false", nil
	default:
		return CanonicalJSON(v), nil
	}
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
		// a quoted scalar may span lines; the continuation is read RAW (a `#` inside quotes is content)
		text, j := rest, i+1
		for closingQuote(text) < 0 && j < len(p.lines) {
			text += "\n" + p.lines[j].raw
			j++
		}
		end := closingQuote(text)
		if end < 0 {
			return nil, i, p.errAt(i, "unterminated quoted scalar")
		}
		if strings.TrimSpace(stripComment(text[end+1:])) != "" {
			return nil, i, p.errAt(i, "unexpected text after a quoted scalar")
		}
		s, err := unquote(foldQuoted(text[:end+1]))
		if err != nil {
			return nil, i, p.errAt(i, err.Error())
		}
		return s, j, nil
	case rest[0] == '&' || rest[0] == '*' || rest[0] == '!':
		return nil, i, p.errAt(i, "unsupported: anchors, aliases and tags")
	}
	// plain scalar — gather continuation lines (more indented than this mapping, not structure)
	parts := []string{rest}
	j := i + 1
	for j < len(p.lines) {
		l := p.lines[j]
		if l.blank() {
			// a blank line inside a plain scalar folds to a newline — only if more text follows
			k := j + 1
			for k < len(p.lines) && p.lines[k].blank() {
				k++
			}
			if k < len(p.lines) && p.lines[k].indent > indent && !looksStructural(p.lines[k].text) {
				parts = append(parts, "")
				j++
				continue
			}
			break
		}
		if l.indent <= indent || looksStructural(l.text) {
			break
		}
		if _, _, isKey := splitKey(l.text); isKey {
			return nil, j, p.errAt(j, "mapping values are not allowed here (a `: ` inside a plain scalar)")
		}
		parts = append(parts, l.text)
		j++
	}
	v, err := scalar(foldPlain(parts))
	if err != nil {
		return nil, i, p.errAt(i, err.Error())
	}
	return v, j, nil
}

func looksStructural(text string) bool {
	return text == "-" || strings.HasPrefix(text, "- ") || strings.HasPrefix(text, "[") || strings.HasPrefix(text, "{")
}

// foldPlain joins plain-scalar lines: a single space between lines, a blank line becomes a newline.
func foldPlain(parts []string) string {
	var b strings.Builder
	pendingNL := 0
	for i, s := range parts {
		if s == "" {
			pendingNL++
			continue
		}
		if i > 0 {
			if pendingNL > 0 {
				b.WriteString(strings.Repeat("\n", pendingNL))
			} else {
				b.WriteByte(' ')
			}
		}
		pendingNL = 0
		b.WriteString(strings.TrimSpace(s))
	}
	return b.String()
}

// scalarNode is a bare scalar standing as a whole node (a document that is one string, a sequence
// item), at the given indentation.
func (p *parser) scalarNode(i, indent int) (any, int, error) {
	l := p.lines[i]
	if l.text[0] == '&' || l.text[0] == '*' || l.text[0] == '!' {
		return nil, i, p.errAt(i, "unsupported: anchors, aliases and tags")
	}
	// the mapping-value parser does exactly the right thing for a value at this indentation when told
	// its parent is one column to the left
	return p.value(i, indent-1, l.text)
}

// blockScalar parses `|` / `>` with an optional chomping indicator and explicit indentation.
func (p *parser) blockScalar(i, indent int, header string) (any, int, error) {
	literal := header[0] == '|'
	chomp := "clip"
	explicit := 0
	for _, c := range header[1:] {
		switch {
		case c == '-':
			chomp = "strip"
		case c == '+':
			chomp = "keep"
		case c >= '1' && c <= '9':
			explicit = int(c - '0')
		case c == ' ':
		default:
			return nil, i, p.errAt(i, "unsupported block scalar header "+header)
		}
	}
	// content: the following lines more indented than the parent (or blank)
	j := i + 1
	var body []string
	contentIndent := -1
	if explicit > 0 {
		contentIndent = indent + explicit
	}
	for j < len(p.lines) {
		raw := p.lines[j].raw
		trimmed := strings.TrimRight(raw, " \t")
		if trimmed == "" {
			body = append(body, "")
			j++
			continue
		}
		ind := 0
		for ind < len(raw) && raw[ind] == ' ' {
			ind++
		}
		if ind <= indent {
			break
		}
		if contentIndent < 0 {
			contentIndent = ind
		}
		if ind < contentIndent {
			break
		}
		body = append(body, raw[contentIndent:])
		j++
	}
	// trailing blank lines are the chomping's business
	trailing := 0
	for len(body) > 0 && body[len(body)-1] == "" {
		body = body[:len(body)-1]
		trailing++
	}
	var text string
	if literal {
		text = strings.Join(body, "\n")
	} else {
		text = foldBlock(body)
	}
	switch chomp {
	case "strip":
	case "clip":
		if text != "" {
			text += "\n"
		}
	case "keep":
		text += "\n" + strings.Repeat("\n", trailing)
	}
	return text, j, nil
}

// foldBlock joins folded-scalar lines as PyYAML does (measured 2026-10-10): the break between two
// text lines is a space; each blank line is a newline and the breaks around it fold away; the break
// before or after a more-indented line is kept — so a more-indented line after a blank line gets both.
func foldBlock(body []string) string {
	var b strings.Builder
	prevMore, blanks, started := false, 0, false
	for _, s := range body {
		if s == "" {
			blanks++
			continue
		}
		more := strings.HasPrefix(s, " ") || strings.HasPrefix(s, "\t")
		if started {
			switch {
			case blanks > 0:
				b.WriteString(strings.Repeat("\n", blanks))
				if more {
					b.WriteByte('\n')
				}
			case more || prevMore:
				b.WriteByte('\n')
			default:
				b.WriteByte(' ')
			}
		}
		b.WriteString(s)
		started, prevMore, blanks = true, more, 0
	}
	return b.String()
}

// foldQuoted turns a quoted scalar that spans lines into the single-line token unquote() reads, with
// PyYAML's flow folding (measured 2026-10-10): leading indentation and trailing blanks of each line
// are dropped; a plain break is one space; each blank line is one newline; in double quotes a `\` at
// the end of a line is an escaped break — the two lines join with nothing between them and the text
// before the backslash keeps its spaces.
func foldQuoted(tok string) string {
	lines := strings.Split(tok, "\n")
	if len(lines) == 1 {
		return tok
	}
	dq := tok[0] == '"'
	escapedBreak := func(s string) bool {
		if !dq {
			return false
		}
		n := 0
		for k := len(s) - 1; k >= 0 && s[k] == '\\'; k-- {
			n++
		}
		return n%2 == 1
	}
	var b strings.Builder
	first := lines[0]
	prevEsc := escapedBreak(first)
	if prevEsc {
		b.WriteString(first[:len(first)-1])
	} else {
		b.WriteString(strings.TrimRight(first, " \t"))
	}
	blanks := 0
	for k := 1; k < len(lines); k++ {
		s := strings.TrimLeft(lines[k], " \t")
		last := k == len(lines)-1
		esc := !last && escapedBreak(s)
		switch {
		case esc:
			s = s[:len(s)-1]
		case !last:
			s = strings.TrimRight(s, " \t")
		}
		if s == "" && !last {
			blanks++
			continue
		}
		switch {
		case blanks > 0:
			b.WriteString(strings.Repeat("\n", blanks))
			blanks = 0
		case prevEsc:
		default:
			b.WriteByte(' ')
		}
		b.WriteString(s)
		prevEsc = esc
	}
	return b.String()
}

// ── flow collections ──────────────────────────────────────────────────────────────────────────────

// flow parses `[…]` or `{…}` starting on line i, continuing onto following lines until it balances.
func (p *parser) flow(i int, first string) (any, int, error) {
	text := first
	j := i + 1
	for !flowBalanced(text) && j < len(p.lines) {
		text += " " + strings.TrimSpace(p.lines[j].text)
		j++
	}
	if !flowBalanced(text) {
		return nil, i, p.errAt(i, "unbalanced flow collection")
	}
	fp := &flowParser{s: text}
	v, err := fp.value()
	if err != nil {
		return nil, i, p.errAt(i, err.Error())
	}
	fp.skipSpace()
	if fp.pos != len(fp.s) {
		return nil, i, p.errAt(i, "unexpected text after a flow collection")
	}
	return v, j, nil
}

func flowBalanced(s string) bool {
	depth := 0
	inS, inD := false, false
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case inD:
			if c == '\\' {
				i++
			} else if c == '"' {
				inD = false
			}
		case inS:
			if c == '\'' {
				inS = false
			}
		case c == '"':
			inD = true
		case c == '\'':
			inS = true
		case c == '[' || c == '{':
			depth++
		case c == ']' || c == '}':
			depth--
		}
	}
	return depth <= 0 && !inS && !inD
}

type flowParser struct {
	s   string
	pos int
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
		m := NewMap()
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
			k, err := keyString(kv)
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
	case '&', '*', '!':
		return nil, errors.New("unsupported: anchors, aliases and tags")
	}
	tok, err := f.scalarToken(false)
	if err != nil {
		return nil, err
	}
	return scalar(tok)
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
	for f.pos < len(f.s) {
		c := f.s[f.pos]
		if c == ',' || c == ']' || c == '}' {
			break
		}
		if c == ':' && (f.pos+1 == len(f.s) || f.s[f.pos+1] == ' ' || f.s[f.pos+1] == ',' || f.s[f.pos+1] == ']' || f.s[f.pos+1] == '}') {
			break
		}
		if c == '[' || c == '{' {
			return "", errors.New("unexpected `" + string(c) + "` inside a plain flow scalar")
		}
		f.pos++
	}
	return strings.TrimSpace(f.s[start:f.pos]), nil
}

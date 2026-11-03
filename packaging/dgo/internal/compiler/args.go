package compiler

import (
	"fmt"
	"io"
	"os"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
)

// ── the command line, read the way reconcile.py's argparse parser reads it ─────────────────────────
//
// A native verb must take what `reconcile.py <verb> …` takes and refuse what it refuses, in the same
// words and with the same exit code: `dgo validate --extra` answering 0 where reconcile.py answers 2
// would be a gate that passes on a typo. So this is main()'s ArgumentParser, ported: its options in
// declaration order, argparse's own steps (_parse_known_args: classify every string, take the
// options and their values left to right, refuse what is left over), its error sentences, and the
// usage and help its HelpFormatter prints, wrapped the way textwrap wraps them. The argparse is the
// one current Pythons carry (measured against 3.12.10): older ones (3.10, 3.11, 3.12.2) word an
// invalid --state with quoted choices, refuse an ambiguous abbreviation before an earlier -h is
// read, and refuse "-hx" where the current one prints the help — three typo paths, nothing else.

// Verbs are the compiler's twenty-one verbs in the order reconcile.py declares them as `verb`'s
// choices — the contract the plan's §6 measured. dgo routes exactly these to the compiler.
// `link-endpoints` (DGO-945) is answered by reconcile.py alone: the map `bbox n8n push` applies.
var Verbs = []string{"plan", "render", "up", "validate", "compose-files", "services", "required-by",
	"compose-services", "blueprints", "generations", "rollback", "apply", "enabled-apps",
	"set-state", "capability-provider", "serve-plan", "remote-get", "remote-set",
	"office-get", "office-set", "link-endpoints"}

// Args is the Namespace main() reads: "", false or nil for an option not given, By's default "user".
type Args struct {
	Capability, App, State, By string
	Create, JSON               bool
	Roots, Exclude             []string // --for (dest `roots`) and --exclude: one entry per use
}

// option is one of main()'s optional arguments as add_argument declares it. An empty metavar is an
// option that takes no value; a nil store is -h/--help, which prints the help instead.
type option struct {
	names   []string
	metavar string
	choices []string
	help    string
	store   func(a *Args, v string)
}

// options are in declaration order: the order argparse tries abbreviations in and lists the options
// in, in the usage line and in the help. The help texts are reconcile.py's, already single-spaced as
// argparse's _split_lines makes them.
var options = []option{
	{names: []string{"-h", "--help"}, help: "show this help message and exit"},
	{names: []string{"--capability"}, metavar: "NAME", help: "capability-provider: the capability name to resolve",
		store: func(a *Args, v string) { a.Capability = v }},
	{names: []string{"--app"}, metavar: "ID", help: "set-state: the app id to write",
		store: func(a *Args, v string) { a.App = v }},
	{names: []string{"--state"}, metavar: "DISPO", choices: dispositions, help: "set-state: enabled | disabled | archived",
		store: func(a *Args, v string) { a.State = v }},
	{names: []string{"--by"}, metavar: "WHO", help: "set-state: provenance recorded with the entry (default: user)",
		store: func(a *Args, v string) { a.By = v }},
	{names: []string{"--create"}, help: "set-state: append the entry if the app has none yet (install path)",
		store: func(a *Args, _ string) { a.Create = true }},
	{names: []string{"--json"}, help: "plan: print one JSON document (apps, remote, plan) instead of the table. " +
		"Diagnostics move to stderr, so stdout is the document and nothing else.",
		store: func(a *Args, _ string) { a.JSON = true }},
	{names: []string{"--for"}, metavar: "APP", help: "services: root the closure at these app id(s) (repeatable or " +
		"comma-separated). Default: every enabled app in platform.state.yaml.",
		store: func(a *Args, v string) { a.Roots = append(a.Roots, v) }},
	{names: []string{"--exclude"}, metavar: "SVC", help: "services: drop these compose services from the output " +
		"(repeatable or comma-separated). Trimming a lane stays possible, but stays VISIBLE.",
		store: func(a *Args, v string) { a.Exclude = append(a.Exclude, v) }},
}

// use is one way to read a command-line string as an option: which one, by what name, and the value
// written into the same string — after "=" (eq), or after "-h" in a bundle of one-letter options. A
// nil opt is an option string this parser does not have: it is left over, and refused at the end.
type use struct {
	opt      *option
	name     string
	explicit string
	inline   bool // a value was written into the string (argparse: explicit_arg is not None)
	eq       bool // …after an "=" (argparse: sep == "=")
}

// parseArgs is ap.parse_args() over [verb] + args. done means argparse answered by itself: the help
// on stdout (exit 0), or a refusal — the usage and one "reconcile.py: error: …" line on stderr
// (exit 2). The verb is the one positional; dgo routes only the twenty choices here, so it always
// is one.
func parseArgs(verb string, args []string, stdout, stderr io.Writer) (*Args, int, bool) {
	argv := append([]string{verb}, args...)
	refuse := func(msg string) (*Args, int, bool) {
		fmt.Fprint(stderr, usage(helpWidth()))
		fmt.Fprintf(stderr, "reconcile.py: error: %s\n", msg)
		return nil, 2, true
	}

	// 1. every string is an option 'O', a value 'A', or the "--" after which all are values '-'
	pattern := make([]byte, len(argv))
	uses := map[int][]use{}
	values := false
	for i, s := range argv {
		switch {
		case values:
			pattern[i] = 'A'
		case s == "--":
			pattern[i], values = '-', true
		default:
			pattern[i] = 'A'
			if ways, isOpt := classify(s); isOpt {
				pattern[i], uses[i] = 'O', ways
			}
		}
	}

	// 2. left to right: the positional where it stands ('(-*A-*)', a "--" beside it absorbed), each
	// option with its value, and every string neither takes left over
	a := &Args{By: "user"}
	var extras []string
	verbTaken := false
	positional := func(start int) int {
		i := start
		for i < len(pattern) && pattern[i] == '-' {
			i++
		}
		if verbTaken || i == len(pattern) || pattern[i] != 'A' {
			return start
		}
		for i++; i < len(pattern) && pattern[i] == '-'; i++ {
		}
		verbTaken = true
		return i
	}
	last := -1
	for i := range uses {
		last = max(last, i)
	}
	start := 0
	for start <= last {
		next := last
		for i := range uses {
			if i >= start && i < next {
				next = i
			}
		}
		if start != next {
			if end := positional(start); end > start {
				start = end
				continue
			}
			extras = append(extras, argv[start:next]...)
			start = next
		}
		ways := uses[start]
		if len(ways) > 1 { // an abbreviation that fits two options, refused where the parser meets it
			names := make([]string, len(ways))
			for i, w := range ways {
				names[i] = w.name
			}
			return refuse(fmt.Sprintf("ambiguous option: %s could match %s", argv[start], strings.Join(names, ", ")))
		}
		u := ways[0]
		if u.opt == nil {
			extras = append(extras, argv[start])
			start++
			continue
		}
		// what this one string sets, in order: "-hh" is -h twice
		type take struct {
			opt   *option
			value string
		}
		var taken []take
		opt, named, explicit, inline, eq := u.opt, u.name, u.explicit, u.inline, u.eq
		stop := start + 1
	read:
		for {
			switch {
			case !inline:
				if opt.metavar == "" {
					taken = append(taken, take{opt, ""})
				} else if stop < len(pattern) && pattern[stop] == 'A' {
					taken = append(taken, take{opt, argv[stop]})
					stop++
				} else {
					return refuse(argName(opt) + ": expected one argument")
				}
				break read
			case opt.metavar != "":
				taken = append(taken, take{opt, explicit})
				break read
			case named[1] == '-' || explicit == "" || eq || explicit[0] == '-':
				return refuse(argName(opt) + ": ignored explicit argument " + pyval.Repr(explicit))
			}
			// a value written into a one-letter option that takes none is more of them ("-hh"); a
			// letter that is no option is left over, with the rest of the string ("-hx": -x)
			taken = append(taken, take{opt, ""})
			r, size := utf8.DecodeRuneInString(explicit)
			more := exactOption("-" + string(r))
			if more == nil {
				extras = append(extras, "-"+explicit)
				break
			}
			opt, named, explicit = more, "-"+string(r), explicit[size:]
			inline, eq = explicit != "", false
			if inline && explicit[0] == '=' {
				explicit, eq = explicit[1:], true
			}
		}
		for _, t := range taken {
			if t.opt.store == nil {
				fmt.Fprint(stdout, help(helpWidth()))
				return nil, 0, true
			}
			if t.opt.choices != nil && !contains(t.opt.choices, t.value) {
				return refuse(fmt.Sprintf("%s: invalid choice: %s (choose from %s)", argName(t.opt),
					pyval.Repr(t.value), strings.Join(t.opt.choices, ", ")))
			}
			t.opt.store(a, t.value)
		}
		start = stop
	}
	extras = append(extras, argv[positional(start):]...)
	if len(extras) > 0 {
		return refuse("unrecognized arguments: " + strings.Join(extras, " "))
	}
	return a, 0, false
}

// classify is _parse_optional: is this string an option, and as which? Every option it may be is
// returned; more than one is an ambiguous abbreviation, which the parser refuses when it reaches it.
func classify(s string) ([]use, bool) {
	if s == "" || s[0] != '-' {
		return nil, false
	}
	if o := exactOption(s); o != nil {
		return []use{{opt: o, name: s}}, true
	}
	if s == "-" {
		return nil, false
	}
	if name, value, ok := strings.Cut(s, "="); ok {
		if o := exactOption(name); o != nil {
			return []use{{opt: o, name: name, explicit: value, inline: true, eq: true}}, true
		}
	}
	if ways := prefixMatches(s); len(ways) > 0 {
		return ways, true
	}
	// what looks like a negative number, or holds a space, was meant as a value
	if negativeNumber(s) || strings.Contains(s, " ") {
		return nil, false
	}
	return []use{{name: s}}, true
}

// prefixMatches is _get_option_tuples: an abbreviation ("--ap" is --app, its value after "="), and
// with one dash also "-hX" — -h with X written into it.
func prefixMatches(s string) []use {
	prefix, value, eq := strings.Cut(s, "=")
	_, size := utf8.DecodeRuneInString(s[1:])
	var out []use
	for i := range options {
		for _, n := range options[i].names {
			switch {
			case s[1] != '-' && n == s[:1+size]:
				out = append(out, use{&options[i], n, s[1+size:], true, false})
			case strings.HasPrefix(n, prefix):
				out = append(out, use{&options[i], n, value, eq, eq})
			}
		}
	}
	return out
}

func exactOption(s string) *option {
	for i := range options {
		for _, n := range options[i].names {
			if n == s {
				return &options[i]
			}
		}
	}
	return nil
}

// negativeNumber is argparse's ^-\d+$|^-\d*\.\d+$ — Python's \d is any decimal digit, and its $ also
// matches before one final newline.
func negativeNumber(s string) bool {
	body, ok := strings.CutPrefix(strings.TrimSuffix(s, "\n"), "-")
	if !ok {
		return false
	}
	whole, frac, dot := strings.Cut(body, ".")
	if !dot {
		return body != "" && decimal(body)
	}
	return decimal(whole) && frac != "" && decimal(frac)
}

func decimal(s string) bool {
	for _, r := range s {
		if !unicode.IsDigit(r) {
			return false
		}
	}
	return true
}

// argName is how an ArgumentError names its option: its strings joined by "/" ("-h/--help").
func argName(o *option) string { return "argument " + strings.Join(o.names, "/") }

// ── the usage and the help, as HelpFormatter lays them out ─────────────────────────────────────────

// helpWidth is the width argparse formats for: shutil.get_terminal_size().columns - 2, the columns
// being $COLUMNS when int() reads a positive number in it (pyval.Int), else 80. Python asks a terminal
// on stdout before falling back to 80 and dgo does not (the standard library has no portable call for
// it), so only an interactive terminal of another width with $COLUMNS unset sees the text wrapped
// elsewhere; every reader of the bytes — a pipe, a file, a gate — gets argparse's. A width too large
// for an int saturates — every width past the longest line wraps the same, which is nothing.
func helpWidth() int {
	c, ok := pyval.Int(os.Getenv("COLUMNS"))
	switch {
	case !ok || strings.HasPrefix(c.Text, "-") || c.Text == "0":
		return 80 - 2
	case !c.Fits || c.N > 1<<40:
		return 1<<40 - 2
	}
	return int(c.N) - 2
}

// usage is format_usage(): "usage: reconcile.py [-h] [--capability NAME] … {plan,…}", broken into
// lines as _format_usage breaks it when it is wider than w — the options after the program's name,
// the verb's choices on a line of their own.
func usage(w int) string {
	const prog, prefix = "reconcile.py", "usage: "
	opts := make([]string, len(options))
	for i, o := range options {
		opts[i] = "[" + strings.TrimSpace(o.names[0]+" "+o.metavar) + "]"
	}
	verb := []string{"{" + strings.Join(Verbs, ",") + "}"}
	if full := prog + " " + strings.Join(append(opts, verb...), " "); len(prefix)+len(full) <= w {
		return prefix + full + "\n"
	}
	lines := func(parts []string, indent string, first bool) []string {
		var out, line []string
		n := len(indent) - 1
		if first {
			n = len(prefix) - 1
		}
		for _, p := range parts {
			if n+1+len(p) > w && len(line) > 0 {
				out = append(out, indent+strings.Join(line, " "))
				line, n = nil, len(indent)-1
			}
			line = append(line, p)
			n += len(p) + 1
		}
		out = append(out, indent+strings.Join(line, " "))
		if first {
			out[0] = out[0][len(indent):]
		}
		return out
	}
	var out []string
	if float64(len(prefix)+len(prog)) <= 0.75*float64(w) {
		indent := strings.Repeat(" ", len(prefix)+len(prog)+1)
		out = append(lines(append([]string{prog}, opts...), indent, true), lines(verb, indent, false)...)
	} else { // a narrow screen: the program's name on its own line
		indent := strings.Repeat(" ", len(prefix))
		out = lines(append(append([]string(nil), opts...), verb...), indent, false)
		if len(out) > 1 {
			out = append(lines(opts, indent, false), lines(verb, indent, false)...)
		}
		out = append([]string{prog}, out...)
	}
	return prefix + strings.Join(out, "\n") + "\n"
}

// help is format_help(): the usage, the positional, then each option with its help text in a column
// at help_position — min(the longest invocation + 4, 24, w - 20 but at least 4) — wrapped to what is
// left of the width (11 at least); an invocation too wide for its column puts the help on the next
// line.
func help(w int) string {
	verb := "{" + strings.Join(Verbs, ",") + "}"
	longest := len(verb)
	for _, o := range options {
		longest = max(longest, len(invocation(o)))
	}
	col := min(longest+4, min(24, max(w-20, 4)))
	var b strings.Builder
	b.WriteString(usage(w))
	b.WriteString("\npositional arguments:\n  " + verb + "\n\noptions:\n")
	for _, o := range options {
		inv, indent := invocation(o), 0
		if len(inv) <= col-4 {
			b.WriteString("  " + inv + strings.Repeat(" ", col-4-len(inv)) + "  ")
		} else {
			b.WriteString("  " + inv + "\n")
			indent = col
		}
		for i, line := range wrap(o.help, max(w-col, 11)) {
			if i > 0 {
				indent = col
			}
			b.WriteString(strings.Repeat(" ", indent) + line + "\n")
		}
	}
	return b.String()
}

// invocation is how the help names an option: "-h, --help", "--capability NAME".
func invocation(o option) string {
	parts := make([]string, len(o.names))
	for i, n := range o.names {
		parts[i] = strings.TrimSpace(n + " " + o.metavar)
	}
	return strings.Join(parts, ", ")
}

// wrap is textwrap.wrap(text, width) with its defaults, for ASCII text (the help texts are) and a
// width above 0 (textwrap refuses less): the chunks filled greedily, a chunk wider than a whole line
// broken at the width — after its last hyphen when one is in reach — and no line starting (but the
// first) or ending with a space.
func wrap(text string, width int) []string {
	chunks := textChunks(text)
	var lines []string
	for len(chunks) > 0 {
		if len(lines) > 0 && strings.TrimSpace(chunks[0]) == "" {
			chunks = chunks[1:]
		}
		var line []string
		n := 0
		for len(chunks) > 0 && n+len(chunks[0]) <= width {
			line, n, chunks = append(line, chunks[0]), n+len(chunks[0]), chunks[1:]
		}
		if len(chunks) > 0 && len(chunks[0]) > width {
			c, end := chunks[0], width-n
			if h := strings.LastIndexByte(c[:end], '-'); h > 0 && strings.Trim(c[:h], "-") != "" {
				end = h + 1
			}
			line, chunks[0] = append(line, c[:end]), c[end:]
		}
		if len(line) > 0 && strings.TrimSpace(line[len(line)-1]) == "" {
			line = line[:len(line)-1]
		}
		if len(line) > 0 {
			lines = append(lines, strings.Join(line, ""))
		}
	}
	return lines
}

// textChunks is TextWrapper.wordsep_re.split (break_on_hyphens) for ASCII text: runs of whitespace,
// an em-dash ("--" between a word and a word character), and words — each cut at the first place
// the regex lets it end: after a hyphen with two letters (or letter-hyphen-letter) before it and a
// letter, an optional hyphen and a letter after it; before an em-dash; or at the word's end.
func textChunks(s string) []string {
	at := func(i int) byte {
		if i < 0 || i >= len(s) {
			return 0
		}
		return s[i]
	}
	letter := func(c byte) bool { return c == '_' || 'a' <= c && c <= 'z' || 'A' <= c && c <= 'Z' }
	word := func(c byte) bool { return letter(c) || '0' <= c && c <= '9' }
	punct := func(c byte) bool { return word(c) || c != 0 && strings.IndexByte(`!"'&.,?`, c) >= 0 }
	space := func(c byte) bool { return c != 0 && strings.IndexByte("\t\n\v\f\r ", c) >= 0 }
	emDash := func(j int) int { // the end of an em-dash starting at j, or -1
		k := j
		for k < len(s) && s[k] == '-' {
			k++
		}
		if k-j >= 2 && word(at(k)) {
			return k
		}
		return -1
	}
	var out []string
	for i := 0; i < len(s); {
		j := i + 1
		switch {
		case space(s[i]):
			for space(at(j)) {
				j++
			}
		case punct(at(i-1)) && emDash(i) > 0:
			j = emDash(i)
		default:
			for ; ; j++ {
				if at(j) == '-' && (letter(at(j-2)) && letter(at(j-1)) || letter(at(j-3)) && at(j-2) == '-' && letter(at(j-1))) &&
					letter(at(j+1)) && (letter(at(j+2)) || at(j+2) == '-' && letter(at(j+3))) {
					j++
					break
				}
				if j == len(s) || space(s[j]) || punct(at(j-1)) && emDash(j) > 0 {
					break
				}
			}
		}
		out = append(out, s[i:j])
		i = j
	}
	return out
}

package compiler

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"syscall"
	"unicode"
	"unicode/utf8"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/pyval"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// ── language (the office's ONE language variable, DGO-971) ─────────────────────────────────────────
//
// reconcile.py's LANGUAGES, state_language(), language_errors() and locale_doc(): `language:` at the top of
// platform.state.yaml, compiled into .generated/registry/locale.json (ai/context/platform-language.md).
// The same file, byte for byte, and the same refusal, word for word.

// language is one entry of LANGUAGES.
type language struct{ code, label, labelEn, dir string }

// languages mirrors LANGUAGES, in its order (the order a switcher lists them in).
var languages = []language{
	{"he", "עברית", "Hebrew", "rtl"},
	{"en", "English", "English", "ltr"},
}

// defaultLanguage mirrors DEFAULT_LANGUAGE.
const defaultLanguage = "he"

func languageOf(code string) (language, bool) {
	for _, l := range languages {
		if l.code == code {
			return l, true
		}
	}
	return language{}, false
}

// declaredLanguage is `str(state.get("language") or "").strip().lower()`.
func declaredLanguage(doc *yamlish.Map) string {
	v := get(doc, "language")
	if !truthy(v) {
		return ""
	}
	return pyLower(pyval.Strip(pyval.Str(v)))
}

// stateLanguage is state_language(state): the declared code when a dictionary has it, else the default.
func stateLanguage(doc *yamlish.Map) string {
	if code := declaredLanguage(doc); code != "" {
		if _, ok := languageOf(code); ok {
			return code
		}
	}
	return defaultLanguage
}

// languageErrors is language_errors(state): the one line for a code no dictionary has.
func languageErrors(doc *yamlish.Map) []string {
	raw := declaredLanguage(doc)
	if raw == "" {
		return nil
	}
	if _, ok := languageOf(raw); ok {
		return nil
	}
	return []string{fmt.Sprintf("platform.state.yaml: language '%s' is not a language this platform has a "+
		"dictionary for (expected one of %s)", raw, strings.Join(languageCodes(), ", "))}
}

// localeDoc is locale_doc(state): active, default, dir, and every language this platform has.
func localeDoc(doc *yamlish.Map) *yamlish.Map {
	code := stateLanguage(doc)
	l, _ := languageOf(code)
	available := make([]any, 0, len(languages))
	for _, x := range languages {
		available = append(available, ordered("code", x.code, "label", x.label, "label_en", x.labelEn, "dir", x.dir))
	}
	return ordered("active", code, "default", code, "dir", l.dir, "available", available)
}

// LangCmd is `lang [--lang CODE] [--by WHO]` (reconcile.py main(), DGO-971; native since DGO-1238): without
// --lang, the office's language and every language it may have; with it, set_language() — THE writer of the
// top-level `language:` — under the state's lock, the same lines and refusals.
func LangCmd(repo string, args []string, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("lang", args, stdout, stderr)
	if done {
		return code
	}
	if !a.LangGiven { // OMITTED says the language; an EMPTY code is a code, and is refused below
		st, err := LoadState(repo, stdout, stderr)
		if err != nil {
			return failed(err, stderr)
		}
		active, note := stateLanguage(st.Doc), ""
		if declaredLanguage(st.Doc) == "" {
			note = "  (not declared: the default)"
		}
		fmt.Fprintf(stdout, "language: %s%s\n", active, note)
		for _, l := range languages {
			mark := ""
			if l.code == active {
				mark = "   <- active"
			}
			fmt.Fprintf(stdout, "  %s  %s / %s  %s%s\n", l.code, l.labelEn, l.label, l.dir, mark)
		}
		return 0
	}
	lang := lowerArg(pyval.Strip(a.Lang)) // set_language()'s `str(code).strip().lower()`, once
	if _, ok := languageOf(lang); !ok {   // set_language() asks this before it reads the file
		fmt.Fprintf(stderr, "  ERROR unknown language %s; expected one of %s\n", pyval.Repr(lang), strings.Join(languageCodes(), ", "))
		return 1
	}
	lock := lockState(repo)
	defer lock.release()
	text, err := readText(statePath(repo))
	var d *dies
	if errors.As(err, &d) && d.codec != "" {
		fmt.Fprintln(stderr, "  ERROR "+d.codec) // a UnicodeDecodeError is a ValueError: main() says it
		return 1
	}
	if err != nil {
		fmt.Fprintln(stderr, "  ERROR "+osErrorText(repo, err)) // an OSError: main() says str(e)
		return 1
	}
	next, changed, err := setLanguage(text, lang, a.By)
	if isGap(err) {
		return failed(err, stderr) // the reader's gap, said as every verb says it — never «fix it by hand»
	}
	if err != nil {
		fmt.Fprintf(stderr, "  ERROR %v\n", err)
		return 1
	}
	if !changed {
		fmt.Fprintf(stdout, "language is already %s — nothing to change\n", lang)
		return 0
	}
	// `--by` is said after the write, and reconcile.py, holding a byte that is not UTF-8 as \udcHH, writes the file
	// and only then fails printing it: refused here, before anything changes
	if !utf8.ValidString(a.By) {
		fmt.Fprintln(stderr, "  ERROR --by must be UTF-8 text — nothing written")
		return 1
	}
	if err := lock.write(repo, next, stderr); err != nil {
		if errors.As(err, &d) && strings.HasPrefix(d.what, stateName+": PermissionError: ") {
			fmt.Fprintln(stderr, "  ERROR "+strings.TrimPrefix(d.what, stateName+": PermissionError: ")) // caught, as on read
			return 1
		}
		if _, isDies := err.(*dies); !isDies {
			fmt.Fprintln(stderr, "  ERROR "+osErrorText(repo, err)) // a read-only mount: _write_state's open names the file
			return 1
		}
		return failed(err, stderr)
	}
	fmt.Fprintf(stdout, "language -> %s (by %s)\n", lang, a.By)
	return 0
}

// osErrorText is str(e) of the OSError set_language() raises reading the state file — `[Errno N] strerror:
// 'path'`, the path as Python names it — for the two a state file meets: not there, and not this user's.
// Anything else keeps the reader's own words.
func osErrorText(repo string, err error) string {
	path := pyval.Repr(pythonsState(repo))
	var errno syscall.Errno
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return "[Errno 2] No such file or directory: " + path
	case denied(err):
		return "[Errno 13] Permission denied: " + path
	case runtime.GOOS != "windows" && errors.As(err, &errno) && errno.Error() != "":
		// strerror's words are Go's table with the first letter up: "Is a directory", "Read-only file system"
		msg := errno.Error()
		return fmt.Sprintf("[Errno %d] %s%s: %s", int(errno), strings.ToUpper(msg[:1]), msg[1:], path)
	}
	return inState(err).Error()
}

// lowerArg is str.lower() of an argument as Python holds it — decoded with surrogateescape, so a byte that is
// not UTF-8 stays itself (\udcHH lowers to itself, and pyval.Repr shows it so) and the rest is lowered.
func lowerArg(s string) string {
	var b strings.Builder
	for len(s) > 0 {
		n := 0
		for n < len(s) {
			r, size := utf8.DecodeRuneInString(s[n:])
			if r == utf8.RuneError && size == 1 {
				break
			}
			n += size
		}
		b.WriteString(pyLower(s[:n]))
		if n < len(s) {
			b.WriteByte(s[n]) // a byte that is not UTF-8
			n++
		}
		s = s[n:]
	}
	return b.String()
}

// languageCodes is sorted(LANGUAGES): the codes a refusal names.
func languageCodes() []string {
	codes := make([]string, 0, len(languages))
	for _, l := range languages {
		codes = append(codes, l.code)
	}
	sort.Strings(codes)
	return codes
}

var (
	languageLine  = regexp.MustCompile(`(?m)^language:[^\n]*$`)
	schemaVersion = regexp.MustCompile(`(?m)^(schema_version:[^\n]*\n)`)
)

// byWord is set_language()'s `re.sub(r"[^\w.@-]", "_", by)[:40] or "user"`: the provenance comment is one line
// of word characters (CPython's \w for text: letters, numbers, `_`), cut to 40 characters.
func byWord(by string) string {
	if by == "" {
		by = "user"
	}
	out := make([]rune, 0, len(by))
	for _, r := range by {
		if unicode.IsLetter(r) || unicode.IsNumber(r) || r == '_' || r == '.' || r == '@' || r == '-' {
			out = append(out, r)
		} else {
			out = append(out, '_')
		}
	}
	if len(out) > 40 {
		out = out[:40]
	}
	return string(out) // never empty: `by` is "user" when it is, and each rune stays one rune
}

// setLanguage is set_language() on the file's text: the first top-level `language:` line replaced where it
// is, else one put right under `schema_version:`; the result must read back as the code, or nothing is
// written. Text surgery, as set_disposition is (a YAML round trip would drop every comment). `code` is a
// known one, stripped and lowered (LangCmd asks first). A file the reader cannot read is its gap, said as such.
func setLanguage(txt, code, by string) (string, bool, error) {
	line := "language: " + code + "   # by " + byWord(by)
	next := ""
	if loc := languageLine.FindStringIndex(txt); loc != nil {
		next = txt[:loc[0]] + line + txt[loc[1]:]
	} else if loc := schemaVersion.FindStringSubmatchIndex(txt); loc != nil {
		next = txt[:loc[3]] + "\n" + line + "\n" + txt[loc[3]:]
	} else {
		return "", false, errors.New("platform.state.yaml has no schema_version: line to put the language under")
	}
	v, err := readYAML(stateName, next)
	if isGap(err) {
		return "", false, err
	}
	if err != nil {
		return "", false, errors.New("platform.state.yaml would not parse with this change: nothing written — its " +
			"`language:` is in a shape this writer does not replace; fix it by hand")
	}
	doc, ok := v.(*yamlish.Map)
	if !ok || declaredLanguage(doc) != code {
		return "", false, fmt.Errorf("platform.state.yaml would not read back as language %s: nothing written — "+
			"it declares `language:` in a shape this writer does not replace; fix it by hand", pyval.Repr(code))
	}
	return next, next != txt, nil
}

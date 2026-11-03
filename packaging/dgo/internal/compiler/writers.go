package compiler

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// The writers of platform.state.yaml — reconcile.py's set_disposition, set_office and set_remote —
// and the three verbs main() answers with them: `set-state`, `office-set`, `remote-set`. They write
// and print what reconcile.py writes and prints, byte for byte, refusals and exit statuses included,
// with what reconcile.py does not do, on purpose:
//   - the plan's rule 3, one writer per fact behind a lock: a native write holds the advisory lock
//     data/.locks/platform.state from its read to its replace (and, as Python takes none, a lock that
//     cannot be taken stops nothing — lockState);
//   - the file is replaced atomically (written beside it, renamed over it), where Python's write_text
//     truncates it first and leaves it empty when the write fails half way — yet refused, or written
//     in place, wherever Python's in-place write would be (writeState);
//   - a block is written only if the next native verb reads it back as written (MarshalReadBack), and
//     the remote block only if it nests no deeper than maxNesting.

func statePath(repo string) string { return filepath.Join(repo, stateName) }

// SetStateCmd is `set-state --app <id> --state enabled|disabled|archived [--by <who>] [--create]`.
func SetStateCmd(repo string, args []string, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("set-state", args, stdout, stderr)
	if done {
		return code
	}
	if a.App == "" || a.State == "" {
		fmt.Fprintln(stderr, "set-state needs --app <id> --state <enabled|disabled|archived>")
		return 2
	}
	if !utf8.ValidString(a.App) || !utf8.ValidString(a.By) {
		// Python would write the undecodable bytes back as surrogates and fail half way through the
		// write, leaving an empty state file; nothing is touched here.
		fmt.Fprintln(stderr, "  ERROR --app and --by must be UTF-8 text — nothing written")
		return 1
	}
	lock := lockState(repo)
	defer lock.release()
	text, err := readText(statePath(repo))
	var d *dies
	if errors.As(err, &d) && d.codec != "" {
		// a UnicodeDecodeError is a ValueError, which main() catches around set_disposition
		fmt.Fprintln(stderr, "  ERROR "+d.codec)
		return 1
	}
	if err != nil {
		return failed(inState(err), stderr)
	}
	next, changed, err := setDisposition(text, a.App, a.State, a.By, a.Create)
	if err != nil {
		fmt.Fprintf(stderr, "  ERROR %v\n", err)
		return 1
	}
	if changed {
		if err := lock.write(repo, next, stderr); err != nil {
			return failed(err, stderr)
		}
		fmt.Fprintf(stdout, "%s -> %s (by %s)\n", a.App, a.State, a.By)
		return 0
	}
	// A no-op is not a failure: "no entry" (create it) is told apart from "already so".
	have := currentDisposition(text, a.App)
	if have == "" {
		fmt.Fprintf(stderr, "'%s' not found in platform.state.yaml (use --create to add it)\n", a.App)
		return 1
	}
	fmt.Fprintf(stdout, "%s is already %s — nothing to change\n", a.App, have)
	return 0
}

// entryOf finds `  <id>: { … }` — whitespace (newlines included, as `\s` reads them) before the id
// at the start of a line, the brace block after it.
func entryOf(aid string) *regexp.Regexp {
	return regexp.MustCompile(`(?m)^(` + pyval.SpaceClass + `+` + regexp.QuoteMeta(aid) + `:` + pyval.SpaceClass + `*)\{([^}]*)\}`)
}

var (
	appLine     = regexp.MustCompile(`^  [a-z][\p{L}\p{N}_-]*:`)
	stateWord   = regexp.MustCompile(`state:` + pyval.SpaceClass + `*([A-Za-z_]+)`)
	enabledWord = regexp.MustCompile(`enabled:` + pyval.SpaceClass + `*(true|false)`)
)

// setDisposition is set_disposition() on the file's text: the whole brace block of the app's entry
// replaced by `{ state: <d>, by: <who> }` (text surgery — a YAML round trip would drop every comment),
// or with create a new entry after the last one in `apps:`. Reports whether the text changed.
func setDisposition(txt, aid, dispo, by string, create bool) (string, bool, error) {
	repl := "{ state: " + dispo + ", by: " + by + " }"
	if m := entryOf(aid).FindStringSubmatchIndex(txt); m != nil {
		// The entry's OTHER keys are not this writer's (`workflows:`, `linked:`, DGO-945): kept as
		// written, after the two it owns — set_disposition()'s keep().
		var others []string
		for _, kv := range strings.Split(txt[m[4]:m[5]], ",") {
			key := pyval.Strip(strings.SplitN(kv, ":", 2)[0])
			if pyval.Strip(kv) != "" && key != "state" && key != "by" && key != "enabled" {
				others = append(others, pyval.Strip(kv))
			}
		}
		with := repl
		if len(others) > 0 {
			with = "{ state: " + dispo + ", by: " + by + ", " + strings.Join(others, ", ") + " }"
		}
		next := txt[:m[0]] + txt[m[2]:m[3]] + with + txt[m[1]:]
		return next, next != txt, nil
	}
	if !create {
		return txt, false, nil
	}
	lines := pySplitLines(txt, false)
	inApps, last := false, -1
	for i, ln := range lines {
		if strings.HasPrefix(ln, "apps:") {
			inApps = true
			continue
		}
		if inApps {
			if pyval.Strip(ln) != "" && !strings.HasPrefix(ln, " ") && !strings.HasPrefix(ln, "\t") && !strings.HasPrefix(ln, "#") {
				break
			}
			if appLine.MatchString(ln) {
				last = i
			}
		}
	}
	if last < 0 {
		return "", false, errors.New("platform.state.yaml has no apps: block to extend")
	}
	lines = slices.Insert(lines, last+1, pyLjust("  "+aid+":", 20)+repl+"   # added by "+by)
	return strings.Join(lines, "\n") + "\n", true, nil
}

// currentDisposition is current_disposition(): what the file says of the app, "" for no entry.
func currentDisposition(txt, aid string) string {
	m := entryOf(aid).FindStringSubmatch(txt)
	if m == nil {
		return ""
	}
	if st := stateWord.FindStringSubmatch(m[2]); st != nil && contains(dispositions, strings.ToLower(st[1])) {
		return strings.ToLower(st[1])
	}
	if en := enabledWord.FindStringSubmatch(m[2]); en != nil && en[1] == "true" {
		return "enabled"
	}
	return "disabled"
}

// ── office ────────────────────────────────────────────────────────────────────────────────────────

var (
	officeHues = []string{"olive", "lime", "sky", "plum", "violet", "muted"}
	officeWord = regexp.MustCompile(`^[a-z][a-z0-9-]{0,30}\z`)
	officeTime = regexp.MustCompile(`^\p{Nd}{4}-\p{Nd}{2}-\p{Nd}{2}T\p{Nd}{2}:\p{Nd}{2}:\p{Nd}{2}Z\z`)
	glyphName  = regexp.MustCompile(`(?m)^` + pyval.SpaceClass + `+'?([a-z][a-z0-9-]*)'?:` + pyval.SpaceClass + `*'<`)
)

const (
	officeNameMax = 60
	officeHeader  = "# ── this office's own record: written by the install wizard through the control plane's " +
		"/api/office; read by the console, the link's catalog and `bbox dgo identity` ──"
)

// OfficeSetCmd is `office-set [--by <who>]`: this office's record, a JSON object on stdin, validated
// and written as the `office:` block; the record as the file then holds it is printed back as JSON.
func OfficeSetCmd(repo string, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("office-set", args, stdout, stderr)
	if done {
		return code
	}
	if !utf8.ValidString(a.By) { // --by goes into the block's header: as set-state's, it must be text
		fmt.Fprintln(stderr, "  ERROR --by must be UTF-8 text — nothing written")
		return 1
	}
	raw, err := readStdin(stdin)
	if err != nil {
		return failed(err, stderr)
	}
	if pyval.Strip(raw) == "" {
		fmt.Fprintln(stderr, "  ERROR office-set reads the record as JSON on stdin and got nothing — nothing written")
		return 2
	}
	fields, err := yamlish.LoadJSON(raw)
	if err != nil {
		return notJSON("record", err, stderr)
	}
	record, ok := fields.(*yamlish.Map)
	if !ok { // set_office's first refusal, answered before the lock is waited for
		fmt.Fprintln(stderr, "  - office: a JSON object of fields")
		return 1
	}
	lock := lockState(repo)
	defer lock.release()
	next, changed, errs, err := setOffice(repo, record, a.By)
	if err != nil {
		return failed(err, stderr)
	}
	for _, e := range errs {
		fmt.Fprintln(stderr, "  - "+e)
	}
	if len(errs) > 0 {
		return 1
	}
	if changed {
		if err := lock.write(repo, next, stderr); err != nil {
			return failed(err, stderr)
		}
	}
	office, err := OfficeBlock(repo) // the record as the file holds it now
	if err != nil {
		return failed(err, stderr)
	}
	fmt.Fprintln(stdout, yamlish.DumpsJSON(ordered("written", changed, "office", office)))
	return 0
}

// setOffice is set_office() for a record that is an object: the record merged into the one the file
// holds (a field not given keeps its value), validated whole, and — when it differs — the old block cut
// out and the new one appended with its header. Returns the new text, whether it changed, the
// refusals, or where Python raises.
func setOffice(repo string, in *yamlish.Map, by string) (string, bool, []string, error) {
	cur, err := OfficeBlock(repo)
	if err != nil {
		return "", false, nil, err
	}
	next := yamlish.NewMap()
	for _, k := range cur.Keys() {
		v, _ := cur.Get(k)
		next.Set(k, v)
	}
	var errs []string
	for _, k := range in.Keys() {
		v, _ := in.Get(k)
		if !contains(officeFields, k) {
			errs = append(errs, fmt.Sprintf("office: unknown field %s (the fields are %s)", pyval.Repr(k), strings.Join(officeFields, ", ")))
			continue
		}
		if v == nil || pyval.Strip(pyval.Str(v)) == "" {
			continue
		}
		next.Set(k, strings.Join(pySplit(pyval.Str(v)), " "))
	}
	field := func(k string) string { v, _ := next.Get(k); s, _ := v.(string); return s }
	if pyLen(field("name")) > officeNameMax {
		errs = append(errs, fmt.Sprintf("office: name is one line of at most %d characters", officeNameMax))
	}
	if animal := field("animal"); animal != "" {
		known := pyMatch(officeWord, animal)
		if known {
			glyphs, err := glyphNames(repo)
			if err != nil {
				return "", false, nil, err
			}
			known = glyphs[animal]
		}
		if !known {
			errs = append(errs, fmt.Sprintf("office: animal %s is not a glyph of platform-base/bina-ui/bina-icons.js", pyval.Repr(animal)))
		}
	}
	if hue := field("hue"); hue != "" {
		css, err := readText(filepath.Join(repo, "platform-base", "bina-ui", "theme-tokens.css"))
		var d *dies
		if errors.As(err, &d) {
			return "", false, nil, d // not UTF-8 raises; a file that is not there reads as ""
		}
		if !contains(officeHues, hue) || !strings.Contains(css, "--"+hue+":") {
			errs = append(errs, fmt.Sprintf("office: hue %s is not one of the palette's families (%s) declared in theme-tokens.css",
				pyval.Repr(hue), strings.Join(officeHues, ", ")))
		}
	}
	for _, k := range []string{"terms_accepted_at", "installed_at"} {
		if v := field(k); v != "" && !pyMatch(officeTime, v) {
			errs = append(errs, fmt.Sprintf("office: %s is a UTC time written YYYY-MM-DDTHH:MM:SSZ", k))
		}
	}
	if field("terms_accepted_at") != "" && field("terms_version") == "" {
		errs = append(errs, "office: terms_accepted_at names no terms_version — which terms were accepted?")
	}
	if len(errs) > 0 {
		return "", false, errs, nil
	}
	if sameRecord(next, cur) {
		return "", false, nil, nil
	}
	text, err := readText(statePath(repo)) // the rewrite reads the file again, as set_office does
	if err != nil {
		return "", false, nil, inState(err)
	}
	var out strings.Builder
	skipping := false
	for _, ln := range pySplitLines(text, true) {
		if blockStart(ln, "office") || strings.HasPrefix(ln, officeHeader) {
			skipping = true
			continue
		}
		if skipping {
			if r, _ := utf8.DecodeRuneInString(ln); pyval.Strip(ln) == "" || pyval.IsSpace(r) {
				continue
			}
			skipping = false
		}
		out.WriteString(ln)
	}
	block, err := yamlish.MarshalReadBack(ordered("office", next), yamlish.Options{Width: 1000})
	if errors.Is(err, yamlish.ErrNotReadBack) {
		return "", false, []string{"office: " + err.Error() + " — nothing written"}, nil
	}
	if err != nil {
		return "", false, nil, err
	}
	return strings.TrimRight(out.String(), "\n") + "\n\n" + officeHeader + "  (by " + by + ")\n" + string(block), true, nil, nil
}

// glyphNames is _glyph_names(): every glyph the one icon set draws — an animal must be one of them.
func glyphNames(repo string) (map[string]bool, error) {
	js, err := readText(filepath.Join(repo, "platform-base", "bina-ui", "bina-icons.js"))
	var d *dies
	if errors.As(err, &d) {
		return nil, d
	}
	out := map[string]bool{}
	for _, m := range glyphName.FindAllStringSubmatch(js, -1) {
		out[m[1]] = true
	}
	return out, nil
}

func sameRecord(a, b *yamlish.Map) bool {
	if a.Len() != b.Len() {
		return false
	}
	for _, k := range a.Keys() {
		av, _ := a.Get(k)
		bv, has := b.Get(k)
		if !has || av != bv {
			return false
		}
	}
	return true
}

// ── remote ────────────────────────────────────────────────────────────────────────────────────────

// RemoteSetCmd is `remote-set [--json]`: the `remote:` block — what linked offices give this one, a
// JSON list on stdin — validated (planRemote) and written unless it declares what the file already
// does.
func RemoteSetCmd(repo string, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("remote-set", args, stdout, stderr)
	if done {
		return code
	}
	raw, err := readStdin(stdin)
	if err != nil {
		return failed(err, stderr)
	}
	// NOTHING ON STDIN IS NOT AN EMPTY BLOCK: `[]` is; an empty stdin is a caller whose upstream failed.
	if pyval.Strip(raw) == "" {
		fmt.Fprintln(stderr, "  ERROR remote-set reads the block as JSON on stdin and got nothing — nothing written (an empty block is the JSON `[]`)")
		return 2
	}
	doc, err := yamlish.LoadJSON(raw)
	if err != nil {
		return notJSON("block", err, stderr)
	}
	block, ok := doc.([]any)
	if !ok {
		fmt.Fprintln(stderr, "  - remote must be a list of offices")
		return 1
	}
	if _, err := LoadCatalog(repo); err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	_, errs, err := planRemote(repo, "remote", block)
	if err != nil {
		return failed(err, stderr)
	}
	for _, e := range errs {
		fmt.Fprintln(stderr, "  - "+e)
	}
	if len(errs) > 0 {
		return 1
	}
	changed, refused, err := writeRemote(repo, block, stderr)
	if err != nil {
		return failed(err, stderr)
	}
	if refused != "" {
		fmt.Fprintln(stderr, "  - "+refused)
		return 1
	}
	apps := 0
	for _, e := range block {
		v, _ := e.(*yamlish.Map).Get("apps")
		l, _ := v.([]any)
		apps += len(l)
	}
	if a.JSON {
		fmt.Fprintln(stdout, yamlish.DumpsJSON(ordered("written", changed, "apps", apps, "offices", len(block))))
		return 0
	}
	tail := ""
	if !changed {
		tail = " — nothing to change"
	}
	fmt.Fprintf(stdout, "remote: %d app(s) of %d office(s)%s\n", apps, len(block), tail)
	return 0
}

// maxNesting is how deep a remote block may nest. A linked office's catalog reaches the block with its
// `order`, `module` and `label` copied unchecked, and PyYAML (measured) cannot write a block nested
// past about 330 levels, nor read one past about 500: reconcile.py crashes writing such a block, and
// after a native write every Python reader of the file would crash reading it. A real block nests six
// levels; 100 leaves room for any caller's own stack.
const maxNesting = 100

// writeRemote is the write half of set_remote(): nothing when the block declares what the file's does
// (`fetched` — when a catalog was read — is a reading, not a declaration), else the old `remote:` (and
// a legacy `serve:`) cut out and the new block appended. A block that nests too deep, or that the next
// native read would not read back as written, is refused instead — the sentence why, nothing written.
func writeRemote(repo string, block []any, stderr io.Writer) (changed bool, refused string, err error) {
	lock := lockState(repo)
	defer lock.release()
	text, err := readText(statePath(repo))
	if err != nil {
		return false, "", inState(err)
	}
	v, err := yamlish.Unmarshal([]byte(text))
	if err != nil {
		return false, "", fmt.Errorf("FATAL %s: %v", stateName, err)
	}
	doc, err := mapping(v, stateName)
	if err != nil {
		return false, "", err
	}
	cur, _ := doc.Get("remote")
	have, _ := cur.([]any)
	was, err := declared(have)
	if err != nil {
		return false, "", err
	}
	if now, _ := declared(block); was == now {
		return false, "", nil
	}
	if n := nesting(block); n > maxNesting {
		return false, fmt.Sprintf("remote: the block nests %d levels deep, more than the %d a state file takes — nothing written", n, maxNesting), nil
	}
	var out strings.Builder
	skipping := false
	for _, ln := range pySplitLines(text, true) {
		if blockStart(ln, "remote") || blockStart(ln, "serve") {
			skipping = true
			continue
		}
		if skipping {
			// the entries sit at column 0 (`remote:\n- office: …`): a list item does not end the block
			if r, _ := utf8.DecodeRuneInString(ln); pyval.Strip(ln) == "" || pyval.IsSpace(r) || r == '-' {
				continue
			}
			skipping = false
		}
		out.WriteString(ln)
	}
	next := strings.TrimRight(out.String(), "\n") + "\n"
	if len(block) > 0 {
		b, err := yamlish.MarshalReadBack(ordered("remote", block), yamlish.Options{Width: 1000})
		if errors.Is(err, yamlish.ErrNotReadBack) {
			return false, "remote: " + err.Error() + " — nothing written", nil
		}
		if err != nil {
			return false, "", err
		}
		next += "\n" + string(b)
	}
	return true, "", lock.write(repo, next, stderr)
}

// nesting is how deep a value's collections go: a scalar is 0, a list or a mapping one more than its
// deepest item.
func nesting(v any) int {
	deepest := 0
	switch t := v.(type) {
	case []any:
		for _, x := range t {
			deepest = max(deepest, nesting(x))
		}
	case *yamlish.Map:
		for _, k := range t.Keys() {
			x, _ := t.Get(k)
			deepest = max(deepest, nesting(x))
		}
	default:
		return 0
	}
	return deepest + 1
}

// declared is set_remote's declared(): the block as sorted JSON, each entry without `fetched`. Only
// its equality is used, so the canonical spelling stands in for Python's sort_keys dump.
func declared(b []any) (string, error) {
	out := make([]any, 0, len(b))
	for _, e := range b {
		m, ok := e.(*yamlish.Map)
		if !ok {
			return "", died("%s: remote: AttributeError: '%s' object has no attribute 'items'", stateName, pyTypeName(e))
		}
		c := yamlish.NewMap()
		for _, k := range m.Keys() {
			if k != "fetched" {
				v, _ := m.Get(k)
				c.Set(k, v)
			}
		}
		out = append(out, c)
	}
	return yamlish.CanonicalJSON(out), nil
}

// ── shared by the three ───────────────────────────────────────────────────────────────────────────

// blockStart is `re.match(r"^<name>:\s*$", line)`: the line that opens a top-level block.
func blockStart(ln, name string) bool {
	return strings.HasPrefix(ln, name+":") && strings.TrimFunc(ln[len(name)+1:], pyval.IsSpace) == ""
}

func ordered(kv ...any) *yamlish.Map {
	m := yamlish.NewMap()
	for i := 0; i+1 < len(kv); i += 2 {
		m.Set(kv[i].(string), kv[i+1])
	}
	return m
}

// readStdin is sys.stdin.read(): all of it, as UTF-8.
func readStdin(r io.Reader) (string, error) {
	raw, err := io.ReadAll(r)
	if err != nil {
		return "", err
	}
	if !utf8.Valid(raw) {
		return "", decodeError("stdin", raw)
	}
	return string(raw), nil
}

// notJSON answers json.loads' refusal: the ValueError main() catches (exit 2), or the RecursionError
// it does not.
func notJSON(what string, err error, stderr io.Writer) int {
	if errors.Is(err, yamlish.ErrJSONTooDeep) {
		return failed(died("stdin: RecursionError: %v", err), stderr)
	}
	fmt.Fprintf(stderr, "  ERROR the %s is not JSON: %v\n", what, err)
	return 2
}

// inState names the state file in a failure to read it (FileNotFoundError, where Python raises).
func inState(err error) error {
	var d *dies
	if errors.As(err, &d) {
		return d
	}
	return fmt.Errorf("%s: %w", stateName, err)
}

// failed is where reconcile.py would have raised — or this process failed on its own (the lock, the
// write): one FATAL line and exit 1, as the read verbs do.
func failed(err error, stderr io.Writer) int {
	msg := err.Error()
	if !strings.HasPrefix(msg, "FATAL ") {
		msg = "FATAL " + msg
	}
	fmt.Fprintln(stderr, msg)
	return 1
}

// stateLock is the advisory lock every native writer of platform.state.yaml holds from its read to its
// replace: data/.locks/platform.state, beside the heavy-job lock bbox keeps in the same directory
// (scripts/lib.sh heavy_admit); the kernel releases it when this process ends, crashes included.
// reconcile.py takes no lock, so one that cannot be taken stops nothing: as heavy_admit does, the
// writer goes on without it — and says so when, and only when, it writes, so a verb that changes
// nothing answers exactly as reconcile.py does.
type stateLock struct {
	f      *os.File
	missed error // why the lock is not held; nil while it is
}

func lockState(repo string) *stateLock {
	f, err := openLock(filepath.Join(repo, "data", ".locks"))
	if err == nil {
		if err = lockFile(f); err != nil {
			f.Close()
		}
	}
	if err != nil {
		return &stateLock{missed: err}
	}
	return &stateLock{f: f}
}

// openLock opens the lock file, creating it (and its directory) for anyone the umask allows: the
// office's writers run as its user and as root in the containers that mount the checkout. One this
// user may not write — such a container's, or one made read-only — is opened for reading: flock(2)
// and LockFileEx lock through a read handle too.
func openLock(dir string) (*os.File, error) {
	if err := os.MkdirAll(dir, 0o777); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "platform.state")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o666)
	if err != nil {
		if ro, rerr := os.Open(path); rerr == nil {
			return ro, nil
		}
	}
	return f, err
}

func (l *stateLock) release() {
	if l.f != nil {
		l.f.Close()
	}
}

// write is writeState under the lock — or, where it could not be taken, after a warning that says why.
func (l *stateLock) write(repo, text string, stderr io.Writer) error {
	if l.missed != nil {
		fmt.Fprintf(stderr, "warning: %s is written without its lock (%v)\n", stateName, l.missed)
	}
	return writeState(repo, text, stderr)
}

// writeState replaces platform.state.yaml with text: written beside it and renamed over it, so a
// reader sees the old file or the new one and a failed write leaves the old one. Python writes in
// place; where a rename would answer otherwise, the file's own permissions decide, as for write_text:
//   - a state file this user may not write (a freeze: chmod 444) is refused with Python's
//     PermissionError — a rename would ask only the directory;
//   - where only the replace is refused — a directory this user may not write in, or on Windows a
//     file another process holds open without sharing its deletion (Go's os.Open, most editors) — the
//     file is written in place, as Python writes it, and a warning says so.
//
// The old file's mode, and its owner where this process may set it, carry over, as they do when
// Python writes in place: a writer running as root in a container must not leave the office a file it
// cannot edit.
func writeState(repo, text string, stderr io.Writer) error {
	path := statePath(repo)
	if real, err := filepath.EvalSymlinks(path); err == nil {
		path = real
	}
	fi, err := os.Stat(path)
	if err != nil {
		return err
	}
	probe, err := os.OpenFile(path, os.O_WRONLY, 0)
	if err != nil {
		if denied(err) {
			return died("%s: PermissionError: [Errno 13] Permission denied: %s", stateName, pyval.Repr(pythonsState(repo)))
		}
		return err
	}
	probe.Close()
	err = replace(path, text, fi)
	if err == nil || !denied(err) {
		return err
	}
	fmt.Fprintf(stderr, "warning: %s could not be replaced (%v) — written in place\n", stateName, err)
	return os.WriteFile(path, []byte(text), fi.Mode().Perm())
}

// replace writes text beside path and renames it over path. Whatever step fails, nothing is left
// beside it (only a writer killed mid-write leaves its .platform.state.yaml.* copy, which git ignores).
func replace(path, text string, old os.FileInfo) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name()) // the copy, unless it was renamed
	_, err = tmp.WriteString(text)
	if err == nil {
		err = tmp.Sync()
	}
	if cerr := tmp.Close(); err == nil {
		err = cerr
	}
	if err == nil {
		err = os.Chmod(tmp.Name(), old.Mode().Perm())
	}
	if err != nil {
		return err
	}
	keepOwner(tmp.Name(), old)
	return os.Rename(tmp.Name(), path)
}

// pythonsState is reconcile.py's STATE as an OSError names it: the checkout's path resolved (links
// followed, made absolute) and the file's name.
func pythonsState(repo string) string {
	dir, err := filepath.Abs(repo)
	if err == nil {
		if real, err := filepath.EvalSymlinks(dir); err == nil {
			dir = real
		}
	}
	return filepath.Join(dir, stateName)
}

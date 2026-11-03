package compiler

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── the verbs that only read: answers about the catalog, the state file and .generated/ ───────────
//
// Each is reconcile.py main()'s branch for the verb, and keeps main()'s order of work, because that
// order decides which refusal a caller sees: required-by and compose-services read the catalog alone
// and validate nothing; office-get and remote-get read only the state file and never create it; the
// rest load the catalog and the state, validate, and only then look at their options. The command
// line is read first, as argparse reads it (args.go). Where reconcile.py dies with a traceback — a
// file it cannot read, a manifest entry it indexes and finds empty — the verb stops too: the same exit
// code, nothing on stdout, one FATAL line instead of the traceback.

// ValidateCmd and EnabledAppsCmd are the two verbs ported first, now reading their command line:
// what argparse refuses is refused in its words, and an option main() ignores for the verb
// (`validate --app x`) is ignored.
func ValidateCmd(repo string, args []string, stdout, stderr io.Writer) int {
	if _, code, done := parseArgs("validate", args, stdout, stderr); done {
		return code
	}
	return ValidateVerb(repo, stdout, stderr)
}

func EnabledAppsCmd(repo string, args []string, stdout, stderr io.Writer) int {
	if _, code, done := parseArgs("enabled-apps", args, stdout, stderr); done {
		return code
	}
	return EnabledApps(repo, stdout, stderr)
}

// ServicesCmd is `services [--for APP] [--exclude SVC]`: the compose services a lane must start —
// the resolved closure of --for (default: every enabled app), in dependency order, as one line of
// words; the diagnostics go to stderr so that stdout can be used as it is
// (SERVICES=$(… services --for indox)). An --exclude that names no service is said, not swallowed.
func ServicesCmd(repo string, args []string, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("services", args, stdout, stderr)
	if done {
		return code
	}
	cat, st, _, code := loadAndValidate(repo, stdout, stderr)
	if code != 0 {
		return code
	}
	order, diags, err := Resolve(repo, cat, st, csv(a.Roots))
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	failed := false
	for _, d := range diags {
		if d.Level == "error" {
			failed = true
			fmt.Fprintln(stderr, "  ERROR "+d.Msg)
		} else {
			fmt.Fprintln(stderr, "  info  "+d.Msg)
		}
	}
	if failed {
		fmt.Fprintln(stderr, "RESOLVE FAILED")
		return 1
	}
	drop := map[string]bool{}
	for _, x := range csv(a.Exclude) {
		drop[x] = true
	}
	var lane []string
	known := map[string]bool{}
	for _, aid := range order {
		names, err := composeServices(repo, cat.Apps[aid])
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 1
		}
		for _, s := range names {
			known[s] = true
			if !drop[s] && !contains(lane, s) {
				lane = append(lane, s)
			}
		}
	}
	var stale []string
	for _, x := range sortedKeys(drop) {
		if !known[x] {
			stale = append(stale, x)
		}
	}
	if len(stale) > 0 {
		fmt.Fprintf(stderr, "warning: --exclude names %d service(s) that do not exist: %s\n", len(stale), strings.Join(stale, ", "))
	}
	fmt.Fprintln(stdout, strings.Join(lane, " "))
	return 0
}

// RequiredByCmd is `required-by --app ID`: the enabled apps that cannot run without ID — directly or
// through a provider of theirs — as one JSON list ([] is nobody). Asked of the resolver, as
// reconcile.py asks it: an app requires ID when its own closure (resolve rooted at it) holds ID.
func RequiredByCmd(repo string, args []string, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("required-by", args, stdout, stderr)
	if done {
		return code
	}
	cat, err := LoadCatalog(repo)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	if _, known := cat.Apps[a.App]; !known {
		fmt.Fprintln(stderr, "required-by needs --app <id> of an app that has a manifest")
		return 2
	}
	st, err := LoadState(repo, stdout, stderr)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	enabled, err := EnabledIDs(st, cat)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	out := []any{}
	for _, aid := range sortedKeys(enabled) {
		if aid == a.App {
			continue
		}
		order, _, err := Resolve(repo, cat, st, []string{aid})
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 1
		}
		if contains(order, a.App) {
			out = append(out, aid)
		}
	}
	fmt.Fprintln(stdout, yamlish.DumpsJSON(out))
	return 0
}

// ComposeServicesCmd is `compose-services --app ID`: the compose services that ONE app declares, a
// line each — not `services`' closure, because stopping an app must not stop the database it uses.
func ComposeServicesCmd(repo string, args []string, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("compose-services", args, stdout, stderr)
	if done {
		return code
	}
	if a.App == "" {
		fmt.Fprintln(stderr, "compose-services needs --app <id>")
		return 2
	}
	cat, err := LoadCatalog(repo)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	app, known := cat.Apps[a.App]
	if !known {
		fmt.Fprintf(stderr, "unknown app '%s'\n", a.App)
		return 1
	}
	names, err := composeServices(repo, app)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	for _, n := range names {
		fmt.Fprintln(stdout, n)
	}
	return 0
}

// CapabilityProviderCmd is `capability-provider --capability NAME`: the one RUNNING app that declares
// NAME, on stdout; nothing and exit 1 when none does; exit 1 and the ambiguity named on stderr when
// two do. RUNNING is the resolved closure — the enabled apps and the providers they pull in
// (DGO-993: n8n runs because bina-ds pulls it in, and is the workflow provider all the same). It is
// how layer 0 reaches a singleton (the control plane) by the role it plays, never by an app id.
func CapabilityProviderCmd(repo string, args []string, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("capability-provider", args, stdout, stderr)
	if done {
		return code
	}
	cat, st, _, code := loadAndValidate(repo, stdout, stderr)
	if code != 0 {
		return code
	}
	if a.Capability == "" {
		fmt.Fprintln(stderr, "capability-provider needs --capability <name>")
		return 2
	}
	running, diags, err := Resolve(repo, cat, st, nil)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	// A refused plan answers nothing, as enabled-apps refuses it: its closure can name a provider that
	// only the refused plan pulls in.
	failed := false
	for _, d := range diags {
		if d.Level == "error" {
			fmt.Fprintln(stderr, "  ERROR "+d.Msg)
			failed = true
		}
	}
	if failed {
		return 1
	}
	ids := append([]string(nil), running...)
	sort.Strings(ids)
	var provs []string
	for _, aid := range ids {
		caps, err := cat.Apps[aid].entries("capabilities") // read, and read whole, by Validate already
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 1
		}
		for _, c := range caps {
			if pyEqual(c["name"], a.Capability) {
				provs = append(provs, aid)
				break
			}
		}
	}
	switch len(provs) {
	case 0:
		return 1
	case 1:
		fmt.Fprintln(stdout, provs[0])
		return 0
	}
	fmt.Fprintf(stderr, "  ERROR capability '%s' has %d running providers (%s) — ambiguous\n", a.Capability, len(provs), strings.Join(provs, ", "))
	return 1
}

// BlueprintsCmd is `blueprints [--for APP]`: which app owns which n8n workflow directory, read from
// each manifest's `blueprints.n8n` — "<id>\t<dir>" a line, ids sorted, the directory relative to the
// checkout with forward slashes on every OS (a hook prefixes its own root: gate G10). Without --for
// only the apps whose workflows THIS office holds answer: enabled ones and the workflow engine wherever
// the plan runs it, as `workflows:` places them (DGO-945, DGO-1001), since a switched-off app's
// workflows must not be pushed; with it, exactly the apps named, enabled or not, and a name that
// declares no directory is an error.
func BlueprintsCmd(repo string, args []string, stdout, stderr io.Writer) int {
	a, code, done := parseArgs("blueprints", args, stdout, stderr)
	if done {
		return code
	}
	cat, st, _, code := loadAndValidate(repo, stdout, stderr)
	if code != 0 {
		return code
	}
	want := map[string]bool{}
	for _, id := range csv(a.Roots) {
		want[id] = true
	}
	enabled, err := EnabledIDs(st, cat) // asked even with --for, as main() asks it
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	// …and the workflow ENGINE's own automations are part of the engine: they follow it wherever it runs,
	// pulled in as much as enabled (DGO-1001 — n8n, pulled in by bina-ds and off in the state). Any OTHER
	// app the plan only pulls in runs as a provider, and its automations stay off unless its own entry
	// switches them on (chat pulling INDOX in must not activate INDOX's workflows). A refused plan pulls
	// nothing in: its closure can name a provider only the refused plan pulls in.
	// `--for` names its apps and never asks who runs: it does not depend on the plan resolving either.
	var running []string
	var diags []Diag
	if len(want) == 0 {
		running, diags, err = Resolve(repo, cat, st, nil)
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 1
		}
	}
	runs := map[string]bool{}
	for aid, on := range enabled {
		runs[aid] = on
	}
	refused := false
	for _, d := range diags {
		refused = refused || d.Level == "error"
	}
	for _, aid := range running {
		if refused {
			break
		}
		caps, err := cat.Apps[aid].entries("capabilities")
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 1
		}
		for _, c := range caps {
			if pyEqual(c["name"], "workflow") {
				runs[aid] = true
			}
		}
	}
	ids := append([]string(nil), cat.Order...)
	sort.Strings(ids)
	var rows []string
	declared := map[string]bool{}
	for _, aid := range ids {
		app := cat.Apps[aid]
		bp, _ := app.Raw["blueprints"].(map[string]any)
		dir, _ := bp["n8n"].(string)
		if dir = pyval.Strip(dir); dir == "" {
			continue
		}
		if len(want) > 0 && !want[aid] || len(want) == 0 && !workflowsHere(get(st.Apps, aid), runs[aid]) {
			continue
		}
		p := realPath(joinPath(app.Dir, dir))
		if fi, err := os.Stat(p); err != nil || !fi.IsDir() {
			fmt.Fprintf(stderr, "  ERROR %s: blueprints.n8n -> %s is not a directory\n", aid, dir)
			return 1
		}
		rel, err := checkoutRelative(repo, p)
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 1
		}
		rows = append(rows, aid+"\t"+rel)
		declared[aid] = true
	}
	var missing []string
	for _, id := range sortedKeys(want) {
		if !declared[id] {
			missing = append(missing, id)
		}
	}
	if len(missing) > 0 {
		fmt.Fprintln(stderr, "  ERROR no blueprints.n8n declared for: "+strings.Join(missing, ", "))
		return 1
	}
	for _, r := range rows {
		fmt.Fprintln(stdout, r)
	}
	return 0
}

// workflowsHere is workflows_here(entry, runs) (DGO-945): does THIS office's n8n run the app's
// workflows? Absent, where the app runs for its workflows (`runs`: enabled, or the workflow engine
// pulled in by a plan that stands — DGO-1001); `here`, yes; another office's name, no.
func workflowsHere(entry any, runs bool) bool {
	m, ok := entry.(*yamlish.Map)
	if !ok {
		return runs
	}
	w := pyLower(pyval.Strip(pyval.Str(orEmpty(get(m, "workflows")))))
	if w == "" {
		return runs
	}
	return w == "here"
}

// GenerationsCmd is `generations`: every archived render under .generated/generations/, oldest first,
// with how many entries each holds, and the rollback that restores the newest.
func GenerationsCmd(repo string, args []string, stdout, stderr io.Writer) int {
	if _, code, done := parseArgs("generations", args, stdout, stderr); done {
		return code
	}
	if _, _, _, code := loadAndValidate(repo, stdout, stderr); code != 0 {
		return code
	}
	dir := filepath.Join(repo, genDir, "generations")
	gens := generationDirs(dir)
	if len(gens) == 0 {
		fmt.Fprintln(stdout, "no generations yet — the first `render` archives the current .generated/")
		return 0
	}
	for _, g := range gens {
		fmt.Fprintf(stdout, "  %s  %4d file(s)\n", g, countEntries(filepath.Join(dir, g)))
	}
	fmt.Fprintf(stdout, "rollback with: reconcile.py rollback --for %s\n", gens[len(gens)-1])
	return 0
}

// generationDirs is _gen_dirs(): the generations under dir, by number — the directories (or links to
// one) named in digits, as archive_generation writes them (%04d). Python's isdigit() would also take
// digits of other scripts, which nothing writes, so ASCII it is.
func generationDirs(dir string) []string {
	var entries []os.DirEntry
	if d, err := os.Open(dir); err == nil { // no such directory: no generations
		// in the directory's own order, as iterdir() lists it: generations of one number keep it
		entries, _ = d.ReadDir(-1)
		d.Close()
	}
	var gens []string
	for _, e := range entries {
		if fi, err := os.Stat(filepath.Join(dir, e.Name())); err == nil && fi.IsDir() && asciiDigits(e.Name()) {
			gens = append(gens, e.Name())
		}
	}
	sort.SliceStable(gens, func(i, j int) bool { // by number, as int(name) orders them
		a, b := strings.TrimLeft(gens[i], "0"), strings.TrimLeft(gens[j], "0")
		return len(a) < len(b) || len(a) == len(b) && a < b
	})
	return gens
}

// OfficeGetCmd is `office-get`: the state file's `office:` block — this office's own record, as the
// file has it — as one JSON object; {} before the install wizard ran, and {} when there is no file
// (it is read, never created, here).
func OfficeGetCmd(repo string, args []string, stdout, stderr io.Writer) int {
	if _, code, done := parseArgs("office-get", args, stdout, stderr); done {
		return code
	}
	block, err := OfficeBlock(repo)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	fmt.Fprintln(stdout, yamlish.DumpsJSON(block))
	return 0
}

// RemoteGetCmd is `remote-get`: the state file's `remote:` block — what linked offices give this one,
// as declared — as JSON, [] when there is none. Read, never created; unlike office-get, a missing
// file is an error, because reconcile.py's remote_block has no answer for one.
func RemoteGetCmd(repo string, args []string, stdout, stderr io.Writer) int {
	if _, code, done := parseArgs("remote-get", args, stdout, stderr); done {
		return code
	}
	list, err := RemoteBlock(repo)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	fmt.Fprintln(stdout, yamlish.DumpsJSON(list))
	return 0
}

// RemoteBlock is remote_block(): the `remote:` list as the file has it, [] when the block is not a
// list — what remote-get prints and the control plane's GET /api/remote answers. Unlike office_block()
// it does not catch a file that cannot be read: Python raises there, and so this returns the error.
func RemoteBlock(repo string) ([]any, error) {
	v, err := ReadState(repo)
	if err != nil {
		return nil, fmt.Errorf("FATAL %s: %v", stateName, err)
	}
	doc, err := mapping(v, stateName)
	if err != nil {
		return nil, err
	}
	block, _ := doc.Get("remote")
	list, ok := block.([]any)
	if !ok {
		list = []any{}
	}
	return list, nil
}

// officeFields mirrors OFFICE_FIELDS: the facts the install wizard writes about this office.
var officeFields = []string{"name", "animal", "hue", "terms_version", "terms_accepted_at", "installed_at"}

// OfficeBlock is office_block(): the `office:` fields the file declares, in its order, each as str()
// spells it (a null is no field); empty when the file cannot be read or has no such block. It is what
// office-get prints and the control plane's GET /api/office answers as `office`.
func OfficeBlock(repo string) (*yamlish.Map, error) {
	out := yamlish.NewMap()
	v, err := ReadState(repo)
	if errors.As(err, new(*fs.PathError)) {
		return out, nil // `except OSError: return {}`
	}
	if err != nil {
		return nil, fmt.Errorf("FATAL %s: %v", stateName, err)
	}
	doc, err := mapping(v, stateName)
	if err != nil {
		return nil, err
	}
	v, _ = doc.Get("office")
	block, ok := v.(*yamlish.Map)
	if !ok {
		return out, nil
	}
	for _, k := range block.Keys() {
		if v, _ := block.Get(k); v != nil && contains(officeFields, k) {
			out.Set(k, pyval.Str(v))
		}
	}
	return out, nil
}

// composeServices is compose_services(app): the service names the app's own compose file declares,
// in the file's order; none for an app that declares no compose file (a blueprint, a library).
func composeServices(repo string, app *App) ([]string, error) {
	services, err := composeServiceMap(repo, app)
	if err != nil || services == nil {
		return nil, err
	}
	return services.Keys(), nil
}

// composeServiceMap is the `services:` mapping of the app's own compose file, nil when it declares
// none — read where compose_services reads it, stopping where it stops.
func composeServiceMap(repo string, app *App) (*yamlish.Map, error) {
	comp := app.Raw["compose"]
	if !truthy(comp) {
		return nil, nil
	}
	rel, ok := comp.(string)
	if !ok { // the path join raises
		return nil, died("%s: compose is %s, not a path", app.ID, pyval.Repr(comp))
	}
	p := joinPath(app.Dir, rel)
	shown := p
	if r, under := strings.CutPrefix(p, repo+string(filepath.Separator)); under {
		shown = r // the path as Python's relative_to(REPO) prints it, in this OS's separators
	}
	raw, err := os.ReadFile(p)
	if err == nil && !utf8.Valid(raw) {
		err = errors.New("not UTF-8")
	}
	if err != nil {
		return nil, died("%s: %v", shown, err)
	}
	v, err := yamlish.Unmarshal(raw)
	if err != nil {
		return nil, died("%s: %v", shown, err)
	}
	doc, err := mapping(v, shown)
	if err != nil {
		return nil, err
	}
	sv, _ := doc.Get("services")
	services, err := mapping(sv, shown+": services")
	if err != nil {
		return nil, err
	}
	return services, nil
}

// joinPath is pathlib's `dir / rel`: rel itself when it is absolute; on Windows a rel with a root
// but no drive ("/Users/…") lands on dir's drive and one with a drive but no root ("D:x") on that
// drive; else rel is appended — without cleaning "..", which realPath or the OS resolves as Python
// leaves it to.
func joinPath(dir, rel string) string {
	rel = filepath.FromSlash(rel)
	vol := filepath.VolumeName(rel)
	switch {
	case filepath.IsAbs(rel):
		return rel
	case vol == "" && strings.HasPrefix(rel, string(filepath.Separator)): // a root, no drive (Windows only)
		return filepath.VolumeName(dir) + rel
	case vol != "" && !strings.EqualFold(vol, filepath.VolumeName(dir)): // another drive, no root
		return rel
	}
	return dir + string(filepath.Separator) + rel[len(vol):]
}

// realPath is os.path.realpath(p, strict=False) for an absolute p — what pathlib's resolve() answers.
// On Windows the path is normalised first ("nope\..\flows" is "flows" lexically, as ntpath does); on
// other systems each component is resolved in turn — a link followed, a component that is not there
// kept as it is and then taken away by "..", as posixpath does — so the two agree where Python's do.
func realPath(p string) string {
	if runtime.GOOS == "windows" {
		return filepath.Clean(p)
	}
	path, _ := joinReal("/", strings.TrimPrefix(p, "/"), map[string]*string{})
	return path
}

// joinReal is posixpath._joinrealpath: rest resolved onto path, one component at a time; false when
// a link loops (the rest is then appended unresolved, as Python returns it).
func joinReal(path, rest string, seen map[string]*string) (string, bool) {
	join := func(a, b string) string {
		if strings.HasSuffix(a, "/") {
			return a + b
		}
		return a + "/" + b
	}
	for rest != "" {
		var name string
		name, rest, _ = strings.Cut(rest, "/")
		switch name {
		case "", ".":
			continue
		case "..":
			if dir, base := posixSplit(path); base == ".." {
				path = join(join(dir, ".."), "..")
			} else {
				path = dir
			}
			continue
		}
		next := join(path, name)
		fi, err := os.Lstat(next)
		if err != nil || fi.Mode()&os.ModeSymlink == 0 {
			path = next
			continue
		}
		if done, ok := seen[next]; ok {
			if done == nil {
				return join(next, rest), false // a loop
			}
			path = *done
			continue
		}
		seen[next] = nil
		target, err := os.Readlink(next)
		if err != nil {
			path = next
			continue
		}
		var ok bool
		if strings.HasPrefix(target, "/") {
			path, ok = joinReal("/", target[1:], seen)
		} else {
			path, ok = joinReal(path, target, seen)
		}
		if !ok {
			return join(path, rest), false
		}
		resolved := path
		seen[next] = &resolved
	}
	return path, true
}

// posixSplit is posixpath.split: everything up to the last "/" (trailing slashes trimmed, unless it is
// all slashes), and what follows it.
func posixSplit(p string) (string, string) {
	i := strings.LastIndex(p, "/") + 1
	head, tail := p[:i], p[i:]
	if head != "" && strings.Trim(head, "/") != "" {
		head = strings.TrimRight(head, "/")
	}
	return head, tail
}

// checkoutRelative is `Path(p).resolve().relative_to(REPO).as_posix()`: links resolved on both sides,
// forward slashes; a directory outside the checkout is where reconcile.py stops (ValueError).
func checkoutRelative(repo, p string) (string, error) {
	real, err := filepath.EvalSymlinks(p)
	if err != nil {
		return "", fmt.Errorf("FATAL %s: %v", p, err)
	}
	root, err := filepath.EvalSymlinks(repo)
	if err != nil {
		return "", fmt.Errorf("FATAL %s: %v", repo, err)
	}
	rel, err := filepath.Rel(root, real)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("FATAL %s is not inside the checkout %s", real, root)
	}
	return filepath.ToSlash(rel), nil
}

// countEntries is len(list(d.rglob("*"))): every file and directory below d, hidden ones included —
// a link counted, never followed, as Python 3.12 walks.
func countEntries(dir string) int {
	list, err := os.ReadDir(dir)
	if err != nil {
		return 0
	}
	n := len(list)
	for _, e := range list {
		if e.IsDir() {
			n += countEntries(filepath.Join(dir, e.Name()))
		}
	}
	return n
}

func asciiDigits(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return s != ""
}

// csv is main()'s csv(): every value of a repeatable option split on commas and whitespace, the
// empty pieces dropped — `--for a,b --for c` is a, b, c.
func csv(vals []string) []string {
	var out []string
	for _, v := range vals {
		out = append(out, strings.FieldsFunc(v, func(r rune) bool { return r == ',' || pyval.IsSpace(r) })...)
	}
	return out
}

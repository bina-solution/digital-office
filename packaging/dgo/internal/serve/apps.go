package serve

import (
	"errors"
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/compiler"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/pyval"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/screen"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// apps is api_apps() where this office has no container engine at all — the phone's native core
// (DGO-1090), which builds this server with NewNative: the install wizard's first question. There
// _container_index() is None, so every app's runtime is "unknown" and its Started and Ready are Unknown
// (DockerUnavailable), and the answer is the office's state file and its manifests, nothing else. On an
// office with an engine the container answers it, as before: its index is live state this process
// cannot see.
//
// What app.py would read otherwise than this does, or raise on (its 500 is Python's own wording), is
// the container's — on the phone, the proxy's 502, never a guess: a readable .env (_repo_env reads it),
// a compose file that is there (_services_of parses it), a state file or a manifest the compiler's
// readers refuse, a shape Python dereferences and fails on, an id or a generation's name not ASCII.
func (s *server) apps(w http.ResponseWriter, r *http.Request) bool {
	if !s.engineless {
		return false
	}
	s.syncMachine(r) // the machine's own state, once a boot and in the background: the next catalog shows it
	doc, err := s.catalog()
	if err != nil {
		return s.unvouched(r, err)
	}
	reply(w, http.StatusOK, doc)
	return true
}

// screenDir is where an office root carries app-management's screen (office-root.sh): its static/ as the
// container's image does.
var screenDir = filepath.Join("platform-base", "app-management", "static")

// screen is app.py's index() and static_files() where this office has no container engine — the phone's core
// (DGO-1328): «אפליקציות» is app-management's screen, and on a phone there is no container to serve it, so the
// tile answered «the machine is not on this phone» though the calls it opens with (api/apps, enable, job,
// office) are answered here; its other verbs (catalog, room, archive, apply, uninstall, move) are still the
// container's, so on the phone they answer Absent. send_from_directory's files, from the office root: a
// regular file under screenDir, reached through no link, no `..`, no backslash, no hidden name (screen.Serve);
// anything else — or a root that carries no screen — is the container's (on the phone, Absent), as before.
func (s *server) screen(w http.ResponseWriter, r *http.Request) bool {
	return s.engineless && screen.Serve(w, r, filepath.Join(s.repo, screenDir))
}

// catalog is _catalog() with `cidx` None, wrapped as api_apps() answers it.
func (s *server) catalog() (*yamlish.Map, error) {
	if f, err := os.Open(filepath.Join(s.repo, ".env")); err == nil {
		f.Close()
		return nil, errors.New("a .env is here, and _repo_env reads it")
	}
	entries, err := stateApps(s.repo)
	if err != nil {
		return nil, err
	}
	cat, err := compiler.LoadCatalog(s.repo)
	if err != nil {
		return nil, err
	}
	gen, err := generation(s.repo)
	if err != nil {
		return nil, err
	}
	if !utf8.ValidString(s.project) { // os.environ's surrogateescape would write what Go cannot
		return nil, errors.New("COMPOSE_PROJECT is not UTF-8")
	}
	var ids []string
	for id, app := range cat.Apps {
		if strings.HasPrefix(id, ".") { // glob does not see a directory whose name begins with a dot
			continue
		}
		for i := 0; i < len(id); i++ {
			if id[i] >= 0x80 {
				return nil, fmt.Errorf("the app id %q is not ASCII", id)
			}
		}
		// a manifest's own `_broken` survives _load_manifests, and app.py lists it as broken
		if compiler.Truthy(get(app.Doc(), "_broken")) {
			return nil, fmt.Errorf("%s: its manifest says _broken", id)
		}
		ids = append(ids, id)
	}
	// _load_manifests' order — apps/ sorted, then platform-base/ — in which app.py stamps the conditions
	sort.Slice(ids, func(i, j int) bool {
		ai, aj := cat.Apps[ids[i]].Root == "apps", cat.Apps[ids[j]].Root == "apps"
		if ai != aj {
			return ai
		}
		return ids[i] < ids[j]
	})
	pending := map[[2]string][2]string{} // the stamps this answer takes, kept only if it is answered
	// _unmet_deps runs over every app's `use` and every manifest's `capabilities`: where it would raise,
	// so does the catalog
	for _, id := range ids {
		if err := deps(cat.Apps[id].Doc(), cat, ids); err != nil {
			return nil, fmt.Errorf("%s: %v", id, err)
		}
	}
	var apps []*yamlish.Map
	for _, id := range ids {
		a, err := s.entry(cat.Apps[id], entries, gen, pending)
		if err != nil {
			return nil, fmt.Errorf("%s: %v", id, err)
		}
		apps = append(apps, a)
	}
	s.mu.Lock()
	for k, v := range pending {
		s.stamps[k] = v
	}
	s.mu.Unlock()
	key := func(a *yamlish.Map) (bool, bool, string) {
		core, _ := a.Get("core")
		enabled, _ := a.Get("enabled")
		id, _ := a.Get("id")
		return core.(bool), !enabled.(bool), id.(string)
	}
	sort.SliceStable(apps, func(i, j int) bool { // (core, not enabled, id)
		ci, ei, ii := key(apps[i])
		cj, ej, ij := key(apps[j])
		if ci != cj {
			return !ci
		}
		if ei != ej {
			return !ei
		}
		return ii < ij
	})
	installable, core := 0, 0
	list := make([]any, len(apps))
	for i, a := range apps {
		list[i] = a
		if c, _ := a.Get("core"); c.(bool) {
			core++
		} else {
			installable++
		}
	}
	counts := object("total", len(apps), "installable", installable, "running", 0, "core", core)
	return object("project", s.project, "counts", counts, "apps", list), nil
}

// stateApps is _load_state(): the state file's `apps:` — {} for a file that is not there, and the
// container's for one this reader refuses (PyYAML might read it) or one whose top or `apps` is not a
// mapping where app.py fails on it.
func stateApps(repo string) (*yamlish.Map, error) {
	doc, err := compiler.ReadState(repo)
	switch {
	case errors.As(err, new(*fs.PathError)):
		return yamlish.NewMap(), nil
	case err != nil:
		return nil, err
	case !compiler.Truthy(doc):
		return yamlish.NewMap(), nil
	}
	top, ok := doc.(*yamlish.Map)
	if !ok {
		return nil, errors.New("the state file is not a mapping, and app.py fails on it")
	}
	apps, _ := top.Get("apps")
	if !compiler.Truthy(apps) {
		return yamlish.NewMap(), nil
	}
	m, ok := apps.(*yamlish.Map)
	if !ok {
		return nil, errors.New("apps: is not a mapping, and app.py fails on it")
	}
	// a key YAML typed (80:, yes:) can share its spelling with a string key, which this reader merges
	for _, k := range m.Keys() {
		if _, isStr := m.TypedKey(k).(string); !isStr {
			return nil, fmt.Errorf("apps: the key %s is not a string", k)
		}
	}
	return m, nil
}

// generation is _generation(): the highest number among .generated/generations' names, 0 for none — a
// name that is not ASCII is left to the container (app.py skips it too since DGO-632's rule: stepping
// aside stays right).
func generation(repo string) (int, error) {
	des, err := os.ReadDir(filepath.Join(repo, ".generated", "generations"))
	if err != nil {
		return 0, nil
	}
	best := 0
	for _, d := range des {
		n := d.Name()
		digits := n != ""
		for i := 0; i < len(n); i++ {
			if n[i] >= 0x80 {
				return 0, fmt.Errorf("a generation named %q", n)
			}
			digits = digits && n[i] >= '0' && n[i] <= '9'
		}
		if !digits {
			continue
		}
		v, err := strconv.Atoi(n)
		if err != nil {
			return 0, fmt.Errorf("a generation named %q", n)
		}
		if v > best {
			best = v
		}
	}
	return best, nil
}

// hashable is a value a Python set or `in` takes: a scalar, never a dict or a list.
func hashable(v any) bool {
	switch v.(type) {
	case *yamlish.Map, []any:
		return false
	}
	return true
}

// deps refuses where _unmet_deps would raise: a `use` that does not iterate, a hard use's unhashable
// strength or capability, a provider's `capabilities` that does not iterate or holds an entry that is
// neither a name nor an object with a hashable name. Its answer is never used here (no runtime is known).
func deps(m *yamlish.Map, cat *compiler.Catalog, ids []string) error {
	use, _ := m.Get("use")
	if !compiler.Truthy(use) {
		return nil
	}
	list, isList := use.([]any)
	if !isList {
		if _, isStr := use.(string); isStr {
			return nil // its characters are not objects: each is skipped
		}
		return errors.New("use: is not a list, and _unmet_deps fails on it")
	}
	for _, u := range list {
		um, ok := u.(*yamlish.Map)
		if !ok {
			continue
		}
		strength, has := um.Get("strength")
		if !has {
			strength = "requires"
		}
		if !hashable(strength) {
			return errors.New("a use's strength is not hashable")
		}
		if st, _ := strength.(string); st != "requires" && st != "requisite" && st != "binds_to" {
			continue
		}
		want, _ := um.Get("capability")
		if !hashable(want) {
			return errors.New("a use's capability is not hashable")
		}
		for _, other := range ids {
			caps, _ := cat.Apps[other].Doc().Get("capabilities")
			if !compiler.Truthy(caps) {
				continue
			}
			if _, isStr := caps.(string); isStr {
				continue
			}
			cl, ok := caps.([]any)
			if !ok {
				return fmt.Errorf("%s: capabilities: is not a list", other)
			}
			for _, c := range cl {
				switch cv := c.(type) {
				case string:
				case *yamlish.Map:
					if name, _ := cv.Get("name"); !hashable(name) {
						return fmt.Errorf("%s: a capability's name is not hashable", other)
					}
				default:
					return fmt.Errorf("%s: a capability is neither a name nor an object", other)
				}
			}
		}
	}
	return nil
}

// mapOr is `v or {}` where app.py then calls .get on it: a falsy value is an empty mapping, a truthy
// one must be a mapping.
func mapOr(v any, what string) (*yamlish.Map, error) {
	if !compiler.Truthy(v) {
		return yamlish.NewMap(), nil
	}
	m, ok := v.(*yamlish.Map)
	if !ok {
		return nil, fmt.Errorf("%s is not a mapping, and app.py fails on it", what)
	}
	return m, nil
}

// get is a mapping's value, nil where it has none (dict.get).
func get(m *yamlish.Map, k string) any { v, _ := m.Get(k); return v }

// opensInside is app-management's opens_inside (11d4b258, DGO-1502): «פתיחה» opens the app INSIDE the
// console exactly when the console has a tile for it. `tile: false` never does (a door with no tile);
// an app on its own host (`external`) always does; any other module does when it has an alias and is
// not `embed: false`. Python's `is False` is identity with the boolean, so a 0 or an empty text is not
// False there, and is not here.
func opensInside(module *yamlish.Map) bool {
	isFalse := func(k string) bool {
		v, ok := module.Get(k)
		b, isBool := v.(bool)
		return ok && isBool && !b
	}
	if isFalse("tile") {
		return false
	}
	if compiler.Truthy(get(module, "external")) {
		return true
	}
	return compiler.Truthy(get(module, "alias")) && !isFalse("embed")
}

// or is Python's `a or b`.
func or(vs ...any) any {
	for _, v := range vs[:len(vs)-1] {
		if compiler.Truthy(v) {
			return v
		}
	}
	return vs[len(vs)-1]
}

// entry is one app of _catalog(), as app.py builds it with no docker view.
func (s *server) entry(app *compiler.App, entries *yamlish.Map, gen int, pending map[[2]string][2]string) (*yamlish.Map, error) {
	aid, m := app.ID, app.Doc()
	raw, said := entries.Get(aid) // state.get(aid) — every key a string (stateApps)
	entry, err := mapOr(raw, "its state entry")
	if err != nil {
		return nil, err
	}
	dispo, err := compiler.Disposition(raw)
	if err != nil {
		return nil, err
	}
	// …an app the office runs unless its state says otherwise («מכולות», compiler.OnUnlessSaid)
	if !said && slices.Contains(compiler.OnUnlessSaid, aid) {
		dispo = "enabled"
	}
	by := get(entry, "by")
	if !hashable(by) {
		return nil, errors.New("its state entry's `by` is not a scalar")
	}
	enabled, archived := dispo == "enabled", dispo == "archived"

	// the UI's routing entry: the first that declares a module, else the first
	routing := []any{yamlish.NewMap()}
	if v := get(m, "routing"); compiler.Truthy(v) {
		list, ok := v.([]any)
		if !ok {
			return nil, errors.New("routing: is not a list")
		}
		routing = list
	}
	var ui *yamlish.Map
	for _, rv := range routing {
		rm, ok := rv.(*yamlish.Map)
		if !ok {
			return nil, errors.New("a routing entry is not a mapping")
		}
		if compiler.Truthy(get(rm, "module")) {
			ui = rm
			break
		}
	}
	if ui == nil {
		ui = routing[0].(*yamlish.Map)
	}
	module, err := mapOr(get(ui, "module"), "its module")
	if err != nil {
		return nil, err
	}
	var launch any
	if host := get(ui, "host"); compiler.Truthy(host) {
		h, ok := host.(string)
		if !ok {
			return nil, errors.New("its routing host is not text")
		}
		path := ""
		if u := get(module, "url"); compiler.Truthy(u) {
			us, ok := u.(string)
			if !ok {
				return nil, errors.New("its module url is not text")
			}
			path = pyval.Strip(us)
		}
		sso, err := mapOr(get(ui, "sso"), "its sso")
		if err != nil {
			return nil, err
		}
		env := ""
		if v := get(sso, "base_url_env"); compiler.Truthy(v) {
			if env, ok = v.(string); !ok {
				return nil, errors.New("its sso.base_url_env is not text")
			}
		}
		origin := publicOrigin(aid, h, env)
		url := origin
		switch {
		case path != "" && !strings.HasPrefix(path, "http://") && !strings.HasPrefix(path, "https://"):
			url = origin + "/" + strings.TrimLeft(path, "/")
		case path != "":
			url = path
		}
		if !utf8.ValidString(url) { // an environment value os.environ reads with surrogateescape
			return nil, errors.New("its launch URL is not UTF-8")
		}
		// screen: the app declared one of its own (a routing entry with a module, and not `tile: false`, whose
		// screen lives in another app) — what the console's screen search offers (DGO-1760); app.py's
		// `bool(r_ui.get("module")) and module.get("tile") is not False`
		tile, said := module.Get("tile")
		noTile, isBool := tile.(bool)
		launch = object("url", url, "embed", opensInside(module), "module", or(get(module, "id"), aid),
			"screen", compiler.Truthy(get(ui, "module")) && !(said && isBool && !noTile))
	}
	services := []any{}
	if c := get(m, "compose"); compiler.Truthy(c) {
		name, ok := c.(string)
		if !ok {
			return nil, errors.New("compose: is not text")
		}
		path := name // os.path.join(_dir, name): an absolute name stands alone, nothing is cleaned
		if !filepath.IsAbs(name) {
			path = app.Dir + string(os.PathSeparator) + name
		}
		if _, err := os.Stat(path); err == nil {
			return nil, errors.New("its compose file is here, and _services_of parses it")
		}
	}
	title, err := mapOr(get(m, "title"), "its title")
	if err != nil {
		return nil, err
	}
	summary, err := mapOr(get(m, "summary"), "its summary")
	if err != nil {
		return nil, err
	}
	data, err := mapOr(get(m, "data"), "its data")
	if err != nil {
		return nil, err
	}
	onUninstall, has := data.Get("on_uninstall")
	if !has {
		onUninstall = "keep"
	}
	volumes := or(get(data, "volumes"), []any{})

	// the conditions, with no docker view: Resolved, Installed, then Unknown — or the archived four
	var conds []any
	c := func(typ, status, reason, message string) {
		conds = append(conds, object("type", typ, "status", status, "reason", reason, "message", message,
			"observedGeneration", gen, "lastTransitionTime", s.stamp(aid, typ, status, pending)))
	}
	c("Resolved", "True", "InCatalog", "")
	switch {
	case archived:
		c("Installed", "True", "Archived", "images removed, data kept")
		c("Started", "False", "Archived", "")
		c("Ready", "False", "Archived", "unarchive to run")
	default:
		if enabled {
			c("Installed", "True", "ContainersPresent", "")
		} else {
			c("Installed", "False", "NotInstalled", "")
		}
		c("Started", "Unknown", "DockerUnavailable", "")
		c("Ready", "Unknown", "DockerUnavailable", "")
	}

	return object(
		"id", aid,
		"name", or(get(title, "he"), get(title, "en"), aid),
		"name_en", or(get(title, "en"), aid),
		"summary", or(get(summary, "he"), get(summary, "en"), ""),
		"layer", get(m, "layer"),
		"kind", get(m, "kind"),
		"version", get(m, "version"),
		"icon", or(get(module, "icon"), "app"),
		"core", app.Root == "platform-base",
		"launch", launch,
		"enabled", enabled,
		"conditions", conds,
		"state_desired", dispo,
		"archived", archived,
		"state_by", by,
		"installed", enabled || archived,
		"services", services,
		"on_uninstall", onUninstall,
		"volumes", volumes,
		// **rt with no docker view
		"state", "unknown", "running", nil, "total", len(services), "health", "unknown", "present", nil,
	), nil
}

// stamp is _stamp(): a condition's lastTransitionTime, held while its status is unchanged — in this
// process's memory, as app.py keeps it in its own. A new one goes into pending, which the catalog keeps
// only once its whole answer is given: an answer handed to the container takes no stamp.
func (s *server) stamp(aid, typ, status string, pending map[[2]string][2]string) string {
	k := [2]string{aid, typ}
	s.mu.Lock()
	prev, ok := s.stamps[k]
	s.mu.Unlock()
	if ok && prev[0] == status {
		return prev[1]
	}
	at := s.now().UTC().Format("2006-01-02T15:04:05Z")
	pending[k] = [2]string{status, at}
	return at
}

// envRef is _repo_env's ${NAME} and ${NAME:-default}.
var envRef = regexp.MustCompile(`\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}`)

// repoEnv is _repo_env() where there is no .env (catalog refuses one): the process's variable, its
// references expanded five deep, stripped.
func repoEnv(name string, depth int) string {
	v := pyval.Strip(os.Getenv(name))
	if strings.Contains(v, "${") && depth < 5 {
		v = envRef.ReplaceAllStringFunc(v, func(ref string) string {
			sm := envRef.FindStringSubmatch(ref)
			if got := repoEnv(sm[1], depth+1); got != "" {
				return got
			}
			return sm[2]
		})
	}
	return pyval.Strip(v)
}

// isLocalhost is _is_localhost(): the hostname alone, port and path aside.
func isLocalhost(v string) bool {
	h := v // re.sub(r"^https?://", "", v): the scheme, once, at the start
	if strings.HasPrefix(h, "http://") {
		h = h[len("http://"):]
	} else if strings.HasPrefix(h, "https://") {
		h = h[len("https://"):]
	}
	h, _, _ = strings.Cut(h, "/")
	if i := strings.LastIndex(h, ":"); i >= 0 {
		h = h[:i]
	}
	h = compiler.PyLower(h)
	return h == "localhost" || strings.HasSuffix(h, ".localhost")
}

// publicOrigin is _public_origin(): the routing entry's own sso.base_url_env, then <APP>_BASE_URL, then
// <host>.<DEPLOYMENT_DOMAIN>, then <host>.localhost.
func publicOrigin(aid, host, baseEnv string) string {
	v := ""
	for _, name := range []string{baseEnv, compiler.BaseURLEnv(aid)} {
		v = ""
		if name != "" {
			v = repoEnv(name, 0)
		}
		if v != "" {
			break
		}
	}
	if v != "" {
		if !strings.HasPrefix(v, "http://") && !strings.HasPrefix(v, "https://") {
			if isLocalhost(v) {
				v = "http://" + v
			} else {
				v = "https://" + v
			}
		}
		return strings.TrimRight(v, "/")
	}
	dom := repoEnv("DEPLOYMENT_DOMAIN", 0)
	if dom == "" {
		dom = repoEnv("COMPANY_BASE_DOMAIN", 0)
	}
	if dom != "" && dom != "localhost" {
		return "https://" + host + "." + dom
	}
	return "http://" + host + ".localhost"
}

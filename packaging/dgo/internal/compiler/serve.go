package compiler

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── the reverse plane: the apps of linked offices, shown and routed HERE (platform/manager/serve.py) ─
//
// planRemote (remote.go) accepts the `remote:` block; what follows turns its entries into the four
// things this office serves them through — the traefik file (render), the network aliases of the
// link proxy (render_aliases), the console's tiles (module_entries) and the sign-in hosts
// (sso_hosts) — and the `serve-plan` verb that prints them. Every name, port and header below is
// serve.py's, byte for byte: the oracle diffs the files they land in.

const (
	signedInPath = "/.dgo/signed-in" // SIGNED_IN_PATH: answered by this office, never forwarded
	enterPath    = "/.dgo/enter"     // ENTER_PATH: this office's sign-in, then the console again
)

// ownHost is OWN_HOST: what the tile of an app that keeps its own host names — the question and the
// way in.
var ownHost = [][2]string{{"signed_in", signedInPath}, {"enter", enterPath}}

// servedOf is serve.plan(state, cat) through source(): the `remote:` block when it declares anything,
// else the legacy `serve:` one; nothing to plan is no entries, and a block that is not a list one
// refusal.
func servedOf(repo string, st *State) ([]remoteEntry, []string, error) {
	name := "remote"
	raw, _ := st.Doc.Get("remote")
	if noBlock(raw) {
		name = "serve"
		raw, _ = st.Doc.Get("serve")
	}
	if noBlock(raw) {
		return nil, nil, nil
	}
	block, ok := raw.([]any)
	if !ok {
		return nil, []string{fmt.Sprintf("%s: חייב להיות רשימה של לשכות מרוחקות (office/address/apps), לא %s", name, pyTypeName(raw))}, nil
	}
	return planRemote(repo, name, block)
}

// noBlock is `v in (None, [], {})`.
func noBlock(v any) bool {
	switch t := v.(type) {
	case nil:
		return true
	case []any:
		return len(t) == 0
	case *yamlish.Map:
		return t.Len() == 0
	}
	return false
}

// consoleHost is `(console_routes[0].get("host") if console_routes else "") or "console"`, and the
// console's first route ({} when it has none).
func consoleHost(cat *Catalog) (string, *yamlish.Map, error) {
	first := yamlish.NewMap()
	if console := cat.Apps["console"]; console != nil {
		var err error
		if first, err = firstRouting(console.doc, "console"); err != nil {
			return "", nil, err
		}
	}
	return pyval.Str(either(get(first, "host"), "console")), first, nil
}

// ── the office's mark: apps/dgo-extend/identity.py's vocabulary ─────────────────────────────────────

// The mark a linked office is drawn with — a palette family's NAME and a glyph's NAME — is dgo-extend's
// (identity.py: OFFICE_HUES, OFFICE_ANIMALS, HUES_ALIAS, NAMED_MARKS, HANDLE_ALIASES); serve.py imports
// it from the app, and a checkout without the app draws no mark. A compiled binary cannot import a
// Python module, so this is its copy, held to the app's own file by TestMarksAreDgoExtends.
var (
	officeHueNames = []string{"grey", "lime", "sky", "olive", "plum", "blue", "violet"}
	officeAnimals  = []string{"elephant", "deer", "eagle", "owl", "fox", "horse", "raven", "hare", "lion", "swan"}
	hueAliases     = map[string]string{"muted": "grey"}
	namedMarks     = map[string][2]string{"hp": {"grey", "elephant"}, "macbook": {"lime", "deer"}, "vps": {"sky", "eagle"}}
	handleAliases  = map[string]string{"hp-laptop": "hp", "vps1": "vps"}
)

// officeMark is _mark(value, office): the mark the office published when it is one the vocabularies
// know (clean_mark), else the one its name gets (mark_for) — nil where dgo-extend is not installed.
func officeMark(repo string, value any, office string) *yamlish.Map {
	if !isRegular(filepath.Join(repo, "apps", "dgo-extend", "identity.py")) {
		return nil
	}
	if m, ok := value.(*yamlish.Map); ok {
		color := pyLower(pyval.Strip(pyval.Str(either(get(m, "color"), ""))))
		if alias, ok := hueAliases[color]; ok {
			color = alias
		}
		animal := pyLower(pyval.Strip(pyval.Str(either(get(m, "animal"), ""))))
		if contains(officeHueNames, color) && contains(officeAnimals, animal) {
			return ordered("color", color, "animal", animal)
		}
	}
	name := pyLower(pyval.Strip(office))
	pair, named := namedMarks[name]
	if !named {
		pair, named = namedMarks[handleAliases[name]]
	}
	if !named { // a hash of the name picks from what the owner's three offices do not wear
		var free []string
		for _, h := range officeHueNames {
			taken := false
			for _, p := range namedMarks {
				taken = taken || p[0] == h
			}
			if !taken {
				free = append(free, h)
			}
		}
		sum := sha256.Sum256([]byte(name))
		digest, _ := strconv.ParseUint(hex.EncodeToString(sum[:4]), 16, 64)
		n := uint64(len(free))
		pair = [2]string{free[digest%n], officeAnimals[(digest/n)%uint64(len(officeAnimals))]}
	}
	return ordered("color", pair[0], "animal", pair[1])
}

// ── what the entries are rendered into ──────────────────────────────────────────────────────────────

// throughConsole is through_console(app): may it be framed through this console's own origin? Only an
// app embedded at home that names the authority it answers under.
func throughConsole(a remoteApp) bool { return a.moduleKind != "external" && a.host != "" }

// tileless is _tileless(): the app's own manifest, in THIS office's catalog, declares every routed
// module `tile: false` (DGO-890) — a door that draws no tile here, nor on a linked office's console.
func tileless(cat *Catalog, appID string) bool {
	a := cat.Apps[appID]
	if a == nil {
		return false
	}
	routes, err := dicts(get(a.doc, "routing"), appID+": routing")
	if err != nil {
		return false
	}
	n := 0
	for _, r := range routes {
		m, ok := get(r, "module").(*yamlish.Map)
		if !ok || m.Len() == 0 {
			continue
		}
		n++
		if getOr(m, "tile", true) != false {
			return false
		}
	}
	return n > 0
}

// moduleEntries is module_entries(): the console tile of each remote app, one per (office, alias) —
// external, namespaced `<alias>.<office>`, marked with its office. The office's label and mark are the
// entry's own objects, as in Python, so the registry writes them once and refers to them after. An app
// this office's catalog declares tileless draws none.
func moduleEntries(served []remoteEntry, cat *Catalog) []any {
	var out []any
	for _, e := range served {
		for _, a := range e.apps {
			if tileless(cat, a.app) {
				continue
			}
			tile := a.alias + "." + e.office
			t := ordered("id", tile, "name", a.name, "icon", a.icon, "group", a.group,
				"desc", strings.Trim(a.desc+" · "+pyval.Str(get(e.label, "he")), " ·"),
				"order", a.order, "external", true, "host", tile, "embed", "/a/"+a.alias+"/")
			if throughConsole(a) {
				from := make([]any, len(e.identFrom))
				for i, u := range e.identFrom {
					from[i] = u
				}
				t.Set("proxy", "/a/"+tile+"/")
				t.Set("door", ordered("base", fmt.Sprintf("http://%s:%d", tile, door(e, a)), "host", a.host,
					"user", either(e.identTo, ""), "from", from))
			} else {
				for _, kv := range ownHost {
					t.Set(kv[0], kv[1])
				}
			}
			var mark any
			if e.mark != nil {
				mark = e.mark
			}
			t.Set("office", e.office)
			t.Set("label", e.label)
			t.Set("remote", ordered("office", e.office, "label", e.label, "link", either(e.link, e.office),
				"address", e.address, "commit", e.commit, "mark", mark, "port", a.port, "api_port", a.apiPort,
				"alias", a.alias, "module_id", a.moduleID))
			out = append(out, t)
		}
	}
	return out
}

// door is `int(entry.get("link_port") or 0) or app["port"]`: the link's door when the office
// published one, else the app's own port.
func door(e remoteEntry, a remoteApp) int64 {
	if e.linkPort != 0 {
		return e.linkPort
	}
	return a.port
}

// ownOrigins is own_origins(): every Origin a page on host sends — each scheme it can arrive by, and
// the port it reached this edge on when that is not the scheme's own.
func ownOrigins(host string, entryPoints []string, port string) []any {
	var schemes []string
	// `lan` is plain HTTP like `web` (apps/lan-console: the office's console on its local network)
	if contains(entryPoints, "web") || contains(entryPoints, "lan") {
		schemes = append(schemes, "http")
	}
	if contains(entryPoints, "websecure") {
		schemes = append(schemes, "https")
	}
	ports := []string{""}
	if port != "" {
		ports = append(ports, ":"+port)
	}
	var out []any
	for _, p := range ports {
		for _, s := range schemes {
			out = append(out, s+"://"+host+p)
		}
	}
	return out
}

// strs is a list of text as a YAML/JSON list.
func strs(xs ...string) []any {
	out := make([]any, len(xs))
	for i, x := range xs {
		out[i] = x
	}
	return out
}

// serveRender is serve.render(): traefik's file-provider config for every remote app — two routers
// per host (the `.localhost` one and, on a domain, the TLS one with its http twin that redirects),
// the identity the serving office sees, the Host and Origin its app expects — and, for a host whose
// sign-in a frame cannot show (a remote app of its own host, or one of this office's framed apps), the
// question and the way in, answered here. "" when there is nothing to route. lanDomain/lanPort: the
// console's NAME on the office's local network (DGO-1126), one more form per app on the `lan` entry,
// signed in by that entry's own outpost (`lan-auth@docker`).
func serveRender(served []remoteEntry, cat *Catalog, domain, consolePort string, framed map[string]string, lanDomain, lanPort string) (string, error) {
	if len(served) == 0 && len(framed) == 0 {
		return "", nil
	}
	cHost, console, err := consoleHost(cat)
	if err != nil {
		return "", err
	}
	domain = pyval.Strip(either(domain, "localhost").(string))
	routers, services, middlewares := yamlish.NewMap(), yamlish.NewMap(), yamlish.NewMap()
	const (
		asksMW  = "dgo-remote-console-asks"
		answers = "dgo-remote-console-answers"
		returns = "dgo-remote-console-returns"
		httpsMW = "dgo-remote-https"
	)
	asked := false
	headers := func(k, v string) *yamlish.Map {
		return ordered("headers", ordered("customRequestHeaders", ordered(k, v)))
	}
	tls := func(r *yamlish.Map, entryPoints []string) {
		if contains(entryPoints, "websecure") {
			r.Set("tls", ordered("certResolver", "myresolver"))
		}
	}
	lanDomain = pyval.Strip(lanDomain)
	// doorOf: the sign-in in front of a form — the LAN entry's own outpost there, authentik's elsewhere
	doorOf := func(entryPoints []string) string {
		if len(entryPoints) == 1 && entryPoints[0] == "lan" {
			return "lan-auth@docker"
		}
		return "authentik@file"
	}
	ownHostRouters := func(name, host string, entryPoints []string) {
		auth := doorOf(entryPoints)
		for _, h := range []struct {
			tail, path string
			chain      []any
		}{
			{"signed-in", "Path(`" + signedInPath + "`)", strs(asksMW, auth, answers)},
			{"enter", "PathPrefix(`" + enterPath + "`)", strs(auth, returns)},
		} {
			r := ordered("rule", "Host(`"+host+"`) && "+h.path, "entryPoints", strs(entryPoints...),
				"service", answers, "middlewares", h.chain)
			tls(r, entryPoints)
			routers.Set(name+"-"+h.tail, r)
		}
		asked = true
	}
	for _, e := range served {
		mwName := "dgo-remote-" + e.office + "-identity"
		if e.identTo != nil {
			mw := headers("X-authentik-username", e.identTo.(string))
			if len(e.identFrom) > 0 {
				h, _ := mw.Get("headers")
				c, _ := h.(*yamlish.Map).Get("customRequestHeaders")
				c.(*yamlish.Map).Set("X-DGO-From", strings.Join(e.identFrom, ","))
			}
			middlewares.Set(mwName, mw)
		}
		for _, a := range e.apps {
			tile := a.alias + "." + e.office
			svc := "dgo-remote-" + e.office + "-" + a.alias
			services.Set(svc, ordered("loadBalancer", ordered(
				"servers", []any{ordered("url", fmt.Sprintf("http://%s:%d", tile, door(e, a)))},
				"passHostHeader", true)))
			baseMW := []string{"authentik@file"}
			if e.identTo != nil {
				baseMW = append(baseMW, mwName)
			}
			ownMW := ""
			if a.host != "" {
				hostMW := svc + "-host"
				middlewares.Set(hostMW, headers("Host", a.host))
				baseMW = append(baseMW, hostMW)
				ownMW = svc + "-own-origin"
				middlewares.Set(ownMW, headers("Origin", "http://"+a.host))
			}
			type form struct {
				name, host  string
				entryPoints []string
				port        string
			}
			forms := []form{{svc + "-console-local", tile + "." + cHost + ".localhost", []string{"web"}, ""}}
			if domain == "localhost" {
				forms[0].port = consolePort
			} else {
				forms = append(forms, form{svc + "-console", tile + "." + cHost + "." + domain, []string{"web", "websecure"}, ""})
			}
			if lanDomain != "" {
				forms = append(forms, form{svc + "-console-lan", tile + "." + cHost + "." + lanDomain, []string{"lan"}, lanPort})
			}
			for _, f := range forms {
				chain := make([]string, len(baseMW))
				for i, m := range baseMW {
					if m == "authentik@file" {
						m = doorOf(f.entryPoints)
					}
					chain[i] = m
				}
				router := func(rule string, chain []string) *yamlish.Map {
					r := ordered("rule", rule, "entryPoints", strs(f.entryPoints...), "service", svc, "middlewares", strs(chain...))
					tls(r, f.entryPoints)
					return r
				}
				routers.Set(f.name, router("Host(`"+f.host+"`)", chain))
				if contains(f.entryPoints, "websecure") {
					routers.Set(f.name+"-http", ordered("rule", "Host(`"+f.host+"`)", "entryPoints", strs("web"),
						"service", "noop@internal", "middlewares", strs(httpsMW)))
					middlewares.Set(httpsMW, ordered("redirectScheme", ordered("scheme", "https", "permanent", true)))
				}
				if ownMW != "" {
					var own []string
					for _, o := range ownOrigins(f.host, f.entryPoints, f.port) {
						own = append(own, "Header(`Origin`, `"+o.(string)+"`)")
					}
					routers.Set(f.name+"-own-origin", router("Host(`"+f.host+"`) && ("+strings.Join(own, " || ")+")",
						append(append([]string(nil), chain...), ownMW)))
				}
				if !throughConsole(a) {
					ownHostRouters(f.name, f.host, f.entryPoints)
				}
			}
		}
	}
	names := make([]string, 0, len(framed))
	for n := range framed {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		ownHostRouters(n, framed[n], []string{"web"})
	}
	if asked {
		consoles := []string{cHost + ".localhost"}
		port := consolePort
		if domain != "localhost" {
			consoles, port = append(consoles, cHost+"."+domain), ""
		}
		origins := ownOrigins(consoles[0], []string{"web"}, port)
		for _, wide := range consoles[1:] {
			origins = append(origins, ownOrigins(wide, []string{"web", "websecure"}, "")...)
		}
		if lanDomain != "" {
			consoles = append(consoles, cHost+"."+lanDomain)
			origins = append(origins, ownOrigins(consoles[len(consoles)-1], []string{"lan"}, lanPort)...)
		}
		middlewares.Set(asksMW, ordered("headers", ordered("accessControlAllowOriginList", origins,
			"accessControlAllowCredentials", true)))
		escaped := make([]string, len(consoles))
		for i, c := range consoles {
			escaped[i] = pyReEscape(c)
		}
		middlewares.Set(returns, ordered("redirectRegex", ordered(
			"regex", "^(https?://)[^/]+\\.("+strings.Join(escaped, "|")+")((?::[0-9]+)?)"+pyReEscape(enterPath)+"(.*)$",
			"replacement", "${1}${2}${3}/#${4}")))
		consolePortOf, err := pyInt(either(get(console, "port"), int64(8000)))
		if err != nil {
			return "", raisedAt("console: routing[0].port", err)
		}
		middlewares.Set(answers, ordered("replacePath", ordered("path", "/healthz")))
		services.Set(answers, ordered("loadBalancer", ordered("servers", []any{ordered("url",
			"http://"+pyval.Str(either(get(console, "service"), "console"))+":"+consolePortOf.Text)})))
	}
	http := yamlish.NewMap()
	if middlewares.Len() > 0 {
		http.Set("middlewares", middlewares)
	}
	http.Set("routers", routers)
	http.Set("services", services)
	body, err := yamlish.Marshal(ordered("http", http), yamlish.Options{Width: 1000})
	if err != nil {
		return "", err
	}
	return "# GENERATED by platform/manager/serve.py from platform.state.yaml `remote:` — DO NOT EDIT.\n" +
		"# The apps of another office, shown HERE under this office's SSO: one router per app on\n" +
		"# <alias>.<office>.<console host>.<domain>, forwarding to the link proxy's network alias.\n" +
		"# A FILE and not labels because traefik refuses an external server URL in a docker label.\n" + string(body), nil
}

// tileAliases is the sorted set of `<alias>.<office>` of every remote app.
func tileAliases(served []remoteEntry) []string {
	var out []string
	for _, e := range served {
		for _, a := range e.apps {
			if t := a.alias + "." + e.office; !contains(out, t) {
				out = append(out, t)
			}
		}
	}
	sort.Strings(out)
	return out
}

// renderAliases is serve.render_aliases(): the compose overlay that puts every `<alias>.<office>` on
// the link proxy's network — the name each router forwards to — or "" when no office is shown here.
func renderAliases(served []remoteEntry) (string, error) {
	// every app's, and every door's with no tile (DGO-945): an alias is all a door is on this side
	aliases := tileAliases(served)
	for _, e := range served {
		for _, d := range e.doors {
			if t := d.alias + "." + e.office; !contains(aliases, t) {
				aliases = append(aliases, t)
			}
		}
	}
	sort.Strings(aliases)
	if len(aliases) == 0 {
		return "", nil
	}
	body, err := yamlish.Marshal(ordered("services", ordered("dgo-net", ordered("networks",
		ordered("traefik-network", ordered("aliases", strs(aliases...)))))), yamlish.Options{Width: 1000})
	if err != nil {
		return "", err
	}
	return "# GENERATED by platform/manager/serve.py from platform.state.yaml `remote:` — DO NOT EDIT.\n" +
		"# One network alias per remote app on the link proxy's namespace (dgo-net): this is what\n" +
		"# makes `http://<alias>.<office>:<port>` resolve inside the office network, for the edge\n" +
		"# and for every agent. Applied by `dc up -d`, i.e. when the remote app set changes.\n" + string(body), nil
}

// ssoHost is one record of serve.sso_hosts(): the sign-in provider a remote app's nested host needs.
type ssoHost struct{ slug, name, host, portHost string }

// ssoHosts is serve.sso_hosts(): `<alias>.<office>.<console host>.<domain>` per remote app — the very
// string its router matches — and on `.localhost` the same host with the console's port.
func ssoHosts(served []remoteEntry, cat *Catalog, domain, consolePort string) ([]ssoHost, error) {
	cHost, _, err := consoleHost(cat)
	if err != nil {
		return nil, err
	}
	var out []ssoHost
	for _, e := range served {
		for _, a := range e.apps {
			framed := a.alias + "." + e.office + "." + cHost
			h := ssoHost{slug: "dgo-remote-" + e.office + "-" + a.alias,
				name: a.name + " · " + pyval.Str(get(e.label, "he")), host: framed + "." + domain}
			if domain == "localhost" {
				h.host = framed + ".localhost"
				if consolePort != "" {
					h.portHost = framed + ".localhost:" + consolePort
				}
			}
			out = append(out, h)
		}
	}
	return out, nil
}

// describe is serve.describe(): a flat, printable row per remote app — what serve-plan prints.
func describe(served []remoteEntry, cat *Catalog) ([]any, error) {
	cHost, _, err := consoleHost(cat)
	if err != nil {
		return nil, err
	}
	var rows []any
	for _, e := range served {
		for _, a := range e.apps {
			nested := a.alias + "." + e.office + "." + cHost
			rows = append(rows, ordered("office", e.office, "address", e.address, "app", a.app, "alias", a.alias,
				"host", nested+".<DEPLOYMENT_DOMAIN>", "local_host", nested+".localhost",
				"target", fmt.Sprintf("http://%s.%s:%d", a.alias, e.office, a.port), "tile", a.alias+"."+e.office,
				"identity_to", get(a.identity, "to"), "identity_from", get(a.identity, "from")))
		}
	}
	return rows, nil
}

// ServePlanCmd is `serve-plan`: what the `remote:` block routes — each app's hosts and target, the
// console's tiles, the network aliases, and where the two files go — as one JSON document; the plan's
// refusals on stderr and exit 1 instead, as `validate` refuses.
func ServePlanCmd(repo string, args []string, stdout, stderr io.Writer) int {
	if _, code, done := parseArgs("serve-plan", args, stdout, stderr); done {
		return code
	}
	cat, st, _, code := loadAndValidate(repo, stdout, stderr)
	if code != 0 {
		return code
	}
	served, errs, err := servedOf(repo, st)
	if err != nil {
		return failed(err, stderr)
	}
	for _, e := range errs {
		fmt.Fprintln(stderr, "  - "+e)
	}
	if len(errs) > 0 {
		return 1
	}
	rows, err := describe(served, cat)
	if err != nil {
		return failed(err, stderr)
	}
	fmt.Fprintln(stdout, yamlish.IndentJSON(ordered("remote", orEmptyList(rows), "tiles", orEmptyList(moduleEntries(served, cat)),
		"aliases", strs(tileAliases(served)...), "traefik", "platform-base/traefik/config/zz-serve.yaml",
		"aliases_file", ".generated/remote.override.yml")))
	return 0
}

// orEmptyList is a list that is [] rather than nil when it holds nothing.
func orEmptyList(xs []any) []any {
	if xs == nil {
		return []any{}
	}
	return xs
}

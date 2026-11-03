package compiler

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// serve.plan(): the `remote:` block — what linked offices give this one — checked and turned into the
// entries render routes and tiles (serve.go). Every entry becomes an edge route and a tile, and the
// block arrives from ANOTHER office, so it is refused here, a sentence per reason (in Hebrew, as the
// office reads them): before it is written (set_remote), and by every render and serve-plan after.
// One plan for the three, as in Python — and so is what plan() does to the block it is handed: it
// rewrites each app's `identity.to` and `identity.from` as strings, and set_remote writes the block
// so rewritten.

// serve.py's validators, each ending in `\Z` since DGO-615 (Python's `$` also matched before a trailing
// newline, so "alice\n" passed as an identity): compiled with Go's `\z`, which is `\Z`, and matched as
// written.
var (
	officeRE    = regexp.MustCompile(`^[a-z][a-z0-9-]{1,30}\z`)
	labelRE     = regexp.MustCompile(`^[a-z][a-z0-9-]{0,30}\z`)
	headerRE    = regexp.MustCompile(`^[A-Za-z0-9@._+\-]{1,128}\z`)
	authorityRE = regexp.MustCompile(`^[a-z0-9]([a-z0-9.\-]{0,251})?(:\p{Nd}{1,5})?\z`)
	wgAddress   = regexp.MustCompile(`^` + pyval.SpaceClass + `*Address` + pyval.SpaceClass + `*=` + pyval.SpaceClass + `*([0-9]{1,3}(?:\.[0-9]{1,3}){3})`)
)

// remoteApp is one app of a linked office as plan() accepts it (its `clean` row).
type remoteApp struct {
	app, alias                       string
	port                             int64
	apiPort                          any // its agent's second door, an int64 — nil when it publishes none
	name, nameEn, icon, group, desc  string
	order                            any // as the block has it (900 when it has none)
	host, health                     string
	moduleKind, modulePath, moduleID string
	identity                         *yamlish.Map // `to` and `from`, each only where set
}

// remoteDoor is one door with no tile a linked office gives this one (plan()'s `services`, DGO-945):
// only an address on this office's network (renderAliases), never a tile, a route or a sign-in.
type remoteDoor struct {
	app, alias string
	port       int64
}

// remoteEntry is one linked office as plan() accepts it.
type remoteEntry struct {
	office, address string
	apps            []remoteApp
	doors           []remoteDoor
	linkPort        int64
	label           *yamlish.Map // {he, en}: one object, shared by every tile of the office as in Python
	link, commit    string
	mark            *yamlish.Map // the office's colour and animal; nil without dgo-extend's vocabulary
	identTo         any          // the link's one `to`, or nil
	identFrom       []string
}

// planRemote is plan() over the block named `name` (remote, or the legacy serve): the entries it
// accepts and its refusals, in its order. An error is an exception plan() raises instead of refusing
// (it crashes reconcile.py).
func planRemote(repo, name string, block []any) ([]remoteEntry, []string, error) {
	var out []remoteEntry
	var errs []string
	refuse := func(format string, a ...any) { errs = append(errs, fmt.Sprintf(format, a...)) }
	seenOffice, seenLabel := map[string]bool{}, map[string]string{}
	var mine map[string]bool
	for i, item := range block {
		where := fmt.Sprintf("%s[%d]", name, i)
		entry, ok := item.(*yamlish.Map)
		if !ok {
			refuse("%s: חייב להיות אובייקט עם office, address ו-apps", where)
			continue
		}
		oid := pyLower(pyval.Strip(pyval.Str(orEmpty(get(entry, "office")))))
		if !officeRE.MatchString(oid) {
			refuse("%s.office %s אינו מזהה לשכה תקין", where, pyval.Repr(get(entry, "office")))
			continue
		}
		where = fmt.Sprintf("%s[%d] (%s)", name, i, oid)
		if seenOffice[oid] {
			refuse("%s.office: אותה לשכה מוצהרת פעמיים", where)
			continue
		}
		seenOffice[oid] = true

		addr := pyval.Strip(pyval.Str(orEmpty(get(entry, "address"))))
		ip, version := parseIP(addr)
		switch {
		case version == 0:
			refuse("%s.address %s אינה כתובת IPv4 — זו כתובת הלשכה המרוחקת במנהרה (למשל 10.79.3.2)", where, pyval.Repr(addr))
			continue
		case version == 6 || ip[0] != 10 || ip[1] != 79:
			refuse("%s.address %s מחוץ ל-10.79.0.0/16 — כתובת שנגישה מהאינטרנט אינה קישור, ובקשה שתישלח אליה לא תעבור במנהרה", where, addr)
			continue
		case ip[3] == 0 || ip[3] == 255:
			refuse("%s.address %s: x.0/x.255 הן כתובות רשת/שידור, לא כתובת של לשכה", where, addr)
			continue
		}
		if mine == nil {
			var err error
			if mine, err = ownAddresses(repo); err != nil {
				return nil, nil, err
			}
		}
		if mine[addr] {
			refuse("%s.address %s היא הכתובת של הלשכה הזו בקישור הזה (מ-.dgo) — הצד השני הוא הקצה האחר של אותו /24", where, addr)
			continue
		}

		rawDoors := get(entry, "services")
		doorList, isList := rawDoors.([]any)
		if rawDoors != nil && !isList {
			refuse("%s.services חייב להיות רשימה של דלתות (app, alias, port)", where)
			continue
		}
		// …and `apps` may be empty only beside a door (DGO-945): an office that gives this one a
		// capability and no screen at all.
		apps, ok := get(entry, "apps").([]any)
		if !ok || (len(apps) == 0 && len(doorList) == 0) {
			refuse("%s.apps חייב להיות רשימה של אפליקציות שהלשכה הזו מציגה", where)
			continue
		}
		var clean []remoteApp
		for j, item := range apps {
			at := fmt.Sprintf("%s.apps[%d]", where, j)
			app, ok := item.(*yamlish.Map)
			if !ok {
				refuse("%s חייב להיות אובייקט (app, port ועוד)", at)
				continue
			}
			field := func(k string) any { v, _ := app.Get(k); return v }
			aid := pyLower(pyval.Strip(pyval.Str(orEmpty(field("app")))))
			if !labelRE.MatchString(aid) {
				refuse("%s.app %s אינו מזהה אפליקציה תקין", at, pyval.Repr(field("app")))
				continue
			}
			alias := field("alias")
			if !truthy(alias) {
				alias = aid
			}
			label := pyLower(pyval.Strip(pyval.Str(alias)))
			if !labelRE.MatchString(label) {
				refuse("%s.alias %s אינו תווית מארח תקינה", at, pyval.Repr(field("alias")))
				continue
			}
			if owner, taken := seenLabel[oid+"."+label]; taken {
				refuse("%s.alias '%s' כבר נתפס על ידי %s — שתי אפליקציות של אותה לשכה לא יכולות לחלוק מארח", at, label, owner)
				continue
			}
			port, err := pyInt(field("port"))
			if err != nil {
				if errors.Is(err, errNotInt) {
					refuse("%s.port חייב להיות מספר — הפורט שהאפליקציה מאזינה עליו בלשכה שמגישה אותה", at)
					continue
				}
				return nil, nil, raisedAt(at+".port", err)
			}
			if !port.InRange(1, 65535) {
				refuse("%s.port %s מחוץ לטווח", at, port.Text)
				continue
			}
			var apiPortOf any // None
			if api := field("agent_api_port"); !absent(api) {
				apiPort, err := pyInt(api)
				if err != nil {
					if errors.Is(err, errNotInt) {
						refuse("%s.agent_api_port חייב להיות מספר", at)
						continue
					}
					return nil, nil, raisedAt(at+".agent_api_port", err)
				}
				if !apiPort.InRange(1, 65535) || apiPort.Text == port.Text {
					refuse("%s.agent_api_port חייב להיות פורט אחר, בטווח", at)
					continue
				}
				apiPortOf = apiPort.N
			}
			ident := yamlish.NewMap() // `app.get("identity") or {}`: a missing one is a fresh dict
			if v := field("identity"); truthy(v) {
				if ident, ok = v.(*yamlish.Map); !ok {
					refuse("%s.identity חייב להיות אובייקט (to, from)", at)
					continue
				}
			}
			to := ""
			if v, _ := ident.Get("to"); !absent(v) {
				if !headerRE.MatchString(pyval.Str(v)) {
					refuse("%s.identity.to: הערך נכתב לכותרת HTTP, ולכן מותר רק אותיות, ספרות ותווי @ . _ + - (בלי רווחים ובלי שורה חדשה)", at)
					continue
				}
				to = pyval.Str(v)
				ident.Set("to", to)
			}
			if v, _ := ident.Get("from"); !absent(v) {
				users, isList := v.([]any)
				if !isList {
					users = []any{v}
				}
				names, bad := []any{}, false
				for _, u := range users {
					if !absent(u) {
						bad = bad || !headerRE.MatchString(pyval.Str(u))
						names = append(names, pyval.Str(u))
					}
				}
				if bad {
					refuse("%s.identity.from: כל שם נכתב לכותרת HTTP, ולכן מותר רק אותיות, ספרות ותווי @ . _ + - (בלי רווחים ובלי שורה חדשה)", at)
					continue
				}
				ident.Set("from", names)
			}
			seenLabel[oid+"."+label] = oid + ":" + aid
			host := pyLower(pyval.Strip(pyval.Str(orEmpty(field("host")))))
			if host != "" && !authorityRE.MatchString(host) {
				refuse("%s.host %s אינו שם מארח תקין — זה השם שהאפליקציה של הלשכה האחרת מצפה לקבל בכותרת Host", at, pyval.Repr(field("host")))
				continue
			}
			title, _ := field("title").(*yamlish.Map) // `app.get("title") or {}`, and {} unless a dict
			nameHe := pyval.Str(either(either(field("name"), get(title, "he")), aid))
			// plan() reads the module's kind, path and id with `(app.get("module") or {}).get(…)`,
			// which raises on a module that is something other than an object.
			module, err := dict(field("module"), at+".module")
			if err != nil {
				return nil, nil, err
			}
			named := yamlish.NewMap() // `{k: ident[k] for k in ("to", "from") if ident.get(k)}`
			for _, k := range []string{"to", "from"} {
				if v := get(ident, k); truthy(v) {
					named.Set(k, v)
				}
			}
			clean = append(clean, remoteApp{
				app: aid, alias: label, port: port.N, apiPort: apiPortOf,
				name:       nameHe,
				nameEn:     pyval.Str(either(either(field("name_en"), get(title, "en")), nameHe)),
				icon:       pyval.Str(either(field("icon"), "external")),
				group:      pyval.Str(either(field("group"), "מרוחק")),
				desc:       pyval.Str(either(field("desc"), "אפליקציה של הלשכה "+oid)),
				order:      getOr(app, "order", int64(900)),
				host:       host,
				health:     pyval.Str(either(field("health"), "/healthz")),
				moduleKind: pyval.Str(either(get(module, "kind"), "embedded")),
				modulePath: pyval.Str(either(get(module, "path"), "/a/"+label+"/")),
				moduleID:   pyval.Str(either(get(module, "id"), aid)),
				identity:   named,
			})
		}
		var doors []remoteDoor
		for j, item := range doorList {
			at := fmt.Sprintf("%s.services[%d]", where, j)
			svc, ok := item.(*yamlish.Map)
			if !ok {
				refuse("%s חייב להיות אובייקט (app, alias, port)", at)
				continue
			}
			field := func(k string) any { v, _ := svc.Get(k); return v }
			sid := pyLower(pyval.Strip(pyval.Str(orEmpty(field("app")))))
			label := pyLower(pyval.Strip(pyval.Str(orEmpty(field("alias")))))
			if !labelRE.MatchString(sid) || !labelRE.MatchString(label) {
				refuse("%s: app/alias %s/%s אינם תקינים", at, pyval.Repr(field("app")), pyval.Repr(field("alias")))
				continue
			}
			if owner, taken := seenLabel[oid+"."+label]; taken {
				refuse("%s.alias '%s' כבר נתפס על ידי %s", at, label, owner)
				continue
			}
			port, err := pyInt(field("port"))
			if err != nil && !errors.Is(err, errNotInt) {
				return nil, nil, raisedAt(at+".port", err)
			}
			if err != nil || !port.InRange(1, 65535) { // int() refused: 0, out of range
				refuse("%s.port %s אינו פורט בטווח", at, pyval.Repr(field("port")))
				continue
			}
			seenLabel[oid+"."+label] = oid + ":" + sid
			doors = append(doors, remoteDoor{app: sid, alias: label, port: port.N})
		}
		if len(clean) == 0 && len(doors) == 0 {
			continue
		}
		var users, from []string // ONE identity per link: the distinct `to` names, sorted; the `from` names
		for _, a := range clean {
			if to, _ := get(a.identity, "to").(string); to != "" && !contains(users, to) {
				users = append(users, to)
			}
			names, _ := get(a.identity, "from").([]any)
			for _, u := range names {
				if !contains(from, u.(string)) {
					from = append(from, u.(string))
				}
			}
		}
		sort.Strings(users)
		sort.Strings(from)
		if len(users) > 1 {
			refuse("%s: שני מיפויי זהות שונים (%s) — קישור אחד, זהות אחת", where, strings.Join(users, ", "))
			continue
		}
		var door pyval.Integer // None and "" are no door: 0
		if v := get(entry, "link_port"); !absent(v) {
			p, err := pyInt(v)
			if err != nil && !errors.Is(err, errNotInt) {
				return nil, nil, raisedAt(where+".link_port", err)
			}
			if !p.InRange(1, 65535) { // not a number reads as 0 there
				refuse("%s.link_port %s אינו פורט בטווח", where, pyval.Repr(v))
				continue
			}
			door = p
		}
		e := remoteEntry{office: oid, address: addr, apps: clean, doors: doors, linkPort: door.N,
			label:     officeLabel(get(entry, "label"), oid, where, refuse),
			link:      pyval.Str(either(get(entry, "link"), oid)),
			commit:    pyval.Str(either(get(entry, "commit"), "")),
			mark:      officeMark(repo, get(entry, "mark"), oid),
			identFrom: from}
		if len(users) == 1 {
			e.identTo = users[0]
		}
		out = append(out, e)
	}
	return out, errs, nil
}

// officeLabel is _label(): the office's display name in each language it published — its id where it
// published none, and where the label is neither text nor an object (refused, with the id).
func officeLabel(v any, office, where string, refuse func(string, ...any)) *yamlish.Map {
	he, en := office, office
	switch t := v.(type) {
	case nil:
	case string:
		if t != "" {
			he, en = t, t
		}
	case *yamlish.Map:
		he = pyval.Strip(pyval.Str(either(either(get(t, "he"), get(t, "en")), office)))
		en = pyval.Strip(pyval.Str(either(either(get(t, "en"), get(t, "he")), office)))
	default:
		refuse("%s.label חייב להיות מחרוזת או אובייקט (he, en)", where)
	}
	return ordered("he", he, "en", en)
}

// raisedAt names, in its FATAL line, the field a check raised on.
func raisedAt(field string, err error) error {
	var d *dies
	if errors.As(err, &d) {
		return &dies{what: field + ": " + d.what}
	}
	return err
}

// ownAddresses is own_addresses(): this office's own tunnel address(es) on this machine, from the
// link's record (.dgo/addressing.json) and the WireGuard configs it ships (.dgo/wg0.conf,
// .dgo/pairs/*.conf). A file that is not there, or not JSON, says nothing.
func ownAddresses(repo string) (map[string]bool, error) {
	out := map[string]bool{}
	dgo := filepath.Join(repo, ".dgo")
	if text, err := readText(filepath.Join(dgo, "addressing.json")); err == nil {
		doc, err := yamlish.LoadJSON(text)
		if errors.Is(err, yamlish.ErrJSONTooDeep) {
			return nil, died(".dgo/addressing.json: RecursionError: %v", err)
		}
		if err == nil && truthy(doc) {
			if err := addSelves(out, doc, true); err != nil {
				return nil, err
			}
		}
	}
	files := []string{filepath.Join(dgo, "wg0.conf")}
	if st, err := os.Stat(filepath.Join(dgo, "pairs")); err == nil && st.IsDir() {
		more, _ := filepath.Glob(filepath.Join(dgo, "pairs", "*.conf"))
		files = append(files, more...)
	}
	for _, f := range files {
		text, err := readText(f)
		var d *dies
		if errors.As(err, &d) {
			return nil, d // not UTF-8: a UnicodeDecodeError, which is no OSError
		}
		if err != nil {
			continue
		}
		for _, line := range pySplitLines(text, false) {
			if m := wgAddress.FindStringSubmatch(line); m != nil {
				out[m[1]] = true
			}
		}
	}
	return out, nil
}

// addSelves adds `self` of the record and of each of its `pairs` — raising where Python's `.get`
// would on something that is not an object.
func addSelves(out map[string]bool, v any, top bool) error {
	m, ok := v.(*yamlish.Map)
	if !ok {
		return died(".dgo/addressing.json: AttributeError: '%s' object has no attribute 'get'", pyTypeName(v))
	}
	if self, _ := m.Get("self"); truthy(self) {
		out[pyval.Strip(pyval.Str(self))] = true
	}
	if !top {
		return nil
	}
	pairs, _ := m.Get("pairs")
	switch t := pairs.(type) {
	case []any:
		for _, e := range t {
			if truthy(e) {
				if err := addSelves(out, e, false); err != nil {
					return err
				}
			}
		}
	case *yamlish.Map: // iterating a dict yields its keys, and a key is a str
		for _, k := range t.Keys() {
			if k != "" {
				return died(".dgo/addressing.json: AttributeError: 'str' object has no attribute 'get'")
			}
		}
	case string:
		if t != "" {
			return died(".dgo/addressing.json: AttributeError: 'str' object has no attribute 'get'")
		}
	default:
		if truthy(t) {
			return died(".dgo/addressing.json: TypeError: '%s' object is not iterable", pyTypeName(t))
		}
	}
	return nil
}

// parseIP is ipaddress.ip_address(): the four octets and 4 for an IPv4 address, 6 for an IPv6 one,
// 0 for neither — with Python's rules (no leading zeros in an octet, `::` at most once, a scope id
// after `%`).
func parseIP(s string) ([4]int, int) {
	if v4, ok := parseIPv4(s); ok {
		return v4, 4
	}
	if parseIPv6(s) {
		return [4]int{}, 6
	}
	return [4]int{}, 0
}

func parseIPv4(s string) ([4]int, bool) {
	var out [4]int
	parts := strings.Split(s, ".")
	if len(parts) != 4 || strings.Contains(s, "/") {
		return out, false
	}
	for i, p := range parts {
		if p == "" || len(p) > 3 || (p != "0" && p[0] == '0') || strings.Trim(p, "0123456789") != "" {
			return out, false
		}
		n, _ := strconv.Atoi(p)
		if n > 255 {
			return out, false
		}
		out[i] = n
	}
	return out, true
}

func parseIPv6(s string) bool {
	if strings.Contains(s, "/") {
		return false
	}
	if addr, scope, hasScope := strings.Cut(s, "%"); hasScope {
		if scope == "" || strings.Contains(scope, "%") {
			return false
		}
		s = addr
	}
	parts := strings.Split(s, ":")
	if s == "" || len(parts) < 3 {
		return false
	}
	if strings.Contains(parts[len(parts)-1], ".") {
		if _, ok := parseIPv4(parts[len(parts)-1]); !ok {
			return false
		}
		parts = append(parts[:len(parts)-1], "0", "0") // two hextets' worth of IPv4
	}
	if len(parts) > 9 {
		return false
	}
	skip := -1
	for i := 1; i < len(parts)-1; i++ {
		if parts[i] == "" {
			if skip >= 0 {
				return false
			}
			skip = i
		}
	}
	hi, lo := len(parts), 0
	if skip >= 0 {
		hi, lo = skip, len(parts)-skip-1
		if parts[0] == "" {
			if hi--; hi != 0 {
				return false
			}
		}
		if parts[len(parts)-1] == "" {
			if lo--; lo != 0 {
				return false
			}
		}
		if 8-(hi+lo) < 1 {
			return false
		}
	} else if len(parts) != 8 || parts[0] == "" || parts[len(parts)-1] == "" {
		return false
	}
	for _, p := range append(slices.Clone(parts[:hi]), parts[len(parts)-lo:]...) {
		if p == "" || len(p) > 4 || strings.Trim(p, "0123456789abcdefABCDEF") != "" {
			return false
		}
	}
	return true
}

package compiler

import (
	"errors"
	"fmt"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── the sign-in blueprint: one authentik proxy provider per host an enabled app publishes ──────────
//
// render_authentik(): the providers the COMMITTED blueprint (deployment-apps.yaml) does not already
// own — a layer-3 app's declared `sso`, a base app's host the committed file does not register, each
// framed host, each linked office's app — written as a generated blueprint next to it, with the
// embedded outpost bound to every provider, ONE per host. A blueprint whose entries would collide on
// an identity is refused before it is written: authentik rejects the whole file for one such pair.

const (
	authentikDir       = "platform-base/authentik"
	generatedBlueprint = "zz-generated-apps.yaml" // compiled here; never one of the bootstrap's inputs
)

var (
	nonSpace     = "[^" + pyval.SpaceClass[1:] // Python's \S
	envBaseURL   = regexp.MustCompile(`!Env \[([A-Z0-9_]+_BASE_URL),` + pyval.SpaceClass + `*([^\]]+)\]`)
	ownedSlug    = regexp.MustCompile(`(?m)^  - id: provider-(` + nonSpace + `+)`)
	generatedID  = regexp.MustCompile(`(?m)^  - id: (provider-` + nonSpace + `+)`)
	blueprintTag = regexp.MustCompile(`![\p{L}\p{N}_]+`) // !\w+: the tags, stripped before the YAML is read
)

// committedBlueprint is COMMITTED_AUTHENTIK_BP.
func committedBlueprint(repo string) string {
	return filepath.Join(repo, filepath.FromSlash(authentikDir), "blueprints", "deployment-apps.yaml")
}

// committedSSOEstate is committed_sso_estate(): the host variables the committed blueprint hands its
// own providers (`!Env [<NAME>_BASE_URL, <default>]` → default) and the provider slugs it takes — read
// from the file, never restated. A file that cannot be read owns nothing; one that is not UTF-8 is no
// OSError, and stops the render as it stops reconcile.py.
func committedSSOEstate(repo string) (map[string]string, map[string]bool, error) {
	txt, err := readText(committedBlueprint(repo))
	vars, slugs := map[string]string{}, map[string]bool{}
	var d *dies
	if errors.As(err, &d) {
		return nil, nil, d
	}
	if err != nil {
		return vars, slugs, nil
	}
	for _, m := range envBaseURL.FindAllStringSubmatch(txt, -1) {
		vars[m[1]] = pyval.Strip(m[2])
	}
	for _, m := range ownedSlug.FindAllStringSubmatch(txt, -1) {
		slugs[m[1]] = true
	}
	return vars, slugs, nil
}

// publishedHosts is published_hosts(): {host variable: routed host} for every enabled app that
// publishes a host behind SSO — the same rule its routers are labelled by.
func publishedHosts(cat *Catalog, order []string) (*yamlish.Map, error) {
	hosts := yamlish.NewMap()
	for _, aid := range order {
		doc := cat.Apps[aid].doc
		routes, err := dicts(get(doc, "routing"), aid+": routing")
		if err != nil {
			return nil, err
		}
		for _, r := range routes {
			if !pyEqual(get(r, "auth"), "sso") {
				continue
			}
			s, err := dict(get(r, "sso"), aid+": routing.sso")
			if err != nil {
				return nil, err
			}
			if pyEqual(get(doc, "layer"), int64(3)) && s.Len() == 0 {
				continue
			}
			v := either(either(get(s, "base_url_env"), get(r, "url_env")), baseURLEnv(aid))
			hosts.Set(pyval.Str(v), pyval.Str(either(get(r, "host"), aid))+".${DEPLOYMENT_DOMAIN:-localhost}")
		}
	}
	return hosts, nil
}

// ssoHostEnv is sso_host_env(): {host variable: its fallback} — the committed blueprint's own, and
// every host an enabled app publishes behind SSO, which wins (the routed host is the one an identity
// must know).
func ssoHostEnv(repo string, cat *Catalog, order []string) (map[string]string, error) {
	pairs, _, err := committedSSOEstate(repo)
	if err != nil {
		return nil, err
	}
	published, err := publishedHosts(cat, order)
	if err != nil {
		return nil, err
	}
	for _, k := range published.Keys() {
		v, _ := published.Get(k)
		pairs[k] = v.(string)
	}
	return pairs, nil
}

// ssoProvider is one provider sso_providers() emits: the app, its sso block (as declared, or as the
// compiler completes it for a base app), and the routed host.
type ssoProvider struct {
	aid string
	s   *yamlish.Map
}

// ssoProviders is sso_providers(): every provider this compiler emits — a layer-3 app's declared
// block; a base app's host that the committed blueprint does not own, completed with its slug,
// display name, host variable, default host and `.localhost` twin; then each framed host's.
func ssoProviders(repo string, cat *Catalog, order []string, env *dotenv) ([]ssoProvider, error) {
	ownedVars, ownedSlugs, err := committedSSOEstate(repo)
	if err != nil {
		return nil, err
	}
	var out []ssoProvider
	for _, aid := range order {
		doc := cat.Apps[aid].doc
		routes, err := dicts(get(doc, "routing"), aid+": routing")
		if err != nil {
			return nil, err
		}
		for _, r := range routes {
			if !pyEqual(get(r, "auth"), "sso") {
				continue
			}
			declared, err := dict(get(r, "sso"), aid+": routing.sso")
			if err != nil {
				return nil, err
			}
			s := yamlish.NewMap() // dict(r.get("sso") or {}): a copy
			for _, k := range declared.Keys() {
				s.Set(k, get(declared, k))
			}
			layer3 := pyEqual(get(doc, "layer"), int64(3))
			if layer3 && s.Len() == 0 {
				continue // a layer-3 host without a provider block: not the compiler's to invent
			}
			host := pyval.Str(either(get(r, "host"), aid))
			v := pyval.Str(either(either(get(s, "base_url_env"), get(r, "url_env")), baseURLEnv(aid)))
			slug := either(get(s, "slug"), aid)
			if !layer3 {
				if _, owned := ownedVars[v]; owned || ownedSlugs[pyval.Str(slug)] {
					continue // the committed blueprint registers this host already
				}
				full := ordered("slug", slug, "display_name", either(get(s, "display_name"), enName(get(doc, "title"), pyval.Str(slug))),
					"base_url_env", v, "default_host", host+".localhost", "local_twin", true)
				for _, k := range s.Keys() {
					full.Set(k, get(s, k))
				}
				s = full
			}
			out = append(out, ssoProvider{aid, s})
		}
	}
	framed, err := framedSSOEntries(cat, order, env)
	if err != nil {
		return nil, err
	}
	for _, f := range framed {
		out = append(out, ssoProvider{f.aid, f.sso})
	}
	return out, nil
}

// providerPair is pair(): a proxy provider and its application, as the blueprint's lines.
func providerPair(slug, name, hostExpr string) []string {
	return []string{
		"  - id: provider-" + slug,
		"    model: authentik_providers_proxy.proxyprovider",
		"    state: present", "    identifiers:",
		"      name: " + name + " Provider",
		"    attrs:",
		"      authorization_flow: !Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]",
		"      invalidation_flow: !Find [authentik_flows.flow, [slug, default-provider-invalidation-flow]]",
		"      mode: forward_single",
		"      external_host: " + hostExpr,
		"      access_token_validity: hours=24",
		"      intercept_header_auth: true", "",
		"  - id: app-" + slug,
		"    model: authentik_core.application",
		"    state: present", "    identifiers:",
		"      slug: " + slug, "    attrs:",
		"      name: " + name,
		"      provider: !KeyOf provider-" + slug,
		"      policy_engine_mode: any", ""}
}

// renderAuthentik is render_authentik(): the generated blueprint written beside the committed one —
// or removed when no provider is the compiler's to emit.
func renderAuthentik(repo string, cat *Catalog, order []string, served []remoteEntry, env *dotenv) error {
	providers, err := ssoProviders(repo, cat, order, env)
	if err != nil {
		return err
	}
	dest := filepath.Join(repo, filepath.FromSlash(authentikDir), "blueprints", generatedBlueprint)
	// An office whose identity is forward-auth (authentik switched off, release 0.3.0) has nobody to
	// apply a blueprint: none is written, and the last one is removed. The providers are still read
	// above, so a broken `sso` block is refused the same on every office.
	if len(providers) == 0 || !slices.Contains(order, "authentik") {
		return unlink(dest)
	}
	body := []string{
		"# GENERATED by platform/manager/reconcile.py from each app's routing[].sso — the apps that",
		"# declare one, plus the hosts a base app publishes that the committed blueprint does not own.",
		"# DO NOT EDIT — edit the app's app.json. Gitignored; see gate G9.",
		"version: 1", "metadata:", "  name: Deployment - Generated App Providers",
		"  labels:", `    blueprints.goauthentik.io/instantiate: "true"`,
		"context:",
		`  authentik_external_host: !Format ["%s://%s/", !Env [AUTH_PROTOCOL, https], !Env [AUTH_EXTERNAL_URL, auth.localhost]]`,
		"entries:"}
	hostEnv, err := ssoHostEnv(repo, cat, order)
	if err != nil {
		return err
	}
	for _, p := range providers {
		where := p.aid + ": routing.sso"
		if e := get(p.s, "host_expr"); truthy(e) { // a framed host: a literal external_host
			slug, name, err := slugAndName(p.s, where)
			if err != nil {
				return err
			}
			body = append(body, providerPair(slug, name, pyval.Str(e))...)
			continue
		}
		own := ""
		if v := get(p.s, "base_url_env"); truthy(v) {
			def, err := index(p.s, "default_host", where)
			if err != nil {
				return err
			}
			own = env.envHere(pyval.Str(v), pyval.Str(def), hostEnv)
			slug, name, err := slugAndName(p.s, where)
			if err != nil {
				return err
			}
			body = append(body, providerPair(slug, name, `!Format ["%s://%s", !Env [AUTH_PROTOCOL, https], "`+own+`"]`)...)
		}
		if truthy(get(p.s, "local_twin")) {
			defv, err := index(p.s, "default_host", where)
			if err != nil {
				return err
			}
			def, err := asText(defv, where+".default_host")
			if err != nil {
				return err
			}
			if hostOf(own) != pyLower(def) { // not when the app's own host IS the twin's: one provider per host
				slug, name, err := slugAndName(p.s, where)
				if err != nil {
					return err
				}
				body = append(body, providerPair(slug+"-local", name+" Local", "http://"+def)...)
			}
		}
	}
	remote, err := ssoHosts(served, cat, env.domain(), env.consolePort())
	if err != nil {
		return err
	}
	for _, rec := range remote {
		if rec.portHost != "" {
			body = append(body, providerPair(rec.slug+"-port", rec.name+" (port)", frameHostExpr(rec.portHost))...)
		}
		body = append(body, providerPair(rec.slug, rec.name, frameHostExpr(rec.host))...)
	}

	// The embedded outpost lists every proxy provider — the committed file's by name (!Find: !KeyOf
	// resolves only within one file), the generated ones by id — ONE per host, the first that names it:
	// a second provider of a host freezes the outpost's refresh.
	committed, err := readText(committedBlueprint(repo))
	if err != nil {
		return died("%s: %v", "platform-base/authentik/blueprints/deployment-apps.yaml", err)
	}
	base, err := providersIn("platform-base/authentik/blueprints/deployment-apps.yaml", committed)
	if err != nil {
		return err
	}
	text := strings.Join(body, "\n")
	generated, err := providersIn("the generated blueprint", text)
	if err != nil {
		return err
	}
	genHost := map[string]any{}
	for _, p := range generated {
		genHost[p.id] = p.expr
	}
	type ref struct {
		ref  string
		expr any
	}
	var refs []ref
	for _, p := range base {
		name, err := textStrip(p.name, "deployment-apps.yaml: "+p.id+".identifiers.name")
		if err != nil {
			return err
		}
		refs = append(refs, ref{`!Find [authentik_providers_proxy.proxyprovider, [name, "` + name + `"]]`, p.expr})
	}
	for _, m := range generatedID.FindAllStringSubmatch(text, -1) {
		refs = append(refs, ref{"!KeyOf " + m[1], genHost[m[1]]})
	}
	seen, gated := map[string]bool{}, []string{}
	var bind []string
	for _, r := range refs {
		host := ssoHostHere(r.expr, hostEnv, env)
		if host != "" && seen[host] {
			continue
		}
		if !seen[host] && host != "" {
			gated = append(gated, host)
		}
		seen[host] = true
		bind = append(bind, r.ref)
	}
	sort.Strings(gated)
	gatedList := make([]any, len(gated))
	for i, h := range gated {
		gatedList[i] = h
	}
	// the hosts this render gates, in the blueprint's own context: one write with the providers
	body = slices.Insert(body, slices.Index(body, "context:")+1, "  gated_hosts: "+yamlish.DumpsJSON(gatedList))
	body = append(body,
		"  - id: embedded-outpost",
		"    model: authentik_outposts.outpost",
		"    state: present", "    identifiers:",
		"      managed: goauthentik.io/outposts/embedded",
		"    attrs:",
		"      name: authentik Embedded Outpost",
		"      type: proxy", "      config:",
		"        authentik_host: !Context authentik_external_host",
		"      providers:")
	for _, r := range bind {
		body = append(body, "        - "+r)
	}
	body = append(body, "")
	if err := assertUniqueIdentities(body); err != nil {
		return err
	}
	return write(dest, strings.Join(body, "\n")+"\n")
}

// slugAndName are a provider block's `slug` and `display_name`, as pair() spells them.
func slugAndName(s *yamlish.Map, where string) (string, string, error) {
	slug, err := index(s, "slug", where)
	if err != nil {
		return "", "", err
	}
	name, err := index(s, "display_name", where)
	if err != nil {
		return "", "", err
	}
	return pyval.Str(slug), pyval.Str(name), nil
}

// textStrip is `v.strip()` of a value that must be text.
func textStrip(v any, where string) (string, error) {
	s, err := asText(v, where)
	return pyval.Strip(s), err
}

// blueprintProvider is one entry providers_in() finds: its id, its provider name, and its
// external_host as the blueprint spells it with the tags stripped.
type blueprintProvider struct {
	id   string
	name any
	expr any
}

// providersIn is providers_in(text) of the named blueprint: every `provider-*` entry that names its
// provider — read as YAML once its `!Tags` are stripped, because the committed file mixes block and
// inline mappings and a pattern finds only one of the two.
func providersIn(name, text string) ([]blueprintProvider, error) {
	v, err := readYAML(name, blueprintTag.ReplaceAllString(text, ""))
	if isGap(err) {
		return nil, err
	}
	if err != nil { // safe_load raises: reconcile.py stops too
		return nil, died("%s: %v", name, err)
	}
	doc, err := dict(v, name)
	if err != nil {
		return nil, err
	}
	items, err := each(getOr(doc, "entries", []any{}), name+": entries") // `.get("entries", [])`: no `or`
	if err != nil {
		return nil, err
	}
	var out []blueprintProvider
	for _, ev := range items {
		e, err := asDict(ev, name+": entries")
		if err != nil {
			return nil, err
		}
		id := pyval.Str(getOr(e, "id", ""))
		idents, isDict := get(e, "identifiers").(*yamlish.Map)
		if !strings.HasPrefix(id, "provider-") || !isDict || !truthy(get(idents, "name")) {
			continue
		}
		attrs, err := dict(get(e, "attrs"), name+": "+id+".attrs")
		if err != nil {
			return nil, err
		}
		out = append(out, blueprintProvider{id, get(idents, "name"), get(attrs, "external_host")})
	}
	return out, nil
}

// ssoHostHere is sso_host_here(): the `host[:port]` a provider's external_host is on this machine —
// a literal URL, or a `!Format` filled from its literals and its `!Env`s as this office resolves them
// — or "" when it cannot be told (a URL with no "//", a format Python could not fill).
func ssoHostHere(expr any, hostEnv map[string]string, env *dotenv) string {
	if parts, ok := expr.([]any); ok {
		args := make([]string, 0, len(parts))
		for i, a := range parts {
			if i == 0 {
				continue
			}
			if l, isList := a.([]any); isList && len(l) > 0 {
				def := ""
				if len(l) > 1 {
					def = pyval.Str(l[1])
				}
				args = append(args, env.envHere(pyval.Str(l[0]), def, hostEnv))
			} else {
				args = append(args, env.here(pyval.Str(a)))
			}
		}
		filled := ""
		if len(parts) > 0 {
			var ok bool
			if filled, ok = pyFormat(pyval.Str(parts[0]), args); !ok {
				return ""
			}
		}
		expr = filled
	}
	s := ""
	if truthy(expr) {
		s = pyval.Str(expr)
	}
	if !strings.Contains(s, "//") {
		return ""
	}
	return hostOf(s)
}

// pyFormat is `format % tuple(args)` for text arguments, as PyUnicode_Format reads it: after each %,
// flags, a width, a precision and a length modifier (h, l, L — read and ignored), then the conversion.
// %s, %r, %a and %c (of one character) take a text; %% is a %. False where Python raises: too few or
// too many arguments, a mapping key, a `*` (it wants a number), a conversion that wants a number, an
// unknown one, a % with nothing after it.
func pyFormat(format string, args []string) (string, bool) {
	var b strings.Builder
	f := []rune(format)
	next := 0
	for i := 0; i < len(f); i++ {
		if f[i] != '%' {
			b.WriteRune(f[i])
			continue
		}
		i++
		spec, left := i, false
		for ; i < len(f) && strings.ContainsRune("-+ #0", f[i]); i++ {
			left = left || f[i] == '-'
		}
		number := func() int {
			n := 0
			for ; i < len(f) && f[i] >= '0' && f[i] <= '9'; i++ {
				n = min(n*10+int(f[i]-'0'), 1<<20)
			}
			return n
		}
		if i < len(f) && (f[i] == '(' || f[i] == '*') {
			return "", false
		}
		width, prec := number(), -1
		if i < len(f) && f[i] == '.' {
			i++
			if i < len(f) && f[i] == '*' {
				return "", false
			}
			prec = number()
		}
		if i < len(f) && strings.ContainsRune("hlL", f[i]) {
			i++
		}
		if i == len(f) {
			return "", false
		}
		if f[i] == '%' { // "%%" is a %; a % after a flag, a width or a precision is a conversion Python refuses
			if i != spec {
				return "", false
			}
			b.WriteByte('%')
			continue
		}
		if next == len(args) {
			return "", false
		}
		s := args[next]
		next++
		switch f[i] {
		case 's':
		case 'r':
			s = pyval.Repr(s)
		case 'a':
			s = asciiRepr(s)
		case 'c':
			if pyLen(s) != 1 {
				return "", false
			}
			prec = -1
		default:
			return "", false
		}
		if prec >= 0 && prec < pyLen(s) {
			s = string([]rune(s)[:prec])
		}
		if pad := width - pyLen(s); pad > 0 && left {
			s += strings.Repeat(" ", pad)
		} else if pad > 0 {
			s = strings.Repeat(" ", pad) + s
		}
		b.WriteString(s)
	}
	return b.String(), next == len(args)
}

// asciiRepr is ascii(s): repr with every character past ASCII escaped.
func asciiRepr(s string) string {
	var b strings.Builder
	for _, r := range pyval.Repr(s) {
		switch {
		case r < 0x80:
			b.WriteRune(r)
		case r <= 0xff:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r <= 0xffff:
			fmt.Fprintf(&b, `\u%04x`, r)
		default:
			fmt.Fprintf(&b, `\U%08x`, r)
		}
	}
	return b.String()
}

// assertUniqueIdentities is assert_unique_identities(): no two providers of one name and no two
// applications of one slug — authentik resolves an entry by it, so a pair collapses into one row and
// the WHOLE file is rejected. The render refuses instead, naming the two.
func assertUniqueIdentities(body []string) error {
	identKey := map[string]string{"authentik_providers_proxy.proxyprovider": "name", "authentik_core.application": "slug"}
	seen := map[[2]string]map[string]string{}
	var model, ident, entry string
	for _, line := range body {
		s := pyval.Strip(line)
		if rest, ok := strings.CutPrefix(s, "- id: "); ok {
			model, ident, entry = "", "", rest
			continue
		}
		if rest, ok := strings.CutPrefix(s, "model: "); ok {
			model, ident = rest, identKey[rest]
			continue
		}
		if ident != "" && strings.HasPrefix(s, ident+":") {
			_, value, _ := strings.Cut(s, ":")
			value = strings.Trim(strings.Trim(pyval.Strip(value), `"`), "'")
			key := [2]string{model, ident}
			if seen[key] == nil {
				seen[key] = map[string]string{}
			}
			if first, dup := seen[key][value]; dup {
				return &exit{"FATAL the generated authentik blueprint has two entries with the same " + ident + " '" + value + "': " +
					first + " and " + entry + ". authentik resolves an entry by it, so the two collapse into one row and the WHOLE file " +
					"is rejected — give one of them an identity of its own (see framed_sso_entries)."}
			}
			seen[key][value] = entry
			ident = "" // one identity line per entry
		}
	}
	return nil
}

// composeServicesMounting is compose_services(app, mounting): the app's compose services that mount
// something at that path in the container — by `mounting in str(volume)`, as reconcile.py asks.
func composeServicesMounting(repo string, app *App, mounting string) ([]string, error) {
	services, err := composeServiceMap(repo, app)
	if err != nil || services == nil {
		return nil, err
	}
	var out []string
	for _, name := range services.Keys() {
		svc, err := dict(get(services, name), app.ID+": compose services."+name)
		if err != nil {
			return nil, err
		}
		vols, err := list(get(svc, "volumes"), app.ID+": compose services."+name+".volumes")
		if err != nil {
			return nil, err
		}
		for _, v := range vols {
			if strings.Contains(pyval.Str(v), mounting) {
				out = append(out, name)
				break
			}
		}
	}
	return out, nil
}

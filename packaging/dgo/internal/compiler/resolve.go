package compiler

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// hard mirrors HARD: the strengths that pull a provider in.
var hard = map[string]bool{"requires": true, "requisite": true, "binds_to": true}

// Hard reports whether a use[] strength pulls its provider in — asked by the store's resolver
// (internal/store) so the set stays one.
func Hard(strength string) bool { return hard[strength] }

// Diag is one resolver diagnostic: level "error" or "info", and the message reconcile.py prints.
type Diag struct {
	Level, Msg string
}

// Resolve mirrors resolve(cat, state, roots): the ordered enabled ids and the diagnostics.
// Strength, provider selection, ops negotiation, conflicts, ordering and cycles — the same rules in
// the same words. roots seeds the closure instead of the state's enabled set (`services --for`).
//
// It reads each manifest as reconcile.py does, since required-by asks it without validating first:
// an absent field takes Python's default and a present null does not (`strength: null` is no hard
// strength), `ops` is set(ops or []) — "write" is five letters — and `after` and a binding count by
// Python truth (`bindings: {sql: }` binds nothing). A field Python cannot iterate, an entry it cannot
// index, a value it cannot hash is where reconcile.py dies, and where this returns the error.
func Resolve(repo string, cat *Catalog, st *State, roots []string) ([]string, []Diag, error) {
	var diags []Diag
	enabled := map[string]bool{}
	if len(roots) > 0 {
		var unknown []string
		for _, r := range roots {
			if _, ok := cat.Apps[r]; !ok {
				unknown = append(unknown, r)
			}
		}
		if len(unknown) > 0 {
			sort.Strings(unknown)
			return nil, nil, fmt.Errorf("FATAL unknown app id(s): %s — not a manifest in platform-base/ or apps/", strings.Join(unknown, ", "))
		}
		for _, r := range roots {
			enabled[r] = true
		}
	} else {
		ids, err := EnabledIDs(st, cat)
		if err != nil {
			return nil, nil, err
		}
		enabled = ids
		for _, aid := range st.Apps.Keys() {
			if _, ok := cat.Apps[aid]; !ok {
				diags = append(diags, Diag{"info", fmt.Sprintf("%s: in state but not yet migrated to apps/ (legacy lane)", aid)})
			}
		}
	}

	// provider[cap] = app ids in catalog order, each capability known as a Python dict knows its key
	provider := map[string][]string{}
	for _, aid := range cat.Order {
		caps, err := cat.Apps[aid].entries("capabilities")
		if err != nil {
			return nil, nil, err
		}
		for i, c := range caps {
			name, ok := c["name"]
			if !ok {
				return nil, nil, died("%s: capabilities[%d] has no name", aid, i)
			}
			key, ok := pyKey(name)
			if !ok {
				return nil, nil, died("%s: capabilities[%d].name is %s, which cannot name anything", aid, i, pyval.Repr(name))
			}
			provider[key] = append(provider[key], aid)
		}
	}

	// the bridge for capabilities still served by un-migrated services
	legacyCaps := map[string]string{}
	if raw, err := os.ReadFile(filepath.Join(repo, "platform", "legacy-capabilities.yaml")); err == nil {
		if v, err := yamlish.Unmarshal(raw); err == nil {
			if m, ok := v.(*yamlish.Map); ok {
				for _, k := range m.Keys() {
					val, _ := m.Get(k)
					legacyCaps[k] = pyval.Str(val)
				}
			}
		}
	}

	// admin-chosen capability → provider bindings: a mapping's `provider`, else the value itself,
	// kept as Python keeps it — a falsy one is no binding, and the consumer's default_provider decides
	bindings := map[string]any{}
	bv, _ := st.Doc.Get("bindings")
	bm, err := mapping(bv, stateName+": bindings")
	if err != nil {
		return nil, nil, err
	}
	for _, k := range bm.Keys() {
		v, _ := bm.Get(k)
		if m, ok := v.(*yamlish.Map); ok {
			v, _ = m.Get("provider")
		}
		bindings[k] = v
	}
	// ...and the product's, for a capability the office's state binds nothing for (default_bindings)
	product := defaultBindings(repo)

	// transitively pull in providers of hard-used capabilities
	want := map[string]bool{}
	var frontier []string
	for aid := range enabled {
		want[aid] = true
		frontier = append(frontier, aid)
	}
	sort.Strings(frontier) // Python's set order is arbitrary; sorted here so the diagnostics are stable
	for len(frontier) > 0 {
		aid := frontier[len(frontier)-1]
		frontier = frontier[:len(frontier)-1]
		uses, err := cat.Apps[aid].entries("use")
		if err != nil {
			return nil, nil, err
		}
		for i, u := range uses {
			strength := pyGet(u, "strength", "requires")
			if _, ok := pyKey(strength); !ok {
				return nil, nil, died("%s: use[%d].strength is %s, which cannot be looked up", aid, i, pyval.Repr(strength))
			}
			if s, _ := strength.(string); !hard[s] {
				continue
			}
			capv, key, err := useCapability(aid, i, u)
			if err != nil {
				return nil, nil, err
			}
			cap := pyval.Str(capv)
			name, isText := capv.(string) // a dict of the state file or the bridge is keyed by text
			provs := provider[key]
			if len(provs) == 0 {
				if legacy, bridged := legacyCaps[name]; isText && bridged {
					diags = append(diags, Diag{"info", fmt.Sprintf("%s: '%s' served by legacy '%s' (not yet migrated)", aid, cap, legacy)})
				} else {
					diags = append(diags, Diag{"error", fmt.Sprintf("%s: requires capability '%s' — no provider in catalog and not declared in platform/legacy-capabilities.yaml", aid, cap)})
				}
				continue
			}
			// ops negotiation: refuse a provider missing a required op
			need := map[string]any{}
			if ops := pyGet(u, "ops", nil); truthy(ops) {
				var ok bool
				if need, _, ok = pySet(ops); !ok {
					return nil, nil, died("%s: use[%d].ops is %s, which is no set of ops", aid, i, pyval.Repr(ops))
				}
			}
			var eligible []string
			for _, p := range provs {
				have, err := providedOps(cat.Apps[p], key)
				if err != nil {
					return nil, nil, err
				}
				var missing []any
				for k, op := range need {
					if _, has := have[k]; !has {
						missing = append(missing, op)
					}
				}
				if len(missing) == 0 {
					eligible = append(eligible, p)
					continue
				}
				sorted, ok := pySorted(missing)
				if !ok {
					return nil, nil, died("%s: use[%d]: ops %s cannot be sorted", aid, i, pyval.Repr(missing))
				}
				diags = append(diags, Diag{"error", fmt.Sprintf("%s: provider '%s' lacks ops %s for '%s'", aid, p, pyval.Repr(sorted), cap)})
			}
			// provider selection: a binding, then the consumer's default_provider, then the one eligible
			// provider this office runs, then the product's binding (`product_bindings:` in
			// platform.state.default.yaml) unless this office switched it off, then the only one
			chosen := ""
			if len(eligible) == 1 {
				chosen = eligible[0]
			} else if len(eligible) > 1 {
				var bound, productBound any
				if isText {
					bound = bindings[name]
					productBound = product[name]
				}
				pref := pyGet(u, "default_provider", nil)
				sortedOK := append([]string(nil), eligible...)
				sort.Strings(sortedOK)
				switch {
				case truthy(bound) && textIn(bound, eligible):
					chosen = bound.(string)
					diags = append(diags, Diag{"info", fmt.Sprintf("%s: bound to '%s' by platform.state.yaml", cap, chosen)})
				case truthy(bound):
					diags = append(diags, Diag{"error", fmt.Sprintf("%s: platform.state.yaml binds '%s', which is not an eligible provider (%s)", cap, pyval.Str(bound), strings.Join(sortedOK, ", "))})
				case truthy(pref) && textIn(pref, eligible):
					chosen = pref.(string)
					diags = append(diags, Diag{"info", fmt.Sprintf("%s: '%s' selected via %s's default_provider", cap, chosen, aid)})
				default:
					// what THIS office's state runs, and what it lists but switched off — the state's,
					// never a lane's roots; a provider that names the capability twice is one provider
					on, err := EnabledIDs(st, cat)
					if err != nil {
						return nil, nil, err
					}
					var running []string
					for _, p := range sortedOK {
						if on[p] && (len(running) == 0 || running[len(running)-1] != p) {
							running = append(running, p)
						}
					}
					prod, _ := productBound.(string)
					_, listed := st.Apps.Get(prod)
					switch {
					case len(running) == 1:
						chosen = running[0]
						diags = append(diags, Diag{"info", fmt.Sprintf("%s: '%s' is the one eligible provider this office runs", cap, chosen)})
					case truthy(productBound) && textIn(productBound, eligible) && (len(running) > 0 && contains(running, prod) || len(running) == 0 && !listed):
						chosen = prod
						diags = append(diags, Diag{"info", fmt.Sprintf("%s: bound to '%s' by %s (this office's %s binds none)", cap, chosen, defaultName, stateName)})
					default:
						diags = append(diags, Diag{"error", fmt.Sprintf("%s: capability '%s' has %d eligible providers (%s) and no rule to choose — set `bindings.%s` in platform.state.yaml or `default_provider` on the use[] entry",
							aid, cap, len(eligible), strings.Join(sortedOK, ", "), cap)})
					}
				}
			}
			if chosen != "" && !want[chosen] {
				want[chosen] = true
				frontier = append(frontier, chosen)
				diags = append(diags, Diag{"info", fmt.Sprintf("%s: pulled in as provider of '%s' for %s", chosen, cap, aid)})
			}
		}
	}

	// conflicts: "these two cannot both be enabled", reported naming both, never resolved by guessing
	wantSorted := sortedKeys(want)
	for _, aid := range wantSorted {
		uses, err := cat.Apps[aid].entries("use")
		if err != nil {
			return nil, nil, err
		}
		for i, u := range uses {
			if !pyEqual(pyGet(u, "strength", nil), "conflicts") {
				continue
			}
			target := pyGet(u, "capability", nil)
			key, ok := pyKey(target)
			if !ok {
				return nil, nil, died("%s: use[%d].capability is %s, which cannot be looked up", aid, i, pyval.Repr(target))
			}
			hits := map[string]bool{}
			for _, p := range provider[key] {
				if want[p] {
					hits[p] = true
				}
			}
			if name, isText := target.(string); isText && want[name] {
				hits[name] = true
			}
			for _, other := range sortedKeys(hits) {
				if other == aid {
					continue
				}
				diags = append(diags, Diag{"error", fmt.Sprintf("conflict: '%s' and '%s' cannot both be enabled (%s declares conflicts with '%s') — disable one in platform.state.yaml", aid, other, aid, pyval.Str(target))})
			}
		}
	}

	// ordering graph: only `after` edges, and never through weak links
	edges := map[string]map[string]bool{}
	for _, aid := range wantSorted {
		edges[aid] = map[string]bool{}
		uses, err := cat.Apps[aid].entries("use")
		if err != nil {
			return nil, nil, err
		}
		for i, u := range uses {
			if !truthy(pyGet(u, "after", true)) || pyEqual(pyGet(u, "dependency", "strong"), "weak") {
				continue
			}
			_, key, err := useCapability(aid, i, u)
			if err != nil {
				return nil, nil, err
			}
			for _, p := range provider[key] {
				if want[p] && p != aid {
					edges[aid][p] = true
				}
			}
		}
	}

	var order, stack []string
	seen := map[string]int{}
	var visit func(n string)
	visit = func(n string) {
		switch seen[n] {
		case 2:
			return
		case 1:
			i := indexOf(stack, n)
			cyc := strings.Join(append(append([]string(nil), stack[i:]...), n), " -> ")
			diags = append(diags, Diag{"error", fmt.Sprintf("dependency CYCLE: %s (break it with dependency:'weak')", cyc)})
			return
		}
		seen[n] = 1
		stack = append(stack, n)
		for _, d := range sortedKeys(edges[n]) {
			visit(d)
		}
		stack = stack[:len(stack)-1]
		seen[n] = 2
		order = append(order, n)
	}
	for _, n := range wantSorted {
		visit(n)
	}
	return order, diags, nil
}

// useCapability is u["capability"] where the resolver indexes it, and the key a dict finds it by.
func useCapability(aid string, i int, u map[string]any) (any, string, error) {
	capv, ok := u["capability"]
	if !ok {
		return nil, "", died("%s: use[%d] has no capability", aid, i)
	}
	key, ok := pyKey(capv)
	if !ok {
		return nil, "", died("%s: use[%d].capability is %s, which cannot be looked up", aid, i, pyval.Repr(capv))
	}
	return capv, key, nil
}

// providedOps is set(required_ops) | set(optional_ops) of a provider's first capability entry of
// that name, each set() of the field as Python builds it.
func providedOps(p *App, key string) (map[string]any, error) {
	caps, err := p.entries("capabilities")
	if err != nil {
		return nil, err
	}
	have := map[string]any{}
	for _, c := range caps {
		if k, _ := pyKey(c["name"]); k != key {
			continue
		}
		for _, field := range []string{"required_ops", "optional_ops"} {
			ops, _, ok := pySet(pyGet(c, field, []any{}))
			if !ok {
				return nil, died("%s: capability %s: %s is %s, which is no set of ops", p.ID, pyval.Repr(c["name"]), field, pyval.Repr(c[field]))
			}
			for k, op := range ops {
				have[k] = op
			}
		}
		break
	}
	return have, nil
}

// defaultBindings is default_bindings(): the product's capability → provider choices,
// `product_bindings:` in platform.state.default.yaml (never `bindings:`, which a fresh install's copy
// would make the office's own), each a mapping's `provider` or the value itself. A default file that
// is missing, unreadable, not a mapping, or binds nothing answers an empty map, as Python answers {}.
func defaultBindings(repo string) map[string]any {
	out := map[string]any{}
	text, err := readText(filepath.Join(repo, defaultName))
	if err != nil {
		return out
	}
	v, err := yamlish.Unmarshal([]byte(text))
	if err != nil {
		return out
	}
	doc, ok := v.(*yamlish.Map)
	if !ok {
		return out
	}
	bv, _ := doc.Get("product_bindings")
	bm, ok := bv.(*yamlish.Map)
	if !ok {
		return out
	}
	for _, k := range bm.Keys() {
		val, _ := bm.Get(k)
		if m, ok := val.(*yamlish.Map); ok {
			val, _ = m.Get("provider")
		}
		out[k] = val
	}
	return out
}

// textIn is `v in xs` for a list of text: only text can equal text.
func textIn(v any, xs []string) bool {
	s, ok := v.(string)
	return ok && contains(xs, s)
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func contains(xs []string, x string) bool {
	for _, v := range xs {
		if v == x {
			return true
		}
	}
	return false
}

func indexOf(xs []string, x string) int {
	for i, v := range xs {
		if v == x {
			return i
		}
	}
	return -1
}

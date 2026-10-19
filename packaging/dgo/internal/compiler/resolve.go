package compiler

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// hard mirrors HARD: the strengths that pull a provider in.
var hard = map[string]bool{"requires": true, "requisite": true, "binds_to": true}

// Diag is one resolver diagnostic: level "error" or "info", and the message reconcile.py prints.
type Diag struct {
	Level, Msg string
}

// Resolve mirrors resolve(cat, state, roots): the ordered enabled ids and the diagnostics.
// Strength, provider selection, ops negotiation, conflicts, ordering and cycles — the same rules in
// the same words. roots seeds the closure instead of the state's enabled set (`services --for`).
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
		enabled = EnabledIDs(st, cat)
		for _, aid := range st.Apps.Keys() {
			if _, ok := cat.Apps[aid]; !ok {
				diags = append(diags, Diag{"info", fmt.Sprintf("%s: in state but not yet migrated to apps/ (legacy lane)", aid)})
			}
		}
	}

	// provider[cap] = app ids in catalog order
	provider := map[string][]string{}
	for _, aid := range cat.Order {
		for _, c := range cat.Apps[aid].list("capabilities") {
			if name, ok := c["name"].(string); ok {
				provider[name] = append(provider[name], aid)
			}
		}
	}

	// the bridge for capabilities still served by un-migrated services
	legacyCaps := map[string]string{}
	if raw, err := os.ReadFile(filepath.Join(repo, "platform", "legacy-capabilities.yaml")); err == nil {
		if v, err := yamlish.Unmarshal(raw); err == nil {
			if m, ok := v.(*yamlish.Map); ok {
				for _, k := range m.Keys() {
					val, _ := m.Get(k)
					legacyCaps[k] = yamlStr(val)
				}
			}
		}
	}

	// admin-chosen capability → provider bindings
	bindings := map[string]string{}
	if bv, ok := st.Doc.Get("bindings"); ok {
		if bm, ok := bv.(*yamlish.Map); ok {
			for _, k := range bm.Keys() {
				v, _ := bm.Get(k)
				if m, ok := v.(*yamlish.Map); ok {
					p, _ := m.Get("provider")
					bindings[k] = yamlStr(p)
				} else {
					bindings[k] = yamlStr(v)
				}
			}
		}
	}

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
		for _, u := range cat.Apps[aid].list("use") {
			if !hard[strOr(u, "strength", "requires")] {
				continue
			}
			cap, _ := u["capability"].(string)
			provs := provider[cap]
			if len(provs) == 0 {
				if legacy, ok := legacyCaps[cap]; ok {
					diags = append(diags, Diag{"info", fmt.Sprintf("%s: '%s' served by legacy '%s' (not yet migrated)", aid, cap, legacy)})
				} else {
					diags = append(diags, Diag{"error", fmt.Sprintf("%s: requires capability '%s' — no provider in catalog and not declared in platform/legacy-capabilities.yaml", aid, cap)})
				}
				continue
			}
			// ops negotiation: refuse a provider missing a required op
			need := strList(u["ops"])
			var ok []string
			for _, p := range provs {
				var have map[string]bool
				for _, c := range cat.Apps[p].list("capabilities") {
					if n, _ := c["name"].(string); n == cap {
						have = map[string]bool{}
						for _, o := range strList(c["required_ops"]) {
							have[o] = true
						}
						for _, o := range strList(c["optional_ops"]) {
							have[o] = true
						}
						break
					}
				}
				var missing []string
				for _, o := range need {
					if !have[o] {
						missing = append(missing, o)
					}
				}
				if len(need) > 0 && len(missing) > 0 {
					sort.Strings(missing)
					diags = append(diags, Diag{"error", fmt.Sprintf("%s: provider '%s' lacks ops %s for '%s'", aid, p, pyList(missing), cap)})
				} else {
					ok = append(ok, p)
				}
			}
			// provider selection: a binding, then the consumer's default_provider, then the only one
			chosen := ""
			if len(ok) == 1 {
				chosen = ok[0]
			} else if len(ok) > 1 {
				bound := bindings[cap]
				pref := strOr(u, "default_provider", "")
				sortedOK := append([]string(nil), ok...)
				sort.Strings(sortedOK)
				switch {
				case bound != "" && contains(ok, bound):
					chosen = bound
					diags = append(diags, Diag{"info", fmt.Sprintf("%s: bound to '%s' by platform.state.yaml", cap, chosen)})
				case bound != "":
					diags = append(diags, Diag{"error", fmt.Sprintf("%s: platform.state.yaml binds '%s', which is not an eligible provider (%s)", cap, bound, strings.Join(sortedOK, ", "))})
				case pref != "" && contains(ok, pref):
					chosen = pref
					diags = append(diags, Diag{"info", fmt.Sprintf("%s: '%s' selected via %s's default_provider", cap, chosen, aid)})
				default:
					diags = append(diags, Diag{"error", fmt.Sprintf("%s: capability '%s' has %d eligible providers (%s) and no rule to choose — set `bindings.%s` in platform.state.yaml or `default_provider` on the use[] entry",
						aid, cap, len(ok), strings.Join(sortedOK, ", "), cap)})
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
		for _, u := range cat.Apps[aid].list("use") {
			if strOr(u, "strength", "") != "conflicts" {
				continue
			}
			target, _ := u["capability"].(string)
			hits := map[string]bool{}
			if provs, isCap := provider[target]; isCap {
				for _, p := range provs {
					if want[p] {
						hits[p] = true
					}
				}
			}
			if want[target] {
				hits[target] = true
			}
			for _, other := range sortedKeys(hits) {
				if other == aid {
					continue
				}
				diags = append(diags, Diag{"error", fmt.Sprintf("conflict: '%s' and '%s' cannot both be enabled (%s declares conflicts with '%s') — disable one in platform.state.yaml", aid, other, aid, target)})
			}
		}
	}

	// ordering graph: only `after` edges, and never through weak links
	edges := map[string]map[string]bool{}
	for aid := range want {
		edges[aid] = map[string]bool{}
		for _, u := range cat.Apps[aid].list("use") {
			if after, ok := u["after"].(bool); ok && !after {
				continue
			}
			if strOr(u, "dependency", "strong") == "weak" {
				continue
			}
			cap, _ := u["capability"].(string)
			for _, p := range provider[cap] {
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

func sortedKeys(m map[string]bool) []string {
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

// yamlStr spells a YAML scalar the way Python's f-string would.
func yamlStr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case string:
		return t
	case bool:
		if t {
			return "True"
		}
		return "False"
	default:
		return fmt.Sprint(t)
	}
}

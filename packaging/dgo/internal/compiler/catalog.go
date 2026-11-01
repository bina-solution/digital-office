// Package compiler is platform/manager/reconcile.py, verb by verb, in Go — core-005 step 2.
//
// The contract is the Python compiler's: the same names, arguments, output bytes and exit codes, so
// that every hook, gate and script that calls `reconcile.py <verb>` (the plan's §6, 173 tests) can
// call `dgo <verb>` without noticing. Python stays the oracle until the last verb matches: each verb
// ported here carries a test that runs reconcile.py beside it on the real checkout and diffs the two.
// `DGO_COMPILER=python` makes dgo delegate a verb again — the plan's per-verb rollback.
//
// What is ported, in the order of the verbs' callers: the catalog (load_catalog), the state file
// (load_state, disposition), the resolver (resolve) and `enabled-apps`. What is NOT yet: `validate`
// (the schema walk), which reconcile.py runs before `enabled-apps`; until it lands, a native
// `enabled-apps` trusts manifests the manifest gate has already validated — the one divergence, and
// only on a manifest that would fail validation.
package compiler

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// App is one manifest as load_catalog() keeps it: the decoded JSON plus where it lives.
type App struct {
	ID    string
	Layer int
	Dir   string         // absolute directory of the manifest
	Root  string         // "platform-base" or "apps" — the directory is the layer
	Raw   map[string]any // the manifest; numbers are json.Number
}

// Catalog keeps the manifests in load order (platform-base sorted, then apps sorted): the Python
// dict's insertion order, which the resolver's provider lists inherit.
type Catalog struct {
	Order []string
	Apps  map[string]*App
}

// catalogRoots mirrors CATALOG_ROOTS = {BASE: (1, 2), APPS: (3,)}.
var catalogRoots = []struct {
	name   string
	layers []int
}{
	{"platform-base", []int{1, 2}},
	{"apps", []int{3}},
}

// LoadCatalog reads every <root>/*/app.json. Its refusals are reconcile.py's FATAL lines, verbatim
// where the text does not depend on the JSON library.
func LoadCatalog(repo string) (*Catalog, error) {
	cat := &Catalog{Apps: map[string]*App{}}
	for _, r := range catalogRoots {
		dir := filepath.Join(repo, r.name)
		if st, err := os.Stat(dir); err != nil || !st.IsDir() {
			continue
		}
		matches, _ := filepath.Glob(filepath.Join(dir, "*", "app.json"))
		sort.Strings(matches)
		for _, m := range matches {
			rel := filepath.ToSlash(strings.TrimPrefix(m, repo+string(filepath.Separator)))
			raw, err := os.ReadFile(m)
			if err != nil {
				return nil, fmt.Errorf("FATAL %s: %v", rel, err)
			}
			dec := json.NewDecoder(strings.NewReader(string(raw)))
			dec.UseNumber()
			var a map[string]any
			if err := dec.Decode(&a); err != nil {
				return nil, fmt.Errorf("FATAL %s: invalid JSON: %v", rel, err)
			}
			id, _ := a["id"].(string)
			dirName := filepath.Base(filepath.Dir(m))
			if id != dirName {
				return nil, fmt.Errorf("FATAL %s: id '%s' != directory '%s'", rel, pyStr(a["id"]), dirName)
			}
			layer, isInt := intOf(a["layer"])
			if !isInt || !containsInt(r.layers, layer) {
				want := "platform-base/"
				if isInt && layer == 3 {
					want = "apps/"
				}
				return nil, fmt.Errorf("FATAL %s: layer %s manifest is in %s/, which holds layer(s) %s — move it to %s",
					rel, pyStr(a["layer"]), r.name, joinInts(r.layers, ", "), want)
			}
			if _, dup := cat.Apps[id]; dup {
				return nil, fmt.Errorf("FATAL duplicate app id '%s' in both platform-base/ and apps/", id)
			}
			cat.Apps[id] = &App{ID: id, Layer: layer, Dir: filepath.Dir(m), Root: r.name, Raw: a}
			cat.Order = append(cat.Order, id)
		}
	}
	return cat, nil
}

// list is a JSON array field as a slice of maps (entries that are not objects are skipped, as the
// Python `.get(...)` chains would skip them by failing later — the schema forbids them anyway).
func (a *App) list(key string) []map[string]any {
	arr, _ := a.Raw[key].([]any)
	out := make([]map[string]any, 0, len(arr))
	for _, e := range arr {
		if m, ok := e.(map[string]any); ok {
			out = append(out, m)
		}
	}
	return out
}

// strList is a JSON array of strings (`ops`, `required_ops`, …).
func strList(v any) []string {
	arr, _ := v.([]any)
	out := make([]string, 0, len(arr))
	for _, e := range arr {
		if s, ok := e.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func strOr(m map[string]any, key, def string) string {
	if v, ok := m[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return def
}

// intOf reads a JSON integer (json.Number or float64); false when it is not an integer.
func intOf(v any) (int, bool) {
	switch t := v.(type) {
	case json.Number:
		if i, err := strconv.ParseInt(t.String(), 10, 64); err == nil {
			return int(i), true
		}
	case float64:
		if t == float64(int(t)) {
			return int(t), true
		}
	case int:
		return t, true
	case int64:
		return int(t), true
	}
	return 0, false
}

func containsInt(xs []int, x int) bool {
	for _, v := range xs {
		if v == x {
			return true
		}
	}
	return false
}

func joinInts(xs []int, sep string) string {
	parts := make([]string, len(xs))
	for i, v := range xs {
		parts[i] = strconv.Itoa(v)
	}
	return strings.Join(parts, sep)
}

// pyStr spells a JSON value the way Python's f-string would spell the decoded object (None, True,
// 3, 'x' is only used through repr elsewhere; here str()).
func pyStr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case bool:
		if t {
			return "True"
		}
		return "False"
	case json.Number:
		return t.String()
	case string:
		return t
	default:
		return fmt.Sprint(t)
	}
}

// pyList is repr() of a list of strings: ['a', 'b'].
func pyList(xs []string) string {
	q := make([]string, len(xs))
	for i, s := range xs {
		q[i] = "'" + strings.ReplaceAll(s, "'", "\\'") + "'"
	}
	return "[" + strings.Join(q, ", ") + "]"
}

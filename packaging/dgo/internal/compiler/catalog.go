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
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// App is one manifest as load_catalog() keeps it: the decoded JSON plus where it lives.
type App struct {
	ID    string
	Layer int
	Dir   string         // absolute directory of the manifest
	Root  string         // "platform-base" or "apps" — the directory is the layer
	Raw   map[string]any // the manifest; numbers are json.Number (NaN and the infinities float64)
	// doc is the same manifest as json.loads holds it — its key order, Python's numbers — which is
	// what render writes from: a tile, a capability or a provider entry is written in the manifest's
	// own key order, which Raw does not keep.
	doc *yamlish.Map
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

// LoadCatalog reads every <root>/*/app.json as load_catalog() does — read_text(encoding="utf-8"), then
// json.loads, which is yamlish.LoadJSON here: the one reader of JSON as Python reads it, so a manifest
// is valid exactly where Python finds it valid (NaN included), and a refusal is worded, and placed in
// the text, as json.loads words and places it. Its refusals are reconcile.py's FATAL lines; where
// Python raises what load_catalog does not catch — a manifest that is not UTF-8, nesting past the
// recursion limit, a document that is no object — one FATAL line in the traceback's place.
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
			rel := strings.TrimPrefix(m, repo+string(filepath.Separator)) // as relative_to prints it: this OS's separators
			text, err := readText(m)
			var undecodable *dies
			switch {
			case errors.As(err, &undecodable):
				return nil, died("%s: UnicodeDecodeError: %s", rel, undecodable.codec)
			case err != nil:
				return nil, fmt.Errorf("FATAL %s: %v", rel, err)
			}
			v, err := yamlish.LoadJSON(text)
			switch {
			case errors.Is(err, yamlish.ErrUnpairedSurrogate): // Python keeps the half character
				return nil, &gapError{rel, err}
			case errors.Is(err, yamlish.ErrJSONTooDeep):
				return nil, died("%s: RecursionError: %v", rel, err)
			case err != nil:
				// a JSONDecodeError, in load_catalog's words — and the one ValueError that is not one (an
				// integer of more than 4300 digits), a traceback there, stops here as well
				return nil, fmt.Errorf("FATAL %s: invalid JSON: %v", rel, err)
			}
			doc, isObject := v.(*yamlish.Map)
			if !isObject { // `a["_dir"] = m.parent` raises TypeError
				return nil, died("%s: TypeError: the manifest is a %s, not an object", rel, pyTypeName(v))
			}
			a := plainJSON(doc).(map[string]any)
			id, _ := a["id"].(string)
			dirName := filepath.Base(filepath.Dir(m))
			if id != dirName { // str() of the value as json.loads holds it: a mapping in its own key order
				return nil, fmt.Errorf("FATAL %s: id '%s' != directory '%s'", rel, pyval.Str(get(doc, "id")), dirName)
			}
			layer := 0 // `a.get("layer") not in layers` compares by ==, so 1.0 and true are layer 1
			for _, l := range r.layers {
				if pyEqual(a["layer"], int64(l)) {
					layer = l
				}
			}
			if layer == 0 {
				want := "platform-base/"
				if pyEqual(a["layer"], int64(3)) {
					want = "apps/"
				}
				return nil, fmt.Errorf("FATAL %s: layer %s manifest is in %s/, which holds layer(s) %s — move it to %s",
					rel, pyval.Str(get(doc, "layer")), r.name, joinInts(r.layers, ", "), want)
			}
			if _, dup := cat.Apps[id]; dup {
				return nil, fmt.Errorf("FATAL duplicate app id '%s' in both platform-base/ and apps/", id)
			}
			cat.Apps[id] = &App{ID: id, Layer: layer, Dir: filepath.Dir(m), Root: r.name, Raw: a, doc: doc}
			cat.Order = append(cat.Order, id)
		}
	}
	return cat, nil
}

// plainJSON is a manifest in Raw's terms — those of encoding/json's UseNumber decode, which every read
// of Raw (validate, resolve, the store) is written for: an object a map[string]any, a number a
// json.Number spelled so that it reads back as the same Python int or float — and NaN or an infinity,
// which json.loads reads and no JSON number spells, a float64.
func plainJSON(v any) any {
	switch t := v.(type) {
	case *yamlish.Map:
		out := make(map[string]any, t.Len())
		for _, k := range t.Keys() {
			e, _ := t.Get(k)
			out[k] = plainJSON(e)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, e := range t {
			out[i] = plainJSON(e)
		}
		return out
	case int64:
		return json.Number(strconv.FormatInt(t, 10))
	case yamlish.BigInt:
		return json.Number(t)
	case float64:
		if math.IsNaN(t) || math.IsInf(t, 0) {
			return t
		}
		return json.Number(pyval.Repr(t)) // repr(float) always has its point or exponent
	}
	return v
}

// entries is `for x in a.get(key, [])` with each x then read as an object (x.get, x[…]): the field's
// items, or the error where reconcile.py dies — a field it cannot iterate (null, a number), or an
// item that is no object. Nothing is skipped: a manifest no validator refused is read as Python
// reads it.
func (a *App) entries(key string) ([]map[string]any, error) {
	v, set := a.Raw[key]
	if !set {
		return nil, nil
	}
	items, ok := pyIter(v)
	if !ok {
		return nil, died("%s: %s is %s, which cannot be iterated", a.ID, key, pyval.Repr(v))
	}
	out := make([]map[string]any, len(items))
	for i, x := range items {
		m, ok := x.(map[string]any)
		if !ok {
			return nil, died("%s: %s[%d] is %s, not an object", a.ID, key, i, pyval.Repr(x))
		}
		out[i] = m
	}
	return out, nil
}

// List is entries for another package: the store reads the same manifest arrays the resolver does,
// as Python reads them — an error where reconcile.py would die on the field.
func (a *App) List(key string) ([]map[string]any, error) { return a.entries(key) }

// Doc is the manifest as json.loads holds it — its key order and Python's numbers — for a reader that
// answers with the manifest's own values, as app-management's catalog does (serve, DGO-1090).
func (a *App) Doc() *yamlish.Map { return a.doc }

// BaseURLEnv is base_url_env(): the `<APP>_BASE_URL` variable an app's public host is rendered from.
func BaseURLEnv(appID string) string { return baseURLEnv(appID) }

// PyLower is Python's str.lower().
func PyLower(s string) string { return pyLower(s) }

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

func joinInts(xs []int, sep string) string {
	parts := make([]string, len(xs))
	for i, v := range xs {
		parts[i] = strconv.Itoa(v)
	}
	return strings.Join(parts, sep)
}

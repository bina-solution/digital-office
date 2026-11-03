package compiler

import (
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── a manifest or a state block read the way reconcile.py's dict methods read it ──────────────────
//
// render reads the ordered manifests (App.doc) and the state file, both *yamlish.Map, as reconcile.py
// reads its dicts: .get with and without a default, `x or {}` / `x or []`, d[k]. Each helper answers
// what Python answers and stops where Python raises — after validate() every field the schema types
// has its type, so a stop is a field the schema leaves open (a nested required key, an untyped value).

// get is d.get(k): the value, nil for a key that is not there (and for no mapping at all).
func get(d *yamlish.Map, k string) any {
	if d == nil {
		return nil
	}
	v, _ := d.Get(k)
	return v
}

// getOr is d.get(k, def): the value when the key is there — a null included — else def.
func getOr(d *yamlish.Map, k string, def any) any {
	if d != nil {
		if v, ok := d.Get(k); ok {
			return v
		}
	}
	return def
}

// either is Python's `a or b`.
func either(a, b any) any {
	if truthy(a) {
		return a
	}
	return b
}

// dict is `v or {}` read as a dict: an empty one for a falsy v, else the mapping — where v is
// something else, Python's .get raises (AttributeError), and so does this.
func dict(v any, where string) (*yamlish.Map, error) {
	if !truthy(v) {
		return yamlish.NewMap(), nil
	}
	if m, ok := v.(*yamlish.Map); ok {
		return m, nil
	}
	return nil, died("%s: AttributeError: '%s' object has no attribute 'get'", where, pyTypeName(v))
}

// asDict is x read as a dict (x.get, x[k]): the mapping, or where Python raises — x is no dict.
func asDict(x any, where string) (*yamlish.Map, error) {
	if m, ok := x.(*yamlish.Map); ok {
		return m, nil
	}
	return nil, died("%s: AttributeError: '%s' object has no attribute 'get'", where, pyTypeName(x))
}

// dicts is `for x in (v or [])` with each x then read as a dict: the items, or where Python raises — a
// value it cannot iterate, or an item that is no dict.
func dicts(v any, where string) ([]*yamlish.Map, error) {
	items, err := list(v, where)
	if err != nil {
		return nil, err
	}
	return asDicts(items, where)
}

// asDicts reads each item as a dict, stopping where one is not.
func asDicts(items []any, where string) ([]*yamlish.Map, error) {
	out := make([]*yamlish.Map, len(items))
	for i, x := range items {
		var err error
		if out[i], err = asDict(x, where); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// list is `for x in (v or [])`: a falsy value is no items; else each.
func list(v any, where string) ([]any, error) {
	if !truthy(v) {
		return nil, nil
	}
	return each(v, where)
}

// each is `for x in v` (and `list(v)`, `.extend(v)`) with v as it is: a list's items, a text's
// characters, a mapping's keys — and where Python cannot iterate it (None, a number, a bool), the
// TypeError, which `x or []` would have spared.
func each(v any, where string) ([]any, error) {
	items, ok := pyIter(v)
	if !ok {
		return nil, died("%s: TypeError: '%s' object is not iterable", where, pyTypeName(v))
	}
	return items, nil
}

// index is d[k]: the value, or the KeyError where the key is not there.
func index(d *yamlish.Map, k, where string) (any, error) {
	if v, ok := d.Get(k); ok {
		return v, nil
	}
	return nil, died("%s: KeyError: %s", where, pyval.Repr(k))
}

// asText is a value Python adds to or strips as a str — `host + ".localhost"`, `s.strip()` — or the
// TypeError (an AttributeError for a method) where it is not one.
func asText(v any, where string) (string, error) {
	if s, ok := v.(string); ok {
		return s, nil
	}
	return "", died("%s: TypeError: %s is a %s, not a str", where, pyval.Repr(v), pyTypeName(v))
}

// firstRouting is `(a.get("routing") or [{}])[0]`: the app's first routing entry, {} when it has none.
func firstRouting(a *yamlish.Map, where string) (*yamlish.Map, error) {
	routes, err := list(get(a, "routing"), where+": routing")
	if err != nil || len(routes) == 0 {
		return yamlish.NewMap(), err
	}
	return asDict(routes[0], where+": routing[0]")
}

// routedService is `(a.get("routing") or [{}])[0].get("service") or fallback`: the service an app's
// first route names — the target every overlay of the app lands on.
func routedService(a *yamlish.Map, fallback any, where string) (any, error) {
	r, err := firstRouting(a, where)
	if err != nil {
		return nil, err
	}
	return either(get(r, "service"), fallback), nil
}

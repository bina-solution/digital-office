package compiler

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── values as Python holds them ────────────────────────────────────────────────────────────────────
//
// reconcile.py works on what json.loads and yaml.safe_load hand it, spells it with str() and repr()
// in its messages, and dies (a traceback, exit 1) where its code meets a value it cannot iterate,
// index or hash. This file and internal/pyval are dgo's one copy of those rules, for both kinds of
// value it reads — a manifest decoded by encoding/json (UseNumber) and a YAML document decoded by
// yamlish — so that a message is spelled as Python spells it, and a verb stops exactly where
// reconcile.py stops.

// died is the error of a verb stopping where reconcile.py dies with an exception: one FATAL line in
// the traceback's place, exit 1, nothing on stdout (a *dies, python.go).
func died(format string, a ...any) error { return &dies{what: fmt.Sprintf(format, a...)} }

// Python's spellings — repr(), str() — str.isspace()/strip() and int() of a str are internal/pyval's,
// the one copy the console and the store read with too.

// Truthy is truthy for the packages that read what this one reads — the control plane follows
// app.py's `x or {}` the same way.
func Truthy(v any) bool { return truthy(v) }

// truthy is Python truth: None, False, 0, "", [] and {} are false.
func truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case bool:
		return t
	case int64:
		return t != 0
	case float64:
		return t != 0
	case json.Number:
		f, err := t.Float64()
		return err != nil || f != 0 // an overflow is inf in Python, and inf is true
	case string:
		return t != ""
	case []any:
		return len(t) > 0
	case *yamlish.Map:
		return t.Len() > 0
	case map[string]any:
		return len(t) > 0
	}
	return true
}

// pyEqual is == between two scalars: numbers by value with a bool an int (True == 1 == 1.0), text by
// text, None only to None.
func pyEqual(a, b any) bool {
	na, aNum := numericValue(a)
	nb, bNum := numericValue(b)
	if aNum || bNum {
		return aNum && bNum && na == nb
	}
	switch ta := a.(type) {
	case nil:
		return b == nil
	case string:
		tb, ok := b.(string)
		return ok && ta == tb
	}
	return false
}

// numericValue reads a number or a bool (Python's bool is an int) as float64.
func numericValue(v any) (float64, bool) {
	switch t := v.(type) {
	case bool:
		if t {
			return 1, true
		}
		return 0, true
	case json.Number:
		f, err := t.Float64()
		return f, err == nil
	case int64:
		return float64(t), true
	case float64:
		return t, true
	}
	return 0, false
}

// pyKey is how a dict or a set tells values apart: equal values (1, 1.0, True) share a key; a list
// or an object has none — it cannot be hashed, and Python raises where it is asked to.
func pyKey(v any) (string, bool) {
	switch t := v.(type) {
	case nil:
		return "z", true
	case string:
		return "s" + t, true
	case []any, map[string]any, *yamlish.Map:
		return "", false
	}
	f, _ := numericValue(v)
	return "n" + strconv.FormatFloat(f, 'g', -1, 64), true
}

// pyIter is `for x in v`: a list's items, a string's characters, a mapping's keys; false where Python
// cannot iterate the value (None, a number, a bool).
func pyIter(v any) ([]any, bool) {
	switch t := v.(type) {
	case []any:
		return t, true
	case string:
		out := []any{}
		for _, r := range t {
			out = append(out, string(r))
		}
		return out, true
	case map[string]any:
		out := []any{}
		for _, k := range sortedKeysAny(t) {
			out = append(out, k)
		}
		return out, true
	case *yamlish.Map:
		out := []any{}
		for _, k := range t.Keys() {
			out = append(out, k)
		}
		return out, true
	}
	return nil, false
}

// pyGet is `m.get(key, def)`: the value when the key is there — a null included — else def.
func pyGet(m map[string]any, key string, def any) any {
	if v, ok := m[key]; ok {
		return v
	}
	return def
}

// pySet is set(v): the items of an iterable by Python equality, the first of equal items kept, in
// the order met; false where Python raises — v is not iterable, or an item is a list or an object.
func pySet(v any) (map[string]any, []string, bool) {
	items, ok := pyIter(v)
	if !ok {
		return nil, nil, false
	}
	set, order := map[string]any{}, []string{}
	for _, x := range items {
		k, ok := pyKey(x)
		if !ok {
			return nil, nil, false
		}
		if _, seen := set[k]; !seen {
			set[k] = x
			order = append(order, k)
		}
	}
	return set, order, true
}

// pySorted is sorted() of a set's items: text by code point, numbers by value; false where Python's
// comparison raises — text beside a number, or None beside anything.
func pySorted(xs []any) ([]any, bool) {
	out := append([]any(nil), xs...)
	if len(out) < 2 {
		return out, true
	}
	allText, allNum := true, true
	for _, x := range out {
		if _, ok := x.(string); !ok {
			allText = false
		}
		if _, ok := numericValue(x); !ok {
			allNum = false
		}
	}
	switch {
	case allText:
		sort.Slice(out, func(i, j int) bool { return out[i].(string) < out[j].(string) })
	case allNum:
		sort.SliceStable(out, func(i, j int) bool {
			a, _ := numericValue(out[i])
			b, _ := numericValue(out[j])
			return a < b
		})
	default:
		return nil, false
	}
	return out, true
}

package compiler

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// maxBriefBytes mirrors MAX_BRIEF_BYTES: an app's AGENT.md is injected into every agent session.
const maxBriefBytes = 6000

// strengths mirrors STRENGTHS.
var strengths = map[string]bool{"requires": true, "wants": true, "requisite": true, "binds_to": true, "conflicts": true}

// Validate mirrors validate(cat): structural validation against platform/schema/app.schema.json
// without a jsonschema library — the same checks, the same sentences. It returns the error lines and
// the capability → providers map. Only what reconcile.py enforces is enforced: required and unknown
// top-level fields, declared types and enums at every depth, a sub-object's required keys at the top
// level, layer and kind, use[] strengths, route and tile conflicts, the agent's brief (present, inside
// the app, within budget), the compose file (present; forbidden for a blueprint or a library).
// `pattern`, `minimum`, `minItems`, `oneOf` in the schema are documentation to the Python validator,
// and so they are here.
func Validate(repo string, cat *Catalog) ([]string, map[string][]string, error) {
	raw, err := os.ReadFile(filepath.Join(repo, "platform", "schema", "app.schema.json"))
	if err != nil {
		return nil, nil, fmt.Errorf("FATAL platform/schema/app.schema.json: %v", err)
	}
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.UseNumber()
	var schema map[string]any
	if err := dec.Decode(&schema); err != nil {
		return nil, nil, fmt.Errorf("FATAL platform/schema/app.schema.json: invalid JSON: %v", err)
	}
	props, _ := schema["properties"].(map[string]any)
	required := strList(schema["required"])
	kindEnum := []any{}
	if kindSpec, ok := props["kind"].(map[string]any); ok {
		kindEnum, _ = kindSpec["enum"].([]any)
	}

	var errs []string
	provided := map[string][]string{}
	claimedHosts, claimedModules := map[string][]string{}, map[string][]string{}
	for _, aid := range cat.Order {
		a := cat.Apps[aid]
		var keys []string
		for k := range a.Raw {
			if !strings.HasPrefix(k, "_") {
				keys = append(keys, k)
			}
		}
		sort.Strings(keys)
		keySet := map[string]bool{}
		for _, k := range keys {
			keySet[k] = true
		}
		for _, miss := range required {
			if !keySet[miss] {
				errs = append(errs, fmt.Sprintf("%s: missing required field '%s'", aid, miss))
			}
		}
		for _, k := range keys {
			if _, allowed := props[k]; !allowed {
				errs = append(errs, fmt.Sprintf("%s: unknown field '%s'", aid, k))
			}
		}
		for _, k := range keys {
			spec, allowed := props[k].(map[string]any)
			if !allowed {
				continue
			}
			v := a.Raw[k]
			types := typeList(spec["type"])
			if len(types) == 0 {
				continue
			}
			if v == nil && contains(types, "null") {
				continue
			}
			if !isOfTypes(v, types) {
				errs = append(errs, fmt.Sprintf("%s: field '%s' must be %s, got %s", aid, k, strings.Join(types, "|"), pyTypeName(v)))
				continue
			}
			if obj, ok := v.(map[string]any); ok {
				for _, sub := range strList(spec["required"]) {
					if _, has := obj[sub]; !has {
						errs = append(errs, fmt.Sprintf("%s: field '%s' is missing required key '%s'", aid, k, sub))
					}
				}
			}
			path := fmt.Sprintf("field '%s'", k)
			checkEnums(aid, v, spec, path, &errs)
			checkTypes(aid, v, spec, path, &errs)
		}
		if l, ok := intOf(a.Raw["layer"]); !ok || (l != 1 && l != 2 && l != 3) {
			errs = append(errs, fmt.Sprintf("%s: layer must be 1|2|3", aid))
		}
		if !inEnum(a.Raw["kind"], kindEnum) {
			errs = append(errs, fmt.Sprintf("%s: invalid kind '%s'", aid, pyStr(a.Raw["kind"])))
		}
		for _, c := range a.list("capabilities") {
			if name, ok := c["name"].(string); ok {
				provided[name] = append(provided[name], aid)
			}
		}
		for _, u := range a.list("use") {
			s := strOr(u, "strength", "requires")
			if !strengths[s] {
				errs = append(errs, fmt.Sprintf("%s: use[%s] bad strength '%s'", aid, pyStr(u["capability"]), s))
			}
		}
		for _, r := range a.list("routing") {
			if host, ok := r["host"].(string); ok && host != "" {
				claimedHosts[host] = append(claimedHosts[host], aid)
			}
			if mod, ok := r["module"].(map[string]any); ok {
				if mid, ok := mod["id"].(string); ok && mid != "" {
					claimedModules[mid] = append(claimedModules[mid], aid)
				}
			}
		}
		// the app's brief for the office agent
		if ag, ok := a.Raw["agent"]; ok && ag != nil {
			agm, _ := ag.(map[string]any)
			rel := strings.TrimSpace(strOr(agm, "context", ""))
			switch {
			case rel == "":
				errs = append(errs, fmt.Sprintf("%s: agent.context must name the brief file (convention: AGENT.md)", aid))
			case strings.HasPrefix(rel, "/") || hasDotDot(rel):
				errs = append(errs, fmt.Sprintf("%s: agent.context must be a path INSIDE apps/%s/, got '%s'", aid, aid, rel))
			default:
				st, err := os.Stat(filepath.Join(a.Dir, filepath.FromSlash(rel)))
				if err != nil || st.IsDir() {
					errs = append(errs, fmt.Sprintf("%s: agent.context '%s' does not exist — the agent would never learn how to operate this app", aid, rel))
				} else if st.Size() > maxBriefBytes {
					errs = append(errs, fmt.Sprintf("%s: agent.context '%s' is %d bytes, over the %d budget — this file is injected into EVERY agent session, so it buys its size from every other app's brief. Cut it to what a caller cannot read off the manifest (what the app is FOR, its vocabulary, its traps).", aid, rel, st.Size(), maxBriefBytes))
				}
			}
		}
		comp := strOr(a.Raw, "compose", "")
		if comp != "" {
			if _, err := os.Stat(filepath.Join(a.Dir, filepath.FromSlash(comp))); err != nil {
				errs = append(errs, fmt.Sprintf("%s: compose '%s' not found", aid, comp))
			}
			if kind := strOr(a.Raw, "kind", ""); kind == "blueprint" || kind == "library" {
				errs = append(errs, fmt.Sprintf("%s: kind=%s must not declare compose", aid, kind))
			}
		}
	}
	for _, host := range sortedKeysOf(claimedHosts) {
		if owners := claimedHosts[host]; len(owners) > 1 {
			sort.Strings(owners)
			errs = append(errs, fmt.Sprintf("route conflict: host '%s' claimed by %s — only one app can own an edge route", host, strings.Join(owners, ", ")))
		}
	}
	for _, mid := range sortedKeysOf(claimedModules) {
		if owners := claimedModules[mid]; len(owners) > 1 {
			sort.Strings(owners)
			errs = append(errs, fmt.Sprintf("tile conflict: console module '%s' claimed by %s — the shell would route one app's tile to the other", mid, strings.Join(owners, ", ")))
		}
	}
	return errs, provided, nil
}

// checkEnums mirrors _check_enums: every `enum` the schema declares, at every depth, including
// inside array items. An explicit null passes only where the schema declares null as a type.
func checkEnums(aid string, val any, spec map[string]any, path string, errs *[]string) {
	if enum, ok := spec["enum"].([]any); ok && enum != nil {
		if val == nil && contains(typeList(spec["type"]), "null") {
			return
		}
		if !inEnum(val, enum) {
			*errs = append(*errs, fmt.Sprintf("%s: %s must be one of %s, got %s", aid, path, joinEnum(enum), pyReprJSON(val)))
		}
		return
	}
	if props, ok := spec["properties"].(map[string]any); ok {
		if obj, ok := val.(map[string]any); ok {
			for _, k := range sortedKeysAny(props) {
				if sub, has := obj[k]; has {
					if subSpec, ok := props[k].(map[string]any); ok {
						checkEnums(aid, sub, subSpec, path+"."+k, errs)
					}
				}
			}
		}
	}
	if items, ok := spec["items"].(map[string]any); ok {
		if arr, ok := val.([]any); ok {
			for i, el := range arr {
				checkEnums(aid, el, items, fmt.Sprintf("%s[%d]", path, i), errs)
			}
		}
	}
}

// checkTypes mirrors _check_types: declared types at every depth; a value of the wrong type is
// reported once and not descended into.
func checkTypes(aid string, val any, spec map[string]any, path string, errs *[]string) {
	if types := typeList(spec["type"]); len(types) > 0 {
		if !(val == nil && contains(types, "null")) {
			if !isOfTypes(val, types) {
				*errs = append(*errs, fmt.Sprintf("%s: %s must be %s, got %s", aid, path, strings.Join(types, "|"), pyTypeName(val)))
				return
			}
		}
	}
	if props, ok := spec["properties"].(map[string]any); ok {
		if obj, ok := val.(map[string]any); ok {
			for _, k := range sortedKeysAny(props) {
				if sub, has := obj[k]; has {
					if subSpec, ok := props[k].(map[string]any); ok {
						checkTypes(aid, sub, subSpec, path+"."+k, errs)
					}
				}
			}
		}
	}
	if items, ok := spec["items"].(map[string]any); ok {
		if arr, ok := val.([]any); ok {
			for i, el := range arr {
				checkTypes(aid, el, items, fmt.Sprintf("%s[%d]", path, i), errs)
			}
		}
	}
}

// typeList is the schema's `type`: a string or a list of strings.
func typeList(v any) []string {
	switch t := v.(type) {
	case string:
		return []string{t}
	case []any:
		return strList(t)
	}
	return nil
}

// isOfTypes is isinstance(val, JS[type]…) with Python's quirks kept: a bool IS an int (and a
// number), a float is not an integer, and an unknown type name matches nothing.
func isOfTypes(val any, types []string) bool {
	for _, t := range types {
		switch t {
		case "object":
			if _, ok := val.(map[string]any); ok {
				return true
			}
		case "array":
			if _, ok := val.([]any); ok {
				return true
			}
		case "string":
			if _, ok := val.(string); ok {
				return true
			}
		case "boolean":
			if _, ok := val.(bool); ok {
				return true
			}
		case "integer":
			if _, ok := val.(bool); ok {
				return true
			}
			if n, ok := val.(json.Number); ok && isIntNumber(n) {
				return true
			}
		case "number":
			if _, ok := val.(bool); ok {
				return true
			}
			if _, ok := val.(json.Number); ok {
				return true
			}
		}
	}
	return false
}

func isIntNumber(n json.Number) bool {
	s := n.String()
	return !strings.ContainsAny(s, ".eE")
}

// pyTypeName is type(v).__name__ for a decoded JSON value.
func pyTypeName(v any) string {
	switch t := v.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case string:
		return "str"
	case json.Number:
		if isIntNumber(t) {
			return "int"
		}
		return "float"
	case []any:
		return "list"
	case map[string]any:
		return "dict"
	}
	return fmt.Sprintf("%T", v)
}

// inEnum is `val in enum` with Python equality: numbers compare by value, True == 1, False == 0.
func inEnum(val any, enum []any) bool {
	for _, e := range enum {
		if pyEqual(val, e) {
			return true
		}
	}
	return false
}

func pyEqual(a, b any) bool {
	na, aNum := numericValue(a)
	nb, bNum := numericValue(b)
	if aNum && bNum {
		return na == nb
	}
	if aNum != bNum {
		return false
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
	case int:
		return float64(t), true
	case int64:
		return float64(t), true
	case float64:
		return t, true
	}
	return 0, false
}

// joinEnum is '|'.join(map(str, enum)).
func joinEnum(enum []any) string {
	parts := make([]string, len(enum))
	for i, e := range enum {
		parts[i] = pyStr(e)
	}
	return strings.Join(parts, "|")
}

// pyReprJSON is repr() of a decoded JSON scalar (what `{val!r}` prints).
func pyReprJSON(v any) string {
	switch t := v.(type) {
	case string:
		if strings.Contains(t, "'") && !strings.Contains(t, "\"") {
			return "\"" + t + "\""
		}
		return "'" + strings.ReplaceAll(t, "'", "\\'") + "'"
	case []any:
		parts := make([]string, len(t))
		for i, e := range t {
			parts[i] = pyReprJSON(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		keys := sortedKeysAny(t)
		parts := make([]string, len(keys))
		for i, k := range keys {
			parts[i] = pyReprJSON(k) + ": " + pyReprJSON(t[k])
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return pyStr(v)
}

func hasDotDot(rel string) bool {
	for _, part := range strings.Split(rel, "/") {
		if part == ".." {
			return true
		}
	}
	return false
}

func sortedKeysOf(m map[string][]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func sortedKeysAny(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

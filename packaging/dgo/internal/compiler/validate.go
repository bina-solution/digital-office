package compiler

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
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
	claimedHosts, claimedModules := map[string][]any{}, map[string][]any{}
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
		layerOK := false // `a.get("layer") not in (1, 2, 3)` compares by ==: 1.0 and true are 1
		for _, l := range []int64{1, 2, 3} {
			layerOK = layerOK || pyEqual(a.Raw["layer"], l)
		}
		if !layerOK {
			errs = append(errs, fmt.Sprintf("%s: layer must be 1|2|3", aid))
		}
		if _, ok := pyKey(a.Raw["kind"]); !ok { // `not in set(enum)` hashes it
			return nil, nil, died("%s: kind is %s, which cannot be looked up", aid, pyval.Repr(a.Raw["kind"]))
		}
		if !inEnum(a.Raw["kind"], kindEnum) {
			errs = append(errs, fmt.Sprintf("%s: invalid kind '%s'", aid, pyval.Str(a.Raw["kind"])))
		}
		caps, err := a.entries("capabilities")
		if err != nil {
			return nil, nil, err
		}
		for i, c := range caps {
			name, ok := c["name"]
			if !ok {
				return nil, nil, died("%s: capabilities[%d] has no name", aid, i)
			}
			if _, ok := pyKey(name); !ok {
				return nil, nil, died("%s: capabilities[%d].name is %s, which cannot name anything", aid, i, pyval.Repr(name))
			}
			// a name that is not text fails the type check above, so the OK line never lists it
			if s, isText := name.(string); isText {
				provided[s] = append(provided[s], aid)
			}
		}
		uses, err := a.entries("use")
		if err != nil {
			return nil, nil, err
		}
		for i, u := range uses {
			s := pyGet(u, "strength", "requires")
			if _, ok := pyKey(s); !ok {
				return nil, nil, died("%s: use[%d].strength is %s, which cannot be looked up", aid, i, pyval.Repr(s))
			}
			if name, _ := s.(string); !strengths[name] {
				errs = append(errs, fmt.Sprintf("%s: use[%s] bad strength '%s'", aid, pyval.Str(pyGet(u, "capability", nil)), pyval.Str(s)))
			}
		}
		if routing := a.Raw["routing"]; truthy(routing) { // `a.get("routing") or []`
			items, ok := pyIter(routing)
			if !ok {
				return nil, nil, died("%s: routing is %s, which cannot be iterated", aid, pyval.Repr(routing))
			}
			for i, x := range items {
				r, ok := x.(map[string]any)
				if !ok {
					return nil, nil, died("%s: routing[%d] is %s, not an object", aid, i, pyval.Repr(x))
				}
				if host := pyGet(r, "host", nil); truthy(host) {
					if err := claim(claimedHosts, host, aid); err != nil {
						return nil, nil, died("%s: routing[%d].host %v", aid, i, err)
					}
				}
				if mod := pyGet(r, "module", nil); truthy(mod) { // `(r.get("module") or {}).get("id")`
					m, ok := mod.(map[string]any)
					if !ok {
						return nil, nil, died("%s: routing[%d].module is %s, not an object", aid, i, pyval.Repr(mod))
					}
					if mid := pyGet(m, "id", nil); truthy(mid) {
						if err := claim(claimedModules, mid, aid); err != nil {
							return nil, nil, died("%s: routing[%d].module.id %v", aid, i, err)
						}
					}
				}
			}
		}
		// the app's brief for the office agent
		if ag, ok := a.Raw["agent"]; ok && ag != nil {
			agm, ok := ag.(map[string]any)
			if !ok {
				return nil, nil, died("%s: agent is %s, not an object", aid, pyval.Repr(ag))
			}
			rel := ""
			if ctx := pyGet(agm, "context", nil); truthy(ctx) { // `(ag.get("context") or "").strip()`
				s, ok := ctx.(string)
				if !ok {
					return nil, nil, died("%s: agent.context is %s, not text", aid, pyval.Repr(ctx))
				}
				rel = pyval.Strip(s)
			}
			switch {
			case rel == "":
				errs = append(errs, fmt.Sprintf("%s: agent.context must name the brief file (convention: AGENT.md)", aid))
			case strings.HasPrefix(rel, "/") || hasDotDot(rel):
				errs = append(errs, fmt.Sprintf("%s: agent.context must be a path INSIDE apps/%s/, got %s", aid, aid, pyval.Repr(rel)))
			default:
				st, err := os.Stat(joinPath(a.Dir, rel))
				if err != nil || !st.Mode().IsRegular() {
					errs = append(errs, fmt.Sprintf("%s: agent.context '%s' does not exist — the agent would never learn how to operate this app", aid, rel))
				} else if st.Size() > maxBriefBytes {
					errs = append(errs, fmt.Sprintf("%s: agent.context '%s' is %d bytes, over the %d budget — this file is injected into EVERY agent session, so it buys its size from every other app's brief. Cut it to what a caller cannot read off the manifest (what the app is FOR, its vocabulary, its traps).", aid, rel, st.Size(), maxBriefBytes))
				}
			}
		}
		comp := a.Raw["compose"]
		if truthy(comp) {
			s, ok := comp.(string)
			if !ok { // the path join raises
				return nil, nil, died("%s: compose is %s, not a path", aid, pyval.Repr(comp))
			}
			if _, err := os.Stat(joinPath(a.Dir, s)); err != nil {
				errs = append(errs, fmt.Sprintf("%s: compose '%s' not found", aid, s))
			}
			if kind, _ := a.Raw["kind"].(string); kind == "blueprint" || kind == "library" {
				errs = append(errs, fmt.Sprintf("%s: kind=%s must not declare compose", aid, kind))
			}
		}
	}
	for _, c := range []struct {
		claims     map[string][]any
		what, line string
	}{
		{claimedHosts, "routing hosts", "route conflict: host '%s' claimed by %s — only one app can own an edge route"},
		{claimedModules, "console modules", "tile conflict: console module '%s' claimed by %s — the shell would route one app's tile to the other"},
	} {
		names := make([]any, 0, len(c.claims))
		for _, cl := range c.claims {
			names = append(names, cl[0])
		}
		sorted, ok := pySorted(names) // sorted(claims.items()): text beside a number is where Python raises
		if !ok {
			return nil, nil, died("the %s %s cannot be sorted", c.what, pyval.Repr(names))
		}
		for _, name := range sorted {
			key, _ := pyKey(name)
			if owners := c.claims[key][1:]; len(owners) > 1 {
				ids := make([]string, len(owners))
				for i, o := range owners {
					ids[i] = o.(string)
				}
				sort.Strings(ids)
				errs = append(errs, fmt.Sprintf(c.line, pyval.Str(name), strings.Join(ids, ", ")))
			}
		}
	}
	return errs, provided, nil
}

// claim is claims.setdefault(name, []).append(aid): each entry holds the name first, then every
// claimant. A name Python cannot hash is where it raises.
func claim(claims map[string][]any, name any, aid string) error {
	key, ok := pyKey(name)
	if !ok {
		return fmt.Errorf("is %s, which cannot be looked up", pyval.Repr(name))
	}
	if claims[key] == nil {
		claims[key] = []any{name}
	}
	claims[key] = append(claims[key], aid)
	return nil
}

// checkEnums mirrors _check_enums: every `enum` the schema declares, at every depth, including
// inside array items. An explicit null passes only where the schema declares null as a type.
func checkEnums(aid string, val any, spec map[string]any, path string, errs *[]string) {
	if enum, ok := spec["enum"].([]any); ok && enum != nil {
		if val == nil && contains(typeList(spec["type"]), "null") {
			return
		}
		if !inEnum(val, enum) {
			*errs = append(*errs, fmt.Sprintf("%s: %s must be one of %s, got %s", aid, path, joinEnum(enum), pyval.Repr(val)))
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
			if _, ok := val.(float64); ok { // NaN or an infinity, which a manifest holds as float64
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
	case map[string]any, *yamlish.Map:
		return "dict"
	case int64, yamlish.BigInt: // the state file's and stdin's values
		return "int"
	case float64:
		return "float"
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

// joinEnum is '|'.join(map(str, enum)).
func joinEnum(enum []any) string {
	parts := make([]string, len(enum))
	for i, e := range enum {
		parts[i] = pyval.Str(e)
	}
	return strings.Join(parts, "|")
}

func hasDotDot(rel string) bool {
	for _, part := range strings.Split(rel, "/") {
		if part == ".." {
			return true
		}
	}
	return false
}

func sortedKeysAny(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

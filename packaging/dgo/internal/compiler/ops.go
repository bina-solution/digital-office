package compiler

import (
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/pyval"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// verbName is reconcile.py's VERB_NAME (fullmatch: anchored here).
var (
	verbName = regexp.MustCompile(`^[a-z][a-z0-9-]{0,40}$`)
	opKeys   = []string{"id", "method", "path", "endpoint", "access", "verb", "ui", "summary"}
)

// servedCapabilities is the comprehension both functions below share: the names, in the manifest's order and
// duplicates kept, of the capabilities that are objects with a text name and a truthy endpoint.
func servedCapabilities(caps any) []string {
	var out []string
	items, _ := caps.([]any)
	for _, x := range items {
		c, ok := x.(map[string]any)
		if !ok {
			continue
		}
		if name, isText := c["name"].(string); isText && truthy(c["endpoint"]) {
			out = append(out, name)
		}
	}
	return out
}

// checkOps is _check_ops (DGO-1244): what the structural walk cannot say of an app's `ops` — each op's required
// keys and no key the schema does not name, an id given once, the endpoint that serves it found, and a verb that
// is a verb's name. The same lines, in the same order. The manifest only: whether hooks/<verb> exists is
// DGO-1246's gate (the trees validate runs on hold manifests without their hooks).
func checkOps(aid string, a *App, spec map[string]any, errs *[]string) {
	ops, ok := a.Raw["ops"].([]any)
	if !ok {
		return
	}
	served := servedCapabilities(a.Raw["capabilities"])
	required := strList(spec["required"])
	props, _ := spec["properties"].(map[string]any)
	seen := map[string]bool{}
	for i, x := range ops {
		op, isMap := x.(map[string]any)
		if !isMap {
			continue
		}
		for _, miss := range required {
			if _, has := op[miss]; !has {
				*errs = append(*errs, fmt.Sprintf("%s: ops[%d] has no '%s'", aid, i, miss))
			}
		}
		var extras []string
		for k := range op {
			if _, known := props[k]; !known {
				extras = append(extras, k)
			}
		}
		sort.Strings(extras) // UTF-8 bytes sort as code points do: sorted()
		for _, k := range extras {
			*errs = append(*errs, fmt.Sprintf("%s: ops[%d] has the key '%s', which an op does not have", aid, i, k))
		}
		if oid, isText := op["id"].(string); isText {
			if !verbName.MatchString(oid) { // the op's name in every answer: the schema's pattern, held here
				*errs = append(*errs, fmt.Sprintf("%s: ops[%d] id %s is not an op's name (a-z, 0-9, -)", aid, i, pyval.Repr(oid)))
			}
			if seen[oid] {
				*errs = append(*errs, fmt.Sprintf("%s: ops[%d] '%s' is declared twice — an op's id is its name in the answer", aid, i, oid))
			}
			seen[oid] = true
		}
		if path, isText := op["path"].(string); isText && !strings.HasPrefix(path, "/") {
			*errs = append(*errs, fmt.Sprintf("%s: ops[%d] path %s does not start at the endpoint's root (/)", aid, i, pyval.Repr(path)))
		}
		capv := op["capability"]
		if capName, isText := capv.(string); capv == nil && len(served) != 1 {
			*errs = append(*errs, fmt.Sprintf("%s: ops[%d] names no capability, and the app has %d with an endpoint — name the one that serves it", aid, i, len(served)))
		} else if isText && !contains(served, capName) {
			*errs = append(*errs, fmt.Sprintf("%s: ops[%d] capability '%s' is not one of this app's capabilities with an endpoint", aid, i, capName))
		}
		if verb, isText := op["verb"].(string); isText && !verbName.MatchString(verb) {
			*errs = append(*errs, fmt.Sprintf("%s: ops[%d] verb %s is not a verb's name (a-z, 0-9, -)", aid, i, pyval.Repr(verb)))
		}
	}
}

// opsRegistry is ops_registry(): {app: [op…]} of every enabled app that declares `ops`, in app-id order, each op
// as declared in opKeys order, its `capability` replaced by `endpoint` (validate has refused an op it could not
// place). From the manifest as json.loads holds it, so a summary keeps its own key order.
func opsRegistry(cat *Catalog, order []string) *yamlish.Map {
	ids := append([]string(nil), order...)
	sort.Strings(ids) // app ids are ASCII: bytes and code points agree
	out := yamlish.NewMap()
	for _, aid := range ids {
		doc := cat.Apps[aid].doc
		ops, _ := get(doc, "ops").([]any)
		if len(ops) == 0 {
			continue
		}
		ends := yamlish.NewMap()
		capsList, _ := get(doc, "capabilities").([]any)
		for _, x := range capsList {
			c, ok := x.(*yamlish.Map)
			if !ok {
				continue
			}
			name, isText := get(c, "name").(string)
			if endpoint := get(c, "endpoint"); isText && truthy(endpoint) {
				ends.Set(name, endpoint) // a dict comprehension: the last of a name wins, at its first place
			}
		}
		rows := make([]any, 0, len(ops))
		for _, x := range ops {
			op, ok := x.(*yamlish.Map)
			if !ok {
				continue
			}
			capv := get(op, "capability")
			if !truthy(capv) && len(ends.Keys()) == 1 { // `op.get("capability") or next(iter(ends))`
				capv = ends.Keys()[0]
			} else if !truthy(capv) {
				capv = nil
			}
			row := yamlish.NewMap()
			for _, k := range opKeys {
				var v any
				if k == "endpoint" {
					if name, isText := capv.(string); isText {
						v, _ = ends.Get(name)
					}
				} else {
					v = get(op, k)
				}
				if v != nil {
					row.Set(k, v)
				}
			}
			rows = append(rows, row)
		}
		out.Set(aid, rows)
	}
	return out
}

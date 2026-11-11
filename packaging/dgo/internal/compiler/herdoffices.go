package compiler

import (
	"path/filepath"
	"regexp"
	"sort"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// HERD_NAME and WG_PUBLIC_KEY, as reconcile.py spells them (fullmatch: anchored here).
var (
	herdName    = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]*$`)
	wgPublicKey = regexp.MustCompile(`^[A-Za-z0-9+/]{43}=$`)
)

// herdOffices is herd_offices() (DGO-1800): computers' registry of the herd — {"offices": {id: {"wg_public_key",
// "aliases"}}, "keys": every office's key, sorted}. An office is the herd's by its WireGuard key, never by a name
// (herd.yaml: a client's machine may be called `portable`). herd.yaml read as YAML, as safe_load reads it; a file
// that cannot be read gives no office, and an office without a well-formed key is none of the herd's. A reader
// gap (yamlish refusing what PyYAML reads) is said, not answered differently.
func herdOffices(repo string) (*yamlish.Map, error) {
	doc, err := loadYAML(filepath.Join(repo, "apps", "computers", "herd.yaml"))
	if isGap(err) {
		return nil, err
	}
	out := yamlish.NewMap()
	keySet := map[string]bool{}
	if m, ok := doc.(*yamlish.Map); ok && err == nil {
		if offices, ok := get(m, "offices").(*yamlish.Map); ok {
			for _, oid := range offices.Keys() {
				o, _ := get(offices, oid).(*yamlish.Map)
				key, _ := get(o, "wg_public_key").(string)
				_, isString := offices.TypedKey(oid).(string) // `7:` is no id: isinstance(oid, str)
				if o == nil || !isString || !herdName.MatchString(oid) || !wgPublicKey.MatchString(key) {
					continue
				}
				named := []any{}
				seen := map[string]bool{}
				if list, ok := get(o, "aliases").([]any); ok {
					for _, a := range list {
						if s, ok := a.(string); ok && herdName.MatchString(s) && !seen[s] {
							seen[s] = true
							named = append(named, s)
						}
					}
				}
				entry := yamlish.NewMap()
				entry.Set("wg_public_key", key)
				entry.Set("aliases", named)
				out.Set(oid, entry)
				keySet[key] = true
			}
		}
	}
	keys := make([]string, 0, len(keySet))
	for k := range keySet {
		keys = append(keys, k)
	}
	sort.Strings(keys) // sorted(): every key is ASCII base64, so bytes and code points agree
	flat := make([]any, 0, len(keys))
	for _, k := range keys {
		flat = append(flat, k)
	}
	res := yamlish.NewMap()
	res.Set("offices", out)
	res.Set("keys", flat)
	return res, nil
}

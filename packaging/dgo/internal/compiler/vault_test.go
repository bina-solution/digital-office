package compiler

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// copyVaultSources puts every document apps/obsidian/vault.yaml names (`notes` and `herd_docs`) from this
// checkout into dir, so a render oracle case compiles the vault as an office does — the trees otherwise carry
// the declaration alone, and each note is the «missing» one.
func copyVaultSources(t *testing.T, dir string) {
	t.Helper()
	src := repoRoot(t)
	raw, err := os.ReadFile(filepath.Join(src, filepath.FromSlash(vaultManifestRel)))
	if err != nil {
		t.Skip("this checkout has no " + vaultManifestRel)
	}
	v, err := yamlish.Unmarshal(raw)
	if err != nil {
		t.Fatal(err)
	}
	man, _ := v.(*yamlish.Map)
	copied := 0
	for _, key := range []string{"notes", "herd_docs"} {
		rows, _ := get(man, key).([]any)
		for _, row := range rows {
			m, _ := row.(*yamlish.Map)
			rel, _ := get(m, "from").(string)
			if rel == "" {
				continue
			}
			body, err := os.ReadFile(filepath.Join(src, filepath.FromSlash(rel)))
			if err != nil {
				continue // a source this checkout lacks is the «missing» note on both sides
			}
			put(t, dir, rel, string(body))
			copied++
		}
	}
	if copied == 0 {
		t.Fatalf("%s names no document this checkout has", vaultManifestRel)
	}
}

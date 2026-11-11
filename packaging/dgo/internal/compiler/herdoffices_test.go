package compiler

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// computers' registry of the herd (DGO-1800): the cases of platform/manager/test_herd_offices.py and the JSON
// reconcile.py writes for them, byte for byte — an office by its key, never by a name. The render oracle holds
// the real herd.yaml on both sides.
func TestHerdOffices(t *testing.T) {
	k1, k2 := strings.Repeat("A", 43)+"=", "+0B1Hc+7nYPESAjx/uu3JSDeuYQYadu7dvV0eb/C5B8="
	repo := t.TempDir()
	dir := filepath.Join(repo, "apps", "computers")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	herd := func(text []byte) string {
		if err := os.WriteFile(filepath.Join(dir, "herd.yaml"), text, 0o644); err != nil {
			t.Fatal(err)
		}
		got, err := herdOffices(repo)
		if err != nil {
			t.Fatal(err)
		}
		return yamlish.IndentJSON(got)
	}
	empty := "{\n  \"offices\": {},\n  \"keys\": []\n}"
	cases := []struct{ name, text, want string }{
		{"each office by its key; aliases said, quoted or not, bad and repeated ones dropped; one without a key is none",
			"offices:\n" +
				"  a:\n    label: A\n    wg_public_key: '" + k1 + "'\n    aliases: ['a-1', \"a2\", BAD, a-1, 7, x/y]   # a comment\n" +
				"  b:\n    wg_public_key: " + k2 + "\n" +
				"  nokey:\n    aliases: [portable]\n" +
				"  badkey:\n    wg_public_key: 'not-a-key'\n" +
				"hub: a\n",
			"{\n  \"offices\": {\n    \"a\": {\n      \"wg_public_key\": \"" + k1 + "\",\n      \"aliases\": [\n        \"a-1\",\n        \"a2\"\n      ]\n    },\n" +
				"    \"b\": {\n      \"wg_public_key\": \"" + k2 + "\",\n      \"aliases\": []\n    }\n  },\n" +
				"  \"keys\": [\n    \"" + k2 + "\",\n    \"" + k1 + "\"\n  ]\n}"},
		{"a duplicate key is its last, as safe_load reads it",
			"offices:\n  a:\n    wg_public_key: '" + k1 + "'\n    aliases: [one]\n    aliases: [two]\n",
			"{\n  \"offices\": {\n    \"a\": {\n      \"wg_public_key\": \"" + k1 + "\",\n      \"aliases\": [\n        \"two\"\n      ]\n    }\n  },\n" +
				"  \"keys\": [\n    \"" + k1 + "\"\n  ]\n}"},
		{"no offices block", "hub: vps1\n", empty},
		{"an id YAML does not type as a string is no office", "offices:\n  7:\n    wg_public_key: '" + k1 + "'\n", empty},
		{"not YAML", "offices: [unclosed\n", empty},
	}
	for _, c := range cases {
		if got := herd([]byte(c.text)); got != c.want {
			t.Errorf("%s:\n got %s\nwant %s", c.name, got, c.want)
		}
	}
	if got := herd([]byte("offices:\n  a: \xff\n")); got != empty {
		t.Errorf("not UTF-8: got %s, want %s", got, empty)
	}
	if err := os.Remove(filepath.Join(dir, "herd.yaml")); err != nil {
		t.Fatal(err)
	}
	if got := herd(nil); got != empty { // an empty file: safe_load gives None
		t.Errorf("an empty herd file: got %s, want %s", got, empty)
	}
}

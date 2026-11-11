package compiler

import (
	"testing"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// TestTheLanguageIsReconcilePys (DGO-971): `language:` in platform.state.yaml is read as reconcile.py reads
// it — no declaration, any case, trimmed — and a code no dictionary has is refused in the same words,
// before every manifest's own line. locale.json's bytes are held by TestRenderMatchesPython.
func TestTheLanguageIsReconcilePys(t *testing.T) {
	for _, lang := range []string{"", "language: en\n", "language: ' EN '\n", "language: he\n", "language: eng\n",
		"language: Hebrew\n", "language: 1\n", "language: true\n", "language: [en]\n", "language: null\n",
		"language: false\n", "language: 0\n", "language: ''\n"} {
		for _, files := range []map[string]string{
			{"apps/web/app.json": manifest("web", 3, "")},
			{"apps/web/app.json": manifest("web", 3, ""), "apps/bad/app.json": manifest("bad", 3, `"compose":5`)},
		} {
			repo := pyFixture(t, files, "schema_version: 1\n"+lang+"apps:\n  web: { enabled: true }\n")
			agree(t, repo, []call{argv("validate"), argv("enabled-apps")})
		}
	}
}

// TestLocaleDoc: the artifact's shape, and the default where nothing (or no dictionary) is declared.
func TestLocaleDoc(t *testing.T) {
	he := `{
  "active": "he",
  "default": "he",
  "dir": "rtl",
  "available": [
    {
      "code": "he",
      "label": "עברית",
      "label_en": "Hebrew",
      "dir": "rtl"
    },
    {
      "code": "en",
      "label": "English",
      "label_en": "English",
      "dir": "ltr"
    }
  ]
}`
	for _, doc := range []*yamlish.Map{nil, yamlish.NewMap(), ordered("language", "eng"), ordered("language", false)} {
		if got := yamlish.IndentJSON(localeDoc(doc)); got != he {
			t.Errorf("%v: got\n%s", doc, got)
		}
	}
	// written out in full: a replacer over `he` cannot change the top-level "dir" and leave the list's alone
	// (the second reader of DGO-971 caught the one that tried)
	en := `{
  "active": "en",
  "default": "en",
  "dir": "ltr",
  "available": [
    {
      "code": "he",
      "label": "עברית",
      "label_en": "Hebrew",
      "dir": "rtl"
    },
    {
      "code": "en",
      "label": "English",
      "label_en": "English",
      "dir": "ltr"
    }
  ]
}`
	if got := yamlish.IndentJSON(localeDoc(ordered("language", " En "))); got != en {
		t.Errorf("en: got\n%s\nwant\n%s", got, en)
	}
	if got := languageErrors(ordered("language", "eng")); len(got) != 1 || got[0] != "platform.state.yaml: language 'eng' "+
		"is not a language this platform has a dictionary for (expected one of en, he)" {
		t.Errorf("eng: %q", got)
	}
}

package serve

import (
	"os"
	"path/filepath"
	"testing"
)

// TestTheWizardsOfficeRecordIsWrittenAsFlaskWritesIt: PUT /api/office on an office with no container
// engine (the phone's core, DGO-1090) — what the install wizard writes first — answered byte for byte as
// app.py answers it, and the state file it leaves byte for byte the one app.py's office-set leaves: a
// body that is not a JSON object (no JSON type, a list, not JSON), a record the compiler refuses (its
// sentences, one by one), a name, and the wizard's signature, after which the office is installed.
func TestTheWizardsOfficeRecordIsWrittenAsFlaskWritesIt(t *testing.T) {
	state, err := os.ReadFile(filepath.Join(checkout(t), "platform.state.core.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	files := coreManifests(t)
	files["platform.state.yaml"] = string(state)
	// the record's vocabulary, as the office root carries it (office-root.sh): a hue and an animal are
	// checked against them
	for _, p := range []string{"platform-base/bina-ui/theme-tokens.css", "platform-base/bina-ui/bina-icons.js"} {
		b, err := os.ReadFile(filepath.Join(checkout(t), p))
		if err != nil {
			t.Fatal(err)
		}
		files[p] = string(b)
	}
	theirs, mine := fixture(t, files), fixture(t, files)
	o := startOracle(t, theirs)
	now := int64(1793560000)
	s := engineless(t, mine, &now)
	put := func(contentType, body string) exchange {
		return exchange{Method: "PUT", Path: "/api/office", Body: []byte(body), ContentType: contentType}
	}
	// Not here: a body of no JSON type (text/plain). A write any page could send without asking is refused
	// by this process's own guard (outsider: formable) before any route — 403, where app.py, with no such
	// guard, answers 400.
	for _, q := range []exchange{
		put("application/json", `["name"]`),
		put("application/json", `{"name": `),
		put("application/json", `{"nope": 1, "installed_at": "yesterday"}`),
		put("application/json; charset=utf-8", `{"name": "בינה סלושנס", "terms_version": "2026-10"}`),
		put("application/merge-patch+json", `{"terms_accepted_at": "2026-11-01T20:00:00Z"}`),
		put("application/json", `{"hue": "teal", "animal": "unicorn-of-nowhere"}`),
		// the wizard's whole record, as install.js sends it
		put("application/json", `{"name": "הלשכה הדיגיטלית", "animal": "raven", "hue": "violet", "terms_version": "2026-10",
			"terms_accepted_at": "2026-11-01T20:00:00Z", "installed_at": "2026-11-01T20:01:00Z"}`),
	} {
		same(t, q.String(), ask(s, q), o.ask(t, q))
		a, err := os.ReadFile(filepath.Join(theirs, "platform.state.yaml"))
		if err != nil {
			t.Fatal(err)
		}
		b, err := os.ReadFile(filepath.Join(mine, "platform.state.yaml"))
		if err != nil {
			t.Fatal(err)
		}
		if string(a) != string(b) {
			t.Fatalf("%s: the state file\n--- Go ---\n%s\n--- app.py ---\n%s", q.String(), b, a)
		}
	}
}

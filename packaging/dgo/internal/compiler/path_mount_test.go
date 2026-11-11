package compiler

import (
	"testing"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// The native compiler's half of DGO-553 — the two places the port has to answer exactly as
// `platform/manager/reconcile.py` does, and did not:
//
//   · `own_host_only(module)` — the console declares `embed: false, path_mount: true`. The port read
//     only the first half, so it would render the console as own-host-only: a linked office's
//     «המרכז» tile would carry no `door`, and the whole-console half of the feature would stop
//     working the day an office moves to this compiler, silently.
//   · `remote_records(served)` — the per-app record the computers app reads to know where a peer's
//     «מחשבים» is reachable. The port wrote every field but `door`, so `remote.apps()` would skip
//     every peer record and the shared fleet would come back empty, with nothing saying why.
//
// These are pure functions over declarations, so they are tested here without the Python oracle that
// the render tests need.

func module(t *testing.T, kv ...any) *yamlish.Map {
	t.Helper()
	m := yamlish.NewMap()
	for i := 0; i+1 < len(kv); i += 2 {
		m.Set(kv[i].(string), kv[i+1])
	}
	return m
}

func TestOwnHostOnlyHonoursPathMount(t *testing.T) {
	cases := []struct {
		name string
		m    *yamlish.Map
		want bool
	}{
		{"an app on its own host at home", module(t, "external", true), true},
		{"an app not framed at home at all", module(t, "embed", false), true},
		{"an embedded-only app that answers the console's own paths", module(t, "passthrough", true), true},
		{"the console: embed false + path_mount — mounted under a path", module(t, "embed", false, "path_mount", true), false},
		{"path_mount on its own is enough", module(t, "path_mount", true), false},
		{"external wins over path_mount (an origin cannot be mounted)", module(t, "external", true, "path_mount", true), true},
		{"passthrough wins over path_mount (measured failing, 2026-10-09)", module(t, "passthrough", true, "path_mount", true), true},
		{"plain embedded app", module(t, "embed", true), false},
	}
	for _, c := range cases {
		if got := ownHostOnly(c.m); got != c.want {
			t.Errorf("%s: ownHostOnly = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestRemoteRecordCarriesTheDoor(t *testing.T) {
	served := []remoteEntry{{
		office:   "macbook",
		address:  "10.79.5.2",
		link:     "macbook",
		commit:   "abc123",
		linkPort: 9005,
		label:    module(t, "he", "MacBook", "en", "MacBook"),
		identTo:  "akadmin",
		apps: []remoteApp{{
			app: "computers", alias: "computers", port: 8977,
			name: "מחשבים", icon: "monitor", group: "תשתית", desc: "",
			order: int64(9), host: "computers.localhost", health: "/healthz",
			moduleKind: "embedded", modulePath: "/a/computers/", moduleID: "computers",
		}},
	}}
	names, records := remoteRecords(served)
	if len(names) != 1 || names[0] != "remote.macbook.computers.json" {
		t.Fatalf("names = %v", names)
	}
	rec := records[names[0]]
	// The app that READS this file (apps/computers/remote.py) needs the base and the authority: a
	// record without them is an office it may not proxy, i.e. no shared machines at all.
	door, err := dict(get(rec, "door"), "door")
	if err != nil {
		t.Fatalf("the record carries no door: %v", err)
	}
	want := map[string]string{
		"base": "http://computers.macbook:9005", // the pair's door port, not the app's own
		"host": "computers.localhost",           // the authority the door routes on
		"user": "akadmin",                       // the identity the serving office mapped
	}
	for k, v := range want {
		if got := pyvalStr(get(door, k)); got != v {
			t.Errorf("door.%s = %q, want %q", k, got, v)
		}
	}
}

// pyvalStr is a tiny convenience so the table above reads like the values it asserts.
func pyvalStr(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case nil:
		return ""
	}
	return ""
}

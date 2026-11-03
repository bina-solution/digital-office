package serve

import (
	"bytes"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// engineless is the native core's control plane (NewNative) on repo, its clock the test's, with a
// container that must not be asked.
func engineless(t *testing.T, repo string, now *int64) *server {
	t.Helper()
	s, err := newServer(repo, "http://127.0.0.1:9", "", log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	s.engineless = true
	s.now = func() time.Time { return time.Unix(*now, 0) }
	s.upstream = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Errorf("%s %s reached the container: it must be answered natively", r.Method, r.URL)
		w.WriteHeader(http.StatusTeapot)
	})
	return s
}

// coreManifests are the core office's own manifests, as the APK's office root carries them.
func coreManifests(t *testing.T) map[string]string {
	t.Helper()
	files := map[string]string{}
	for _, p := range []string{
		"platform-base/app-management/app.json", "platform-base/traefik/app.json", "platform-base/forward-auth/app.json",
		"platform-base/connections/app.json", "platform-base/console/app.json", "platform-base/notifications/app.json",
		"platform-base/bina-ui/app.json", "apps/dgo-extend/app.json", "apps/computers/app.json",
	} {
		b, err := os.ReadFile(filepath.Join(checkout(t), p))
		if err != nil {
			t.Fatal(err)
		}
		files[p] = string(b)
	}
	return files
}

// TestTheCatalogWithNoEngineMatchesFlask: GET /api/apps on an office with no container engine — the
// phone's core (DGO-1090) — byte for byte as app.py answers it with no docker view, through a sequence
// that one clock and one memory of transitions run through on both sides: the core office as the APK
// carries it, then an app switched on later (its Installed moves, the rest hold their stamps), then one
// archived; with the launch URLs' every source (an app's own base-url variable with the edge's port, a
// reference to another variable, a relative, an absolute and a blank module url, a module on a later
// routing entry) and every fallback (title, summary, icon, data).
func TestTheCatalogWithNoEngineMatchesFlask(t *testing.T) {
	t.Setenv("COMPOSE_PROJECT", "office")
	t.Setenv("FLASK_DEBUG", "")
	t.Setenv("DEPLOYMENT_DOMAIN", "")
	t.Setenv("COMPANY_BASE_DOMAIN", "")
	t.Setenv("CONSOLE_BASE_URL", "console.localhost:8080")
	t.Setenv("ZZ_EDGE_BASE_URL", "${ZZ_EDGE_HOST}/")
	t.Setenv("ZZ_EDGE_HOST", "edge.example.co.il")
	files := coreManifests(t)
	files["apps/zz-edge/app.json"] = `{"id": "zz-edge", "layer": 3, "kind": "service", "version": 2.5,
		"title": {"en": "Edge cases"}, "summary": {"en": "every fallback"},
		"routing": [{"host": "zz-api"}, {"host": "zz", "module": {"embed": "/a/zz/", "url": "/inbox/", "icon": ""}}],
		"data": {"on_uninstall": null, "volumes": {}}}`
	files["apps/zz-abs/app.json"] = `{"id": "zz-abs", "layer": 3, "title": {"he": "קישור"},
		"routing": [{"host": "abs", "module": {"id": "abs-tile", "url": "https://elsewhere.example/x"}}]}`
	files["apps/zz-blank/app.json"] = `{"id": "zz-blank", "layer": 3, "routing": [{"host": "blank", "module": {"url": "  "}}],
		"data": {"on_uninstall": "delete", "volumes": ["blank_data"]}}`
	state, err := os.ReadFile(filepath.Join(checkout(t), "platform.state.core.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	files["platform.state.yaml"] = string(state)
	repo := fixture(t, files)
	o := startOracle(t, repo)
	now := int64(1793560000)
	s := engineless(t, repo, &now)
	same := func(step string) {
		t.Helper()
		q := exchange{Method: "GET", Path: "/api/apps", Now: now}
		want, got := o.ask(t, q), ask(s, q)
		if got.Status != want.Status || got.ContentType != want.ContentType || !bytes.Equal(got.Body, want.Body) {
			t.Fatalf("%s: GET /api/apps = %d %s\n%s\n--- Flask: %d %s\n%s", step, got.Status, got.ContentType, got.Body,
				want.Status, want.ContentType, want.Body)
		}
	}
	same("the core office")
	now += 100
	write(t, repo, map[string]string{"platform.state.yaml": string(state) + "  zz-edge:  { enabled: true, by: wizard }\n"})
	same("an app switched on")
	now += 100
	write(t, repo, map[string]string{"platform.state.yaml": string(state) + "  zz-edge:  { state: archived, by: cli }\n  zz-abs: { enabled: false }\n"})
	same("an app archived")
	now += 100
	same("nothing changed")
}

// TestTheCatalogIsTheContainersWhereThisCannotVouch: an office with an engine; a .env (app.py reads
// it); a compose file that is there; a manifest the compiler refuses, or one app.py lists as broken; a
// shape app.py fails on or reads its own way; a key YAML typed — each the container's, never a guess.
func TestTheCatalogIsTheContainersWhereThisCannotVouch(t *testing.T) {
	now := int64(1793560000)
	base := map[string]string{
		"platform.state.yaml":      "schema_version: 1\napps:\n  zz: { enabled: true }\n",
		"apps/zz/app.json":         `{"id": "zz", "layer": 3}`,
		"platform-base/c/app.json": `{"id": "c", "layer": 2}`,
	}
	cases := map[string]map[string]string{
		"a .env":                   {".env": "X=1\n"},
		"a compose file":           {"apps/zz/app.json": `{"id": "zz", "layer": 3, "compose": "docker-compose.yml"}`, "apps/zz/docker-compose.yml": "services: {}\n"},
		"a broken manifest":        {"apps/zz/app.json": `{"id": "zz",`},
		"an entry not a map":       {"platform.state.yaml": "schema_version: 1\napps:\n  zz: enabled\n"},
		"routing not a list":       {"apps/zz/app.json": `{"id": "zz", "layer": 3, "routing": "x"}`},
		"a host not text":          {"apps/zz/app.json": `{"id": "zz", "layer": 3, "routing": [{"host": 8080}]}`},
		"a use not iterable":       {"apps/zz/app.json": `{"id": "zz", "layer": 3, "use": 7}`},
		"a non-scalar by":          {"platform.state.yaml": "schema_version: 1\napps:\n  zz: { enabled: true, by: [a] }\n"},
		"a unicode generation":     {".generated/generations/٣/x": "x"},
		"a manifest's own _broken": {"apps/zz/app.json": `{"id": "zz", "layer": 3, "_broken": "x"}`},
		"a key YAML typed":         {"platform.state.yaml": "schema_version: 1\napps:\n  zz: { enabled: true }\n  80: { enabled: true }\n"},
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			files := map[string]string{}
			for k, v := range base {
				files[k] = v
			}
			for k, v := range change {
				files[k] = v
			}
			repo := t.TempDir()
			write(t, repo, files)
			s := engineless(t, repo, &now)
			reached := false
			s.upstream = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { reached = true; w.WriteHeader(299) })
			if a := ask(s, exchange{Method: "GET", Path: "/api/apps"}); a.Status != 299 || !reached {
				t.Fatalf("answered natively (%d %s) — must be the container's", a.Status, a.Body)
			}
		})
	}
	// and on an office with an engine, the catalog is the container's whatever it holds
	repo := t.TempDir()
	write(t, repo, base)
	s := engineless(t, repo, &now)
	s.engineless = false
	reached := false
	s.upstream = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { reached = true; w.WriteHeader(299) })
	if ask(s, exchange{Method: "GET", Path: "/api/apps"}); !reached {
		t.Fatal("an office with an engine answered its catalog natively")
	}
}

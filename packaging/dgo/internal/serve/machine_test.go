package serve

import (
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/edge"
)

// fakeMachine is the phone's machine as the core sees it: down (port 0) until the test brings it up.
type fakeMachine struct {
	port    int
	token   string
	wanted  int
	refused string
}

func (m *fakeMachine) Up() (int, string) { return m.port, m.token }

func (m *fakeMachine) Refused() string { return m.refused }

func (m *fakeMachine) Forget() { m.refused = "" }

func (m *fakeMachine) Step() string { return "" }

func (m *fakeMachine) Want() error {
	m.wanted++
	return nil
}

// The phone's core (DGO-1090, android-path.md "the machine on demand"): the install wizard enables a
// container app — the machine is asked for, and the enable and its job answer 202 while it starts; once it
// is up, the job hands the enable on to the machine's app-management, signed for that request with the
// caller's identity, then follows the machine's own job, and the job done mirrors the app on in the core's
// state (by: machine). An app that runs in no container stays the container's to answer.
func TestAContainerAppIsEnabledInTheMachine(t *testing.T) {
	repo := t.TempDir()
	write(t, repo, map[string]string{
		"platform.state.yaml":            "schema_version: 1\napps:\n  console: { enabled: true }\n",
		"platform-base/console/app.json": `{"id": "console", "layer": 2}`,
		"apps/n8n/app.json":              `{"id": "n8n", "layer": 3, "compose": "docker-compose.yml"}`,
		"apps/notes/app.json":            `{"id": "notes", "layer": 3}`,
	})
	token := strings.Repeat("k", 40)
	var seen []string
	jobs := 0
	vm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		at, nonce := r.Header.Get(edge.EdgeAt), r.Header.Get(edge.EdgeNonce)
		if r.Host != "apps.localhost" || r.Header.Get("X-authentik-username") != "owner" ||
			r.Header.Get(edge.EdgeSig) != edge.EdgeSigned(token, at, nonce, r.Method, r.Host, r.URL.RequestURI(), r.Header) {
			t.Errorf("%s %s Host %s: not signed for itself, as the owner", r.Method, r.URL, r.Host)
			w.WriteHeader(http.StatusForbidden)
			return
		}
		seen = append(seen, r.Method+" "+r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == "POST" && r.URL.Path == "/api/apps/n8n/enable":
			w.WriteHeader(http.StatusAccepted)
			_, _ = io.WriteString(w, `{"ok": true, "job": "n8n"}`)
		case r.Method == "GET" && r.URL.Path == "/api/apps/n8n/job":
			if jobs++; jobs == 1 {
				w.WriteHeader(http.StatusAccepted)
				_, _ = io.WriteString(w, `{"ok": true, "step": "pulling"}`)
				return
			}
			_, _ = io.WriteString(w, `{"ok": true}`)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(vm.Close)
	m := &fakeMachine{token: token}
	h, err := NewNative(repo, "http://127.0.0.1:9", log.New(io.Discard, "", 0), m, "localhost")
	if err != nil {
		t.Fatal(err)
	}
	s := h.(*server)
	containers := 0
	s.upstream = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { containers++; w.WriteHeader(299) })
	owner := [][2]string{{"X-authentik-username", "owner"}}
	enable := exchange{Method: "POST", Path: "/api/apps/n8n/enable", Body: []byte("{}"), ContentType: "application/json", Headers: owner}
	job := exchange{Method: "GET", Path: "/api/apps/n8n/job", Headers: owner}

	if a := ask(s, enable); a.Status != http.StatusAccepted || m.wanted != 1 || len(seen) != 0 {
		t.Fatalf("the enable, the machine down: %d %s (asked for: %d)", a.Status, a.Body, m.wanted)
	}
	if a := ask(s, job); a.Status != http.StatusAccepted || !strings.Contains(string(a.Body), "machine is starting") || m.wanted != 2 {
		t.Fatalf("the job while it starts: %d %s (asked for again: %d)", a.Status, a.Body, m.wanted)
	}
	m.refused = "the machine is not on this phone yet"
	if a := ask(s, job); a.Status != http.StatusServiceUnavailable || !strings.Contains(string(a.Body), "not on this phone") {
		t.Fatalf("the job, the app refusing the machine: %d %s", a.Status, a.Body)
	}
	// the owner asks again: the reason is the app's to give again, not a refusal for good
	if a := ask(s, enable); a.Status != http.StatusAccepted || m.refused != "" || m.wanted != 3 {
		t.Fatalf("the enable again, after a refusal: %d %s (asked for: %d)", a.Status, a.Body, m.wanted)
	}
	m.port = vm.Listener.Addr().(*net.TCPAddr).Port
	if a := ask(s, job); a.Status != http.StatusAccepted || strings.Join(seen, ", ") != "POST /api/apps/n8n/enable" {
		t.Fatalf("the job, the machine up: %d %s — the machine was asked %v", a.Status, a.Body, seen)
	}
	if a := ask(s, job); a.Status != http.StatusAccepted {
		t.Fatalf("the machine's job, still running: %d %s", a.Status, a.Body)
	}
	if a := ask(s, job); a.Status != http.StatusOK {
		t.Fatalf("the machine's job, done: %d %s", a.Status, a.Body)
	}
	state, err := os.ReadFile(filepath.Join(repo, "platform.state.yaml"))
	if err != nil || !strings.Contains(string(state), "n8n:") || !strings.Contains(string(state), "machine") {
		t.Fatalf("the core's state after the machine's job is done:\n%s", state)
	}
	if containers != 0 {
		t.Fatalf("%d of these went to the container", containers)
	}
	if ask(s, exchange{Method: "POST", Path: "/api/apps/notes/enable", Body: []byte("{}"), ContentType: "application/json"}); containers != 1 {
		t.Fatal("an app that runs in no container was not left to the container")
	}
	// an enable asked while the machine was down, then asked again with it up: handed on once, and the job
	// follows the machine's own job — it does not hand the enable on a second time
	seen = nil
	s.waiting.add("n8n")
	ask(s, enable)
	if s.waiting.has("n8n") {
		t.Fatal("the enable asked before the machine was up still waits after one handed on with it up")
	}
	ask(s, job)
	if strings.Join(seen, ", ") != "POST /api/apps/n8n/enable, GET /api/apps/n8n/job" {
		t.Fatalf("the machine was asked %v", seen)
	}
}

// A container app's disable on the phone's core: while the machine is down the machine is asked for and
// the disable answered 503 (the app's refusal, when it gave one, is the reason); once it is up, the disable
// is handed to the machine's app-management, and its answer done mirrors the app off in the core's state.
func TestAContainerAppIsDisabledInTheMachine(t *testing.T) {
	repo := t.TempDir()
	write(t, repo, map[string]string{
		"platform.state.yaml":            "schema_version: 1\napps:\n  console: { enabled: true }\n  n8n: { state: enabled, by: machine }\n",
		"platform-base/console/app.json": `{"id": "console", "layer": 2}`,
		"apps/n8n/app.json":              `{"id": "n8n", "layer": 3, "compose": "docker-compose.yml"}`,
	})
	token := strings.Repeat("k", 40)
	var seen []string
	vm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		at, nonce := r.Header.Get(edge.EdgeAt), r.Header.Get(edge.EdgeNonce)
		if r.Header.Get(edge.EdgeSig) != edge.EdgeSigned(token, at, nonce, r.Method, r.Host, r.URL.RequestURI(), r.Header) {
			t.Errorf("%s %s: not signed for itself", r.Method, r.URL)
			w.WriteHeader(http.StatusForbidden)
			return
		}
		seen = append(seen, r.Method+" "+r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"ok": true, "id": "n8n", "enabled": false}`)
	}))
	t.Cleanup(vm.Close)
	m := &fakeMachine{token: token}
	h, err := NewNative(repo, "http://127.0.0.1:9", log.New(io.Discard, "", 0), m, "localhost")
	if err != nil {
		t.Fatal(err)
	}
	s := h.(*server)
	s.upstream = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Errorf("%s %s went to the container", r.Method, r.URL) })
	disable := exchange{Method: "POST", Path: "/api/apps/n8n/disable", Body: []byte("{}"), ContentType: "application/json",
		Headers: [][2]string{{"X-authentik-username", "owner"}}}

	s.waiting.add("n8n") // an enable asked before the machine was up
	if a := ask(s, disable); a.Status != http.StatusServiceUnavailable || m.wanted != 1 || !strings.Contains(string(a.Body), "starting now") {
		t.Fatalf("the disable, the machine down: %d %s (asked for: %d)", a.Status, a.Body, m.wanted)
	}
	if s.waiting.has("n8n") {
		t.Fatal("the enable asked before the machine was up is still waiting to be handed on after the disable")
	}
	m.refused = "the machine is not on this phone yet"
	if a := ask(s, disable); a.Status != http.StatusServiceUnavailable || m.wanted != 1 || !strings.Contains(string(a.Body), "not on this phone") {
		t.Fatalf("the disable, the app refusing the machine: %d %s (asked for: %d)", a.Status, a.Body, m.wanted)
	}
	m.refused = ""
	m.port = vm.Listener.Addr().(*net.TCPAddr).Port
	s.handed.add("n8n enabled") // an enable handed on earlier whose end nobody followed
	if a := ask(s, disable); a.Status != http.StatusOK || strings.Join(seen, ", ") != "POST /api/apps/n8n/disable" {
		t.Fatalf("the disable, the machine up: %d %s — the machine was asked %v", a.Status, a.Body, seen)
	}
	if s.handed.has("n8n enabled") {
		t.Fatal("an enable still pending after the disable: its job's old done would switch the mirror back on")
	}
	state, err := os.ReadFile(filepath.Join(repo, "platform.state.yaml"))
	if err != nil || !strings.Contains(string(state), "n8n: { state: disabled, by: machine }") {
		t.Fatalf("the core's state after the machine switched n8n off:\n%s", state)
	}
}

// Once each time the machine comes up, the core's first catalog has the core's mirror set to the machine's
// own state, in its background: a container app on there is on here (by: machine); one the core has on by:
// machine that is off or archived there is so here; an app that runs in no container, a platform app, one
// the owner switched here (by: wizard) and one with a switch under way are never the machine's to say.
func TestTheMirrorFollowsTheMachine(t *testing.T) {
	repo := t.TempDir()
	state := "schema_version: 1\napps:\n  console: { enabled: true }\n  indox: { state: enabled, by: machine }\n" +
		"  meet: { state: enabled, by: wizard }\n  notes: { state: enabled, by: machine }\n" +
		"  drive: { state: enabled, by: machine }\n  cad: { state: enabled, by: machine }\n"
	write(t, repo, map[string]string{
		"platform.state.yaml":            state,
		"platform-base/console/app.json": `{"id": "console", "layer": 2}`,
		"apps/n8n/app.json":              `{"id": "n8n", "layer": 3, "compose": "docker-compose.yml"}`,
		"apps/indox/app.json":            `{"id": "indox", "layer": 3, "compose": "docker-compose.yml"}`,
		"apps/meet/app.json":             `{"id": "meet", "layer": 3, "compose": "docker-compose.yml"}`,
		"apps/drive/app.json":            `{"id": "drive", "layer": 3, "compose": "docker-compose.yml"}`,
		"apps/cad/app.json":              `{"id": "cad", "layer": 3, "compose": "docker-compose.yml"}`,
		"apps/notes/app.json":            `{"id": "notes", "layer": 3}`,
	})
	var mu sync.Mutex
	token := strings.Repeat("k", 40) // this boot's: the machine signs every request with it
	var asked atomic.Int32
	vm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		tok := token
		mu.Unlock()
		at, nonce := r.Header.Get(edge.EdgeAt), r.Header.Get(edge.EdgeNonce)
		if r.URL.Path != "/api/apps" || r.Host != "apps.localhost" || r.Header.Get("X-authentik-username") != "owner" ||
			r.Header.Get(edge.EdgeSig) != edge.EdgeSigned(tok, at, nonce, r.Method, r.Host, r.URL.RequestURI(), r.Header) {
			t.Errorf("%s %s Host %s: not the machine's app list, signed as the owner", r.Method, r.URL, r.Host)
			w.WriteHeader(http.StatusForbidden)
			return
		}
		asked.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"apps": [{"id": "n8n", "enabled": true}, {"id": "indox", "enabled": false},
			{"id": "meet", "enabled": false}, {"id": "notes", "enabled": false}, {"id": "gone", "enabled": true},
			{"id": "console", "enabled": false}, {"id": "drive", "enabled": false},
			{"id": "cad", "enabled": false, "state_desired": "archived"}]}`)
	}))
	t.Cleanup(vm.Close)
	m := &fakeMachine{token: token, port: vm.Listener.Addr().(*net.TCPAddr).Port}
	h, err := NewNative(repo, "http://127.0.0.1:9", log.New(io.Discard, "", 0), m, "localhost")
	if err != nil {
		t.Fatal(err)
	}
	s := h.(*server)
	s.upstream = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(299) })
	s.handed.addFor("drive enabled", strconv.Itoa(m.port)+" "+token) // the owner's enable of drive, under way on this boot
	catalog := exchange{Method: "GET", Path: "/api/apps", Headers: [][2]string{{"X-authentik-username", "owner"}}}
	ask(s, catalog)
	ask(s, catalog)
	s.syncing.Wait()
	if n := asked.Load(); n != 1 {
		t.Fatalf("the machine was asked for its apps %d times in one boot", n)
	}
	after, err := os.ReadFile(filepath.Join(repo, "platform.state.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	words := strings.Join(strings.Fields(string(after)), " ") // set-state pads a new entry's key to a column
	for _, want := range []string{"n8n: { state: enabled, by: machine }", "indox: { state: disabled, by: machine }",
		"meet: { state: enabled, by: wizard }", "notes: { state: enabled, by: machine }", "console: { enabled: true }",
		"drive: { state: enabled, by: machine }", "cad: { state: archived, by: machine }"} {
		if !strings.Contains(words, want) {
			t.Errorf("the core's state lacks %q:\n%s", want, after)
		}
	}
	if strings.Contains(words, "gone") {
		t.Errorf("an app the core has no manifest of was mirrored:\n%s", after)
	}
	mu.Lock()
	token = strings.Repeat("j", 40) // the machine again, another boot (another token): asked again
	m.token = token
	mu.Unlock()
	ask(s, catalog)
	s.syncing.Wait()
	if n := asked.Load(); n != 2 {
		t.Fatalf("the machine's next boot was not asked for its apps (asked %d)", n)
	}
	// drive's switch was the earlier boot's, and ended with it: this boot's mirror says what the machine has
	if b, _ := os.ReadFile(filepath.Join(repo, "platform.state.yaml")); !strings.Contains(strings.Join(strings.Fields(string(b)), " "),
		"drive: { state: disabled, by: machine }") {
		t.Errorf("an earlier boot's switch still kept drive from the mirror:\n%s", b)
	}
}

package native

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/edge"
)

// files writes each path under dir.
func files(t *testing.T, dir string, fs map[string]string) {
	t.Helper()
	for p, body := range fs {
		full := filepath.Join(dir, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(full), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

// over is a client whose every connection is the socket at path.
func over(path string) *http.Client {
	return &http.Client{Timeout: 10 * time.Second, Transport: &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		var d net.Dialer
		return d.DialContext(ctx, "unix", path)
	}}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

// The phone's first screen, natively and over sockets alone (DGO-1090): the WebView's request reaches the
// edge's socket; the edge asks forward-auth on its socket; the console behind it asks the control plane on
// its socket whether the office is set up; the control plane answers from the office root — a fresh core
// office, so the install wizard is the first screen. Anonymous, the request gets the sign-in's answer.
func TestTheFirstScreenOverTheCoresSockets(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the native core is the phone's: its sockets' modes are Unix ones")
	}
	// what this process's own environment could say instead: the rollbacks, a version, a TTL
	for _, k := range []string{"BBOX_CONTROL_PLANE", "DGO_CONSOLE", "BUILD_VERSION", "CONSOLE_OFFICE_TTL_S"} {
		t.Setenv(k, "") // restored after the test
		os.Unsetenv(k)
	}
	root := t.TempDir()
	files(t, root, map[string]string{
		".dgo-office-root":                         "dgo office root\n",
		"platform.state.yaml":                      "schema_version: 1\napps:\n  console: { enabled: true }\n  dgo-extend: { enabled: true }\n",
		"platform-base/console/app.json":           `{"id": "console", "layer": 2}`,
		"apps/dgo-extend/app.json":                 `{"id": "dgo-extend", "layer": 3, "core": true}`,
		".generated/registry/console.modules.yaml": "[]\n",
	})
	static := filepath.Join(t.TempDir(), "static")
	files(t, static, map[string]string{"index.html": "the console\n", "install.html": "the install wizard\n"})
	dir, err := os.MkdirTemp("", "nat") // short: a socket's path has a limit of ~100 bytes
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })

	// forward-auth, on its own socket: the cookie `dgo_session=ok` is the owner
	ln, err := edge.ListenUnix(filepath.Join(dir, ForwardAuthSocket))
	if err != nil {
		t.Fatal(err)
	}
	fa := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if c, err := r.Cookie("dgo_session"); err == nil && c.Value == "ok" && r.URL.Path == "/auth/traefik" {
			w.Header().Set("X-authentik-username", "owner")
			return
		}
		http.Redirect(w, r, "http://signin.localhost:8080/login", http.StatusFound)
	})}
	go fa.Serve(ln)
	t.Cleanup(func() { fa.Close() })

	c, err := Open(root, Options{Dir: dir, Domain: "localhost", Static: static, Console: "http://127.0.0.1:9", Apps: "http://127.0.0.1:9"},
		log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Close(context.Background()) })
	for _, s := range []string{EdgeSocket, ConsoleSocket, ControlSocket} {
		if st, err := os.Stat(filepath.Join(dir, s)); err != nil || st.Mode().Perm() != 0o600 {
			t.Fatalf("%s: %v, want a socket of mode 0600", s, err)
		}
	}

	ask := func(path, cookie string) (int, string) {
		t.Helper()
		req, err := http.NewRequest("GET", "http://console.localhost:8080"+path, nil)
		if err != nil {
			t.Fatal(err)
		}
		if cookie != "" {
			req.AddCookie(&http.Cookie{Name: "dgo_session", Value: cookie})
		}
		res, err := over(filepath.Join(dir, EdgeSocket)).Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer res.Body.Close()
		b, _ := io.ReadAll(res.Body)
		return res.StatusCode, string(b)
	}
	if code, body := ask("/", "ok"); code != http.StatusOK || body != "the install wizard\n" {
		t.Fatalf("the owner's first screen = %d %q, want the install wizard", code, body)
	}
	if code, body := ask("/api/version", "ok"); code != http.StatusOK || !strings.Contains(body, "dev") {
		t.Fatalf("/api/version = %d %q, answered natively", code, body)
	}
	if code, _ := ask("/", ""); code != http.StatusFound {
		t.Fatalf("anonymous = %d, want the sign-in's 302", code)
	}

	// the wizard, as install.js runs it: the apps it offers, then the office's record with its signature —
	// and the next "/" is the shell, its brand line's record the one just written
	send := func(method, path, body string) (int, string) {
		t.Helper()
		req, err := http.NewRequest(method, "http://console.localhost:8080"+path, strings.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.AddCookie(&http.Cookie{Name: "dgo_session", Value: "ok"})
		if body != "" {
			req.Header.Set("Content-Type", "application/json")
		}
		req.Header.Set("Origin", "http://console.localhost:8080")
		res, err := over(filepath.Join(dir, EdgeSocket)).Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer res.Body.Close()
		b, _ := io.ReadAll(res.Body)
		return res.StatusCode, string(b)
	}
	if code, body := send("GET", "/a/app-management/api/apps", ""); code != http.StatusOK || !strings.Contains(body, `"id":"dgo-extend"`) ||
		!strings.Contains(body, `"reason":"DockerUnavailable"`) {
		t.Fatalf("the wizard's apps = %d %s", code, body)
	}
	if code, body := send("PUT", "/a/app-management/api/office", `{"name": "the phone", "installed_at": "2026-11-01T20:01:00Z"}`); code != http.StatusOK ||
		!strings.Contains(body, `"installed":true`) {
		t.Fatalf("the wizard's record = %d %s", code, body)
	}
	if code, body := ask("/", "ok"); code != http.StatusOK || body != "the console\n" {
		t.Fatalf("after the wizard, / = %d %q, want the shell", code, body)
	}
	if code, body := send("GET", "/api/office", ""); code != http.StatusOK || !strings.Contains(body, `"name":"the phone"`) || !strings.Contains(body, `"installed":true`) {
		t.Fatalf("the brand line's record = %d %s", code, body)
	}
}

// The machine as the app reports it: "<port> <token>" in a regular file, or no machine at all.
func TestTheMachineIsWhatTheAppReports(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, MachineFile)
	token := strings.Repeat("k", 32)
	for body, want := range map[string]int{
		"40123 " + token + "\n": 40123, "40123 short": 0, "80 " + token: 0, "70000 " + token: 0, "x " + token: 0,
		"40123": 0, "40123 " + token + " extra": 0, "": 0,
	} {
		if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
		if port, tok := machine(p); port != want || (want != 0 && tok != token) {
			t.Errorf("%q: machine = %d %q, want %d", body, port, tok, want)
		}
	}
	os.Remove(p)
	if port, _ := machine(p); port != 0 {
		t.Error("no file was taken for a machine")
	}
	if err := os.Mkdir(p, 0o700); err != nil {
		t.Fatal(err)
	}
	if port, _ := machine(p); port != 0 {
		t.Error("a directory was taken for a machine")
	}
}

// The app's reason it could not start the machine is read as one line, a long one too (a reason read as
// none would ask for the machine again at every poll), and forgotten when the owner asks again.
func TestTheAppsRefusalIsReadAndForgotten(t *testing.T) {
	dir := t.TempDir()
	m := coreMachine{wanted: filepath.Join(dir, MachineWanted), refused: filepath.Join(dir, MachineRefused)}
	if got := m.Refused(); got != "" {
		t.Fatalf("no file: %q", got)
	}
	long := "zstd: " + strings.Repeat("x", 3000)
	for _, c := range [][2]string{
		{"the machine is not on this phone yet\n", "the machine is not on this phone yet"},
		{"could not be unpacked:\nzstd: a\n  b\n", "could not be unpacked: zstd: a b"},
		{long, long[:2<<10]},
	} {
		if err := os.WriteFile(m.refused, []byte(c[0]), 0o600); err != nil {
			t.Fatal(err)
		}
		if got := m.Refused(); got != c[1] {
			t.Errorf("%.40q: Refused = %.60q, want %.60q", c[0], got, c[1])
		}
	}
	m.Forget()
	if got := m.Refused(); got != "" {
		t.Fatalf("after Forget: %q", got)
	}
	m.Forget() // nothing to forget: no harm
}

// After an update the office's state is the office's, and the APK's own lies beside it: the apps it lists
// that the office's lacks are added as it gives them, the office's own entries untouched, and the file goes.
func TestTheShippedStateAddsWhatTheOfficeLacks(t *testing.T) {
	root := t.TempDir()
	files(t, root, map[string]string{
		"platform.state.yaml":            "schema_version: 1\napps:\n  console: { enabled: true }\n  n8n: { state: enabled, by: machine }\n",
		ShippedState:                     "schema_version: 1\napps:\n  console: { enabled: true }\n  dgo-extend: { enabled: true }\n",
		"platform-base/console/app.json": `{"id": "console", "layer": 2}`,
		"apps/dgo-extend/app.json":       `{"id": "dgo-extend", "layer": 3, "core": true}`,
		"apps/n8n/app.json":              `{"id": "n8n", "layer": 3}`,
	})
	mergeShipped(root, t.Logf)
	state, err := os.ReadFile(filepath.Join(root, "platform.state.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	words := strings.Join(strings.Fields(string(state)), " ") // set-state pads a new entry's key to a column
	for _, want := range []string{"dgo-extend: { state: enabled, by: core }", "n8n: { state: enabled, by: machine }", "console: { enabled: true }"} {
		if !strings.Contains(words, want) {
			t.Errorf("the office's state lacks %q:\n%s", want, state)
		}
	}
	if _, err := os.Stat(filepath.Join(root, ShippedState)); err == nil {
		t.Error("the APK's state was left to be merged again")
	}
	mergeShipped(root, t.Logf) // nothing left to merge: no harm

	// an office state the core cannot read is never written over, though set-state could edit its text (a
	// merge key yamlish refuses, beside the office's own dgo-extend entry): the APK's waits beside it
	odd := t.TempDir()
	const own = "schema_version: 1\napps:\n  dgo-extend: { state: disabled, by: owner }\n<<: {}\n"
	files(t, odd, map[string]string{
		"platform.state.yaml": own,
		ShippedState:          "schema_version: 1\napps:\n  dgo-extend: { enabled: true }\n",
	})
	mergeShipped(odd, t.Logf)
	if b, _ := os.ReadFile(filepath.Join(odd, "platform.state.yaml")); string(b) != own {
		t.Errorf("a state the core cannot read was written over: %q", b)
	}
	if _, err := os.Stat(filepath.Join(odd, ShippedState)); err != nil {
		t.Errorf("the APK's state was dropped before it could be merged: %v", err)
	}
}

// The apps the machine runs are the ones the core's state says it enabled (by: machine), and only their
// hosts wake the machine: asked for, its step shown — or, while the app's refusal holds, the refusal shown
// and nothing asked (a page that loads itself again must not restart what failed).
func TestTheMachinesAppsWakeIt(t *testing.T) {
	root, dir := t.TempDir(), t.TempDir()
	files(t, root, map[string]string{
		"platform-base/console/app.json": `{"id": "console", "layer": 2}`,
		"apps/n8n/app.json":              `{"id": "n8n", "layer": 3, "routing": [{"host": "n8n"}, {"host": "n8n-hooks"}]}`,
		"apps/indox/app.json":            `{"id": "indox", "layer": 3, "routing": [{"host": "incoming-documents"}]}`,
		"apps/notes/app.json":            `{"id": "notes", "layer": 3, "routing": [{"host": "notes"}]}`,
	})
	m := coreMachine{wanted: filepath.Join(dir, MachineWanted), refused: filepath.Join(dir, MachineRefused)}
	wake := m.wake(root, "localhost")
	state := func(apps string) {
		if err := os.WriteFile(filepath.Join(root, "platform.state.yaml"), []byte("schema_version: 1\napps:\n"+apps), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	state("  console: { enabled: true }\n  notes: { state: enabled, by: wizard }\n")
	if on := machineApps(root); len(on) != 0 {
		t.Fatalf("no app of the machine's: %v", on)
	}
	if _, has := wake("notes.localhost", false); has {
		t.Fatal("an app the machine does not run woke it")
	}
	state("  console: { enabled: true }\n  n8n: { state: enabled, by: machine }\n  indox: { state: disabled, by: machine }\n")
	if on := machineApps(root); strings.Join(on, ",") != "n8n" {
		t.Fatalf("the machine's apps = %v, want n8n", on)
	}
	for _, c := range []struct {
		host string
		want bool
	}{
		{"n8n.localhost", true},
		{"n8n.console.localhost", true}, // its console tile's own host
		{"n8n-hooks.localhost", true},
		{"incoming-documents.localhost", false},
		{"typo.localhost", false},
		{"n8n.elsewhere", false},
	} {
		if _, has := wake(c.host, false); has != c.want {
			t.Errorf("%s: wakes the machine = %v, want %v", c.host, has, c.want)
		}
	}
	if _, err := os.Stat(m.wanted); err == nil {
		t.Fatal("asked without being asked to ask")
	}
	if err := os.WriteFile(m.refused, []byte("the machine could not be unpacked: zstd: no space\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if step, _ := wake("n8n.localhost", true); step != "the machine could not be unpacked: zstd: no space" {
		t.Fatalf("the page's step = %q, want the app's refusal", step)
	}
	if _, err := os.Stat(m.wanted); err == nil || m.Refused() == "" {
		t.Fatalf("a refusal the page showed was asked again (wanted: %v) or dropped (%q)", err == nil, m.Refused())
	}
	m.Forget()
	if err := os.WriteFile(filepath.Join(dir, MachineStep), []byte("the office's machine is being unpacked: 40%\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if step, _ := wake("n8n.localhost", true); step != "the office's machine is being unpacked: 40%" {
		t.Fatalf("the page's step = %q", step)
	}
	if _, err := os.Stat(m.wanted); err != nil {
		t.Fatalf("the machine was not asked for: %v", err)
	}
}

// The machine is used only once it has proved it holds the reported token: a server on the reported port
// that cannot answer the nonce — another app holding it — is no machine, and is never sent the token.
func TestTheMachineMustProveItsToken(t *testing.T) {
	token := strings.Repeat("k", 40)
	honest := func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/edge-proof" || r.Host != "signin.localhost" {
			http.NotFound(w, r)
			return
		}
		mac := hmac.New(sha256.New, []byte(token))
		mac.Write([]byte(r.URL.Query().Get("nonce")))
		_, _ = io.WriteString(w, hex.EncodeToString(mac.Sum(nil)))
	}
	var leaked bool
	squatter := func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.String(), token) || strings.Contains(fmt.Sprint(r.Header), token) {
			leaked = true
		}
		_, _ = io.WriteString(w, strings.Repeat("0", 64))
	}
	for name, h := range map[string]http.HandlerFunc{"the machine": honest, "a squatter": squatter} {
		srv := httptest.NewServer(h)
		port := srv.Listener.Addr().(*net.TCPAddr).Port
		file := filepath.Join(t.TempDir(), MachineFile)
		if err := os.WriteFile(file, []byte(fmt.Sprintf("%d %s\n", port, token)), 0o600); err != nil {
			t.Fatal(err)
		}
		got, _ := newMachineGate(file, "signin.localhost", t.Logf).get()
		srv.Close()
		if want := map[string]int{"the machine": port, "a squatter": 0}[name]; got != want {
			t.Errorf("%s: the machine = %d, want %d", name, got, want)
		}
	}
	if leaked {
		t.Fatal("the token was sent to a server that had not proved it holds it")
	}
}

// The edge faces the WebView on loopback or on a socket, never on another address.
func TestTheEdgeListensOnLoopbackOrASocket(t *testing.T) {
	for addr, ok := range map[string]bool{
		"": true, "127.0.0.1:8080": true, "localhost:8080": true, "[::1]:8080": true, "unix:/run/x/edge.sock": true,
		"0.0.0.0:8080": false, ":8080": false, "192.168.1.5:8080": false, "unix:edge.sock": false, "unix://host/edge.sock": false,
	} {
		if _, err := edgeListener(addr, "/run/x/edge.sock"); (err == nil) != ok {
			t.Errorf("--listen %q: %v, want accepted=%v", addr, err, ok)
		}
	}
}

// The core is not built where it would be reachable by others, nor without an office root.
func TestTheCoreRefusesAnOpenDirectoryAndNoRoot(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the native core is the phone's: its directory's modes are Unix ones")
	}
	dir, err := os.MkdirTemp("", "nat")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	o := Options{Dir: dir, Domain: "localhost", Static: t.TempDir(), Console: "http://127.0.0.1:9", Apps: "http://127.0.0.1:9"}
	if _, err := Open("", o, log.New(io.Discard, "", 0)); err == nil || !strings.Contains(err.Error(), "DGO_OFFICE_ROOT") {
		t.Fatalf("no office root: %v", err)
	}
	if err := os.Chmod(dir, 0o750); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(t.TempDir(), o, log.New(io.Discard, "", 0)); err == nil || !strings.Contains(err.Error(), "may be opened by others") {
		t.Fatalf("a directory its group may open: %v", err)
	}
	if err := os.Chmod(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	// a container the console sends the owner's session to: never on a loopback port any app may bind
	for up, ok := range map[string]bool{
		"http://127.0.0.1:9": true, "http://127.0.0.1": true, "http://10.0.2.2:8080": true,
		"http://127.0.0.1:8081": false, "http://localhost:3000": false, "http://[::1]:9000": false,
	} {
		if err := ownUpstream("--console-container", up); (err == nil) != ok {
			t.Errorf("--console-container %s: %v, want accepted=%v", up, err, ok)
		}
	}
	bad := o
	bad.Console = "http://127.0.0.1:8081"
	if _, err := Open(t.TempDir(), bad, log.New(io.Discard, "", 0)); err == nil || !strings.Contains(err.Error(), "any app on the phone may bind") {
		t.Fatalf("Open with --console-container %s: %v", bad.Console, err)
	}
	o.Dir = "relative"
	if _, err := Open(t.TempDir(), o, log.New(io.Discard, "", 0)); err == nil {
		t.Fatal("a relative directory was taken")
	}
}

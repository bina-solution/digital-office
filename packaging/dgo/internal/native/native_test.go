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
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/edge"
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

// The core asks for the machine at its start only for the apps the office runs there for the owner, never for
// its plumbing alone (DGO-1818: a phone with «מכולות» installed booted its machine under TCG at every start for
// the four apps its own state enables). The plumbing is still the machine's, and its hosts still wake it.
func TestOnlyTheOwnersAppsBringTheMachineAtStart(t *testing.T) {
	root, dir := t.TempDir(), t.TempDir()
	plumbing := map[string]string{}
	for _, id := range []string{"connections", "computers", "notifications", "dgo-extend"} {
		plumbing["apps/"+id+"/app.json"] = `{"id": "` + id + `", "layer": 3, "compose": "docker-compose.yml", "routing": [{"host": "` + id + `"}]}`
	}
	plumbing["apps/notes/app.json"] = `{"id": "notes", "layer": 3, "compose": "docker-compose.yml", "routing": [{"host": "notes"}]}`
	files(t, root, plumbing)
	state := func(apps string) {
		if err := os.WriteFile(filepath.Join(root, "platform.state.yaml"), []byte("schema_version: 1\napps:\n"+apps), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	core := "  connections: { state: enabled, by: core }\n  computers: { state: enabled, by: core }\n" +
		"  notifications: { state: enabled, by: core }\n  dgo-extend: { state: enabled, by: core }\n"
	state(core)
	if on := machineApps(root); len(on) != 4 {
		t.Fatalf("the plumbing is the machine's: %v", on)
	}
	if on := startApps(root); len(on) != 0 {
		t.Fatalf("the plumbing alone brought the machine at start: %v", on)
	}
	m := coreMachine{wanted: filepath.Join(dir, MachineWanted), refused: filepath.Join(dir, MachineRefused)}
	if _, has := m.wake(root, "localhost")("dgo-extend.localhost", false); !has {
		t.Fatal("the link's host no longer wakes the machine")
	}
	// a fresh phone's state says no `by` at all: the same
	state("  connections: { enabled: true }\n  dgo-extend: { enabled: true }\n")
	if on := startApps(root); len(on) != 0 {
		t.Fatalf("the plumbing (no by) brought the machine at start: %v", on)
	}
	// an app the owner runs there brings it back; so does plumbing the owner or the machine enabled
	state(core + "  notes: { state: enabled, by: owner }\n")
	if on := startApps(root); strings.Join(on, ",") != "notes" {
		t.Fatalf("at start = %v, want notes", on)
	}
	state("  dgo-extend: { state: enabled, by: machine }\n  computers: { state: enabled, by: owner }\n")
	if on := startApps(root); strings.Join(on, ",") != "dgo-extend,computers" {
		t.Fatalf("at start = %v, want dgo-extend (by: machine) and computers (by: owner)", on)
	}
}

// What Open itself does at the start: the app's ask file is written for the owner's container app, and not for
// the core's own plumbing alone — a reverted call site (machineApps at the start again) fails here.
func TestTheCoresStartAsksForTheMachineOnlyForTheOwnersApps(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the native core is the phone's: its sockets' modes are Unix ones")
	}
	for _, k := range []string{"BBOX_CONTROL_PLANE", "DGO_CONSOLE", "BUILD_VERSION", "CONSOLE_OFFICE_TTL_S"} {
		t.Setenv(k, "")
		os.Unsetenv(k)
	}
	asked := func(apps string) bool {
		t.Helper()
		root := t.TempDir()
		fs := map[string]string{
			".dgo-office-root":                         "dgo office root\n",
			"platform.state.yaml":                      "schema_version: 1\napps:\n  console: { enabled: true }\n" + apps,
			"platform-base/console/app.json":           `{"id": "console", "layer": 2}`,
			".generated/registry/console.modules.yaml": "[]\n",
			"apps/notes/app.json":                      `{"id": "notes", "layer": 3, "compose": "docker-compose.yml", "routing": [{"host": "notes"}]}`,
		}
		for id := range machinePlumbing {
			fs["apps/"+id+"/app.json"] = `{"id": "` + id + `", "layer": 3, "compose": "docker-compose.yml", "routing": [{"host": "` + id + `"}]}`
		}
		files(t, root, fs)
		static := filepath.Join(t.TempDir(), "static")
		files(t, static, map[string]string{"index.html": "the console\n", "install.html": "the install wizard\n"})
		dir, err := os.MkdirTemp("", "nat") // short: a socket's path has a limit of ~100 bytes
		if err != nil {
			t.Fatal(err)
		}
		defer os.RemoveAll(dir)
		c, err := Open(root, Options{Dir: dir, Domain: "localhost", Static: static, Console: "http://127.0.0.1:9", Apps: "http://127.0.0.1:9"},
			log.New(io.Discard, "", 0))
		if err != nil {
			t.Fatal(err)
		}
		defer c.Close(context.Background())
		_, err = os.Stat(filepath.Join(dir, MachineWanted))
		return err == nil
	}
	plumbing := "  connections: { enabled: true }\n  computers: { enabled: true }\n  notifications: { enabled: true }\n  dgo-extend: { enabled: true }\n"
	if asked(plumbing) {
		t.Error("the core asked for the machine at its start for its own plumbing alone")
	}
	if !asked(plumbing + "  notes: { state: enabled, by: owner }\n") {
		t.Error("the core did not ask for the machine at its start for the owner's container app")
	}
}

// The plumbing named by hand is exactly what the core's shipped state enables in containers: a later
// platform.state.core.yaml that enables another container app is seen here, not on a phone.
func TestThePlumbingIsWhatTheCoreStateRunsInContainers(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("links to the checkout")
	}
	repo, _ := os.Getwd()
	for {
		if _, err := os.Stat(filepath.Join(repo, "platform.state.core.yaml")); err == nil {
			break
		}
		parent := filepath.Dir(repo)
		if parent == repo {
			t.Skip("not inside the checkout: no platform.state.core.yaml above here")
		}
		repo = parent
	}
	core, err := os.ReadFile(filepath.Join(repo, "platform.state.core.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "platform.state.yaml"), core, 0o600); err != nil {
		t.Fatal(err)
	}
	for _, d := range []string{"apps", "platform-base", "platform"} {
		if err := os.Symlink(filepath.Join(repo, d), filepath.Join(root, d)); err != nil {
			t.Fatal(err)
		}
	}
	on := machineApps(root)
	sort.Strings(on)
	var want []string
	for id := range machinePlumbing {
		want = append(want, id)
	}
	sort.Strings(want)
	if strings.Join(on, ",") != strings.Join(want, ",") {
		t.Fatalf("the core state's container apps = %v, machinePlumbing = %v: name the new one, or say why it is not plumbing", on, want)
	}
	if got := startApps(root); len(got) != 0 {
		t.Fatalf("the core state alone asks for the machine at start: %v", got)
	}
}

// The apps the machine runs are the ones the core's state says it enabled (by: machine) and the enabled
// ones that run in containers the core does not answer itself (DGO-1328: the core office's dgo-extend), and
// only their hosts wake the machine: asked for, its step shown — or, while the app's refusal holds, the
// refusal shown and nothing asked (a page that loads itself again must not restart what failed).
func TestTheMachinesAppsWakeIt(t *testing.T) {
	root, dir := t.TempDir(), t.TempDir()
	files(t, root, map[string]string{
		"platform-base/console/app.json": `{"id": "console", "layer": 2, "compose": "docker-compose.yml"}`,
		"apps/n8n/app.json":              `{"id": "n8n", "layer": 3, "routing": [{"host": "n8n"}, {"host": "n8n-hooks"}]}`,
		"apps/indox/app.json":            `{"id": "indox", "layer": 3, "routing": [{"host": "incoming-documents"}]}`,
		"apps/notes/app.json":            `{"id": "notes", "layer": 3, "routing": [{"host": "notes"}]}`,
		"apps/dgo-extend/app.json":       `{"id": "dgo-extend", "layer": 3, "compose": "docker-compose.yml", "routing": [{"host": "dgo-extend"}]}`,
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
	// the core office's own dgo-extend runs in containers, which only the machine has: the machine's, and its
	// host wakes it; the console, which the core answers itself, is not, compose or not
	state("  console: { enabled: true }\n  dgo-extend: { enabled: true }\n  notes: { state: enabled, by: wizard }\n")
	if on := machineApps(root); strings.Join(on, ",") != "dgo-extend" {
		t.Fatalf("the machine's apps = %v, want dgo-extend", on)
	}
	if _, has := wake("dgo-extend.localhost", false); !has {
		t.Fatal("the core office's dgo-extend does not wake the machine")
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

// A container app opens on the phone from the machine's own console, as the console container serves it on
// every other office (DGO-1328): before the machine is up, the page that waits for it; once it is up and has
// proved its token, the machine's answer — the identity the edge wrote, the request signed with the token,
// the core's own sign-in left out, a posted body whole. And the rail shows the machine's tiles — the apps it
// runs, the offices it links — beside the core's own, none twice, kept for the next start.
func TestContainerAppsOpenFromTheMachinesConsole(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the native core is the phone's: its sockets' modes are Unix ones")
	}
	for _, k := range []string{"BBOX_CONTROL_PLANE", "DGO_CONSOLE", "BUILD_VERSION", "CONSOLE_OFFICE_TTL_S"} {
		t.Setenv(k, "")
		os.Unsetenv(k)
	}
	root := t.TempDir()
	files(t, root, map[string]string{
		".dgo-office-root":                         "dgo office root\n",
		"platform.state.yaml":                      "schema_version: 1\napps:\n  console: { enabled: true }\n",
		"platform-base/console/app.json":           `{"id": "console", "layer": 2}`,
		".generated/registry/console.modules.yaml": "- {id: home, alias: home, name: the core's home, order: 1}\n",
	})
	shell := t.TempDir() // the console's own views beside its static/, as the image's /app holds modules.yaml
	files(t, shell, map[string]string{"modules.yaml": "- {id: settings, view: settings, name: the core's settings view}\n"})
	static := filepath.Join(shell, "static")
	files(t, static, map[string]string{"index.html": "the console\n", "install.html": "the install wizard\n"})
	dir, err := os.MkdirTemp("", "nat")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
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

	token := strings.Repeat("k", 40)
	type seen struct {
		host, path, user, cookie, body string
		signed                         bool
	}
	got := make(chan seen, 8)
	machine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/edge-proof" && r.Host == "signin.localhost" {
			mac := hmac.New(sha256.New, []byte(token))
			mac.Write([]byte(r.URL.Query().Get("nonce")))
			_, _ = io.WriteString(w, hex.EncodeToString(mac.Sum(nil)))
			return
		}
		// as the machine's forward-auth checks the core's identity (FORWARD_AUTH_EDGE_TOKEN)
		signed := hmac.Equal([]byte(r.Header.Get(edge.EdgeSig)), []byte(edge.EdgeSigned(token,
			r.Header.Get(edge.EdgeAt), r.Header.Get(edge.EdgeNonce), r.Method, r.Host, r.URL.RequestURI(), r.Header)))
		if r.URL.Path == "/api/modules" {
			if !signed || r.Header.Get("X-authentik-username") != "owner" {
				http.Error(w, "nobody", http.StatusUnauthorized)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, `{"modules": [{"id": "home", "alias": "home", "name": "the machine's home"},`+
				`{"id": "n8n", "alias": "n8n", "name": "n8n", "order": 5},`+
				`{"id": "settings", "view": "settings", "name": "the machine's settings view"},`+
				`{"id": "odd", "name": "an order that is no whole number", "order": "first"},`+
				`{"id": "hp-laptop--bina", "alias": "bina", "name": "Bina", "remote": {"office": "hp-laptop", "ok": true}}]}`)
			return
		}
		if strings.HasPrefix(r.URL.Path, "/a/notyet/") { // the machine's edge, before the app's container is up
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			w.WriteHeader(http.StatusNotFound)
			_, _ = io.WriteString(w, "404 page not found\n")
			return
		}
		b, _ := io.ReadAll(r.Body)
		got <- seen{r.Host, r.URL.Path, r.Header.Get("X-authentik-username"), r.Header.Get("Cookie"), string(b), signed}
		_, _ = io.WriteString(w, "the machine's dgo-extend\n")
	}))
	t.Cleanup(machine.Close)

	c, err := Open(root, Options{Dir: dir, Domain: "localhost", Static: static, Console: "http://127.0.0.1:9", Apps: "http://127.0.0.1:9"},
		log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Close(context.Background()) })
	do := func(method, path, body string) (int, string) {
		t.Helper()
		req, err := http.NewRequest(method, "http://console.localhost:8080"+path, strings.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Cookie", "dgo_session=ok; other=1")
		req.Header.Set("Origin", "http://console.localhost:8080")
		req.Header.Set("Accept", "text/html")
		res, err := over(filepath.Join(dir, EdgeSocket)).Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer res.Body.Close()
		b, _ := io.ReadAll(res.Body)
		return res.StatusCode, string(b)
	}

	if code, body := do("GET", "/a/dgo-extend/", ""); code != http.StatusServiceUnavailable {
		t.Fatalf("before the machine is up: %d %.200q, want the page that waits for it", code, body)
	}
	// the rail before the machine is up asks it nothing, and waits on nothing
	if code, body := do("GET", "/api/modules", ""); code != http.StatusOK || strings.Contains(body, `"id":"n8n"`) {
		t.Fatalf("the rail before the machine: %d %.200q", code, body)
	}
	port := machine.Listener.Addr().(*net.TCPAddr).Port
	if err := os.WriteFile(filepath.Join(dir, MachineFile), []byte(fmt.Sprintf("%d %s\n", port, token)), 0o600); err != nil {
		t.Fatal(err)
	}
	if code, body := do("POST", "/a/dgo-extend/api/pair", `{"code": "123"}`); code != http.StatusOK || body != "the machine's dgo-extend\n" {
		t.Fatalf("the machine up: %d %q, want its dgo-extend's answer", code, body)
	}
	s := <-got
	if s.host != "console.localhost:8080" || s.path != "/a/dgo-extend/api/pair" || s.user != "owner" || !s.signed ||
		strings.Contains(s.cookie, "dgo_session") || !strings.Contains(s.cookie, "other=1") || s.body != `{"code": "123"}` {
		t.Fatalf("what the machine was sent: %+v", s)
	}
	// an app whose container is not up yet: the page that waits, never the machine edge's bare 404
	if code, body := do("GET", "/a/notyet/", ""); code != http.StatusServiceUnavailable || strings.Contains(body, "404 page not found") {
		t.Fatalf("an app not up yet in the machine: %d %.200q, want the page that waits", code, body)
	}

	deadline := time.Now().Add(10 * time.Second)
	for {
		_, body := do("GET", "/api/modules", "")
		if strings.Contains(body, `"id":"n8n"`) {
			if !strings.Contains(body, `"id":"hp-laptop--bina"`) || strings.Contains(body, "the machine's home") || !strings.Contains(body, "the core's home") ||
				strings.Contains(body, "the machine's settings view") || !strings.Contains(body, "the core's settings view") || strings.Contains(body, `"id":"odd"`) {
				t.Fatalf("the rail: %s", body)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("the machine's tiles never reached the rail: %s", body)
		}
		time.Sleep(100 * time.Millisecond)
	}
	if b, err := os.ReadFile(filepath.Join(dir, MachineTiles)); err != nil || !strings.Contains(string(b), `"n8n"`) {
		t.Fatalf("the machine's tiles were not kept: %v %q", err, b)
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

// Package native is `dgo be-child native`: the phone's office core in ONE process (DGO-1090,
// ai/context/research/android-path.md) — the console's server and the control plane, each on a Unix
// socket of its own in the app's directory, and the edge in front of them gating through forward-auth,
// the one other process, on its socket beside them.
//
// The directory is its owner's alone, and so is every socket in it (edge.ListenUnix): whatever connects
// is this app. A connection there is therefore the local hop loopback is on a desktop — the console
// believes the identity headers the edge writes, and the control plane answers, as both do 127.0.0.1 —
// and nothing else on the phone can reach them. Loopback is every app's on a phone, so only the edge may
// face the WebView there (--listen 127.0.0.1:8080): it believes no caller. (Not a socket for the WebView:
// shouldInterceptRequest never sees a request's body, so no sign-in could be posted through one.)
package native

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/compiler"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/console"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/edge"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/serve"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// The sockets, in the directory --dir names.
const (
	EdgeSocket        = "edge.sock"         // what the app's WebView opens
	ConsoleSocket     = "console.sock"      // the console's server, behind the edge
	ControlSocket     = "control.sock"      // the control plane, which the console asks about the office
	ForwardAuthSocket = "forward-auth.sock" // forward-auth's own (FORWARD_AUTH_LISTEN=unix:…): not made here
	MachineFile       = "machine"           // the machine's "<port> <token>", while its QEMU holds the port (the app's)
	MachineWanted     = "machine-wanted"    // the control plane's ask for the machine, which the app answers
	MachineRefused    = "machine-refused"   // the app's reason it could not start the machine, while it holds
	MachineStep       = "machine-step"      // what the app does toward the machine now (its disk unpacked)
)

// coreMachine is the machine as the control plane uses it: up as the edge sees it (proved), asked for
// through the app (NativeService watches for MachineWanted).
type coreMachine struct {
	gate            *machineGate
	wanted, refused string
}

func (m coreMachine) Up() (int, string) { return m.gate.get() }

func (m coreMachine) Want() error { return os.WriteFile(m.wanted, []byte("1\n"), 0o600) }

// Refused is the app's reason, one short line of text, or "".
func (m coreMachine) Refused() string { return line(m.refused) }

// Forget removes the app's reason: the next Want is the app's to answer again.
func (m coreMachine) Forget() { _ = os.Remove(m.refused) }

// Step is what the app does toward the machine now, one short line of text, or "".
func (m coreMachine) Step() string { return line(filepath.Join(filepath.Dir(m.refused), MachineStep)) }

// wake is the edge's Wake on the office root: whether host is one of the apps the machine runs (their
// routing hosts, on domain), and, asked, the machine asked for. While the app's refusal holds, the page
// shows it and asks nothing: a page that loads itself again every few seconds must not start an unpack
// that failed over and over — the owner's next enable asks again (down), and so does the app itself, once,
// each time the owner comes back to it (NativeService.inFront).
func (m coreMachine) wake(root, domain string) func(string, bool) (string, bool) {
	return func(host string, ask bool) (string, bool) {
		label, ok := strings.CutSuffix(host, "."+domain)
		// the console opens an external app on a host under its own (app.js externalUrl: plane.console.<domain>)
		label = strings.TrimSuffix(label, ".console")
		if !ok || !machineHosts(root)[label] {
			return "", false
		}
		if !ask {
			return "", true
		}
		if why := m.Refused(); why != "" {
			return why, true
		}
		_ = m.Want()
		return m.Step(), true
	}
}

// ShippedState is the APK's own state, which the app keeps beside the office's when an update carries the
// office's state over (NativeService.unpackRoot): the apps it lists that the office's state lacks — a core
// app the later APK brings — are added with the disposition it gives them, once (the file then goes).
const ShippedState = "platform.state.shipped.yaml"

func mergeShipped(root string, logf func(string, ...any)) {
	path := filepath.Join(root, ShippedState)
	raw, err := os.ReadFile(path)
	if err != nil {
		return
	}
	doc, err := yamlish.Unmarshal(raw)
	top, isMap := doc.(*yamlish.Map)
	if err != nil || !isMap {
		logf("%s does not read: the office's state is kept as it is, and the file goes", ShippedState)
		_ = os.Remove(path)
		return
	}
	rawApps, _ := top.Get("apps")
	shipped, isMap := rawApps.(*yamlish.Map)
	if !isMap {
		_ = os.Remove(path)
		return
	}
	// the office's own apps, or nothing is merged: set-state edits the state by its text, and on a state the
	// core cannot read every shipped app would look missing — and overwrite the office's own entry
	cur, err := compiler.ReadState(root)
	m, isMap := cur.(*yamlish.Map)
	if err != nil || !isMap {
		logf("the office's state does not read: %s is kept for the next start", ShippedState)
		return
	}
	have := map[string]bool{}
	if a, _ := m.Get("apps"); a != nil {
		am, isMap := a.(*yamlish.Map)
		if !isMap {
			logf("the office's state has no apps mapping: %s is kept for the next start", ShippedState)
			return
		}
		for _, k := range am.Keys() {
			have[k] = true
		}
	}
	for _, aid := range shipped.Keys() {
		if have[aid] {
			continue
		}
		entry, _ := shipped.Get(aid)
		d, err := compiler.Disposition(entry)
		if err != nil {
			continue
		}
		var out, errs bytes.Buffer
		if compiler.SetStateCmd(root, []string{"--app", aid, "--state", d, "--by", "core", "--create"}, &out, &errs) != 0 {
			logf("the APK's state lists %s and the office's could not take it: %s", aid, strings.TrimSpace(errs.String()))
			return // the file stays: tried again at the next start
		}
		logf("the APK's state lists %s, which the office's lacked: added (%s)", aid, d)
	}
	_ = os.Remove(path)
}

// machineHosts are the routing hosts (app.json `routing[].host`) of the apps the machine runs.
func machineHosts(root string) map[string]bool {
	on := machineApps(root)
	if len(on) == 0 {
		return nil
	}
	cat, err := compiler.LoadCatalog(root)
	if err != nil {
		return nil
	}
	hosts := map[string]bool{}
	for _, aid := range on {
		app := cat.Apps[aid]
		if app == nil {
			continue
		}
		routes, _ := app.Doc().Get("routing")
		list, _ := routes.([]any)
		for _, r := range list {
			if rm, isMap := r.(*yamlish.Map); isMap {
				if h, _ := rm.Get("host"); h != nil {
					if s, isText := h.(string); isText && s != "" {
						hosts[s] = true
					}
				}
			}
		}
	}
	return hosts
}

// coreServed are the apps of an office that the core answers itself — the console, app-management's
// control plane and the edge in its own process, forward-auth beside it. Every other app of its state that
// runs in containers runs in the machine (android-path.md), whatever enabled it.
var coreServed = map[string]bool{"console": true, "app-management": true, "forward-auth": true, "traefik": true}

// machineApps are the apps of the core's state that the machine runs: those it enabled (`by: machine`,
// mirrored by the control plane once the machine said its enable was done), and every other enabled app
// whose manifest runs it in containers (`compose`) and that the core does not answer itself — the core
// office's own dgo-extend, computers, connections and notifications, which on every other office run in
// containers too (DGO-1328: «הרחבת הלשכה» on the phone is the Mac's, in the phone's machine). The office's
// half that runs in the machine; a state the core cannot read holds none — the control plane says why,
// where it reads it.
func machineApps(root string) []string {
	doc, err := compiler.ReadState(root)
	top, isMap := doc.(*yamlish.Map)
	if err != nil || !isMap {
		return nil
	}
	raw, _ := top.Get("apps")
	apps, isMap := raw.(*yamlish.Map)
	if !isMap {
		return nil
	}
	var on []string
	var cat *compiler.Catalog // read once, when an app's manifest is asked
	noCatalog := false        // …and when it does not read, the machine's own (by: machine) are still its
	for _, aid := range apps.Keys() {
		entry, _ := apps.Get(aid)
		e, isMap := entry.(*yamlish.Map)
		if !isMap {
			continue
		}
		if d, err := compiler.Disposition(entry); err != nil || d != "enabled" {
			continue
		}
		if by, _ := e.Get("by"); by == "machine" {
			on = append(on, aid)
			continue
		}
		if coreServed[aid] || noCatalog {
			continue
		}
		if cat == nil {
			if cat, err = compiler.LoadCatalog(root); err != nil {
				noCatalog = true
				continue
			}
		}
		if app := cat.Apps[aid]; app != nil {
			if c, _ := app.Doc().Get("compose"); c != nil && c != "" {
				on = append(on, aid)
			}
		}
	}
	return on
}

// line is a file's text as one line, its first 2 KiB, or "": the app writes one short line, and a longer
// text is still what it said — never read as none, which would ask for the machine again and again.
func line(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	b, _ := io.ReadAll(io.LimitReader(f, 2<<10))
	return strings.ToValidUTF8(strings.Join(strings.Fields(string(b)), " "), "")
}

// machineGate is the machine as the edge may use it: what the app reports (machine), once the machine has
// proved it holds the reported token — its forward-auth's /edge-proof answers a fresh nonce with
// HMAC-SHA256(token, nonce), which the edge checks before it sends the machine anything. Whatever else holds
// that loopback port (another app, in the moment between the port's choice and QEMU's bind) cannot answer
// it, and is no machine. A proof is remembered for its port and token; a failed one is asked again after 5 s.
type machineGate struct {
	file, signin string
	client       *http.Client
	logf         func(string, ...any)
	mu           sync.Mutex
	proved       string
	proving      bool // one proof at a time, asked outside the lock: no request waits on a booting machine
	failed       string
	failedAt     time.Time
}

func newMachineGate(file, signin string, logf func(string, ...any)) *machineGate {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil
	return &machineGate{file: file, signin: signin, logf: logf, client: &http.Client{Transport: t, Timeout: 3 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
}

func (g *machineGate) get() (int, string) {
	port, token := machine(g.file)
	if port == 0 {
		return 0, ""
	}
	key := strconv.Itoa(port) + " " + token
	g.mu.Lock()
	switch {
	case g.proved == key:
		g.mu.Unlock()
		return port, token
	case g.proving || g.failed == key && time.Since(g.failedAt) < 5*time.Second:
		g.mu.Unlock()
		return 0, ""
	}
	g.proving = true
	g.mu.Unlock()
	ok := g.prove(port, token)
	g.mu.Lock()
	defer g.mu.Unlock()
	g.proving = false
	if ok {
		g.proved = key
		return port, token
	}
	first := g.failed != key // said once a machine: the status (status.go) asks every 2 s while one boots
	g.failed, g.failedAt = key, time.Now()
	if g.logf != nil && first {
		g.logf("the machine on 127.0.0.1:%d has not proved its token (yet): its apps answer nothing until it does", port)
	}
	return 0, ""
}

func (g *machineGate) prove(port int, token string) bool {
	raw := make([]byte, 16)
	if _, err := rand.Read(raw); err != nil {
		return false
	}
	nonce := hex.EncodeToString(raw)
	req, err := http.NewRequest("GET", "http://"+net.JoinHostPort("127.0.0.1", strconv.Itoa(port))+"/edge-proof?nonce="+nonce, nil)
	if err != nil {
		return false
	}
	req.Host = g.signin // the machine's edge routes its sign-in host to its forward-auth
	res, err := g.client.Do(req)
	if err != nil {
		return false
	}
	defer res.Body.Close()
	said, _ := io.ReadAll(io.LimitReader(res.Body, 256))
	mac := hmac.New(sha256.New, []byte(token))
	mac.Write([]byte(nonce))
	return res.StatusCode == http.StatusOK && hmac.Equal([]byte(strings.TrimSpace(string(said))), []byte(hex.EncodeToString(mac.Sum(nil))))
}

// machine is the phone's machine as the app reports it in the sockets' directory (android-path.md, "the
// machine on demand"): a regular file "<port> <token>", written once the machine's QEMU holds the
// loopback port its edge is forwarded to, removed when it ends. Anything else is no machine: the edge
// then sends nothing anywhere for a host it has no route of its own for.
func machine(path string) (int, string) {
	st, err := os.Lstat(path)
	if err != nil || !st.Mode().IsRegular() || st.Size() > 512 {
		return 0, ""
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, ""
	}
	f := strings.Fields(string(b))
	if len(f) != 2 || len(f[1]) < 32 {
		return 0, ""
	}
	port, err := strconv.Atoi(f[0])
	if err != nil || port < 1024 || port > 65535 {
		return 0, ""
	}
	return port, f[1]
}

// machineConsole is the console container's place on the phone (console.Config.Fallback, DGO-1328): every
// route the core's console does not answer — an app's screen under /a/<name>/, which the console proxies to
// the app on every other office — goes to the machine's own console once the machine is up and has proved
// its token, through the machine's edge as the core's edge sends an app's host (edge.MachineProxy: the
// identity the edge wrote, signed for that one request, the core's own sign-in never). Before then it is
// absent: the page that waits for the machine (serve.Absent). Without it every container app — «הרחבת
// הלשכה», «התראות», «חיבורים ומפתחות», «מחשבים» — answered «the machine runs, the app does not answer
// yet» on the phone, its machine up or not.
func machineConsole(up func() (int, string), absent http.Handler, logf func(string, ...any)) http.Handler {
	var proxies sync.Map // "port token" → its proxy: one a boot
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		port, token := up()
		if port == 0 {
			absent.ServeHTTP(w, r)
			return
		}
		// the app routes and the API only: a route of the shell's own that the core's console did not answer
		// (a first screen it could not tell, a Range, a name of index.html) is not the machine console's to
		// answer with its shell, which may be another build than the APK's
		if (r.Method == http.MethodGet || r.Method == http.MethodHead) &&
			!strings.HasPrefix(r.URL.Path, "/a/") && !strings.HasPrefix(r.URL.Path, "/api/") {
			absent.ServeHTTP(w, r)
			return
		}
		key := strconv.Itoa(port) + " " + token
		h, ok := proxies.Load(key)
		if !ok {
			h, _ = proxies.LoadOrStore(key, edge.MachineProxy(port, token, logf))
		}
		if r.Method != http.MethodGet || !strings.Contains(r.Header.Get("Accept"), "text/html") {
			h.(http.Handler).ServeHTTP(w, r)
			return
		}
		// a page, while the machine's apps still come up (its edge and sign-in answer before its console
		// does): the edge's own 404 for a host it has no router for yet, or a 502–504, is the page that waits —
		// which says the machine runs and its app is starting — never the edge's bare error
		p := &pageOrWait{ResponseWriter: w}
		h.(http.Handler).ServeHTTP(p, r)
		if p.waiting {
			absent.ServeHTTP(w, r)
		}
	})
}

// pageOrWait passes the machine's answer to a page on, unless it is its edge saying the app is not there
// yet: then nothing of it is written, and waiting says so.
type pageOrWait struct {
	http.ResponseWriter
	waiting, decided bool
}

func (p *pageOrWait) WriteHeader(code int) {
	if p.decided {
		return
	}
	if code >= 100 && code < 200 && code != http.StatusSwitchingProtocols {
		p.ResponseWriter.WriteHeader(code) // an interim answer (103 Early Hints) is not the answer
		return
	}
	p.decided = true
	h := p.Header()
	notYet := code == http.StatusBadGateway || code == http.StatusServiceUnavailable || code == http.StatusGatewayTimeout ||
		code == http.StatusNotFound && strings.HasPrefix(h.Get("Content-Type"), "text/plain")
	if notYet {
		p.waiting = true
		for k := range h {
			delete(h, k) // the page that waits writes its own
		}
		return
	}
	p.ResponseWriter.WriteHeader(code)
}

func (p *pageOrWait) Write(b []byte) (int, error) {
	if !p.decided {
		p.WriteHeader(http.StatusOK)
	}
	if p.waiting {
		return len(b), nil
	}
	return p.ResponseWriter.Write(b)
}

// Flush passes a flush on once the answer is passed on, and only then: a flush while it is undecided, or
// waiting, would send a status of its own before the page that waits (the proxy flushes a streamed answer
// at once).
func (p *pageOrWait) Flush() {
	if p.decided && !p.waiting {
		_ = http.NewResponseController(p.ResponseWriter).Flush()
	}
}

// Unwrap lets http.ResponseController reach the writer beneath for the rest (a hijack, a deadline).
func (p *pageOrWait) Unwrap() http.ResponseWriter { return p.ResponseWriter }

// MachineTiles is the file in the sockets' directory that keeps the machine's tiles as they were last read.
const MachineTiles = "machine-tiles.json"

// machineTiles are the machine's console's tiles (console.Config.More, DGO-1328): the apps the machine runs
// and the offices its dgo-extend links, which no registry built into the APK can hold. Answered at once from
// what was last read — kept in the sockets' directory, so a core started again shows them while the machine
// comes up — and read again in the background, at most every 15 s while the machine is up, with the identity
// of the request that asks: the machine's console, like every app behind its edge, answers someone signed in
// and no one else. A tile is shown once the machine answered it, and goes with the first answer without it.
type machineTiles struct {
	up     func() (int, string)
	file   string
	host   string // the console's host, as the machine's edge routes it
	client *http.Client
	logf   func(string, ...any)
	mu     sync.Mutex
	last   []byte
	asked  time.Time
	asking bool
}

func newMachineTiles(up func() (int, string), file, host string, logf func(string, ...any)) *machineTiles {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil
	m := &machineTiles{up: up, file: file, host: host, logf: logf,
		client: &http.Client{Transport: t, Timeout: 10 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	if b, err := os.ReadFile(file); err == nil && len(b) <= 4<<20 {
		m.last = b
	}
	return m
}

// get is console.Config.More: the tiles last read, and a read asked in the background when they are old —
// never waited for here: the machine's proof may take seconds while it boots, and the rail waits on nothing.
func (m *machineTiles) get(r *http.Request) []byte {
	m.mu.Lock()
	last := m.last
	ask := !m.asking && time.Since(m.asked) >= 15*time.Second && r.Header.Get("X-authentik-username") != ""
	if ask {
		m.asking, m.asked = true, time.Now()
	}
	m.mu.Unlock()
	if ask {
		ids := http.Header{} // copied: the request is answered before the read ends
		for _, k := range edge.Identity {
			if v := r.Header.Get(k); v != "" {
				ids.Set(k, v)
			}
		}
		go m.read(ids)
	}
	return last
}

// read asks the machine's console for its tiles, once it is up — its /api/modules, signed as the core's
// edge signs — and keeps an answer that reads as one (a 200 whose JSON holds a modules list), written whole.
func (m *machineTiles) read(ids http.Header) {
	defer func() {
		m.mu.Lock()
		m.asking = false
		m.mu.Unlock()
	}()
	port, token := m.up()
	if port == 0 {
		m.mu.Lock()
		m.asked = time.Time{} // no machine yet: the next rail asks again (up is a file's read until it is)
		m.mu.Unlock()
		return
	}
	req, err := http.NewRequest("GET", "http://"+net.JoinHostPort("127.0.0.1", strconv.Itoa(port))+"/api/modules", nil)
	if err != nil {
		return
	}
	req.Host = m.host
	for k, vs := range ids {
		req.Header[k] = vs
	}
	edge.SignForMachine(req.Header, token, req.Method, req.Host, req.URL.RequestURI())
	res, err := m.client.Do(req)
	if err != nil {
		m.logf("the machine's tiles were not read: %v", err)
		return
	}
	defer res.Body.Close()
	body, err := io.ReadAll(io.LimitReader(res.Body, 4<<20))
	var said struct {
		Modules []json.RawMessage `json:"modules"`
	}
	if err != nil || res.StatusCode != http.StatusOK || json.Unmarshal(body, &said) != nil || said.Modules == nil {
		m.logf("the machine's tiles were not read: its console answered %d", res.StatusCode)
		return
	}
	part := m.file + ".part"
	if err := os.WriteFile(part, body, 0o600); err == nil {
		if err := os.Rename(part, m.file); err != nil {
			os.Remove(part)
		}
	}
	m.mu.Lock()
	m.last = body
	m.mu.Unlock()
}

// Options is what the core is built from, besides the office root.
type Options struct {
	Listen  string // the edge's address: a loopback one, unix:<path>, or "" for EdgeSocket in Dir
	Dir     string // the sockets' directory
	Domain  string // the browser opens console.<Domain> and signs in at signin.<Domain>
	Static  string // the console's static/ directory, where this dgo was built without it
	Console string // the console container's URL, for the routes not answered here
	Apps    string // app-management's container URL, likewise
}

// Core is the three servers, listening, and the status the app's screen reads (status.go).
type Core struct {
	servers []*http.Server
	errc    chan error
	stop    chan struct{} // ends sayStatus…
	done    chan struct{} // …which closes this as it returns
	status  string        // the file it writes, removed when the core stops
}

// local marks a request that came over one of the core's sockets as the local hop it is (above).
func local(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.RemoteAddr = "127.0.0.1:0"
		h.ServeHTTP(w, r)
	})
}

// ownDir is the sockets' directory as the core needs it: absolute, a directory, and opened by its owner
// alone — no one else may even search it, so no one else can connect to a socket in it, not in the
// moment between a socket's bind and its chmod either. On a phone: File(filesDir, …) made under the
// app's umask, 077 (getDir()'s 0771 is refused).
func ownDir(dir string) error {
	if !filepath.IsAbs(dir) {
		return fmt.Errorf("--dir %q is not an absolute path", dir)
	}
	st, err := os.Stat(dir)
	if err != nil || !st.IsDir() {
		return fmt.Errorf("--dir %s is not a directory", dir)
	}
	if st.Mode().Perm()&0o077 != 0 {
		return fmt.Errorf("--dir %s may be opened by others than its owner (%v)", dir, st.Mode().Perm())
	}
	return nil
}

// ownUpstream refuses a container URL on a loopback port another app may bind (1024 and above): the
// console sends the owner's identity and session there, and on a phone loopback is every app's.
func ownUpstream(name, raw string) error {
	u, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("%s %q: %v", name, raw, err)
	}
	host, port := u.Hostname(), u.Port()
	ip := net.ParseIP(host)
	if !(host == "localhost" || ip != nil && ip.IsLoopback()) {
		return nil
	}
	if port == "" {
		port = map[string]string{"https": "443"}[u.Scheme]
		if port == "" {
			port = "80"
		}
	}
	if n, err := strconv.Atoi(port); err != nil || n >= 1024 {
		return fmt.Errorf("%s %s: a loopback port any app on the phone may bind — the console sends the owner's session there", name, raw)
	}
	return nil
}

// Open builds the core on the office root and starts its three servers, each on its socket.
func Open(root string, o Options, logger *log.Logger) (*Core, error) {
	if runtime.GOOS == "windows" {
		return nil, errors.New("the native core trusts whatever opens its sockets, which only Unix modes keep to their owner")
	}
	if root == "" {
		return nil, errors.New("no office root — the app names it in DGO_OFFICE_ROOT (main.go officeRoot)")
	}
	if err := ownDir(o.Dir); err != nil {
		return nil, err
	}
	for _, u := range []struct{ name, raw string }{{"--console-container", o.Console}, {"--apps-container", o.Apps}} {
		if err := ownUpstream(u.name, u.raw); err != nil {
			return nil, err
		}
	}
	sock := func(name string) string { return filepath.Join(o.Dir, name) }
	gate := newMachineGate(sock(MachineFile), "signin."+o.Domain, logger.Printf)
	m := coreMachine{gate: gate, wanted: sock(MachineWanted), refused: sock(MachineRefused)}
	mergeShipped(root, logger.Printf) // after an update: the core apps the new APK brings
	control, err := serve.NewNative(root, o.Apps, log.New(logger.Writer(), "dgo control: ", log.LstdFlags), m, o.Domain)
	if err != nil {
		return nil, err
	}
	peers := filepath.Join(o.Dir, "peers") // dgo-extend's linked offices' tiles: none until it runs
	if err := os.MkdirAll(peers, 0o700); err != nil {
		return nil, err
	}
	env := map[string]string{
		"GENERATED_REGISTRY": filepath.Join(root, ".generated", "registry"),
		"CONSOLE_PEERS_DIR":  peers,
		"APP_MANAGEMENT_URL": "unix:" + sock(ControlSocket),
	}
	lookup := func(k string) (string, bool) {
		if v, ok := env[k]; ok {
			return v, true
		}
		return os.LookupEnv(k)
	}
	shell := console.BuiltIn()
	if o.Static != "" {
		shell = nil
	} else if shell == nil {
		return nil, errors.New("this dgo was built without the console's files (-tags consoleembed): --static <dir> is needed")
	}
	// the console container is the machine's console once it is up (a container app's screen under /a/), and
	// before then a clear page, not the proxy's error; its rail shows the machine's tiles too (DGO-1328)
	tiles := newMachineTiles(gate.get, sock(MachineTiles), "console."+o.Domain, logger.Printf)
	// No in-process doors here (console.Config.Doors stays empty): hp-dgo's alerts and dgo-extend handlers
	// (internal/notices, internal/extend, DGO-1328) would answer before the machine's console, and the machine
	// runs those apps itself — its notices would never reach the phone, and a page before the machine is up
	// would be a stub instead of the machine's own «not installed» answer (DGO-1723). The release that took both
	// lines kept this one (DGO-969); the packages stay, ready for a phone with no machine.
	con, err := console.New(console.Config{Static: o.Static, Shell: shell, Upstream: o.Console,
		Trusted: []netip.Prefix{netip.MustParsePrefix("127.0.0.1/32")}, Lookup: lookup, Logf: logger.Printf,
		Fallback: machineConsole(gate.get, serve.Absent(m), logger.Printf), More: tiles.get})
	if err != nil {
		return nil, err
	}
	fa := &url.URL{Scheme: "unix", Path: sock(ForwardAuthSocket)}
	front, err := edge.New(map[string]edge.Route{
		"signin." + o.Domain:  {Upstream: fa},
		"console." + o.Domain: {Upstream: &url.URL{Scheme: "unix", Path: sock(ConsoleSocket)}, Gated: true},
	}, fa.String(), log.New(logger.Writer(), "", log.LstdFlags).Printf) // its lines say "dgo edge:" themselves
	if err != nil {
		return nil, err
	}
	front.Machine = gate.get
	front.Wake = m.wake(root, o.Domain)
	front.Waiting = serve.Absent(m) // a container app's host waits on the same Hebrew page as the console's (DGO-1723)
	at, err := edgeListener(o.Listen, sock(EdgeSocket))
	if err != nil {
		return nil, err
	}
	// every listener bound before any serves: a bind that fails leaves nothing serving, and each one bound
	// is closed (and its socket removed) before Open returns
	type server struct {
		name string
		h    http.Handler
		ln   net.Listener
	}
	all := []server{{name: ControlSocket, h: local(control)}, {name: ConsoleSocket, h: local(con)}, {name: at.name, h: front}}
	for i := range all {
		var err error
		if all[i].name == at.name {
			all[i].ln, err = at.listen()
		} else {
			all[i].ln, err = edge.ListenUnix(sock(all[i].name))
		}
		if err != nil {
			for _, s := range all[:i] {
				s.ln.Close()
			}
			return nil, err
		}
	}
	c := &Core{errc: make(chan error, len(all))}
	// the edge last: nothing reaches it before what stands behind it serves
	for _, s := range all {
		srv := &http.Server{Handler: s.h, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 2 * time.Minute, ErrorLog: logger}
		c.servers = append(c.servers, srv)
		go func(name string, ln net.Listener) {
			if err := srv.Serve(ln); !errors.Is(err, http.ErrServerClosed) {
				c.errc <- fmt.Errorf("%s: %v", name, err)
			}
		}(s.name, s.ln)
	}
	logger.Printf("the office's core: the edge on %s (signin.%s → forward-auth, console.%s → the console, gated); %s and %s in %s",
		at.name, o.Domain, o.Domain, ConsoleSocket, ControlSocket, o.Dir)
	// what the app's status screen reads, from now on (DGO-1723)
	c.stop, c.done, c.status = make(chan struct{}), make(chan struct{}), filepath.Join(o.Dir, StatusFile)
	go sayStatus(root, o.Dir, m, logger.Printf, c.stop, c.done)
	// the office as it was: apps the machine runs bring the machine back with the core (a phone restarted,
	// the app opened again) — asked for once here, every listener bound, and again by any of their hosts
	// opened before it is up
	if on := machineApps(root); len(on) > 0 {
		logger.Printf("the office has apps in its machine (%s): asking the app for it", strings.Join(on, ", "))
		if err := m.Want(); err != nil {
			logger.Printf("could not ask for the machine: %v", err)
		}
	}
	return c, nil
}

// edgeAt is where the edge listens, by the name the log gives it.
type edgeAt struct {
	name   string
	listen func() (net.Listener, error)
}

// edgeListener reads --listen: "" is EdgeSocket in the sockets' directory, unix:<path> a socket there or
// elsewhere, anything else a loopback address — the edge's own rule (edge.Main).
func edgeListener(addr, socket string) (edgeAt, error) {
	switch {
	case addr == "":
		return edgeAt{socket, func() (net.Listener, error) { return edge.ListenUnix(socket) }}, nil
	case strings.HasPrefix(addr, "unix:"):
		u, err := url.Parse(addr)
		if err != nil || u.Opaque != "" || u.Host != "" {
			return edgeAt{}, fmt.Errorf("--listen %s: a socket is unix:<absolute path>", addr)
		}
		return edgeAt{u.Path, func() (net.Listener, error) { return edge.ListenUnix(u.Path) }}, nil
	}
	h, _, err := net.SplitHostPort(addr)
	if ip := net.ParseIP(h); err != nil || !(h == "localhost" || ip != nil && ip.IsLoopback()) {
		return edgeAt{}, fmt.Errorf("--listen %s is not a loopback address nor unix:<path>", addr)
	}
	return edgeAt{addr, func() (net.Listener, error) { return net.Listen("tcp", addr) }}, nil
}

// Close stops the servers, the edge first, finishing the requests in flight until ctx ends; the first
// that could not finish is the error.
func (c *Core) Close(ctx context.Context) error {
	if c.stop != nil {
		// its last write done (or 5 s: a proof it was asking ends in 3), then the file goes — a core that stopped
		// is never said to be up by the file it left
		close(c.stop)
		c.stop = nil
		select {
		case <-c.done:
		case <-time.After(5 * time.Second):
		case <-ctx.Done():
		}
		_ = os.Remove(c.status)
	}
	var first error
	for i := len(c.servers) - 1; i >= 0; i-- {
		if err := c.servers[i].Shutdown(ctx); err != nil && first == nil {
			first = err
		}
	}
	return first
}

// Main is `dgo be-child native`: serve until interrupted, then finish the requests in flight. 2 for a
// usage error or a core that cannot be built, 1 for a server that stopped on its own.
func Main(root string, args []string, stderr io.Writer) int {
	logger := log.New(stderr, "dgo native: ", log.LstdFlags)
	fl := flag.NewFlagSet("dgo be-child native", flag.ContinueOnError)
	fl.SetOutput(stderr)
	var o Options
	fl.StringVar(&o.Listen, "listen", "127.0.0.1:8080", "the edge's address, which the WebView opens: a loopback one, or unix:<path>")
	fl.StringVar(&o.Dir, "dir", os.Getenv("DGO_NATIVE_DIR"), "the sockets' directory: absolute, written by its owner alone (default $DGO_NATIVE_DIR)")
	fl.StringVar(&o.Domain, "domain", "localhost", "the office's domain: the browser opens console.<domain> and signs in at signin.<domain>")
	fl.StringVar(&o.Static, "static", "", "the console's static/ directory, where this dgo was built without it")
	fl.StringVar(&o.Console, "console-container", "http://127.0.0.1:9", "the console container's URL, for the routes not answered here (the office's machine, once it runs)")
	fl.StringVar(&o.Apps, "apps-container", "http://127.0.0.1:9", "app-management's container URL, likewise")
	if err := fl.Parse(args); err != nil {
		return 2
	}
	if fl.NArg() > 0 {
		fmt.Fprintf(stderr, "dgo be-child native: unexpected argument %q\n", fl.Arg(0))
		return 2
	}
	// before Open: a stop asked while the core starts is a stop, not a kill that leaves its sockets
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	c, err := Open(root, o, logger)
	if err != nil {
		fmt.Fprintln(stderr, "dgo be-child native:", err)
		return 2
	}
	code := 0
	select {
	case <-ctx.Done():
	case err := <-c.errc:
		logger.Print(err)
		code = 1
	}
	done, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := c.Close(done); err != nil {
		logger.Printf("the requests in flight did not finish: %v", err)
		code = 1
	}
	return code
}

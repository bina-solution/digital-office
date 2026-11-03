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

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/console"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/edge"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/serve"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
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

// machineApps are the apps of the core's state that the machine enabled (`by: machine`, mirrored by the
// control plane once the machine said its enable was done): the office's half that runs in the machine.
// A state the core cannot read holds none — the control plane says why, where it reads it.
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
	for _, aid := range apps.Keys() {
		entry, _ := apps.Get(aid)
		e, isMap := entry.(*yamlish.Map)
		if !isMap {
			continue
		}
		by, _ := e.Get("by")
		if d, err := compiler.Disposition(entry); err == nil && d == "enabled" && by == "machine" {
			on = append(on, aid)
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
	g.failed, g.failedAt = key, time.Now()
	if g.logf != nil {
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

// Options is what the core is built from, besides the office root.
type Options struct {
	Listen  string // the edge's address: a loopback one, unix:<path>, or "" for EdgeSocket in Dir
	Dir     string // the sockets' directory
	Domain  string // the browser opens console.<Domain> and signs in at signin.<Domain>
	Static  string // the console's static/ directory, where this dgo was built without it
	Console string // the console container's URL, for the routes not answered here
	Apps    string // app-management's container URL, likewise
}

// Core is the three servers, listening.
type Core struct {
	servers []*http.Server
	errc    chan error
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
	con, err := console.New(console.Config{Static: o.Static, Shell: shell, Upstream: o.Console,
		Trusted: []netip.Prefix{netip.MustParsePrefix("127.0.0.1/32")}, Lookup: lookup, Logf: logger.Printf,
		Absent: serve.Absent(m)}) // a container app's page before the machine runs: a clear page, not the proxy's error
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

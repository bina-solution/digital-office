// Package console is platform-base/console/app.py's server inside dgo — step 4 of
// ai/context/core-native-plan.md, first slice: `dgo be-child console`, one of the long-running
// processes of ai/context/dgo-architecture-2026.md §5.1.
//
// WHAT IS ANSWERED HERE. The shell — `/` (the shell, or the install wizard on a fresh office:
// app-management's record says which, asked as app.py asks it) and every file of it — and
// /api/version and /api/modules, the answers made of files. Each is app.py's answer as Flask,
// werkzeug and flask-compress write it: the status, every header, the body. oracle_test.go proves it
// by running app.py itself through Flask's test client on the same fixture. The console writes no
// security header of its own (no Content-Security-Policy, frame-ancestors or nosniff), so neither
// does this: the oracle compares the whole header set, and one header more would fail it.
//
// ONE TREE. --static is read once, at start — every file into memory, with its digest — as the
// image's /app/static is to app.py. What is served and the `shell` an open page compares itself with
// cannot disagree, and a name the host's filesystem would resolve differently from the image's
// (another case, a trailing dot or space, a device name) names nothing. An edit is served after a
// restart, as a change to the image is after a rebuild. A release build of dgo carries the tree itself
// (builtin.go): without --static it serves the console's files as committed when it was built, as the
// image serves them — /app/static's path in each ETag, the paths of the digest written with `/`.
//
// EVERYTHING ELSE IS THE CONSOLE CONTAINER'S, reverse-proxied untouched to --upstream: /healthz (it
// must be able to fail, and most of the console is still the container), /api/me (identity), the
// planes behind the shell (/api/office, /api/connections, /api/conn, /api/svc), the app doors
// (/a/<name>/), every method but GET and HEAD, and every request this port is not proven on. Refuse,
// never guess. DGO_CONSOLE=container proxies every request — the rollback, which needs nothing but
// the container.
//
// IDENTITY IS BELIEVED ONLY FROM THE EDGE (edge.go). The container believes X-authentik-* as the
// forward-auth router wrote them; here a caller that is not a --trusted-proxy has every identity
// header removed before anything reads or forwards the request, and a listener off loopback is
// refused unless the trusted proxy is named.
package console

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/netip"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
)

// Config is what New needs. Lookup is os.LookupEnv in production: app.py's own variables keep their
// names, and an empty value is a value, as os.getenv has it.
type Config struct {
	Static, Upstream string
	Shell            fs.FS          // served when Static is "": static/, modules.yaml and commit-time, as builtin.go embeds them
	Trusted          []netip.Prefix // the peers whose identity headers are believed (edge.go)
	Lookup           func(string) (string, bool)
	Logf             func(string, ...any)
	// Absent answers in the console container's place when it cannot be reached — the phone's core,
	// before its machine runs (serve.Absent, DGO-1084); nil is the 502 it always was
	Absent http.Handler
}

// builtIn is the console's files compiled into this binary (builtin.go, -tags consoleembed), or nil:
// a build without them serves --static only.
var builtIn fs.FS

// BuiltIn is the console's files compiled into this binary, or nil — for a process that builds the
// console's server itself (`dgo be-child native`).
func BuiltIn() fs.FS { return builtIn }

// Server answers the console's routes: here where proven, through the proxy otherwise.
type Server struct {
	native   bool // false under DGO_CONSOLE=container: every request is proxied
	proxy    http.Handler
	trusted  []netip.Prefix
	tree     *tree  // --static as it was at start, or the copy built in (tree.go)
	static   string // app.py's STATIC, absolute: the ETag hashes the paths under it
	root     fs.FS  // app.py's ROOT, STATIC's parent: modules.yaml lives there, as /app holds it in the image
	registry string // GENERATED_REGISTRY: the compiled console.modules.yaml
	peers    string // CONSOLE_PEERS_DIR: the remote placements and link.json
	version  string // BUILD_VERSION, stripped, or "dev"
	office   *officeRecord
	door     http.Handler // /a/app-management/ to a control plane on a socket (plane.go), or nil
	now      func() time.Time
}

// New builds the server. Under DGO_CONSOLE=container nothing of the native side is read — no
// --static, no registry — so nothing of it can keep the container from being reached. Otherwise
// every input app.py would take from a default that only exists inside its image is required: on a
// host the default is not the office's, and a guess answers an empty rail without an error.
func New(c Config) (*Server, error) {
	target, err := url.Parse(c.Upstream)
	if err != nil || (target.Scheme != "http" && target.Scheme != "https") || target.Host == "" {
		return nil, fmt.Errorf("dgo console: --upstream %q is not an http(s) URL of the console container", c.Upstream)
	}
	s := &Server{proxy: newProxy(target, c.Logf, c.Absent), trusted: c.Trusted, now: time.Now}
	if v, _ := c.Lookup("DGO_CONSOLE"); v == "container" {
		return s, nil
	}
	s.native = true
	switch {
	case c.Static != "":
		if s.static, err = filepath.Abs(c.Static); err != nil {
			return nil, err
		}
		if st, err := os.Stat(s.static); err != nil || !st.IsDir() {
			return nil, fmt.Errorf("dgo console: --static %s is not a directory", c.Static)
		}
		if s.tree, err = readTree(s.static); err != nil {
			return nil, fmt.Errorf("dgo console: reading the shell's files: %v", err)
		}
		s.root = os.DirFS(filepath.Dir(s.static))
	case c.Shell != nil:
		if s.tree, err = readBuiltIn(c.Shell); err != nil {
			return nil, fmt.Errorf("dgo console: reading the shell built into dgo: %v", err)
		}
		s.static, s.root = imageStatic, c.Shell
	default:
		return nil, errors.New("dgo console: --static is required — this dgo was built without the console's files")
	}
	required := func(name, what string) (string, error) {
		v, ok := c.Lookup(name)
		if !ok || v == "" {
			return "", fmt.Errorf("dgo console: %s is not set — %s; the image's default is a path or a name only its container has", name, what)
		}
		return v, nil
	}
	for _, d := range []struct {
		dst        *string
		name, what string
	}{
		{&s.registry, "GENERATED_REGISTRY", "the compiler's .generated/registry of this office"},
		{&s.peers, "CONSOLE_PEERS_DIR", "the directory dgo-extend publishes linked offices' tiles to (its dgo_extend_peers volume), or an empty one"},
	} {
		if *d.dst, err = required(d.name, d.what); err != nil {
			return nil, err
		}
		if st, err := os.Stat(*d.dst); err != nil || !st.IsDir() {
			return nil, fmt.Errorf("dgo console: %s=%s is not a directory", d.name, *d.dst)
		}
	}
	plane, err := required("APP_MANAGEMENT_URL", "app-management's URL, which says whether this office's install wizard has run")
	if err != nil {
		return nil, err
	}
	if p, ok := strings.CutPrefix(plane, "unix:"); ok {
		if !strings.HasPrefix(p, "/") {
			return nil, fmt.Errorf("dgo console: APP_MANAGEMENT_URL=%s: a socket is unix:<absolute path>", plane)
		}
		s.door = newPlane(p, c.Logf)
	}
	ttl := 10.0
	if v, ok := c.Lookup("CONSOLE_OFFICE_TTL_S"); ok {
		if ttl, err = strconv.ParseFloat(pyval.Strip(v), 64); err != nil {
			return nil, fmt.Errorf("dgo console: CONSOLE_OFFICE_TTL_S=%q is not a number (app.py fails to start on it too)", v)
		}
	}
	s.office = newOfficeRecord(plane, ttl)
	v, _ := c.Lookup("BUILD_VERSION")
	if s.version = pyval.Strip(v); s.version == "" {
		s.version = "dev"
	}
	return s, nil
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.screen(r)
	if s.native && s.door != nil && planeRequest(r) {
		s.door.ServeHTTP(w, r) // the control plane on its socket, with no container to ask (plane.go)
		return
	}
	if s.native && s.answer(w, r) {
		return
	}
	s.proxy.ServeHTTP(w, r)
}

// answer writes app.py's answer and reports true, or reports false having written nothing.
func (s *Server) answer(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		return false // werkzeug's 405 and its OPTIONS answer are the container's
	}
	switch p := r.URL.Path; {
	case p == "/api/version":
		return s.versionRoute(w, r)
	case p == "/api/me":
		return s.meRoute(w, r)
	case p == "/api/office":
		return s.officeRoute(w, r)
	case p == "/api/modules":
		return s.modulesRoute(w, r)
	case p == "/healthz" || !strings.HasPrefix(p, "/") || strings.HasPrefix(p, "/api/") || strings.HasPrefix(p, "/a/"):
		// /healthz must be able to fail while the container is down; every other /api/ and /a/ path
		// is a route of app.py (or a werkzeug redirect next to one) that this slice does not answer
		return false
	}
	return s.file(w, r)
}

// newProxy forwards a request to the console container as the edge sent it (after screen): the same
// Host (werkzeug builds its redirects from it), the same X-Forwarded-* and Forwarded headers, the
// same query bytes — app.py keeps a query verbatim for the apps it frames, and ReverseProxy's Rewrite
// would re-encode one holding `;`.
func newProxy(target *url.URL, logf func(string, ...any), absent http.Handler) http.Handler {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil               // the container is one direct hop; an HTTP_PROXY must not reroute it
	t.DisableCompression = true // the client's Accept-Encoding, or its absence, reaches the container
	return &httputil.ReverseProxy{
		Transport: t,
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(target)
			pr.Out.Host = pr.In.Host
			pr.Out.URL.RawQuery = pr.In.URL.RawQuery
			for _, h := range []string{"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto"} {
				if v, ok := pr.In.Header[h]; ok {
					pr.Out.Header[h] = v
				}
			}
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			logf("dgo console: %s %s: the console container did not answer: %v", r.Method, r.URL.Path, err)
			if absent != nil {
				absent.ServeHTTP(w, r)
				return
			}
			http.Error(w, "the console container did not answer", http.StatusBadGateway)
		},
	}
}

// Main is `dgo be-child console`: serve until interrupted, then finish the requests in flight. The
// exit code is 2 for a usage error, 1 for a server that could not start or stopped on its own. The
// checkout dgo found is not needed: the console names its files with --static, as the image's /app
// is not a checkout either — or carries them, when it was built with them.
func Main(_ string, args []string, stderr io.Writer) int {
	fs := flag.NewFlagSet("dgo be-child console", flag.ContinueOnError)
	fs.SetOutput(stderr)
	shellArg, staticDoc := "--static <dir>", "the console's static/ directory; its parent holds modules.yaml, as /app does in the image"
	if builtIn != nil {
		shellArg, staticDoc = "[--static <dir>]", staticDoc+" (default: the copy built into this dgo)"
	}
	listen := fs.String("listen", "127.0.0.1:8000", "the address to serve on; off loopback only with --trusted-proxy")
	static := fs.String("static", "", staticDoc)
	upstream := fs.String("upstream", os.Getenv("DGO_CONSOLE_UPSTREAM"), "the console container's URL: every request not answered here goes there (default $DGO_CONSOLE_UPSTREAM)")
	trusted := fs.String("trusted-proxy", os.Getenv("DGO_CONSOLE_TRUSTED_PROXY"), "the edge's addresses or CIDRs, comma-separated: the only callers whose identity headers are believed (default $DGO_CONSOLE_TRUSTED_PROXY)")
	fs.Usage = func() {
		fmt.Fprintf(stderr, "usage: dgo be-child console [--listen 127.0.0.1:8000] %s --upstream <url> [--trusted-proxy <cidr,…>]\n", shellArg)
		fs.PrintDefaults()
		fmt.Fprintln(stderr, "required, because app.py's defaults name its own container: GENERATED_REGISTRY, CONSOLE_PEERS_DIR,\n"+
			"APP_MANAGEMENT_URL; read as app.py reads them: BUILD_VERSION, CONSOLE_OFFICE_TTL_S, GUNICORN_GRACEFUL_TIMEOUT.\n"+
			"DGO_CONSOLE=container sends every request to the container (the rollback; then only --upstream is needed).")
	}
	if err := fs.Parse(args); err != nil {
		return 2
	}
	container := os.Getenv("DGO_CONSOLE") == "container"
	if *upstream == "" || (*static == "" && builtIn == nil && !container) || fs.NArg() > 0 {
		fs.Usage()
		return 2
	}
	peers, err := ParseTrusted(*trusted)
	if err == nil {
		err = listenAllowed(*listen, peers)
	}
	grace := 30 * time.Second // gunicorn's graceful_timeout in the console's image
	if v, ok := os.LookupEnv("GUNICORN_GRACEFUL_TIMEOUT"); ok && err == nil {
		n, perr := strconv.Atoi(strings.TrimSpace(v))
		grace, err = time.Duration(n)*time.Second, perr
	}
	if err != nil {
		fmt.Fprintln(stderr, "dgo console:", err)
		return 2
	}
	logger := log.New(stderr, "", log.LstdFlags)
	s, err := New(Config{Static: *static, Shell: builtIn, Upstream: *upstream, Trusted: peers, Lookup: os.LookupEnv, Logf: logger.Printf})
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	ln, err := net.Listen("tcp", *listen)
	if err != nil {
		fmt.Fprintln(stderr, "dgo console:", err)
		return 1
	}
	// No WriteTimeout: an event stream the container proxies stays open (it bounds them itself, 55 s).
	srv := &http.Server{Handler: s, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 2 * time.Minute, ErrorLog: logger}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	how := "nothing here (DGO_CONSOLE=container)"
	if s.native {
		from := *static
		if from == "" {
			from = "built into dgo"
		}
		how = fmt.Sprintf("the shell (%s, digest %s), /api/version and /api/modules here", from, s.tree.digest)
	}
	logger.Printf("dgo console: http://%s — %s, everything else from %s", ln.Addr(), how, *upstream)
	if err := serveUntil(ctx, srv, ln, grace); err != nil {
		fmt.Fprintln(stderr, "dgo console:", err)
		return 1
	}
	return 0
}

// serveUntil runs srv until ctx ends, then stops taking connections and waits — up to grace — for the
// requests in flight, as gunicorn's graceful_timeout does: Serve returns the moment a shutdown
// begins, so returning on it would cut every download, proxied POST and stream at each restart.
func serveUntil(ctx context.Context, srv *http.Server, ln net.Listener, grace time.Duration) error {
	stopped := make(chan error, 1)
	go func() {
		<-ctx.Done()
		done, cancel := context.WithTimeout(context.Background(), grace)
		defer cancel()
		stopped <- srv.Shutdown(done)
	}()
	if err := srv.Serve(ln); !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return <-stopped
}

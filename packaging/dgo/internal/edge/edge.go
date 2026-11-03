// Package edge is `dgo be-child edge`: the office's edge where there is no traefik — the phone's native
// core (DGO-1090), where the console, identity and the control plane run as processes of the app and no
// container is needed before the console is up.
//
// One listener. A request is routed by its Host (port aside) to the upstream declared for that host. A
// GATED host is first asked about at forward-auth's /auth/traefik exactly as traefik's forwardAuth asks
// (platform-base/traefik/config/authentik-forwardauth.yaml, the forward-auth branch): the request's
// headers, cookies included, plus the X-Forwarded-* this edge writes from the request it received —
// never a client's own. A 2xx sends the request on, carrying the five identity headers the answer named;
// anything else IS the browser's answer, verbatim — status, Location, Set-Cookie and all — which is what
// forward-auth's sign-in, its per-host hand-off and its state cookie are written against. The identity
// headers a client sends are dropped on every host, gated or not: only the identity service speaks for
// a person.
//
// ON ANDROID, LOOPBACK IS NOT A BOUNDARY (the second reader). Every app on a phone can open 127.0.0.1,
// so an upstream that believes identity headers from "the edge on 127.0.0.1" believes them from any app.
// The native core therefore talks to its upstreams over Unix sockets in the app's own directory
// (ai/context/research/android-path.md); a TCP upstream here is for a desktop or a server, where the
// upstream's own listener is what other users cannot reach.
package edge

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"html"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Identity is the header family forward-auth answers with and every app here reads (handlers.go,
// identityHeaders) — the same five traefik's middleware lists as authResponseHeaders.
var Identity = []string{"X-authentik-username", "X-authentik-groups", "X-authentik-email", "X-authentik-name", "X-authentik-uid"}

// Route is one host this edge serves. Its upstream is an http(s) URL, or `unix:<absolute path>`: an app
// on a socket of its own, which on a phone no other app can open (DGO-1090).
type Route struct {
	Upstream *url.URL
	Gated    bool
}

// dialer opens every connection to one Unix socket, whatever address the request names.
type dialer func(ctx context.Context, network, addr string) (net.Conn, error)

// target is where a route's (or the gate's) requests go: an http(s) URL as it is, or for
// `unix:<absolute path>` the socket and the http URL written onto the request — its Host is never
// the browser's (that one is kept on the request), only the connection's name.
func target(u *url.URL) (*url.URL, dialer, error) {
	switch {
	case u == nil:
		return nil, nil, errors.New("no upstream")
	case u.Scheme == "unix":
		if u.Opaque != "" || u.Host != "" || u.RawQuery != "" || u.Fragment != "" {
			return nil, nil, fmt.Errorf("%s: a socket is unix:<absolute path>", u)
		}
		path := u.Path
		if err := socketPath(path); err != nil {
			return nil, nil, err
		}
		return &url.URL{Scheme: "http", Host: "localhost"}, func(ctx context.Context, _, _ string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "unix", path)
		}, nil
	case (u.Scheme == "http" || u.Scheme == "https") && u.Host != "":
		return u, nil, nil
	}
	return nil, nil, fmt.Errorf("%s is not an http(s) URL nor unix:<path>", u)
}

// socketPath refuses a socket path that is not absolute (an "@" name would be the abstract namespace,
// which every app reaches) or that is too long to bind.
func socketPath(path string) error {
	if !strings.HasPrefix(path, "/") {
		return fmt.Errorf("unix:%s: a socket's path is absolute", path)
	}
	if len(path) > maxSocketPath {
		return fmt.Errorf("unix:%s: %d bytes, and a socket's path is at most %d", path, len(path), maxSocketPath)
	}
	return nil
}

// transport is one direct hop on this machine — an HTTP_PROXY must not reroute it — over dial when
// the upstream is a socket.
func transport(dial dialer) *http.Transport {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil
	if dial != nil {
		t.DialContext = dial
	}
	return t
}

// Server routes by host and gates through forward-auth.
type Server struct {
	routes  map[string]Route
	proxies map[string]http.Handler
	auth    *url.URL
	client  *http.Client
	logf    func(string, ...any)
	// Machine, when set, is the phone's machine (DGO-1090, android-path.md "the machine on demand"):
	// while it reports a port, every host this edge has no route for is the machine's — a container
	// app's — gated as the console is and handed to the machine's edge on that loopback port, which its
	// QEMU holds, each request signed with the token the machine was given at its boot (EdgeSigned), the
	// core's own sign-in left out. 0: no machine.
	Machine  func() (port int, token string)
	machines sync.Map // "port token" → its proxy
	// Wake, when set, is asked about a host this edge has no route for while the machine is down: whether
	// it is one of the apps the office runs in its machine (ask false: nothing is done), and then — the
	// caller signed in — the machine asked for (ask true) and the app's step toward it. Such a host answers
	// a page that waits for the machine, so an app opened after the phone restarted comes up instead of
	// answering nobody.
	Wake func(host string, ask bool) (step string, has bool)
}

// The headers the machine's forward-auth takes the core's identity by (FORWARD_AUTH_EDGE_TOKEN): when, and
// the signature of the request (EdgeSigned); a client's own are removed with every X-DGO-* (Claimed).
const (
	EdgeAt    = "X-DGO-Edge-At"
	EdgeNonce = "X-DGO-Edge-Nonce"
	EdgeSig   = "X-DGO-Edge-Sig"
)

// EdgeSigned is the signature of one request to the machine: HMAC-SHA256(token, when, a nonce of its own,
// method, host, URI, the identity in Identity's order) — the request as the machine's edge sees it. The
// token never travels: what an app in the machine may log is a signature of that one request, good once,
// within a minute; two alike in one second carry two nonces.
func EdgeSigned(token, at, nonce, method, host, uri string, h http.Header) string {
	parts := []string{at, nonce, method, host, uri}
	for _, k := range Identity {
		parts = append(parts, h.Get(k))
	}
	mac := hmac.New(sha256.New, []byte(token))
	mac.Write([]byte(strings.Join(parts, "\n")))
	return hex.EncodeToString(mac.Sum(nil))
}

// SignForMachine writes a request's signature for the machine onto h: now, a fresh nonce, and EdgeSigned
// over them, the request and the identity h carries.
func SignForMachine(h http.Header, token, method, host, uri string) {
	raw := make([]byte, 16)
	_, _ = rand.Read(raw) // crypto/rand: a failure here is the platform's, and an empty nonce is refused there
	at, nonce := strconv.FormatInt(time.Now().Unix(), 10), hex.EncodeToString(raw)
	h.Set(EdgeAt, at)
	h.Set(EdgeNonce, nonce)
	h.Set(EdgeSig, EdgeSigned(token, at, nonce, method, host, uri, h))
}

// session is the core's own sign-in, which the machine never needs (it trusts the signature): the
// cookies forward-auth sets, kept from whatever answers on the machine's port.
var session = map[string]bool{"dgo_session": true, "dgo_state": true, "__Host-dgo_state": true}

// withoutSession is a request's Cookie header without the core's own sign-in, every other cookie kept.
func withoutSession(h http.Header) {
	var keep []string
	for _, v := range h.Values("Cookie") {
		for _, part := range strings.Split(v, ";") {
			p := strings.TrimSpace(part)
			if name, _, _ := strings.Cut(p, "="); p != "" && !session[name] {
				keep = append(keep, p)
			}
		}
	}
	h.Del("Cookie")
	if len(keep) > 0 {
		h.Set("Cookie", strings.Join(keep, "; "))
	}
}

// machine is the proxy to the machine's edge on port: proxyTo's, without the core's sign-in, signed.
func (s *Server) machine(port int, token string) http.Handler {
	key := strconv.Itoa(port) + " " + token
	if h, ok := s.machines.Load(key); ok {
		return h.(http.Handler)
	}
	to := &url.URL{Scheme: "http", Host: net.JoinHostPort("127.0.0.1", strconv.Itoa(port))}
	inner := proxyTo(to, nil, "the machine", s.logf).(*httputil.ReverseProxy)
	rewrite := inner.Rewrite
	inner.Rewrite = func(pr *httputil.ProxyRequest) {
		rewrite(pr)
		withoutSession(pr.Out.Header)
		SignForMachine(pr.Out.Header, token, pr.Out.Method, pr.Out.Host, pr.Out.URL.RequestURI())
	}
	h, _ := s.machines.LoadOrStore(key, http.Handler(inner))
	return h.(http.Handler)
}

// waiting answers a host of the machine's while it comes up: 503 and Retry-After, and to a browser's page a
// page that loads itself again every few seconds — the app it asked for, once the machine is up.
func waiting(w http.ResponseWriter, r *http.Request, step string) {
	if step == "" {
		step = "the office's machine is starting"
	}
	w.Header().Set("Retry-After", "5")
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet || !strings.Contains(r.Header.Get("Accept"), "text/html") {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = io.WriteString(w, step+"\n")
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusServiceUnavailable)
	_, _ = io.WriteString(w, `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">`+
		`<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark">`+
		`<meta http-equiv="refresh" content="5"><title>המכונה של המשרד עולה</title></head><body>`+
		`<h1>המכונה של המשרד עולה</h1><p>האפליקציה תיפתח כאן מעצמה כשהמכונה מוכנה.</p>`+
		`<p dir="auto">`+html.EscapeString(step)+`</p></body></html>`+"\n")
}

// New builds the edge: routes by host (lowercase, no port), and the forward-auth URL the gated ones ask
// — or `unix:<path>`, forward-auth's socket, asked at /auth/traefik.
func New(routes map[string]Route, auth string, logf func(string, ...any)) (*Server, error) {
	s := &Server{routes: map[string]Route{}, proxies: map[string]http.Handler{}, logf: logf}
	gated := false
	for host, rt := range routes {
		to, dial, err := target(rt.Upstream)
		if err != nil {
			return nil, fmt.Errorf("dgo edge: %s: the upstream: %v", host, err)
		}
		h := strings.ToLower(host)
		s.routes[h] = rt
		s.proxies[h] = proxyTo(to, dial, upstreamName(rt.Upstream), logf)
		gated = gated || rt.Gated
	}
	var authDial dialer
	if gated {
		u, err := url.Parse(auth)
		if err == nil && u.Scheme == "unix" {
			if u, authDial, err = target(u); err == nil {
				u.Path = "/auth/traefik"
			}
		}
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			return nil, fmt.Errorf("dgo edge: --auth %q is not forward-auth's /auth/traefik URL nor its unix:<socket>, and a gated host needs it", auth)
		}
		s.auth = u
	}
	s.client = &http.Client{
		Transport: transport(authDial),
		Timeout:   30 * time.Second,
		// the auth answer's 302 is the BROWSER's to follow, never this edge's
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	return s, nil
}

func hostname(hostport string) string {
	if h, _, err := net.SplitHostPort(hostport); err == nil {
		return strings.ToLower(h)
	}
	return strings.ToLower(hostport)
}

// Claimed answers whether a request header is one only this edge, or the identity service through it,
// may write — every family the console's screen() refuses from anyone but a trusted proxy, which behind
// this edge it believes (console/edge.go identityHeader; TestTheEdgeStripsWhatTheConsoleBelieves holds
// the two together): X-authentik-* (all of it, its jwt and meta-* too), the office's own X-DGO-*, the
// Remote-*, X-Auth-Request-* and X-Webauth-* families of other auth proxies, X-Remote-User, and every
// forwarding header — matched the way the apps read them (case aside, `_` as `-`: a WSGI server reads
// X_Authentik_Username as the same header, and Go keeps it under a key of its own).
func Claimed(key string) bool {
	k := strings.ReplaceAll(strings.ToLower(key), "_", "-")
	for _, p := range []string{"x-authentik-", "x-dgo-", "remote-", "x-forwarded-", "x-auth-request-", "x-webauth-"} {
		if strings.HasPrefix(k, p) {
			return true
		}
	}
	return k == "forwarded" || k == "x-remote-user" || k == "x-real-ip"
}

// idKey carries the gate's answer from ServeHTTP to the proxy's Rewrite, where it is written onto the
// outgoing request AFTER the hop-by-hop removal: a header the gate set on the incoming request could be
// named in the client's own `Connection:` and removed on the way (the second reader).
type idKey struct{}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	for k := range r.Header {
		if Claimed(k) {
			delete(r.Header, k)
		}
	}
	host := hostname(r.Host)
	rt, ok := s.routes[host]
	if !ok && s.Machine != nil && s.auth != nil {
		if port, token := s.Machine(); port > 0 {
			ids, ok := s.gate(w, r)
			if !ok {
				return
			}
			s.machine(port, token).ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), idKey{}, ids)))
			return
		}
		if s.Wake != nil && r.URL.Path != "/healthz" {
			if _, has := s.Wake(host, false); has {
				if _, ok := s.gate(w, r); !ok {
					return // an anonymous caller signs in first: nobody but the owner starts the machine
				}
				step, _ := s.Wake(host, true)
				waiting(w, r, step)
				return
			}
		}
	}
	if !ok {
		if r.URL.Path == "/healthz" {
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			_, _ = io.WriteString(w, "ok\n")
			return
		}
		http.Error(w, "dgo edge: nothing in this office answers at "+host, http.StatusNotFound)
		return
	}
	if rt.Gated {
		ids, ok := s.gate(w, r)
		if !ok {
			return
		}
		r = r.WithContext(context.WithValue(r.Context(), idKey{}, ids))
	}
	s.proxies[host].ServeHTTP(w, r)
}

// hop-by-hop headers, which a proxy never forwards (RFC 9110 §7.6.1)
var hop = map[string]bool{"Connection": true, "Keep-Alive": true, "Proxy-Authenticate": true, "Proxy-Authorization": true,
	"Te": true, "Trailer": true, "Transfer-Encoding": true, "Upgrade": true, "Content-Length": true}

// gate asks forward-auth about r. True: the identity the answer named, which the proxy writes onto the
// request it sends on. False: the answer has been written to w.
func (s *Server) gate(w http.ResponseWriter, r *http.Request) (map[string]string, bool) {
	req, err := http.NewRequestWithContext(r.Context(), r.Method, s.auth.String(), nil)
	if err != nil {
		http.Error(w, "dgo edge: could not ask the identity service", http.StatusInternalServerError)
		return nil, false
	}
	for k, vs := range r.Header {
		if !hop[k] {
			req.Header[k] = vs
		}
	}
	// written from the request this edge received — a client's own X-Forwarded-* are overwritten here
	req.Header.Set("X-Forwarded-Method", r.Method)
	req.Header.Set("X-Forwarded-Proto", "http")
	req.Header.Set("X-Forwarded-Host", r.Host)
	req.Header.Set("X-Forwarded-Uri", r.URL.RequestURI())
	req.Header.Set("X-Forwarded-For", peer(r.RemoteAddr))
	res, err := s.client.Do(req)
	if err != nil {
		s.logf("dgo edge: %s %s%s: the identity service did not answer: %v", r.Method, r.Host, r.URL.Path, err)
		http.Error(w, "dgo edge: the identity service did not answer", http.StatusBadGateway)
		return nil, false
	}
	defer res.Body.Close()
	if res.StatusCode/100 == 2 {
		// A 2xx that names nobody is not a sign-in: an --auth pointed at the wrong path (a health
		// check answers 200 too) would otherwise open every gated host to everyone.
		if res.Header.Get("X-authentik-username") == "" {
			s.logf("dgo edge: %s %s%s: the identity service answered %d naming nobody — refused", r.Method, r.Host, r.URL.Path, res.StatusCode)
			http.Error(w, "dgo edge: the identity service answered without an identity", http.StatusBadGateway)
			return nil, false
		}
		ids := map[string]string{}
		for _, h := range Identity {
			if v := res.Header.Get(h); v != "" {
				ids[h] = v
			}
		}
		return ids, true
	}
	for k, vs := range res.Header {
		if !hop[k] {
			w.Header()[k] = vs
		}
	}
	w.WriteHeader(res.StatusCode)
	_, _ = io.Copy(w, io.LimitReader(res.Body, 1<<20))
	return nil, false
}

func peer(remote string) string {
	if h, _, err := net.SplitHostPort(remote); err == nil {
		return h
	}
	return remote
}

// proxyTo forwards a request to an upstream with the Host the browser used (apps build their URLs and
// redirects from it) and X-Forwarded-* written from the request this edge received.
func proxyTo(to *url.URL, dial dialer, name string, logf func(string, ...any)) http.Handler {
	t := transport(dial)
	t.DisableCompression = true // the client's Accept-Encoding, or its absence, reaches the app
	return &httputil.ReverseProxy{
		Transport: t,
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(to)
			pr.Out.Host = pr.In.Host
			pr.Out.URL.RawQuery = pr.In.URL.RawQuery
			pr.SetXForwarded()
			// the gate's identity, written here — after the hop-by-hop removal a client's
			// `Connection:` could otherwise turn against it
			if ids, ok := pr.In.Context().Value(idKey{}).(map[string]string); ok {
				for k, v := range ids {
					pr.Out.Header.Set(k, v)
				}
			}
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			logf("dgo edge: %s %s%s: %s did not answer: %v", r.Method, r.Host, r.URL.Path, name, err)
			http.Error(w, "dgo edge: the app did not answer", http.StatusBadGateway)
		},
	}
}

// upstreamName is how the log names an upstream: its host, or the socket's path.
func upstreamName(u *url.URL) string {
	if u.Scheme == "unix" {
		return u.Path
	}
	return u.Host
}

// maxSocketPath is the longest path a Unix socket takes on Linux (sun_path's 108 bytes, its NUL aside);
// a longer one fails only as bind's "invalid argument". Android's adopted storage nears it.
const maxSocketPath = 107

// ListenUnix opens a Unix socket only its owner may open — the phone's edge, which the app's WebView
// reaches over it (loopback is every app's on a phone), and the native core's others (internal/native). A socket a dead process left — one whose connect
// is refused — is replaced; one that answers, or fails any other way (a full backlog, another owner's),
// is not, and anything else at the path is never removed — as forward-auth's FORWARD_AUTH_LISTEN does.
// One process starts it (the app's service): two starting at once could both find the old socket dead.
func ListenUnix(path string) (net.Listener, error) {
	if err := socketPath(path); err != nil {
		return nil, err
	}
	if st, err := os.Lstat(path); err == nil {
		if st.Mode()&os.ModeSocket == 0 {
			return nil, fmt.Errorf("unix:%s is there and is not a socket", path)
		}
		c, err := net.DialTimeout("unix", path, time.Second)
		if err == nil {
			c.Close()
			return nil, fmt.Errorf("unix:%s: another process answers on it", path)
		}
		if !errors.Is(err, syscall.ECONNREFUSED) {
			return nil, fmt.Errorf("unix:%s: %v — not taken over", path, err)
		}
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return nil, err
		}
	}
	ln, err := net.Listen("unix", path)
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(path, 0o600); err != nil {
		ln.Close()
		return nil, err
	}
	return ln, nil
}

// routeFlag is a repeatable `--open host=url` / `--gated host=url`.
type routeFlag struct {
	routes map[string]Route
	gated  bool
}

func (f *routeFlag) String() string { return "" }

func (f *routeFlag) Set(v string) error {
	host, raw, ok := strings.Cut(v, "=")
	if !ok || host == "" || strings.ContainsAny(host, ":/ ") {
		return fmt.Errorf("want host=url, e.g. console.localhost=http://127.0.0.1:8000")
	}
	u, err := url.Parse(raw)
	if err != nil {
		return err
	}
	h := strings.ToLower(host)
	if _, dup := f.routes[h]; dup {
		return fmt.Errorf("%s is routed twice", h)
	}
	f.routes[h] = Route{Upstream: u, Gated: f.gated}
	return nil
}

// Main is `dgo be-child edge`: serve until interrupted, then finish the requests in flight. 2 for a
// usage error, 1 for a server that could not start or stopped on its own.
func Main(_ string, args []string, stderr io.Writer) int {
	fs := flag.NewFlagSet("dgo be-child edge", flag.ContinueOnError)
	fs.SetOutput(stderr)
	routes := map[string]Route{}
	listen := fs.String("listen", "127.0.0.1:8080", "the address to serve on: a loopback one, or unix:<absolute path> (the phone's)")
	auth := fs.String("auth", "http://127.0.0.1:9078/auth/traefik", "forward-auth's /auth/traefik, which every gated host asks first")
	fs.Var(&routeFlag{routes: routes}, "open", "host=url: a host served without the identity check (the sign-in host); repeatable")
	fs.Var(&routeFlag{routes: routes, gated: true}, "gated", "host=url: a host behind the identity check; repeatable")
	fs.Usage = func() {
		fmt.Fprintln(stderr, "usage: dgo be-child edge [--listen 127.0.0.1:8080] [--auth <url>] --open signin.localhost=<url> --gated console.localhost=<url> …")
		fs.PrintDefaults()
	}
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if len(routes) == 0 || fs.NArg() > 0 {
		fs.Usage()
		return 2
	}
	// Loopback only: the sign-in page over plain HTTP to whatever network the machine is on is not an
	// edge this office means to have (the second reader).
	// unix:<path> read as an upstream's is (target), so the three spellings agree
	sock := ""
	if strings.HasPrefix(*listen, "unix:") {
		u, err := url.Parse(*listen)
		if err == nil {
			_, _, err = target(u)
		}
		if err != nil {
			fmt.Fprintf(stderr, "dgo edge: --listen %s: %v\n", *listen, err)
			return 2
		}
		sock = u.Path
	} else if h, _, err := net.SplitHostPort(*listen); err != nil || !(h == "localhost" || net.ParseIP(h) != nil && net.ParseIP(h).IsLoopback()) {
		fmt.Fprintf(stderr, "dgo edge: --listen %s is not a loopback address nor unix:<path>\n", *listen)
		return 2
	}
	onSocket := sock != ""
	logger := log.New(stderr, "", log.LstdFlags)
	s, err := New(routes, *auth, logger.Printf)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	var ln net.Listener
	if onSocket {
		ln, err = ListenUnix(sock)
	} else {
		ln, err = net.Listen("tcp", *listen)
	}
	if err != nil {
		fmt.Fprintln(stderr, "dgo edge:", err)
		return 1
	}
	where := "unix:" + sock
	if !onSocket {
		where = "http://" + ln.Addr().String()
	}
	var said []string
	for h, rt := range routes {
		kind := "open"
		if rt.Gated {
			kind = "gated"
		}
		said = append(said, fmt.Sprintf("%s→%s (%s)", h, upstreamName(rt.Upstream), kind))
	}
	sort.Strings(said)
	logger.Printf("dgo edge: %s — %s", where, strings.Join(said, ", "))
	srv := &http.Server{Handler: s, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 2 * time.Minute, ErrorLog: logger}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	stopped := make(chan error, 1)
	go func() {
		<-ctx.Done()
		done, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		stopped <- srv.Shutdown(done)
	}()
	if err := srv.Serve(ln); !errors.Is(err, http.ErrServerClosed) {
		fmt.Fprintln(stderr, "dgo edge:", err)
		return 1
	}
	if err := <-stopped; err != nil {
		fmt.Fprintln(stderr, "dgo edge:", err)
		return 1
	}
	return 0
}

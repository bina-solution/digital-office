// Package serve is the office's control plane — platform-base/app-management/app.py, the service the
// apps screen, the install wizard and every linked office talk to — as a process of the one binary:
// `dgo be-child control`. Step 3 of ai/context/core-native-plan.md, its first slice.
//
// THE CONTRACT IS app.py's. Every route it declares — the 22 that gate G85 enumerates — is in the table
// below under the same method and rule. A route that needs no docker engine and no network is answered
// here, from the files reconcile.py reads, through internal/compiler: the office record, the remote
// block, the health line. Every other route is handed to app-management's container unchanged, and
// BBOX_CONTROL_PLANE=container hands it EVERY route: the rollback is one variable. Each native answer
// is proven byte-identical to Flask's by serve_test.go, which runs app.py itself as the oracle.
//
// THE REFUSALS ARE app.py's TOO, and they are answered here whatever the container is. A request that
// crossed a link (the door stamps it X-DGO-Office) is refused on every route that writes this office's
// state, in app.py's own words — so an office whose container image predates a guard (eight arrived on
// 2026-10-09, DGO-49) has it anyway. And the process keeps the boundary the container had for free:
// app-management is published on no port, so nothing but this office's own network ever reached it,
// while a port on the host's loopback is reachable from every browser tab on the machine. So a caller
// from another address, a request addressed to another host (DNS rebinding), a page of any origin but
// this listener's own — another port of this machine included — and a write any page could send without
// asking (cross-site request forgery: a form needs no permission to be posted) are refused before a
// route is looked at. And a route is read as the container's server will read it — the method upper
// case, the path cut at `#`, its leading slashes folded — so no spelling of a guarded route passes by.
//
// What a native answer cannot vouch for — a state file the YAML reader refuses, a catalog the compiler
// refuses, an input on which app.py itself fails — is not guessed: the container answers it.
//
// Not here, and next: ConnectRPC on a Unix socket (a named pipe on Windows) in place of the loopback
// port, the office record in SQLite, and the write routes themselves.
package serve

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"html"
	"io"
	"io/fs"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// officeHeader is app.py's OFFICE_HEADER: written by the link's door, the office a request came from.
const officeHeader = "X-DGO-Office"

// route is one route of app.py — every `@app.<verb>(rule)` that G85 enumerates, in app.py's order — and
// what this process does with it. answer answers it natively, or returns false where it cannot vouch
// for app.py's answer. linked is app.py's refusal of a caller that came over a link, in its words,
// answered here before anything else when the route's condition holds (when; nil means always). A
// route with neither is the container's, and the comment says why.
type route struct {
	method, rule, fn string
	answer           func(*server, http.ResponseWriter, *http.Request) bool
	linked           string
	when             func(*http.Request) bool
}

var routes = []route{
	{method: "POST", rule: "/api/reconcile", fn: "api_reconcile", linked: "a linked office does not converge this office"},
	{method: "GET", rule: "/api/apps/<aid>/room", fn: "api_room"},                               // the ENGINE machine's memory, load and disk, as seen from inside it
	{method: "GET", rule: "/api/apps/<aid>/job", fn: "api_job", answer: (*server).jobInMachine}, // a bring-up job lives in the container's own process — or the phone's machine (machine.go)
	{method: "POST", rule: "/api/apps/<aid>/archive", fn: "api_archive", linked: "a linked office does not archive this office's apps"},
	{method: "POST", rule: "/api/apps/<aid>/unarchive", fn: "api_unarchive", linked: "a linked office does not bring this office's apps back"},
	{method: "POST", rule: "/api/apps/<aid>/enable", fn: "api_enable", when: plainSwitchOn, answer: (*server).enableInMachine,
		linked: "a linked office brings an app here only with its data — a plain switch-on of this office's apps is this office's own decision"},
	{method: "POST", rule: "/api/apps/<aid>/apply", fn: "api_apply", linked: "a linked office does not apply this office's apps"},
	{method: "GET", rule: "/api/remote", fn: "api_remote_get", answer: (*server).remote},
	{method: "PUT", rule: "/api/remote", fn: "api_remote_put", linked: "a linked office does not declare what this office shows of others"},
	{method: "POST", rule: "/api/apps/<aid>/move", fn: "api_move", linked: "a move is never handed on from a request that itself arrived over a link"},
	{method: "POST", rule: "/api/apps/<aid>/disable", fn: "api_disable", linked: "a linked office does not switch this office's apps off", answer: (*server).disableInMachine},
	{method: "POST", rule: "/api/apps/<aid>/uninstall", fn: "api_uninstall", linked: "a linked office does not uninstall this office's apps"},
	{method: "GET", rule: "/api/catalog", fn: "api_catalog_index"},            // the office's own signed index (`?ref=` not read since DGO-604)
	{method: "POST", rule: "/api/catalog/preview", fn: "api_catalog_preview"}, // fetches and stages: the container refuses a linked caller (DGO-604)
	{method: "POST", rule: "/api/catalog/install", fn: "api_catalog_install", linked: "a linked office does not install into this office"},
	{method: "GET", rule: "/api/office", fn: "api_office_get", answer: (*server).office},
	{method: "PUT", rule: "/api/office", fn: "api_office_put", linked: "a linked office does not write this office's identity", answer: (*server).officePut},
	{method: "GET", rule: "/healthz", fn: "healthz", answer: (*server).healthz},
	{method: "GET", rule: "/readyz", fn: "readyz"},                             // asks the docker engine
	{method: "GET", rule: "/api/apps", fn: "api_apps", answer: (*server).apps}, // live container state, so here only where there is no engine (apps.go)
	{method: "GET", rule: "/", fn: "index"}, // the screen as the container's image carries it
	{method: "GET", rule: "/<path:path>", fn: "static_files"},
}

// match is the route Werkzeug's router picks for a method (upper case, as Werkzeug makes it) and a path
// (routePath), or nil: literal segments equal, `<aid>` one non-empty segment, `<path:path>` the rest. A
// rule app.py names comes before the catch-all in the table, as it outranks it there. What no rule
// matches (a slash inside, a method app.py does not take) is the container's, so its redirect or its
// 405 is answered as before.
func match(method, path string) *route {
	for i := range routes {
		if rt := &routes[i]; rt.method == method && rt.matches(path) {
			return rt
		}
	}
	return nil
}

// routePath is the path app.py's router matches, read from the request line as the container's server
// and Werkzeug read it: urlsplit's path — cut at the first `#`, then at the first `?`; an absolute-form
// target reduced to its path — percent-decoded, its leading slashes folded into one (Werkzeug matches
// "/" + path.lstrip("/")). Not r.URL.Path: Go keeps a literal `#` in it, where the server cuts it off.
func routePath(r *http.Request) string {
	t := r.RequestURI
	if t == "" {
		t = r.URL.RequestURI()
	}
	t, _, _ = strings.Cut(t, "#")
	t, _, _ = strings.Cut(t, "?")
	if !strings.HasPrefix(t, "/") {
		if _, rest, ok := strings.Cut(t, "://"); ok {
			t = rest[strings.IndexByte(rest+"/", '/'):]
		}
	}
	if p, err := url.PathUnescape(t); err == nil {
		t = p
	}
	return "/" + strings.TrimLeft(t, "/")
}

func (rt *route) matches(path string) bool {
	if rt.rule == "/<path:path>" {
		return len(path) > 1 && path[0] == '/' && path[1] != '/'
	}
	want, got := strings.Split(rt.rule, "/"), strings.Split(path, "/")
	if len(want) != len(got) {
		return false
	}
	for i, seg := range want {
		if seg != got[i] && (seg != "<aid>" || got[i] == "") {
			return false
		}
	}
	return true
}

// server answers app.py's routes: natively where the table says so, otherwise through the container.
type server struct {
	repo      string
	container bool         // BBOX_CONTROL_PLANE=container: every route is the container's
	upstream  http.Handler // app-management's container
	log       *log.Logger

	// engineless: this office has no container engine at all (NewNative, the phone's core) — the one
	// office whose catalog is the state file and the manifests alone (apps.go)
	engineless bool
	project    string                  // app.py's PROJECT: COMPOSE_PROJECT, as it was at the start
	now        func() time.Time        // the conditions' clock
	mu         sync.Mutex              // guards stamps
	stamps     map[[2]string][2]string // (app, condition) → (status, lastTransitionTime): app.py's _TRANSITIONS

	// the phone's machine, where a container app runs (machine.go): nil but on the native core
	machine         Machine
	domain          string // the office's domain: the machine's app-management answers at apps.<domain>
	waiting         appSet // enables asked before the machine was up: their job hands them on
	handed          appSet // switches handed to the machine ("<aid> <state>"): their end is mirrored in the core's state
	toMachineClient *http.Client
	syncMu          sync.Mutex
	synced          string // the machine ("<port> <token>") the core's mirror was last set from (syncMachine)
	syncing         sync.WaitGroup
	switched        atomic.Int64 // switches handed to the machine or ended: a mirror read across one is void
	mirrorMu        sync.Mutex   // a mirror's check and writes, against a switch's own write
}

func (s *server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if why := outsider(r); why != "" {
		reply(w, http.StatusForbidden, object("error", why))
		return
	}
	if !s.container {
		if rt := match(strings.ToUpper(r.Method), routePath(r)); rt != nil {
			if rt.linked != "" && linked(r.Header) && (rt.when == nil || rt.when(r)) {
				reply(w, http.StatusForbidden, object("error", rt.linked))
				return
			}
			if rt.answer != nil && rt.answer(s, w, r) {
				return
			}
		}
	}
	s.upstream.ServeHTTP(w, r)
}

// ── the boundary: who may ask at all ─────────────────────────────────────────────────────────────

// outsider is the refusal of a caller this process must not answer, or "":
//   - only this machine's own callers — checked, not assumed from the bind: traffic from outside can be
//     forwarded to a loopback address (route_localnet);
//   - only a request addressed to this machine: a page that rebinds its own name to 127.0.0.1 still
//     addresses it by that name;
//   - no page but this listener's own, as the browser names it in Origin and Sec-Fetch-Site: a page of
//     any other origin — another port of this machine included (a dev server, a notebook) — is refused;
//   - and no write a page could send without asking (`formable`), for the browser that names neither.
func outsider(r *http.Request) string {
	if ip := net.ParseIP(hostOf(r.RemoteAddr)); ip == nil || !ip.IsLoopback() {
		return "the control plane answers this machine only — the call came from " + r.RemoteAddr
	}
	if r.Host != "" && !thisMachine(hostOf(r.Host)) {
		return "the control plane answers a request addressed to this machine only, not one for " + r.Host
	}
	if o := r.Header.Get("Origin"); o != "" && !strings.EqualFold(o, "http://"+r.Host) {
		return "the control plane answers no page but its own (" + o + ")"
	}
	if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" && site != "none" {
		return "the control plane answers no page but its own (Sec-Fetch-Site: " + site + ")"
	}
	if formable(r) {
		return "the control plane takes a change as JSON, or with an X-DGO-Request header — any page could send this one"
	}
	return ""
}

// formable is a write a page could send without asking first — an HTML form, or fetch in no-cors mode:
// a method other than GET, HEAD and OPTIONS, with no Content-Type or a form's own (the CORS safe list:
// form-urlencoded, multipart, text/plain), and none of the headers a page may not set. Every caller of
// app.py's writes sends JSON (the apps screen, the install wizard, dgo-extend, app.py's own peer calls);
// one that cannot says X-DGO-Request, and the link's door is known by its stamp.
func formable(r *http.Request) bool {
	switch strings.ToUpper(r.Method) {
	case "GET", "HEAD", "OPTIONS":
		return false
	}
	if r.Header.Get("X-DGO-Request") != "" || linked(r.Header) {
		return false
	}
	mt, _, _ := strings.Cut(strings.Join(r.Header.Values("Content-Type"), ","), ";")
	switch strings.ToLower(strings.TrimSpace(mt)) {
	case "", "application/x-www-form-urlencoded", "multipart/form-data", "text/plain":
		return true
	}
	return false
}

// hostOf is the host of a host[:port], brackets of an IPv6 literal removed.
func hostOf(hostport string) string {
	if h, _, err := net.SplitHostPort(hostport); err == nil {
		return h
	}
	return strings.Trim(hostport, "[]")
}

// thisMachine is localhost or a loopback address.
func thisMachine(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// ── the link: what a peer may not do here ────────────────────────────────────────────────────────

// linked is app.py's `request.headers.get(OFFICE_HEADER)`, truthiness and all. WSGI files a header
// under its CGI name — upper case, `-` and `_` alike — and joins two copies into one value, so
// `X_DGO_Office` is the same header to Flask, and two empty copies are a value. Both kept here: no
// spelling of the header is less refused than by app.py.
func linked(h http.Header) bool {
	n, val := 0, ""
	for k, vs := range h {
		if strings.EqualFold(strings.ReplaceAll(k, "_", "-"), officeHeader) {
			n += len(vs)
			val += strings.Join(vs, "")
		}
	}
	return n > 1 || val != ""
}

// maxGuardBody bounds what is read to decide enable's refusal; a larger body is the container's to read.
const maxGuardBody = 64 << 10

// plainSwitchOn is the condition of enable's refusal. app.py reads the body with Flask's
// get_json(silent=True) and refuses a linked caller unless its `restore` is an object — the one thing a
// peer comes here for, a move placing an app with its data. Decided here only where Python cannot
// answer otherwise: an empty body, a body not typed as JSON, a JSON document whose `restore` is not an
// object (whatever Python makes of bytes Go cannot read, it refuses those too). An object `restore`, a
// truthy document that is not an object (app.py fails on it) and bytes Go's strict decoder cannot read
// but Python's lenient one may (a BOM, NaN, UTF-16) are the container's to decide. The body is put back
// for it either way.
func plainSwitchOn(r *http.Request) bool {
	body, err := io.ReadAll(io.LimitReader(r.Body, maxGuardBody+1))
	r.Body = readCloser{io.MultiReader(bytes.NewReader(body), r.Body), r.Body}
	if err != nil || len(body) > maxGuardBody {
		return false
	}
	if len(bytes.TrimSpace(body)) == 0 {
		return true // nothing to read: get_json answers None
	}
	ct := r.Header.Values("Content-Type")
	if len(ct) > 1 || !printableASCII(strings.Join(ct, "")) {
		return false // Werkzeug and Go could read the type apart
	}
	if !jsonMimetype(strings.Join(ct, "")) {
		return true // not typed JSON: get_json answers None
	}
	var v any
	if json.Unmarshal(body, &v) != nil {
		return false
	}
	switch t := v.(type) {
	case map[string]any:
		_, object := t["restore"].(map[string]any)
		return !object
	case nil:
		return true
	case bool:
		return !t
	case float64:
		return t == 0
	case string:
		return t == ""
	case []any:
		return len(t) == 0
	}
	return false
}

// jsonMimetype is Werkzeug's `request.is_json`: the media type before any `;`, trimmed and lower-cased,
// is application/json or application/<anything>+json.
func jsonMimetype(ct string) bool {
	mt, _, _ := strings.Cut(ct, ";")
	mt = strings.ToLower(strings.TrimSpace(mt))
	return mt == "application/json" || strings.HasPrefix(mt, "application/") && strings.HasSuffix(mt, "+json")
}

func printableASCII(s string) bool {
	for i := 0; i < len(s); i++ {
		if c := s[i]; c != '\t' && (c < 0x20 || c > 0x7e) {
			return false
		}
	}
	return true
}

type readCloser struct {
	io.Reader
	io.Closer
}

// ── the native answers ───────────────────────────────────────────────────────────────────────────

// healthz is app.py's healthz().
func (s *server) healthz(w http.ResponseWriter, _ *http.Request) bool {
	reply(w, http.StatusOK, object("ok", true))
	return true
}

// office is api_office_get(): the `office:` record as reconcile.py's office-get reads it, and whether
// this office is installed as _office_installed() decides it.
func (s *server) office(w http.ResponseWriter, r *http.Request) bool {
	rec, err := compiler.OfficeBlock(s.repo)
	if err != nil {
		return s.unvouched(r, err)
	}
	done, err := installed(s.repo, rec)
	if err != nil {
		return s.unvouched(r, err)
	}
	reply(w, http.StatusOK, object("office", rec, "installed", done))
	return true
}

// remote is api_remote_get(): the `remote:` block as reconcile.py's remote-get reads it.
func (s *server) remote(w http.ResponseWriter, r *http.Request) bool {
	block, err := compiler.RemoteBlock(s.repo)
	if err != nil {
		return s.unvouched(r, err)
	}
	reply(w, http.StatusOK, object("remote", block))
	return true
}

// unvouched leaves a request this process cannot answer as app.py would to the container, and says so.
func (s *server) unvouched(r *http.Request, err error) bool {
	s.log.Printf("%s %s: answered by the container — %v", r.Method, r.URL.Path, err)
	return false
}

// installed is app.py's _office_installed(rec): the wizard's own signature (`installed_at`), or any
// layer-3 app switched on — the offices that predate the wizard. In app.py's order, with its two
// readings of a failure: what fails inside its `try` is "not installed", what fails after it is a 500,
// which this returns as an error for the container to answer.
func installed(repo string, rec *yamlish.Map) (bool, error) {
	if v, _ := rec.Get("installed_at"); v != nil && v != "" {
		return true, nil
	}
	// _load_state(): every exception reading the file is {} …
	var apps any
	doc, err := compiler.ReadState(repo)
	switch {
	case errors.As(err, new(*fs.PathError)):
	case err != nil:
		return false, err // a refusal of this reader; PyYAML may read the file
	case compiler.Truthy(doc):
		top, ok := doc.(*yamlish.Map)
		if !ok {
			return false, nil // `.get` on a document that is not a mapping raises inside the try
		}
		apps, _ = top.Get("apps")
	}
	if !compiler.Truthy(apps) {
		return false, nil // `… or {}`: nothing is switched on
	}
	entries, ok := apps.(*yamlish.Map)
	if !ok {
		return false, errors.New("apps: is not a mapping, and app.py fails on it")
	}
	// … then every manifest's root by its id. The compiler's catalog is that map wherever it loads at
	// all; what it refuses, app.py's own walk would still read — the container answers that.
	cat, err := compiler.LoadCatalog(repo)
	if err != nil {
		return false, err
	}
	for _, aid := range entries.Keys() {
		e, _ := entries.Get(aid)
		// reconcile.disposition() raises on a `state` that is truthy and not a string
		d, err := compiler.Disposition(e)
		if err != nil {
			return false, fmt.Errorf("apps.%s: %v, and app.py fails on it", aid, err)
		}
		// app.py finds manifests with glob, which does not see a directory whose name begins with a dot
		// …and not an app the product ships in the core office: app.py's `m.get("core") is True` (DGO-1090)
		if a := cat.Apps[aid]; a != nil && a.Root == "apps" && !strings.HasPrefix(aid, ".") && d == "enabled" && !shippedInCore(a) {
			return true, nil
		}
	}
	return false, nil
}

// shippedInCore is a manifest's `"core": true` — exactly true, as app.py's `is True` reads it.
func shippedInCore(a *compiler.App) bool {
	v, ok := a.Raw["core"].(bool)
	return ok && v
}

// object is a JSON object for reply, from key, value pairs.
func object(kv ...any) *yamlish.Map {
	m := yamlish.NewMap()
	for i := 0; i+1 < len(kv); i += 2 {
		m.Set(kv[i].(string), kv[i+1])
	}
	return m
}

// reply writes what Flask's jsonify writes: json.dumps(sort_keys=True, ensure_ascii=True,
// separators=(",", ":")) of the value, a newline, and the type application/json.
func reply(w http.ResponseWriter, status int, v any) {
	body := yamlish.FlaskJSON(v) + "\n"
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	_, _ = io.WriteString(w, body)
}

// ── the container ────────────────────────────────────────────────────────────────────────────────

// toContainer hands a request to app-management's container as it came — method, the request line's
// target as received (`asReceived`), headers and body; the forwarding headers neither added nor
// dropped; Host the container's own, as the console's door sends it — and its answer back as it went.
// Two things are not handed on, on purpose:
//   - a header whose name holds `_`: the container's gunicorn takes SCRIPT_NAME and PATH_INFO from one
//     from a trusted forwarder, which would route past what this process routed; it drops the rest;
//   - the power of `Connection` over the link's stamp: Go's proxy drops every header Connection names,
//     and X-DGO-Office is put back after, so no caller strips what the door wrote.
//
// absent, when given, answers in the container's place when it cannot be reached — the phone's core, before
// its machine runs (Absent) — instead of the proxy's error.
func toContainer(target *url.URL, logger *log.Logger, absent http.Handler) http.Handler {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil               // the container is on this office's own network, never behind an HTTP(S)_PROXY
	t.DisableCompression = true // no Accept-Encoding the caller did not send
	return &httputil.ReverseProxy{
		Transport: t,
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(target)
			asReceived(pr.Out.URL, pr.In.RequestURI)
			for k := range pr.Out.Header {
				if strings.Contains(k, "_") {
					delete(pr.Out.Header, k)
				}
			}
			for _, h := range []string{"X-Dgo-Office", "Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto"} {
				if v, ok := pr.In.Header[h]; ok {
					pr.Out.Header[h] = v
				}
			}
		},
		ErrorLog: logger,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			logger.Printf("%s %s: the container did not answer: %v", r.Method, r.URL.Path, err)
			if absent != nil {
				absent.ServeHTTP(w, r)
				return
			}
			reply(w, http.StatusBadGateway, object("error", fmt.Sprintf("app-management's container did not answer at %s: %v", target, err)))
		},
	}
}

// Absent answers for a container that is not there on an office with no engine — the phone's core before
// its machine runs (DGO-1084): the owner's tap on «אפליקציות» or «מחשבים» showed the proxy's own error
// («app-management's container did not answer at http://127.0.0.1:9 …», «the console container did not
// answer»). A page where a page was asked for, JSON where JSON was, 503 either way, and the machine's own
// reason (the app's refusal) or what it is doing toward the machine (its step), when it says one.
func Absent(m Machine) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		why := ""
		if m != nil {
			if why = m.Refused(); why == "" {
				why = m.Step()
			}
		}
		w.Header().Set("Cache-Control", "no-store")
		if !wantsPage(r) {
			reply(w, http.StatusServiceUnavailable, object("error", "machine_absent", "message", absentEnglish, "detail", why))
			return
		}
		detail := ""
		if why != "" {
			detail = `<p class="en">` + html.EscapeString(why) + "</p>"
		}
		body := fmt.Sprintf(absentPage, detail)
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Content-Length", strconv.Itoa(len(body)))
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = io.WriteString(w, body)
	})
}

const absentEnglish = "This app runs on the office's machine, which is not on this phone yet."

// absentPage names no colour of its own (the palette is theme-tokens.css's alone, G82): the WebView's own
// colours, a system font, the Hebrew first and the English beside it.
const absentPage = `<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>הלשכה</title><style>body{font-family:system-ui,sans-serif;margin:0;padding:2rem 1.25rem;line-height:1.6}p{max-width:32rem;margin:0 0 1rem}.en{direction:ltr;text-align:left;opacity:.7}</style>
</head><body><p>האפליקציה הזו רצה על מכונת הלשכה, והמכונה עוד לא נמצאת בטלפון הזה.</p>
<p class="en">` + absentEnglish + `</p>%s</body></html>
`

// wantsPage is a request for a page — a navigation, or a frame's — rather than a script's call.
func wantsPage(r *http.Request) bool {
	switch r.Header.Get("Sec-Fetch-Dest") {
	case "document", "iframe", "frame":
		return true
	case "":
		return strings.Contains(r.Header.Get("Accept"), "text/html")
	}
	return false
}

// asReceived makes the outbound request line carry the target the caller sent — a literal `#` and the
// query included, byte for byte — so the container's server reads the very bytes routePath routed. Go's
// URL would re-encode them (the console's door learned that a re-encoded query is another query). An
// absolute-form target goes on as its path and query; one that begins `//` keeps Go's spelling, as raw
// text it would read as a host.
func asReceived(out *url.URL, target string) {
	if !strings.HasPrefix(target, "/") {
		_, rest, ok := strings.Cut(target, "://")
		if !ok {
			return // `*`, and the forms no route takes: Go's own spelling
		}
		end := strings.IndexAny(rest, "/?#") // where the authority ends
		if end < 0 {
			end = len(rest)
		}
		if target = rest[end:]; !strings.HasPrefix(target, "/") {
			target = "/" + target
		}
	}
	if strings.HasPrefix(target, "//") {
		return
	}
	path, query, hasQuery := strings.Cut(target, "?")
	out.Opaque, out.RawQuery, out.ForceQuery = path, query, hasQuery && query == ""
}

// ── the process ──────────────────────────────────────────────────────────────────────────────────

// New is the control plane as a handler, for a process that serves it on a listener of its own — the
// phone's native core, `dgo be-child native` (DGO-1090): repo is the office's root, container
// app-management's URL for every route not answered here; BBOX_CONTROL_PLANE is read as Main reads it.
func New(repo, container string, logger *log.Logger) (http.Handler, error) {
	s, err := newServer(repo, container, os.Getenv("BBOX_CONTROL_PLANE"), logger)
	if err != nil {
		return nil, err // not a typed nil inside the interface
	}
	return s, nil
}

// NewNative is New for an office with no container engine at all — the phone's core: its catalog
// (GET /api/apps) is answered here from the state file and the manifests (apps.go), and a container
// app's enable, job and disable go to its machine (machine.go), at apps.<domain> there; machine may be nil.
func NewNative(repo, container string, logger *log.Logger, machine Machine, domain string) (http.Handler, error) {
	s, err := newServer(repo, container, os.Getenv("BBOX_CONTROL_PLANE"), logger)
	if err != nil {
		return nil, err
	}
	s.engineless, s.machine, s.domain = true, machine, domain
	// the container is the machine's: until it answers, a clear page or refusal, never the proxy's error
	u, _ := url.Parse(container) // newServer has refused one that does not parse
	s.upstream = toContainer(u, logger, Absent(machine))
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil
	s.toMachineClient = &http.Client{Transport: t, Timeout: 40 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	return s, nil
}

// Main runs the control plane until it fails: `dgo be-child control [--listen 127.0.0.1:<port>]
// [--container <url>]`. The container's URL defaults to APP_MANAGEMENT_URL — the name the console
// already gives it — then to http://app-management:8080, where the console looks for it too.
func Main(repo string, args []string, stderr io.Writer) int {
	logger := log.New(stderr, "dgo control: ", log.LstdFlags)
	fl := flag.NewFlagSet("dgo be-child control", flag.ContinueOnError)
	fl.SetOutput(stderr)
	listen := fl.String("listen", "127.0.0.1:0", "the loopback address to answer on (a bare :<port> is 127.0.0.1; port 0 picks a free one)")
	upstream := fl.String("container", envOr("APP_MANAGEMENT_URL", "http://app-management:8080"), "app-management's container: every route not answered here goes there")
	if err := fl.Parse(args); err != nil {
		return 2
	}
	if fl.NArg() > 0 {
		fmt.Fprintf(stderr, "dgo be-child control: unexpected argument %q\n", fl.Arg(0))
		return 2
	}
	s, err := newServer(repo, *upstream, os.Getenv("BBOX_CONTROL_PLANE"), logger)
	if err != nil {
		fmt.Fprintln(stderr, "dgo be-child control:", err)
		return 2
	}
	ln, err := listenLoopback(*listen)
	if err != nil {
		fmt.Fprintln(stderr, "dgo be-child control:", err)
		return 2
	}
	how := "natively: /healthz, GET /api/office, GET /api/remote and every refusal of a linked office; every other route by " + *upstream
	if s.container {
		how = "BBOX_CONTROL_PLANE=container: every route by " + *upstream
	}
	logger.Printf("answering on http://%s — %s", ln.Addr(), how)
	srv := &http.Server{Handler: s, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 2 * time.Minute, ErrorLog: logger}
	logger.Print(srv.Serve(ln))
	return 1
}

// newServer checks what it is given: the container's URL, and the rollback switch, whose one other
// value is refused rather than read as "native" — a misspelt rollback must not look like one.
func newServer(repo, upstream, plane string, logger *log.Logger) (*server, error) {
	if plane != "" && plane != "native" && plane != "container" {
		return nil, fmt.Errorf("BBOX_CONTROL_PLANE=%s: it is container (every route to app-management's container) or native", plane)
	}
	// dgo resolves `be-child` before it looks for a checkout, so the rollback starts anywhere; every
	// native answer reads the checkout's state file and catalog, so outside one only the rollback runs
	if repo == "" && plane != "container" {
		return nil, errors.New("not inside a DGO checkout (no platform/manager/reconcile.py + bbox above here), nor given an office root (DGO_OFFICE_ROOT, a directory with .dgo-office-root and platform.state.yaml) — the native answers read its files; BBOX_CONTROL_PLANE=container needs none")
	}
	// the container's root: a request is handed on with the target it came with, so a path here would go
	// unread
	u, err := url.Parse(upstream)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || strings.Trim(u.Path, "/") != "" || u.RawQuery != "" {
		return nil, fmt.Errorf("--container %q is not the http(s) root URL of app-management's container", upstream)
	}
	project, set := os.LookupEnv("COMPOSE_PROJECT") // os.getenv's default only when it is not set at all
	if !set {
		project = "deployment-hacohen"
	}
	return &server{repo: repo, container: plane == "container", upstream: toContainer(u, logger, nil), log: logger,
		project: project, now: time.Now, stamps: map[[2]string][2]string{}}, nil
}

// listenLoopback opens the address this process answers on, on this machine only. A missing host is
// 127.0.0.1; an address that is not a loopback one is refused before anything is bound, and a name
// that resolves elsewhere is refused once it is.
func listenLoopback(addr string) (net.Listener, error) {
	if !strings.Contains(addr, ":") {
		addr = ":" + addr
	}
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, fmt.Errorf("--listen %s: %v", addr, err)
	}
	if host == "" {
		host = "127.0.0.1"
	}
	refused := fmt.Errorf("--listen %s is not a loopback address — the control plane answers this machine only", addr)
	if ip := net.ParseIP(host); ip != nil && !ip.IsLoopback() {
		return nil, refused
	}
	ln, err := net.Listen("tcp", net.JoinHostPort(host, port))
	if err != nil {
		return nil, err
	}
	if a, ok := ln.Addr().(*net.TCPAddr); !ok || !a.IP.IsLoopback() {
		ln.Close()
		return nil, refused
	}
	return ln, nil
}

func envOr(name, def string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return def
}

// Package extend is «הרחבת הלשכה» — apps/dgo-extend — where the office has no container to run it: the phone's
// core (DGO-1328). dgo-extend links offices into a herd: it pairs them (an identity and a tunnel), declares new
// ones, approves those that ask to join. A phone does none of that yet: it reaches the business through its
// DOOR (DGO_PHONE_DOOR, the public console), and a phone that is an office of the herd in its own right — an
// identity, a tunnel from Android — is a step of its own. So the screen opens and says exactly that.
//
// Its routes, as the screen reads them on load (static/app.js boot):
//
//	GET  /api/pair               409 {"error": <the sentence>} — the screen draws a refusal as a STATE: the
//	                             sentence where the office's card stands, and the two verbs that would be
//	                             refused the same way put away (loadSelf)
//	GET  /api/pair/giving        404 (an office that gives nothing: the card is drawn without that cell)
//	GET  /api/context            the new-office form's facts, all empty, home.error the sentence: the «add»
//	                             button is drawn disabled (loadContext)
//	GET  /api/office · /api/link · /api/invite      empty lists
//	GET  /api/join               the door, no requests, no invites, nothing joined
//	GET  /api/map                this office alone: its name and its door, no links
//	any other method on /api/*   409, the same sentence: nothing is half done
//	GET  / and the screen's files    <root>/apps/dgo-extend/static
//
// What it is NOT: a second dgo-extend. Nothing here pairs, dials, writes a declaration or holds a key.
package extend

import (
	"bytes"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/screen"
)

// screenDir is where an office root carries dgo-extend's screen, as the container's image has it.
var screenDir = filepath.Join("apps", "dgo-extend", "static")

// Config is what the core knows that the screen shows.
type Config struct {
	Root  string // the office root: the screen's files
	Label string // this office's name, as the console shows it ("" — not named)
	Door  string // the business's door this phone opens its apps through (DGO_PHONE_DOOR), or ""
}

type server struct {
	c   Config
	now func() time.Time
}

// New answers «הרחבת הלשכה» on a phone.
func New(c Config) http.Handler { return &server{c: c, now: time.Now} }

// Refusal is the one sentence every verb of linking answers on a phone, and the office's card shows.
func (s *server) refusal() string {
	if s.c.Door != "" {
		return "הטלפון הזה עוד אינו לשכה בעדר: הוא מגיע לעסק דרך הדלת שלו (`" + s.c.Door + "`), ושם כל הלשכות מחוברות. " +
			"חיבור הטלפון כלשכה בפני עצמה — זהות ומנהרה משלו — הוא שלב נפרד, ועד אז אין כאן מה לצמד."
	}
	return "הטלפון הזה עוד אינו לשכה בעדר, ואין לו דלת לעסק: הוא עובד לבד. " +
		"חיבור הטלפון כלשכה בפני עצמה — זהות ומנהרה משלו — הוא שלב נפרד, ועד אז אין כאן מה לצמד."
}

func (s *server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Path
	get := r.Method == http.MethodGet || r.Method == http.MethodHead
	if strings.HasPrefix(p, "/api/") {
		if !get {
			reply(w, http.StatusConflict, map[string]any{"error": s.refusal()})
			return
		}
		s.api(w, p)
		return
	}
	if p == "/healthz" {
		reply(w, http.StatusOK, map[string]any{"ok": true, "linked": false})
		return
	}
	dir := filepath.Join(s.c.Root, screenDir)
	if !get {
		http.NotFound(w, r)
		return
	}
	file := r.Clone(r.Context())
	switch {
	case strings.HasPrefix(p, "/static/"): // app.py: app.mount("/static", static/) — the page loads its code there
		file.URL.Path = strings.TrimPrefix(p, "/static")
	case p == "/connect": // app.py's /connect: the pairing screen
		file.URL.Path = "/connect.html"
	}
	if screen.Serve(w, file, dir) {
		return
	}
	// the console container's history fallback: a page whose last segment has no extension (the map's
	// `map/<office>/<app>`, an office's declaration) is the screen's index.html — with the <base> the console
	// writes into every app's page (console/app.py), so the page's relative static/ and api/ resolve under the
	// app, not under the deep path. Never for an /api/ path: an API's answer is JSON, never a page.
	if last := p[strings.LastIndex(p, "/")+1:]; last != "" && !strings.Contains(last, ".") && !strings.Contains(p, "/api/") {
		if s.page(w, r, dir) {
			return
		}
	}
	http.NotFound(w, r)
}

// page writes the screen's index.html with a <base> of the app's prefix, or reports false: a regular file only.
func (s *server) page(w http.ResponseWriter, r *http.Request, dir string) bool {
	index := filepath.Join(dir, "index.html")
	if fi, err := os.Lstat(index); err != nil || !fi.Mode().IsRegular() {
		return false
	}
	html, err := os.ReadFile(index)
	if err != nil {
		return false
	}
	prefix := strings.TrimSuffix(r.Header.Get("X-Forwarded-Prefix"), "/")
	if !strings.HasPrefix(prefix, "/a/") || strings.ContainsAny(prefix, "\"<>'") {
		prefix = "/a/dgo-extend"
	}
	if i := bytes.Index(html, []byte("<head>")); i >= 0 && !bytes.Contains(html, []byte("<base ")) {
		html = append(html[:i+len("<head>")], append([]byte(`<base href="`+prefix+`/">`), html[i+len("<head>"):]...)...)
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(http.StatusOK)
	if r.Method != http.MethodHead {
		_, _ = w.Write(html)
	}
	return true
}

func (s *server) api(w http.ResponseWriter, p string) {
	empty := map[string]any{"items": []any{}, "count": 0}
	switch p {
	case "/api/pair":
		reply(w, http.StatusConflict, map[string]any{"error": s.refusal()})
	case "/api/pair/giving":
		reply(w, http.StatusNotFound, map[string]any{"error": "not_found"})
	case "/api/context":
		reply(w, http.StatusOK, map[string]any{
			// refused: the screen draws this sentence, not its own «no access to its machine» (loadContext)
			"home":     map[string]any{"error": s.refusal(), "refused": true},
			"machines": []any{}, "machines_error": nil, "git_accounts": []any{}, "domains": []any{},
			"apps": []any{}, "steps": []any{},
		})
	case "/api/office", "/api/link", "/api/invite":
		reply(w, http.StatusOK, empty)
	case "/api/join":
		// the join hub's door is the one OTHER offices join this one through, with an invitation or an approval
		// here — a phone is no hub: no host, and the screen keeps the join card and «invite» away (loadJoin)
		reply(w, http.StatusOK, map[string]any{"door": map[string]any{"host": "", "url": ""}, "requests": []any{},
			"invites": []any{}, "joined": map[string]any{}, "joiner": map[string]any{"state": "off", "joined": map[string]any{}}})
	case "/api/map":
		reply(w, http.StatusOK, map[string]any{
			"home":  map[string]any{"id": "", "label": s.label(), "herd": "", "commit": "", "domain": "", "apps": []any{}, "machine": map[string]any{}},
			"items": []any{}, "at": s.now().Unix(),
		})
	default:
		reply(w, http.StatusNotFound, map[string]any{"error": "not_found"})
	}
}

func (s *server) label() string {
	if s.c.Label != "" {
		return s.c.Label
	}
	return "הטלפון הזה"
}

func reply(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

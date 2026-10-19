package main

import (
	"encoding/json"
	"html/template"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// server is the whole program: one identity, one secret, one file of users.
type server struct {
	users *userStore
	sign  *signer
	// external is where a browser reaches THIS service (`http://auth.localhost`). It must be
	// configured, never derived from the request: a redirect target built from a request header is
	// the classic way a login page becomes a phishing hop, and this is the one hop in the flow that
	// every anonymous caller can ask for.
	external     string
	secureCookie bool
	cookieDomain string
	// suffixes is the office's own host allowlist (`-localhost`, `.hacohen.bina-solutions.co.il`).
	// It is what bounds a return-to URL to hosts this office actually serves.
	suffixes []string
	// legacy (and the key that verifies it) is authentik's session cookie, read during a migration.
	// nil — the default — means this office is fully on this service's own cookie. See legacy.go.
	legacy    *legacySessions
	legacyKey []byte
}

// session resolves the caller: THIS service's cookie first, then authentik's, so a browser that was
// signed in before the swap is not asked again. Both paths end in the same `*session` and the same
// five headers — an app cannot tell which cookie carried its caller, and that is the point.
func (s *server) session(r *http.Request) (*session, error) {
	now := time.Now()
	sess, err := s.sign.read(r, now, s.users)
	if err == nil || s.legacy == nil {
		return sess, err
	}
	return s.legacy.read(r, now, s.legacyKey, s.users)
}

// ── the header contract ──────────────────────────────────────────────────────────────────────────
//
// These five names are not ours to choose. `platform-base/traefik/config/authentik-forwardauth.yaml`
// lists them as `authResponseHeaders`, and traefik drops every one of them from the incoming request
// before copying ours on — which is also why a forged `X-authentik-username` from a client is gone
// before the app sees it. Three readers key on them in live code (console/app.py:80, my-docs/app.py:93,
// indox …/api/__init__.py:6978), two more trust them via a third party (Forgejo and bina-ds both
// name X-authentik-username in their own compose as the reverse-proxy user header), and the door in
// platform/manager/serve.py rewrites the family per linked office. Same names, or none of that works.
//
// X-authentik-jwt and the five X-authentik-meta-* headers the middleware also lists are NOT produced:
// they are an OIDC/JWKS artefact, nothing in this repository reads them, and inventing them would be
// a false claim of a signed token. See the design note — the middleware must drop them in the same
// commit that swaps the address.

func identityHeaders(u *user) map[string]string {
	return map[string]string{
		"X-authentik-username": u.Name,
		"X-authentik-email":    u.Email,
		"X-authentik-name":     u.Display,
		"X-authentik-uid":      u.UID,
		"X-authentik-groups":   u.GroupHeader(),
	}
}

// ── forward-auth: traefik's contract ─────────────────────────────────────────────────────────────
//
// WHAT TRAEFIK DOES WITH THIS RESPONSE (v3.3 — the reason the shape below is not negotiable):
//   - 2xx  → the original request is forwarded to the app, and each header named in the middleware's
//     `authResponseHeaders` is copied from THIS response onto it.
//   - else → this response IS the client's response, verbatim: status, Location and all.
//
// So 200 + the identity headers says "you are in", and 302 + Location says "go and sign in".
//
// It answers for EVERY method, because a gate that only guards GET is not a gate.
func (s *server) forwardAuth(w http.ResponseWriter, r *http.Request) {
	sess, err := s.session(r)
	if err != nil {
		s.challenge(w, r)
		return
	}
	for k, v := range identityHeaders(sess.User) {
		w.Header().Set(k, v)
	}
	w.WriteHeader(http.StatusOK)
}

// challenge sends an anonymous caller to the sign-in page, carrying where to come back to.
//
// 302 for every method, including POST, and deliberately not 401: this mirrors what the estate is
// already proven against (authentik's outpost answers 302 to all of them). A 401 would render as a
// bare browser dialog or a JSON body inside an XHR, where the estate's clients are written to follow
// a redirect — `serve.py` explains that a redirect WITHOUT the return-to is read by the console as
// "the office is down" rather than "sign in".
func (s *server) challenge(w http.ResponseWriter, r *http.Request) {
	target, ok := s.returnTo(r)
	if !ok {
		// Refuse rather than guess. A host this office does not serve is either a misconfigured
		// proxy or somebody trying to make our login page redirect to a foreign site; both want the
		// same answer, and neither wants a 302.
		http.Error(w, "forward-auth: refusing a return-to outside this office", http.StatusBadRequest)
		return
	}
	http.Redirect(w, r, s.external+"/login?rd="+url.QueryEscape(target), http.StatusFound)
}

// returnTo is the ONLY place a return-to URL is produced from a request, and it refuses two things
// on purpose:
//
//  1. a scheme or a path that can leave the URL's own authority (`//evil.example`, `/\evil.example`);
//  2. a host this office does not serve.
//
// (2) is not decoration. The middleware in this estate sets `trustForwardHeader: true`, so a client
// CAN influence X-Forwarded-Host; an unvalidated redirect target built from it is an open redirect.
// The allowlist closes it whether or not that flag is ever corrected — and the new middleware
// proposed in the design note sets it to false as well, because two independent refusals are
// cheaper than one argument about proxy behaviour.
func (s *server) returnTo(r *http.Request) (string, bool) {
	uri := r.Header.Get("X-Forwarded-Uri")
	if uri == "" {
		uri = r.URL.RequestURI()
	}
	if !strings.HasPrefix(uri, "/") || strings.HasPrefix(uri, "//") || strings.HasPrefix(uri, "/\\") {
		return "", false
	}
	proto := "http"
	for _, p := range strings.Split(r.Header.Get("X-Forwarded-Proto"), ",") {
		if p = strings.TrimSpace(p); p == "https" {
			proto = "https"
			break
		}
	}
	for _, cand := range strings.Split(r.Header.Get("X-Forwarded-Host"), ",") {
		host := strings.TrimSpace(cand)
		if host == "" {
			continue
		}
		if h, _, err := net.SplitHostPort(host); err == nil {
			host = h
		}
		if s.allowedHost(host) {
			return proto + "://" + host + uri, true
		}
	}
	return "", false
}

// allowedHost is the office's own host allowlist, and the two spellings differ on purpose:
//
//	".example.com"  → every host UNDER it (`console.example.com`), never the apex
//	"example.com"   → that exact host, and nothing under it
//
// The apex is deliberately NOT covered by the dotted form, and that is the whole reason the two
// spellings exist. traefik serves this office on `<app>.<domain>`; the bare domain is not one of its
// hosts, so a rule that quietly widened to it would make `rd=http://localhost/` a destination this
// office never serves — a redirect off the office onto whatever the name resolves to for the victim.
// Measured 2026-10-09: the first version of this function folded the apex in, and the test that
// asserted a foreign host is refused caught it as `localhost` being redirected TO rather than 400.
func (s *server) allowedHost(host string) bool {
	if host == "" {
		return false
	}
	for _, sfx := range s.suffixes {
		if strings.HasPrefix(sfx, ".") {
			if len(host) > len(sfx) && strings.HasSuffix(host, sfx) {
				return true
			}
			continue
		}
		if host == sfx {
			return true
		}
	}
	return false
}

// okReturnTo validates a return-to that arrived as DATA rather than as a trusted header — the `rd`
// query parameter and the form field. Same allowlist, different entry point, and it must stay the
// same function: two copies of a URL check is how the weaker one becomes the reachable one.
func (s *server) okReturnTo(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") {
		return false
	}
	return s.allowedHost(u.Hostname())
}

// ── sign-in ──────────────────────────────────────────────────────────────────────────────────────

// loginPage is one template with no colour of its own: the palette lives in ONE place in this
// repository (platform-base/bina-ui/theme-tokens.css, gates G27/G82), and a sign-in page rendered by
// a service that cannot read it must not invent a second one. Default browser styling, in Hebrew,
// and nothing else.
var loginPage = template.Must(template.New("login").Parse(`<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>כניסה</title></head><body>
<main>
<h1>כניסה</h1>
{{if .Error}}<p role="alert">{{.Error}}</p>{{end}}
<form method="post" action="/login">
<input type="hidden" name="rd" value="{{.ReturnTo}}">
<p><label>שם משתמש <input name="user" autocomplete="username" autofocus required></label></p>
<p><label>סיסמה <input type="password" name="password" autocomplete="current-password" required></label></p>
<p><button type="submit">כניסה</button></p>
</form>
</main></body></html>
`))

// loginForm carries nothing but the return-to and, on a retry, one sentence.
type loginForm struct {
	ReturnTo string
	Error    string
}

func (s *server) renderLogin(w http.ResponseWriter, status int, f loginForm) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	// This page is the one screen an anonymous caller reaches. It must not be framed by anybody,
	// and it must not be cached by a shared proxy.
	w.Header().Set("X-Frame-Options", "DENY")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = loginPage.Execute(w, f)
}

func (s *server) login(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet, http.MethodHead:
		rd := r.URL.Query().Get("rd")
		if !s.okReturnTo(rd) {
			rd = ""
		}
		s.renderLogin(w, http.StatusOK, loginForm{ReturnTo: rd})
	case http.MethodPost:
		s.doLogin(w, r)
	default:
		w.Header().Set("Allow", "GET, HEAD, POST")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *server) doLogin(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		s.renderLogin(w, http.StatusBadRequest, loginForm{Error: "הבקשה לא נקראה."})
		return
	}
	rd := r.PostFormValue("rd")
	if !s.okReturnTo(rd) {
		rd = ""
	}
	u, ok := s.users.verify(r.PostFormValue("user"), r.PostFormValue("password"))
	if !ok {
		// ONE sentence for a wrong name and for a wrong password. Naming which one was wrong turns
		// the form into a username oracle for anyone who can reach it.
		s.renderLogin(w, http.StatusUnauthorized, loginForm{ReturnTo: rd, Error: "שם המשתמש או הסיסמה שגויים."})
		return
	}
	s.sign.set(w, u.Name, s.secureCookie, s.cookieDomain)
	if rd == "" {
		rd = s.external + "/"
	}
	// 303, so the browser re-requests the destination as a GET: a POST that is answered with the
	// app's page is what puts "confirm resubmission" dialogs in the way of a normal sign-in.
	http.Redirect(w, r, rd, http.StatusSeeOther)
}

// logout ends this browser's session. It clears OUR cookie only — it cannot reach a session that
// an app keeps for itself (Plane, n8n and Supabase all have their own). Said here because the
// alternative is discovering it later and calling it a bug.
func (s *server) logout(w http.ResponseWriter, r *http.Request) {
	s.sign.clear(w, s.secureCookie, s.cookieDomain)
	rd := r.URL.Query().Get("rd")
	if !s.okReturnTo(rd) {
		rd = s.external + "/"
	}
	http.Redirect(w, r, rd, http.StatusSeeOther)
}

// whoami is the whole admin surface: it says who the caller IS, and it cannot say anything else.
//
// Not an accident. Listing, adding or removing users over HTTP would mean a second writer for the
// fact "who may sign in", and the office already has exactly one (the credential plane). The sign-in
// page is the browser's way to ask; this is the console's and the agent's.
func (s *server) whoami(w http.ResponseWriter, r *http.Request) {
	sess, err := s.session(r)
	w.Header().Set("Cache-Control", "no-store")
	if err != nil {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusUnauthorized)
		_ = json.NewEncoder(w).Encode(map[string]any{"signed_in": false})
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"signed_in": true,
		"username":  sess.User.Name,
		"email":     sess.User.Email,
		"name":      sess.User.Display,
		"uid":       sess.User.UID,
		"groups":    sess.User.Groups,
		"expires":   sess.Exp.UTC().Format(time.RFC3339),
	})
}

// healthz answers liveness only. It deliberately touches neither the users file (already in memory,
// by construction) nor the clock: a health probe that can fail for a reason unrelated to serving
// requests is a probe that restarts a working container.
func (s *server) healthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = w.Write([]byte("ok\n"))
}

func (s *server) routes() *http.ServeMux {
	m := http.NewServeMux()
	// The address traefik's middleware dials. Kept at authentik's own path shape
	// (`/outpost.goauthentik.io/auth/traefik`) so the swap is ONE line in one file — but see the
	// design note: the new middleware dials `/auth/traefik`, because a path that names the product
	// we removed is a lie future readers have to un-learn.
	m.HandleFunc("/auth/traefik", s.forwardAuth)
	m.HandleFunc("/healthz", s.healthz)
	m.HandleFunc("/whoami", s.whoami)
	m.HandleFunc("/login", s.login)
	m.HandleFunc("/logout", s.logout)
	m.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/" {
			http.Redirect(w, r, s.external+"/login", http.StatusFound)
			return
		}
		http.NotFound(w, r)
	})
	return m
}

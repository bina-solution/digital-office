package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"html/template"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
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
	// edgeToken is the phone's native core's (fromCore): set only on the machine behind that core.
	edgeToken []byte
	edgeSeen  seenSigs
	// live is the users file as it stands now (live.go); nil in a test that hands `users` in directly.
	live *liveUsers
	// handoff carries a sign-in from the auth host to each app host (handoff.go, F1).
	handoff *handoff
	// limit counts failed sign-ins per name and per address (limit.go, F2).
	limit *limiter
	// firstRun is the pending first-run setup (setup.go); nil, or not pending, on every office that
	// has its owner.
	firstRun *setup
}

// store is the users as they stand now: the file re-read when it changed, or the fixed set a test
// built.
func (s *server) store() *userStore {
	if s.live != nil {
		return s.live.get(time.Now())
	}
	return s.users
}

// session resolves the caller: THIS service's cookie first, then authentik's, so a browser that was
// signed in before the swap is not asked again. Both paths end in the same `*session` and the same
// five headers — an app cannot tell which cookie carried its caller, and that is the point.
func (s *server) session(r *http.Request) (*session, error) {
	now := time.Now()
	users := s.store()
	sess, err := s.sign.read(r, now, users)
	if err == nil || s.legacy == nil {
		return sess, err
	}
	return s.legacy.read(r, now, s.legacyKey, users)
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
	if ids, ok := s.fromCore(r); ok {
		for k, v := range ids {
			w.Header().Set(k, v)
		}
		w.WriteHeader(http.StatusOK)
		return
	}
	sess, err := s.session(r)
	if err != nil {
		if s.redeemCode(w, r) {
			return
		}
		s.challenge(w, r)
		return
	}
	// Signed in already, and the URL still carries a code: the code is spent here and the browser
	// sent to the clean URL, so a live code never reaches the app — its address bar, its logs, the
	// edge's access log — where whoever read it could redeem it.
	if target, ok := s.returnTo(r); ok {
		if clean, code := takeCode(target); code != "" {
			s.handoff.burn(code)
			w.Header().Set("Cache-Control", "no-store")
			http.Redirect(w, r, clean, http.StatusFound)
			return
		}
	}
	for k, v := range identityHeaders(sess.User) {
		w.Header().Set(k, v)
	}
	w.WriteHeader(http.StatusOK)
}

// The phone's native core signs each request it sends this machine (fromCore): when, and the signature.
const (
	edgeAtHeader    = "X-DGO-Edge-At"
	edgeNonceHeader = "X-DGO-Edge-Nonce" // one per request: two alike in one second are two, not a replay
	edgeSigHeader   = "X-DGO-Edge-Sig"
	edgeSkew        = 60 * time.Second // how far the core's clock and this one may be apart
)

// started is when this process began: a signature from before it cannot be one it has seen spent, so
// it is refused (the spent ones are remembered in memory alone).
var started = time.Now()

// edgeIdentity is the family a signature covers, in its order (EdgeSigned in the core's edge).
var edgeIdentity = []string{"X-authentik-username", "X-authentik-groups", "X-authentik-email", "X-authentik-name", "X-authentik-uid"}

// fromCore is a request the phone's native core sent (DGO-1090, ai/context/research/android-path.md
// "the machine on demand"): this forward-auth is the machine's, behind the core, whose edge has asked the
// core's own forward-auth already and writes the identity it answered — and signs that request with the
// token this machine was given at its boot, outside its network: HMAC-SHA256(token, when, method, host,
// URI, identity), the method, host and URI as the machine's edge saw the request (X-Forwarded-*). The
// token never travels: what an app behind this edge may log is a signature of that one request, which
// cannot be made to say anything else, is good within a minute of its time, and once (seen). Without a
// good one (another app on the phone that reached the forwarded port), nothing of the request's identity
// is taken, and a request that names nobody is not a sign-in.
func (s *server) fromCore(r *http.Request) (map[string]string, bool) {
	if len(s.edgeToken) == 0 {
		return nil, false
	}
	at, err := strconv.ParseInt(r.Header.Get(edgeAtHeader), 10, 64)
	if err != nil {
		return nil, false
	}
	if d := time.Since(time.Unix(at, 0)); d > edgeSkew || d < -edgeSkew || at < started.Unix() {
		return nil, false
	}
	nonce := r.Header.Get(edgeNonceHeader)
	if len(nonce) < 16 {
		return nil, false
	}
	ids := map[string]string{}
	parts := []string{strconv.FormatInt(at, 10), nonce, r.Header.Get("X-Forwarded-Method"), r.Header.Get("X-Forwarded-Host"), r.Header.Get("X-Forwarded-Uri")}
	for _, k := range edgeIdentity {
		ids[k] = r.Header.Get(k)
		parts = append(parts, ids[k])
	}
	mac := hmac.New(sha256.New, s.edgeToken)
	mac.Write([]byte(strings.Join(parts, "\n")))
	sig := r.Header.Get(edgeSigHeader)
	if !hmac.Equal([]byte(sig), []byte(hex.EncodeToString(mac.Sum(nil)))) || ids["X-authentik-username"] == "" {
		return nil, false
	}
	if !s.edgeSeen.first(sig, time.Unix(at, 0).Add(edgeSkew)) {
		return nil, false // a signature already spent: a replay
	}
	return ids, true
}

// seenSigs remembers the signatures spent, each until it could no longer be good.
type seenSigs struct {
	mu   sync.Mutex
	till map[string]time.Time
}

// first is true the first time sig is spent; it forgets what has expired as it goes.
func (s *seenSigs) first(sig string, until time.Time) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now()
	if s.till == nil {
		s.till = map[string]time.Time{}
	}
	for k, t := range s.till {
		if now.After(t) {
			delete(s.till, k)
		}
	}
	if _, spent := s.till[sig]; spent {
		return false
	}
	s.till[sig] = until
	return true
}

// edgeProof is /edge-proof?nonce=<n>: that this machine was given the core's token, said without saying
// it — HMAC-SHA256(token, nonce) in hex. The core's edge asks it before it sends a machine anything (the
// identity, the token): whatever else holds the loopback port the machine's edge is forwarded to cannot
// answer it. 404 where no token was given.
func (s *server) edgeProof(w http.ResponseWriter, r *http.Request) {
	nonce := r.URL.Query().Get("nonce")
	if len(s.edgeToken) == 0 || len(nonce) < 16 || len(nonce) > 128 {
		http.NotFound(w, r)
		return
	}
	mac := hmac.New(sha256.New, s.edgeToken)
	mac.Write([]byte(nonce))
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = io.WriteString(w, hex.EncodeToString(mac.Sum(nil)))
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
	// a code that did not redeem (stale, used, another host's) does not ride along to the next round
	target, _ = takeCode(target)
	// This host's state for the round trip (handoff.go): the browser's own cookie if it has a live
	// one (two tabs signing in at once share it), otherwise a new one. Only its hash leaves the host.
	token := ""
	if c, err := r.Cookie(s.stateCookie()); err == nil && len(c.Value) >= 16 && len(c.Value) <= 64 {
		token = c.Value
	} else {
		token = randomToken(18)
		http.SetCookie(w, &http.Cookie{Name: s.stateCookie(), Value: token, Path: "/", MaxAge: int(stateTTL / time.Second),
			HttpOnly: true, Secure: s.secureCookie, SameSite: http.SameSiteLaxMode})
	}
	http.Redirect(w, r, s.external+"/login?rd="+url.QueryEscape(target)+"&"+stateParam+"="+stateHash(token), http.StatusFound)
}

// redeemCode is the app-host half of the hand-off (handoff.go): a request with no session but with
// a good `dgo_code` for ITS host is answered 302 to the same URL without the code, carrying this
// host's own session cookie. False — nothing written — when there is no code or it does not redeem;
// the caller then challenges as for any anonymous request.
func (s *server) redeemCode(w http.ResponseWriter, r *http.Request) bool {
	target, ok := s.returnTo(r)
	if !ok {
		return false
	}
	clean, code := takeCode(target)
	if code == "" {
		return false
	}
	u, err := url.Parse(clean)
	if err != nil {
		return false
	}
	token := ""
	if c, err := r.Cookie(s.stateCookie()); err == nil {
		token = c.Value
	}
	name, minted, ok := s.handoff.redeemAt(code, u.Hostname(), token, time.Now())
	if !ok {
		return false
	}
	// minted before this person signed out: it would mint a session the sign-out meant to end
	if nb := s.sign.revokedBefore(name); !nb.IsZero() && minted.Before(nb) {
		return false
	}
	if _, ok := s.store().byName[name]; !ok {
		return false // removed from the users file since the code was minted
	}
	// host-only (no Domain): it is THIS host's cookie, which is the whole point on `.localhost`
	s.sign.set(w, name, s.secureCookie, "")
	// the round trip is over: its state goes with it
	http.SetCookie(w, &http.Cookie{Name: s.stateCookie(), Value: "", Path: "/", MaxAge: -1,
		HttpOnly: true, Secure: s.secureCookie, SameSite: http.SameSiteLaxMode})
	log.Printf("forward-auth: hand-off user=%q host=%s", name, u.Hostname())
	w.Header().Set("Cache-Control", "no-store")
	http.Redirect(w, r, clean, http.StatusFound)
	return true
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
		port := ""
		if h, p, err := net.SplitHostPort(host); err == nil {
			host, port = h, p
		}
		// The edge's port stays in the return-to: the phone's and the Mac's edge is :8080, and a
		// return-to without it lands on :80, where nothing answers. Digits only — anything else
		// after the colon is how `console.localhost:@evil.example` would become a URL whose HOST is
		// evil.example.
		if !digitsOnly(port) {
			continue
		}
		if s.allowedHost(host) {
			if port != "" {
				host = net.JoinHostPort(host, port)
			}
			return proto + "://" + host + uri, true
		}
	}
	return "", false
}

// digitsOnly is a port as a URL may carry one: empty, or 1–5 ASCII digits.
func digitsOnly(port string) bool {
	if len(port) > 5 {
		return false
	}
	for _, c := range port {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
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
<input type="hidden" name="st" value="{{.State}}">
<p><label>שם משתמש <input name="user" autocomplete="username" autofocus required></label></p>
<p><label>סיסמה <input type="password" name="password" autocomplete="current-password" required></label></p>
<p><button type="submit">כניסה</button></p>
</form>
</main></body></html>
`))

// loginForm carries nothing but the return-to, the app host's state hash (handoff.go) and, on a
// retry, one sentence.
type loginForm struct {
	ReturnTo string
	State    string
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
		// An office with no owner yet has nobody to sign in: the setup page says how to get one.
		if s.firstRun != nil && s.firstRun.pending() {
			http.Redirect(w, r, "/setup?rd="+url.QueryEscape(rd), http.StatusFound)
			return
		}
		st := r.URL.Query().Get(stateParam)
		if !okState(st) {
			st = ""
		}
		// Already signed in on this (the auth) host, and sent here by another app host: nothing to
		// ask — back to it at once, with a code for it (F1). Without a return-to there is nowhere to
		// send a code, and the form is shown as before.
		if rd != "" {
			if sess, err := s.session(r); err == nil {
				s.sendBack(w, r, sess.User.Name, rd, st)
				return
			}
		}
		s.renderLogin(w, http.StatusOK, loginForm{ReturnTo: rd, State: st})
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
	st := r.PostFormValue(stateParam)
	if !okState(st) {
		st = ""
	}
	name := r.PostFormValue("user")
	now := time.Now()
	keys := limitKeys(name, r)
	// Reserved BEFORE the password is checked: a blocked key is refused with the right password too,
	// and parallel attempts count while they run (F2).
	if left := s.limit.begin(now, keys...); left > 0 {
		secs := int(left/time.Second) + 1
		log.Printf("forward-auth: sign-in refused, %d s of a block left: user=%q ip=%q", secs, s.logName(name), clientIP(r))
		w.Header().Set("Retry-After", strconv.Itoa(secs))
		s.renderLogin(w, http.StatusTooManyRequests, loginForm{ReturnTo: rd, State: st,
			Error: "יותר מדי ניסיונות כניסה. נסו שוב בעוד " + strconv.Itoa(secs) + " שניות."})
		return
	}
	// settled whatever happens next — a reservation left behind by a panic would never be forgotten
	var u *user
	ok := false
	defer func() { s.limit.end(time.Now(), ok, keys...) }()
	u, ok = s.store().verify(name, r.PostFormValue("password"))
	if !ok {
		// one line per failure: the name and the address, never the password (F5)
		log.Printf("forward-auth: sign-in failed: user=%q ip=%q", s.logName(name), clientIP(r))
		// ONE sentence for a wrong name and for a wrong password. Naming which one was wrong turns
		// the form into a username oracle for anyone who can reach it.
		s.renderLogin(w, http.StatusUnauthorized, loginForm{ReturnTo: rd, State: st, Error: "שם המשתמש או הסיסמה שגויים."})
		return
	}
	log.Printf("forward-auth: signed in: user=%q ip=%q", u.Name, clientIP(r))
	s.sign.set(w, u.Name, s.secureCookie, s.cookieDomain)
	if rd == "" {
		rd = s.external + "/"
	}
	s.sendBack(w, r, u.Name, rd, st)
}

// logName is a typed name as the log may carry it: the name of a user this office has, or a mark.
// A name that is not a user is often a password typed into the wrong field, and a log is not where a
// password goes.
func (s *server) logName(name string) string {
	if _, ok := s.store().byName[name]; ok {
		return name
	}
	return "(not a user here)"
}

// sendBack returns a signed-in browser to rd (F1). 303, so the browser re-requests the destination as
// a GET: a POST that is answered with the app's page is what puts "confirm resubmission" dialogs in the
// way of a normal sign-in. A code rides along only for an app host that started the round trip (st,
// its state hash) and only when that host is not this one — the auth host holds its own cookie, and a
// code nobody will redeem is one more live code in an address bar. Without a code the app host simply
// challenges again, sets its state, and comes back here, where the browser is now signed in.
func (s *server) sendBack(w http.ResponseWriter, r *http.Request, name, rd, st string) {
	if u, err := url.Parse(rd); err == nil && u.Hostname() != "" && st != "" && !s.isAuthHost(u.Hostname()) {
		rd = withCode(rd, s.handoff.mint(name, u.Hostname(), st, time.Now()))
	}
	w.Header().Set("Cache-Control", "no-store")
	http.Redirect(w, r, rd, http.StatusSeeOther)
}

// isAuthHost answers whether host is this service's own.
func (s *server) isAuthHost(host string) bool {
	u, err := url.Parse(s.external)
	return err == nil && strings.EqualFold(u.Hostname(), host)
}

// logout ends this browser's session. It clears OUR cookie only — it cannot reach a session that
// an app keeps for itself (Plane, n8n and Supabase all have their own). Said here because the
// alternative is discovering it later and calling it a bug. With the per-host hand-off (F1) each app
// host holds its own cookie, which this request cannot clear — so signing out also refuses, from now
// on, every session of this person minted before now (session.go, revoke): one sign-out ends them on
// every host.
//
// A POST, from the page a GET shows (the third reader): signing out now ends a person's sessions on
// every device, and a GET that did it would let any other site do it with a link. A browser does not
// send the Lax session cookie with another site's POST, so such a POST finds nobody to sign out — and
// then changes nothing.
func (s *server) logout(w http.ResponseWriter, r *http.Request) {
	rd := r.FormValue("rd")
	if !s.okReturnTo(rd) {
		rd = s.external + "/"
	}
	switch r.Method {
	case http.MethodGet, http.MethodHead:
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Cache-Control", "no-store")
		_ = logoutPage.Execute(w, rd)
	case http.MethodPost:
		sess, err := s.session(r)
		if err == nil {
			s.sign.revoke(sess.User.Name, time.Now())
			s.sign.clear(w, s.secureCookie, s.cookieDomain)
			log.Printf("forward-auth: signed out: user=%q ip=%q", sess.User.Name, clientIP(r))
		}
		http.Redirect(w, r, rd, http.StatusSeeOther)
	default:
		w.Header().Set("Allow", "GET, HEAD, POST")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

var logoutPage = template.Must(template.New("logout").Parse(`<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>יציאה</title></head><body>
<main>
<h1>יציאה מהלשכה</h1>
<p>היציאה מסיימת את הכניסה בכל המכשירים.</p>
<form method="post" action="/logout">
<input type="hidden" name="rd" value="{{.}}">
<p><button type="submit" autofocus>יציאה</button></p>
</form>
</main></body></html>
`))

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
	m.HandleFunc("/edge-proof", s.edgeProof) // the phone's machine, to its native core (fromCore)
	m.HandleFunc("/healthz", s.healthz)
	m.HandleFunc("/whoami", s.whoami)
	m.HandleFunc("/login", s.login)
	m.HandleFunc("/setup", s.setupHandler)
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

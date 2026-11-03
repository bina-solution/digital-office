package main

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"
	"time"
)

// The review's findings F1–F4 (.claude/needs-azaria.md §2), each with the test the work order names.

// edge stands in for traefik v3: the auth host is this service's own routes; any other host is asked
// about at /auth/traefik first, and gets the app only on a 2xx — otherwise the auth answer verbatim,
// Set-Cookie and Location included. forms counts the sign-in pages it rendered.
func edge(s *server, forms *int) http.Handler {
	routes := s.routes()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host == "auth.localhost" || strings.HasPrefix(r.Host, "auth.localhost:") {
			if r.Method == http.MethodGet && r.URL.Path == "/login" {
				rec := httptest.NewRecorder()
				routes.ServeHTTP(rec, r)
				if rec.Code == http.StatusOK {
					*forms++
				}
				copyResponse(w, rec)
				return
			}
			routes.ServeHTTP(w, r)
			return
		}
		fr := httptest.NewRequest(r.Method, "http://forward-auth/auth/traefik", nil)
		fr.Header.Set("X-Forwarded-Host", r.Host)
		fr.Header.Set("X-Forwarded-Uri", r.URL.RequestURI())
		fr.Header.Set("X-Forwarded-Proto", "http")
		for _, c := range r.Cookies() {
			fr.AddCookie(c)
		}
		rec := httptest.NewRecorder()
		s.forwardAuth(rec, fr)
		if rec.Code/100 == 2 {
			_, _ = io.WriteString(w, "app for "+rec.Header().Get("X-authentik-username"))
			return
		}
		copyResponse(w, rec)
	})
}

func copyResponse(w http.ResponseWriter, rec *httptest.ResponseRecorder) {
	for k, vs := range rec.Header() {
		for _, v := range vs {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(rec.Code)
	_, _ = w.Write(rec.Body.Bytes())
}

// browser is a client whose cookie jar scopes by host, as a browser does, and that reaches the edge
// for every host name.
func browser(t *testing.T, h http.Handler) *http.Client {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	addr := srv.Listener.Addr().String()
	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	return &http.Client{Jar: jar, Transport: &http.Transport{
		DialContext: func(ctx context.Context, network, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, network, addr)
		},
	}}
}

func bodyOf(t *testing.T, res *http.Response) string {
	t.Helper()
	defer res.Body.Close()
	b, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

var stateRE = regexp.MustCompile(`name="st" value="([0-9a-f]{64})"`)

// F1's acceptance: sign in once at console.localhost, open a second gated host — no prompt. Every
// cookie here is host-only, so nothing reaches a host unless that host itself was given it. On an
// :80 edge and on the phone's and the Mac's :8080 one, where the port must survive every hop.
func TestSecondHostSignsInWithoutAPrompt(t *testing.T) {
	for _, port := range []string{"", ":8080"} {
		t.Run("edge"+port, func(t *testing.T) {
			s := testServer(t)
			s.external = "http://auth.localhost" + port
			forms := 0
			c := browser(t, edge(s, &forms))
			console := "http://console.localhost" + port + "/apps?x=1"

			res, err := c.Get(console)
			if err != nil {
				t.Fatal(err)
			}
			body := bodyOf(t, res)
			if forms != 1 || !strings.Contains(body, `name="password"`) {
				t.Fatalf("an anonymous visit did not end on the sign-in page (forms=%d): %q", forms, body)
			}
			// the form carries the app host's state hash, and the browser posts it back as it is
			st := stateRE.FindStringSubmatch(body)
			if st == nil {
				t.Fatalf("the sign-in form carries no state: %q", body)
			}

			res, err = c.PostForm(s.external+"/login", url.Values{
				"user": {"owner"}, "password": {testPassword}, "rd": {console}, "st": {st[1]}})
			if err != nil {
				t.Fatal(err)
			}
			if body := bodyOf(t, res); body != "app for owner" || res.Request.URL.String() != console {
				t.Fatalf("after signing in: %s answered %q, want the app at %s", res.Request.URL, body, console)
			}

			res, err = c.Get("http://other.localhost" + port + "/")
			if err != nil {
				t.Fatal(err)
			}
			if body := bodyOf(t, res); body != "app for owner" || forms != 1 {
				t.Fatalf("the second host: %q after %d sign-in page(s), want the app and no second prompt", body, forms)
			}
			for _, host := range []string{"auth.localhost", "console.localhost", "other.localhost"} {
				found := false
				for _, ck := range c.Jar.Cookies(&url.URL{Scheme: "http", Host: host + port, Path: "/"}) {
					found = found || ck.Name == cookieName
				}
				if !found {
					t.Errorf("%s holds no %s of its own", host, cookieName)
				}
			}
		})
	}
}

// The return-to keeps the edge's port, and nothing but digits passes as one.
func TestReturnToKeepsTheEdgesPortAndOnlyAPort(t *testing.T) {
	s := testServer(t)
	w := httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "console.localhost:8080", "/apps", nil))
	loc, err := url.Parse(w.Header().Get("Location"))
	if w.Code != http.StatusFound || err != nil {
		t.Fatalf("status = %d, Location %q", w.Code, w.Header().Get("Location"))
	}
	if got := loc.Query().Get("rd"); got != "http://console.localhost:8080/apps" {
		t.Errorf("rd = %q, want the edge's port kept", got)
	}
	for _, host := range []string{"console.localhost:@evil.example", "console.localhost:80@evil.example", "console.localhost:123456"} {
		w := httptest.NewRecorder()
		s.forwardAuth(w, fwdReq("GET", host, "/", nil))
		if w.Code != http.StatusBadRequest {
			t.Errorf("host %q: status = %d, want 400", host, w.Code)
		}
	}
}

// A code is for ONE host, ONE browser (its state), ONE use, inside ONE minute, and is never a session
// cookie (nor the reverse).
func TestHandOffCodeIsOneHostOneBrowserOneUseOneMinute(t *testing.T) {
	h := newHandoff([]byte(testSecret))
	now := time.Now()
	const state = "the-browsers-own-state-token"
	st := stateHash(state)

	code := h.mint("owner", "console.localhost", st, now)
	if _, ok := h.redeem(code, "other.localhost", state, now); ok {
		t.Fatal("a code minted for console.localhost redeemed on other.localhost")
	}
	if _, ok := h.redeem(code, "console.localhost", "another-browsers-state-token", now); ok {
		t.Fatal("a code redeemed in a browser holding another state")
	}
	if _, ok := h.redeem(code, "console.localhost", "", now); ok {
		t.Fatal("a code redeemed in a browser holding no state")
	}
	if name, ok := h.redeem(code, "console.localhost", state, now); !ok || name != "owner" {
		t.Fatalf("a fresh code for its own host and browser = %q, %v; want owner, true", name, ok)
	}
	if _, ok := h.redeem(code, "console.localhost", state, now); ok {
		t.Fatal("a code redeemed twice")
	}
	late := h.mint("owner", "console.localhost", st, now)
	if _, ok := h.redeem(late, "console.localhost", state, now.Add(codeTTL)); ok {
		t.Fatal("a code redeemed after its minute")
	}
	burnt := h.mint("owner", "console.localhost", st, now)
	h.burn(burnt)
	if _, ok := h.redeem(burnt, "console.localhost", state, now); ok {
		t.Fatal("a burnt code redeemed")
	}
	tok, _ := (&signer{key: []byte(testSecret), ttl: time.Hour}).issue("owner", now)
	if _, ok := h.redeem(tok, "console.localhost", state, now); ok {
		t.Fatal("a session cookie was accepted as a code")
	}
	r := httptest.NewRequest("GET", "/", nil)
	r.AddCookie(&http.Cookie{Name: cookieName, Value: h.mint("owner", "console.localhost", st, now)})
	if _, err := (&signer{key: []byte(testSecret), ttl: time.Hour}).read(r, now, testServer(t).users); err == nil {
		t.Fatal("a code was accepted as a session cookie")
	}
}

// Login CSRF (the second reader): a user of this office mints a code for their OWN session and plants
// it in a victim's browser by a link. The victim's browser holds its own state — or none — and the
// code is refused: the victim meets the sign-in page, not the attacker's session.
func TestAPlantedCodeIsRefused(t *testing.T) {
	s := testServer(t)
	planted := s.handoff.mint("owner", "console.localhost", stateHash("the-attackers-state-token"), time.Now())
	for _, victim := range []*http.Cookie{nil, {Name: stateName, Value: "the-victims-own-state-token"}} {
		w := httptest.NewRecorder()
		s.forwardAuth(w, fwdReq("GET", "console.localhost", "/apps?"+codeParam+"="+planted, victim))
		loc := w.Header().Get("Location")
		if w.Code != http.StatusFound || !strings.HasPrefix(loc, "http://auth.localhost/login?") {
			t.Fatalf("a planted code (victim state %v) = %d to %q, want the sign-in page", victim, w.Code, loc)
		}
		for _, c := range w.Result().Cookies() {
			if c.Name == cookieName && c.MaxAge >= 0 {
				t.Fatalf("a planted code minted a session: %v", c)
			}
		}
	}
}

// A host that is signed in already spends a code it is handed and sends the browser to the clean URL:
// a live code never reaches the app.
func TestACodeIsSpentWhenTheHostIsSignedIn(t *testing.T) {
	s := testServer(t)
	const state = "the-browsers-own-state-token"
	code := s.handoff.mint("owner", "console.localhost", stateHash(state), time.Now())
	c := &http.Cookie{Name: cookieName}
	c.Value, _ = s.sign.issue("owner", time.Now())
	w := httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "console.localhost", "/apps?x=1&"+codeParam+"="+code, c))
	if w.Code != http.StatusFound || w.Header().Get("Location") != "http://console.localhost/apps?x=1" {
		t.Fatalf("= %d to %q, want 302 to the clean URL", w.Code, w.Header().Get("Location"))
	}
	if _, ok := s.handoff.redeem(code, "console.localhost", state, time.Now()); ok {
		t.Fatal("the code still redeems after the signed-in host spent it")
	}
}

// Signing out on the auth host ends the person's sessions on every host — each holds its own cookie,
// which that one response cannot clear.
func TestSignOutEndsEveryHost(t *testing.T) {
	s := testServer(t)
	before := time.Now().Add(-2 * time.Second)
	authCookie := &http.Cookie{Name: cookieName}
	authCookie.Value, _ = s.sign.issue("owner", before)
	appCookie := &http.Cookie{Name: cookieName}
	appCookie.Value, _ = s.sign.issue("owner", before)

	// a GET only asks; it ends nothing
	r := httptest.NewRequest("GET", "/logout", nil)
	r.AddCookie(authCookie)
	s.logout(httptest.NewRecorder(), r)
	w := httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "console.localhost", "/", appCookie))
	if w.Code != http.StatusOK {
		t.Fatalf("a GET of /logout ended a session (%d): any other site could do it with a link", w.Code)
	}

	r = httptest.NewRequest("POST", "/logout", nil)
	r.AddCookie(authCookie)
	s.logout(httptest.NewRecorder(), r)

	w = httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "console.localhost", "/", appCookie))
	if w.Code == http.StatusOK {
		t.Fatal("an app host's session from before the sign-out still answers 200")
	}
	fresh := &http.Cookie{Name: cookieName}
	fresh.Value, _ = s.sign.issue("owner", time.Now().Add(2*time.Second))
	w = httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "console.localhost", "/", fresh))
	if w.Code != http.StatusOK {
		t.Fatalf("a session minted after the sign-out = %d, want 200", w.Code)
	}
}

// The code leaves the app's own query exactly as it was, and a stale one does not survive.
func TestTakeCodeKeepsTheAppsQuery(t *testing.T) {
	for in, want := range map[string][2]string{
		"/a?x=1&dgo_code=C&y=2":        {"/a?x=1&y=2", "C"},
		"/a?dgo_code=C":                {"/a", "C"},
		"/a?dgo_code=OLD&dgo_code=NEW": {"/a", "NEW"},
		"/a?x=1":                       {"/a?x=1", ""},
		"/a":                           {"/a", ""},
	} {
		if clean, code := takeCode(in); clean != want[0] || code != want[1] {
			t.Errorf("takeCode(%q) = %q, %q; want %q, %q", in, clean, code, want[0], want[1])
		}
	}
	if got := withCode("http://console.localhost/apps?x=1", "C"); got != "http://console.localhost/apps?x=1&dgo_code=C" {
		t.Errorf("withCode = %q", got)
	}
}

// F2's test: the sixth attempt inside a minute is 429, even with the right password, and mints nothing.
func TestSixthAttemptInAMinuteIs429EvenWithTheRightPassword(t *testing.T) {
	s := testServer(t)
	post := func(password string) *httptest.ResponseRecorder {
		form := url.Values{"user": {"owner"}, "password": {password}, "rd": {"http://console.localhost/"}}
		r := httptest.NewRequest("POST", "/login", strings.NewReader(form.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		r.Header.Set("X-Forwarded-For", "203.0.113.7")
		w := httptest.NewRecorder()
		s.login(w, r)
		return w
	}
	for i := 1; i <= limitFails; i++ {
		if w := post("not the password"); w.Code != http.StatusUnauthorized {
			t.Fatalf("wrong attempt %d = %d, want 401", i, w.Code)
		}
	}
	w := post(testPassword)
	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("the sixth attempt = %d, want 429", w.Code)
	}
	if n, err := strconv.Atoi(w.Header().Get("Retry-After")); err != nil || n < 1 || n > 61 {
		t.Errorf("Retry-After = %q, want the seconds left of a one-minute block", w.Header().Get("Retry-After"))
	}
	if sc := w.Header().Values("Set-Cookie"); len(sc) != 0 {
		t.Fatalf("a blocked attempt set a cookie: %v", sc)
	}
}

// …and each later block doubles, and stays at an hour — the first failure after a block does not
// reset the key (the second reader); a right password ends the count.
func TestBlocksDoubleUpToAnHour(t *testing.T) {
	l := newLimiter()
	now := time.Now()
	want := limitFirst
	for round := 0; round < 10; round++ {
		for i := 0; i < limitFails; i++ {
			if left := l.begin(now, "k"); left != 0 {
				t.Fatalf("round %d, attempt %d refused for %s", round+1, i+1, left)
			}
			l.end(now, false, "k")
		}
		if got := l.begin(now, "k"); got != want {
			t.Fatalf("block %d = %s, want %s", round+1, got, want)
		}
		now = now.Add(want + time.Second)
		if want *= 2; want > limitMax {
			want = limitMax
		}
	}
	if left := l.begin(now, "k"); left != 0 {
		t.Fatalf("after the last block: refused for %s", left)
	}
	l.end(now, true, "k")
	if left := l.begin(now, "k"); left != 0 {
		t.Fatalf("after a success: refused for %s", left)
	}
	l.end(now, false, "k")
	if got := l.begin(now, "k"); got != 0 {
		t.Fatalf("one failure after a success blocked for %s", got)
	}
}

// Attempts count while they run: six at once cannot all slip in under one window's five.
func TestParallelAttemptsCannotExceedTheWindow(t *testing.T) {
	l := newLimiter()
	now := time.Now()
	for i := 0; i < limitFails; i++ {
		if left := l.begin(now, "k"); left != 0 {
			t.Fatalf("attempt %d of %d refused", i+1, limitFails)
		}
	}
	if left := l.begin(now, "k"); left == 0 {
		t.Fatal("a sixth attempt went ahead while five were still running")
	}
}

// A stranger cannot lock the owner out: failures from one address do not block the owner's name at
// another.
func TestAStrangerCannotLockTheOwnerOut(t *testing.T) {
	s := testServer(t)
	post := func(ip, password string) int {
		form := url.Values{"user": {"owner"}, "password": {password}}
		r := httptest.NewRequest("POST", "/login", strings.NewReader(form.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		r.Header.Set("X-Forwarded-For", ip)
		w := httptest.NewRecorder()
		s.login(w, r)
		return w.Code
	}
	for i := 0; i <= limitFails; i++ {
		post("198.51.100.9", "not the password")
	}
	if code := post("203.0.113.7", testPassword); code != http.StatusSeeOther {
		t.Fatalf("the owner from his own address = %d, want 303", code)
	}
}

// F4: a changed users file is read again — a new line signs in without a restart, and a bad write
// leaves the last good file answering.
func TestUsersFileIsReReadWhenItChanges(t *testing.T) {
	hash, err := hashPassword(testPassword)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "users")
	owner := "owner owner@localhost Owner 1 - " + hash + "\n"
	if err := os.WriteFile(path, []byte(owner), 0o600); err != nil {
		t.Fatal(err)
	}
	l, err := newLiveUsers(path, false)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	if _, ok := l.get(now).byName["second"]; ok {
		t.Fatal("a user that is not in the file")
	}
	if err := os.WriteFile(path, []byte(owner+"second second@localhost Second 2 - "+hash+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, ok := l.get(now.Add(2*time.Second)).verify("second", testPassword); !ok {
		t.Fatal("a line added to the file does not sign in")
	}
	if err := os.WriteFile(path, []byte("not a users line\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if st := l.get(now.Add(4 * time.Second)); len(st.byName) != 2 {
		t.Fatalf("a malformed write left %d user(s), want the last good 2", len(st.byName))
	}
}

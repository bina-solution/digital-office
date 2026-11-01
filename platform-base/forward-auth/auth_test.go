package main

import (
	"encoding/base64"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

// b64 is the one encoding the users file uses, spelled once for the test that hand-writes a hash.
func b64(b []byte) string { return base64.RawStdEncoding.EncodeToString(b) }

// The five tests the owner asked for, in the order a browser meets them, plus three that cover the
// decisions the code makes on its own (the host allowlist, and refusing to start without a secret).
// Every one of them goes through the real handler and the real hashing — nothing here is stubbed,
// because the things most likely to break are the cookie and the cost of the password check.

const (
	testPassword = "correct horse battery staple"
	testSecret   = "0123456789abcdef0123456789abcdef"
)

func testServer(t *testing.T) *server {
	t.Helper()
	hash, err := hashPassword(testPassword)
	if err != nil {
		t.Fatalf("hashPassword: %v", err)
	}
	u := &user{Name: "owner", Email: "owner@localhost", Display: "הבעלים", UID: "1",
		Groups: []string{"admins", "incoming-docs-admin"}, hash: hash}
	return &server{
		users:        &userStore{byName: map[string]*user{"owner": u}},
		sign:         &signer{key: []byte(testSecret), ttl: time.Hour},
		external:     "http://auth.localhost",
		suffixes:     []string{".localhost"},
		secureCookie: false,
	}
}

// fwdReq builds what traefik's forwardAuth actually sends: the original method and path, plus the
// X-Forwarded-* headers. Nothing else about the original request matters to this service.
func fwdReq(method, host, uri string, cookie *http.Cookie) *http.Request {
	r := httptest.NewRequest("GET", "/auth/traefik", nil)
	r.Method = method
	r.Header.Set("X-Forwarded-Host", host)
	r.Header.Set("X-Forwarded-Uri", uri)
	r.Header.Set("X-Forwarded-Proto", "http")
	if cookie != nil {
		r.AddCookie(cookie)
	}
	return r
}

// 1. Nobody signed in → the browser is sent to the sign-in page, carrying where to come back to.
func TestAnonymousIsSentToSignIn(t *testing.T) {
	s := testServer(t)
	w := httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "console.localhost", "/apps?x=1", nil))

	if w.Code != http.StatusFound {
		t.Fatalf("status = %d, want 302 (traefik forwards anything non-2xx verbatim)", w.Code)
	}
	loc, err := url.Parse(w.Header().Get("Location"))
	if err != nil {
		t.Fatalf("Location is not a URL: %v", err)
	}
	if got, want := loc.Scheme+"://"+loc.Host+loc.Path, "http://auth.localhost/login"; got != want {
		t.Errorf("Location target = %q, want %q", got, want)
	}
	if got, want := loc.Query().Get("rd"), "http://console.localhost/apps?x=1"; got != want {
		t.Errorf("rd = %q, want %q", got, want)
	}
	for _, h := range []string{"X-authentik-username", "X-authentik-groups"} {
		if v := w.Header().Get(h); v != "" {
			t.Errorf("anonymous response carries %s: %q — traefik would copy it onto the app", h, v)
		}
	}
}

// 2. A wrong password is refused, and the refusal mints nothing.
func TestWrongPasswordIsRefused(t *testing.T) {
	s := testServer(t)
	form := url.Values{"user": {"owner"}, "password": {"not the password"}, "rd": {"http://console.localhost/"}}
	r := httptest.NewRequest("POST", "/login", strings.NewReader(form.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	s.login(w, r)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", w.Code)
	}
	if sc := w.Header().Values("Set-Cookie"); len(sc) != 0 {
		t.Fatalf("a refused sign-in set a cookie: %v", sc)
	}
	if body := w.Body.String(); !strings.Contains(body, "שגויים") {
		t.Errorf("the refusal is not shown on the page: %q", body)
	}
}

// …and an unknown name is refused exactly as a wrong password is, and says the same sentence.
func TestUnknownUserLooksLikeWrongPassword(t *testing.T) {
	s := testServer(t)
	form := url.Values{"user": {"someone-else"}, "password": {testPassword}}
	r := httptest.NewRequest("POST", "/login", strings.NewReader(form.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	s.login(w, r)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", w.Code)
	}
	if sc := w.Header().Values("Set-Cookie"); len(sc) != 0 {
		t.Fatalf("an unknown user minted a cookie: %v", sc)
	}
}

//  3. The right password mints a cookie, and that cookie makes forward-auth answer with the identity
//     headers — the whole point of the service.
func TestRightPasswordYieldsCookieAndIdentityHeaders(t *testing.T) {
	s := testServer(t)
	form := url.Values{"user": {"owner"}, "password": {testPassword}, "rd": {"http://console.localhost/apps"}}
	r := httptest.NewRequest("POST", "/login", strings.NewReader(form.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	s.login(w, r)

	if w.Code != http.StatusSeeOther {
		t.Fatalf("status = %d, want 303 (the browser must re-request the destination as a GET)", w.Code)
	}
	if got := w.Header().Get("Location"); got != "http://console.localhost/apps" {
		t.Fatalf("Location = %q, want the return-to", got)
	}
	res := w.Result()
	cookies := res.Cookies()
	if len(cookies) != 1 || cookies[0].Name != cookieName {
		t.Fatalf("cookies = %v, want exactly one %s", cookies, cookieName)
	}
	c := cookies[0]
	if !c.HttpOnly || c.SameSite != http.SameSiteLaxMode || c.Path != "/" || c.Secure {
		t.Errorf("cookie flags are wrong for an http edge: %+v", c)
	}

	w2 := httptest.NewRecorder()
	s.forwardAuth(w2, fwdReq("GET", "console.localhost", "/apps", c))
	if w2.Code != http.StatusOK {
		t.Fatalf("forward-auth with a valid session = %d, want 200", w2.Code)
	}
	for h, want := range map[string]string{
		"X-authentik-username": "owner",
		"X-authentik-email":    "owner@localhost",
		"X-authentik-name":     "הבעלים",
		"X-authentik-uid":      "1",
		// '|' is the separator console/app.py:83 and indox split on; ',' would arrive as one group.
		"X-authentik-groups": "admins|incoming-docs-admin",
	} {
		if got := w2.Header().Get(h); got != want {
			t.Errorf("%s = %q, want %q", h, got, want)
		}
	}
}

// The cookie must survive a POST too: traefik forwards every method, not just GET.
func TestSessionAlsoAnswersAPost(t *testing.T) {
	s := testServer(t)
	c := &http.Cookie{Name: cookieName}
	c.Value, _ = s.sign.issue("owner", time.Now())

	w := httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("POST", "console.localhost", "/api/thing", c))
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 — a gate that only guards GET is not a gate", w.Code)
	}
}

// 4. A tampered cookie is refused exactly like no cookie at all.
func TestTamperedCookieIsRefused(t *testing.T) {
	s := testServer(t)
	good, _ := s.sign.issue("owner", time.Now())

	flip := func(v string) string {
		i := strings.IndexByte(v, '.') + 1 // stay inside the signature
		b := []byte(v)
		if b[i] == 'A' {
			b[i] = 'B'
		} else {
			b[i] = 'A'
		}
		return string(b)
	}
	// The interesting forgery is not a corrupted byte — it is a VALID signature over a name the
	// attacker chose, which only a different key can produce. Both are covered.
	other := &signer{key: []byte("ffffffffffffffffffffffffffffffff"), ttl: time.Hour}
	foreign, _ := other.issue("owner", time.Now())

	for name, value := range map[string]string{
		"tampered signature": flip(good),
		"signed elsewhere":   foreign,
		"no dot at all":      strings.ReplaceAll(good, ".", ""),
		"empty":              "",
	} {
		w := httptest.NewRecorder()
		s.forwardAuth(w, fwdReq("GET", "console.localhost", "/", &http.Cookie{Name: cookieName, Value: value}))
		if w.Code != http.StatusFound {
			t.Errorf("%s: status = %d, want 302 (refused, not served)", name, w.Code)
		}
		if v := w.Header().Get("X-authentik-username"); v != "" {
			t.Errorf("%s: served identity %q", name, v)
		}
	}
}

// An expired cookie is refused, even though its signature is perfectly good.
func TestExpiredCookieIsRefused(t *testing.T) {
	s := testServer(t)
	c := &http.Cookie{Name: cookieName}
	c.Value, _ = s.sign.issue("owner", time.Now().Add(-2*time.Hour))

	w := httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "console.localhost", "/", c))
	if w.Code != http.StatusFound {
		t.Fatalf("status = %d, want 302 — an expired session is not a session", w.Code)
	}
}

// A session whose account was deleted from the users file stops working at once, not at the end of
// its TTL. This is the whole reason the store is consulted on every request.
func TestSessionForARemovedUserIsRefused(t *testing.T) {
	s := testServer(t)
	c := &http.Cookie{Name: cookieName}
	c.Value, _ = s.sign.issue("owner", time.Now())
	delete(s.users.byName, "owner")

	w := httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "console.localhost", "/", c))
	if w.Code != http.StatusFound {
		t.Fatalf("status = %d, want 302", w.Code)
	}
}

//  5. A host this office does not serve is REFUSED, not redirected to. An unvalidated return-to
//     built from X-Forwarded-Host is an open redirect — and this estate sets trustForwardHeader:true,
//     so that header is client-influenced.
func TestForeignHostIsRefusedRatherThanRedirectedTo(t *testing.T) {
	s := testServer(t)

	// `localhost` is the interesting one: it is not `*.localhost`, so the dotted allowlist entry
	// must NOT cover it. This test is why the two spellings of an allowlist entry exist.
	for _, host := range []string{"evil.example", "console.localhost.evil.example", "localhost"} {
		w := httptest.NewRecorder()
		s.forwardAuth(w, fwdReq("GET", host, "/", nil))
		if w.Code != http.StatusBadRequest {
			t.Errorf("host %q: status = %d, want 400 (there is nothing safe to redirect to)", host, w.Code)
		}
		if loc := w.Header().Get("Location"); loc != "" {
			t.Errorf("host %q: redirected to %q", host, loc)
		}
	}

	// A client-supplied X-Forwarded-Host cannot smuggle a target past the allowlist by being first.
	r := fwdReq("GET", "console.localhost", "/", nil)
	r.Header.Set("X-Forwarded-Host", "evil.example, console.localhost")
	w := httptest.NewRecorder()
	s.forwardAuth(w, r)
	if w.Code != http.StatusFound {
		t.Fatalf("status = %d, want 302 for the office's own host", w.Code)
	}
	if loc := w.Header().Get("Location"); strings.Contains(loc, "evil.example") {
		t.Errorf("Location %q carries a foreign host", loc)
	}

	// …and an entry written without a dot means that EXACT host, so the operator can name an apex
	// deliberately when a deployment really does serve one.
	exact := testServer(t)
	exact.suffixes = []string{"localhost", ".localhost"}
	for host, want := range map[string]int{
		"localhost":         http.StatusFound,
		"console.localhost": http.StatusFound,
		"other.localhost":   http.StatusFound,
		"localhost.evil":    http.StatusBadRequest,
	} {
		w := httptest.NewRecorder()
		exact.forwardAuth(w, fwdReq("GET", host, "/", nil))
		if w.Code != want {
			t.Errorf("host %q: status = %d, want %d", host, w.Code, want)
		}
	}
}

// The `rd` on the sign-in page and the `rd` in the form are both DATA, and both are checked.
func TestReturnToOutsideTheOfficeIsDropped(t *testing.T) {
	s := testServer(t)

	w := httptest.NewRecorder()
	s.login(w, httptest.NewRequest("GET", "/login?rd="+url.QueryEscape("http://evil.example/steal"), nil))
	if body := w.Body.String(); strings.Contains(body, "evil.example") {
		t.Errorf("the sign-in page carries a foreign return-to: %q", body)
	}

	form := url.Values{"user": {"owner"}, "password": {testPassword}, "rd": {"http://evil.example/steal"}}
	r := httptest.NewRequest("POST", "/login", strings.NewReader(form.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w2 := httptest.NewRecorder()
	s.login(w2, r)
	if loc := w2.Header().Get("Location"); strings.Contains(loc, "evil.example") {
		t.Errorf("sign-in redirected to a foreign host: %q", loc)
	}
}

// Protocol-relative paths are absolute URLs wearing a path's clothes.
func TestProtocolRelativePathIsNotAReturnTo(t *testing.T) {
	s := testServer(t)
	r := fwdReq("GET", "console.localhost", "//evil.example/x", nil)
	w := httptest.NewRecorder()
	s.forwardAuth(w, r)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", w.Code)
	}
}

// 6. The service refuses to start without a signing key, and refuses a short one.
func TestConfigRefusesToStartWithoutASecret(t *testing.T) {
	t.Setenv("FORWARD_AUTH_EXTERNAL_URL", "http://auth.localhost")
	t.Setenv("FORWARD_AUTH_ALLOWED_HOSTS", ".localhost")
	os.Unsetenv("FORWARD_AUTH_SECRET")
	if _, err := configFromEnv(); err == nil {
		t.Fatal("started with no FORWARD_AUTH_SECRET — an empty key signs a cookie naming anyone")
	}

	t.Setenv("FORWARD_AUTH_SECRET", "short")
	if _, err := configFromEnv(); err == nil {
		t.Fatal("started with a short FORWARD_AUTH_SECRET")
	}

	t.Setenv("FORWARD_AUTH_SECRET", testSecret)
	cfg, err := configFromEnv()
	if err != nil {
		t.Fatalf("a complete configuration was refused: %v", err)
	}
	if cfg.sessionTTL != defaultSession || cfg.listen != defaultListen {
		t.Errorf("defaults not applied: %+v", cfg)
	}
}

// 7. The users file: the format, the duplicate, and the two ways a line can be unusable.
func TestUsersFileParsing(t *testing.T) {
	dir := t.TempDir()
	good, _ := hashPassword(testPassword)
	path := dir + "/users"
	line := func(s string) {
		if err := os.WriteFile(path, []byte(s), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	line("# a comment\n\nowner owner@localhost הבעלים 1 admins,incoming-docs-admin " + good + "\n")
	st, err := loadUsers(path)
	if err != nil {
		t.Fatalf("a well-formed file was refused: %v", err)
	}
	u, ok := st.verify("owner", testPassword)
	if !ok {
		t.Fatal("the right password was refused")
	}
	if u.GroupHeader() != "admins|incoming-docs-admin" {
		t.Errorf("groups = %q", u.GroupHeader())
	}
	if _, ok := st.verify("owner", testPassword+"x"); ok {
		t.Error("a wrong password was accepted")
	}

	line("owner owner@localhost הבעלים 1 - " + good + "\nowner o@l O 2 - " + good + "\n")
	if _, err := loadUsers(path); err == nil {
		t.Error("a duplicate user was accepted")
	}

	line("owner owner@localhost הבעלים 1 -\n") // no hash field
	if _, err := loadUsers(path); err == nil {
		t.Error("a five-field line was accepted")
	}

	line("owner owner@localhost הבעלים 1 - not-a-hash\n")
	if _, err := loadUsers(path); err == nil {
		t.Error("an unparseable hash was accepted")
	}

	line("# nobody\n")
	if _, err := loadUsers(path); err == nil {
		t.Error("an empty store was accepted — it can only refuse, so it must not start")
	}
}

//  8. The hashing itself: the same password never hashes twice the same, the stored parameters are
//     honoured, and a hash written at a lower iteration count still verifies (so the count can be
//     raised without invalidating the credential plane's entries).
func TestPasswordHashRoundTrip(t *testing.T) {
	a, err := hashPassword(testPassword)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := hashPassword(testPassword)
	if a == b {
		t.Error("two hashes of one password are identical — the salt is not random")
	}
	for _, h := range []string{a, b} {
		ok, err := checkPassword(h, testPassword)
		if err != nil || !ok {
			t.Errorf("checkPassword(%q) = %v, %v", h, ok, err)
		}
		if ok, _ := checkPassword(h, testPassword+" "); ok {
			t.Errorf("checkPassword accepted a trailing space")
		}
	}

	// A hash written by a future, stronger build must still verify here.
	salt := []byte("0123456789abcdef")
	weak := "pbkdf2-sha256$1000$" + b64(salt) + "$" + b64(pbkdf2SHA256([]byte(testPassword), salt, 1000, keyLen))
	if ok, err := checkPassword(weak, testPassword); err != nil || !ok {
		t.Errorf("a hash with a different iteration count did not verify: %v, %v", ok, err)
	}

	if _, err := checkPassword("plaintext", testPassword); err == nil {
		t.Error("a hash that is not ours parsed")
	}
}

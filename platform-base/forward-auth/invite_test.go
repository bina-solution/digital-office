package main

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Invitations (invite.go, DGO-1751): the owner brings a person in; the person chooses their own password.

// inviteOffice is an office with its owner, a live users file on disk, and the invitations beside it.
func inviteOffice(t *testing.T) (*server, *invites, string) {
	t.Helper()
	dir := t.TempDir()
	usersFile := filepath.Join(dir, "users")
	hash, err := hashPassword(testPassword)
	if err != nil {
		t.Fatal(err)
	}
	owner := "# the owner's own note\nowner owner@localhost הבעלים 1 admins " + hash + "\n"
	if err := os.WriteFile(usersFile, []byte(owner), 0o600); err != nil {
		t.Fatal(err)
	}
	live, err := newLiveUsers(usersFile, false)
	if err != nil {
		t.Fatal(err)
	}
	iv := &invites{path: filepath.Join(dir, "invites"), usersFile: usersFile}
	s := testServer(t)
	s.live, s.users, s.invites = live, nil, iv
	return s, iv, usersFile
}

func mint(t *testing.T, iv *invites, line string, now time.Time) (string, int) {
	t.Helper()
	var out bytes.Buffer
	rc := mintInvite(iv, strings.NewReader(line+"\n"), &out, now)
	return strings.TrimSpace(out.String()), rc
}

func TestAnInvitationKeepsOnlyItsHashAndThePersonChoosesTheirPassword(t *testing.T) {
	s, iv, usersFile := inviteOffice(t)
	before, _ := os.ReadFile(usersFile)
	code, rc := mint(t, iv, "galit galit@example.com רות", time.Now())
	if rc != 0 || len(code) < 32 {
		t.Fatalf("-invite = %d, code %q; want 0 and a code of 32+ characters", rc, code)
	}
	raw, _ := os.ReadFile(iv.path)
	if strings.Contains(string(raw), code) || !strings.Contains(string(raw), codeHash(code)) {
		t.Fatal("the invitations file must hold the code's sha256, never the code")
	}
	if fi, _ := os.Stat(iv.path); fi.Mode().Perm() != 0o600 {
		t.Fatalf("the invitations file is %v, want 0600", fi.Mode().Perm())
	}

	get := func(target string) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, httptest.NewRequest("GET", target, nil))
		return w
	}
	post := func(v url.Values) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/invite", strings.NewReader(v.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, r)
		return w
	}
	const pw = "a passphrase long enough"

	for _, target := range []string{"/invite", "/invite?code=wrong"} {
		if w := get(target); w.Code != http.StatusOK || strings.Contains(w.Body.String(), `name="password"`) {
			t.Fatalf("%s = %d with a form; want the page that says the link is not valid", target, w.Code)
		}
	}
	w := get("/invite?code=" + url.QueryEscape(code))
	if !strings.Contains(w.Body.String(), `name="password"`) || !strings.Contains(w.Body.String(), "רות") {
		t.Fatal("the right code does not show the form with the person's name")
	}
	if w.Header().Get("Referrer-Policy") != "no-referrer" || w.Header().Get("X-Frame-Options") != "DENY" {
		t.Fatal("the page carrying the code must send no Referer and must not be framed")
	}
	if w := post(url.Values{"code": {"wrong"}, "password": {pw}, "again": {pw}}); w.Code != http.StatusForbidden {
		t.Fatalf("a wrong code = %d, want 403", w.Code)
	}
	if w := post(url.Values{"code": {code}, "password": {"short"}, "again": {"short"}}); w.Code != http.StatusBadRequest {
		t.Fatalf("a short password = %d, want 400", w.Code)
	}
	if w := post(url.Values{"code": {code}, "password": {pw}, "again": {pw + "x"}}); w.Code != http.StatusBadRequest {
		t.Fatalf("two different passwords = %d, want 400", w.Code)
	}
	// a user name sent in the form is ignored: the invitation names the person, not the browser
	w = post(url.Values{"code": {code}, "user": {"owner"}, "password": {pw}, "again": {pw}})
	if w.Code != http.StatusSeeOther {
		t.Fatalf("the right code and a good password = %d, want 303", w.Code)
	}
	var cookie *http.Cookie
	for _, c := range w.Result().Cookies() {
		if c.Value != "" {
			cookie = c
		}
	}
	if cookie == nil {
		t.Fatal("an accepted invitation must sign the person in")
	}
	who := httptest.NewRequest("GET", "/whoami", nil)
	who.AddCookie(cookie)
	ww := httptest.NewRecorder()
	s.routes().ServeHTTP(ww, who)
	if !strings.Contains(ww.Body.String(), `"username":"galit"`) {
		t.Fatalf("the cookie an invitation sets must name the invited person: /whoami = %d %s", ww.Code, ww.Body.String())
	}
	after, _ := os.ReadFile(usersFile)
	if !bytes.HasPrefix(after, before) {
		t.Fatal("the users file must keep every byte it had, the owner's note included")
	}
	st, err := loadUsers(usersFile)
	if err != nil {
		t.Fatalf("the users file does not load after an invitation: %v", err)
	}
	u, ok := st.byName["galit"]
	if !ok || u.Email != "galit@example.com" || u.Display != "רות" || strings.Join(u.Groups, ",") != peopleGroup {
		t.Fatalf("the invited person's line: %+v, want galit, her email and display, and the group people (DGO-1755)", u)
	}
	if _, ok := st.verify("galit", pw); !ok {
		t.Fatal("the invited person cannot sign in with the password they chose")
	}
	if _, ok := st.verify("owner", testPassword); !ok {
		t.Fatal("the owner can no longer sign in")
	}
	if fi, _ := os.Stat(usersFile); fi.Mode().Perm() != 0o600 {
		t.Fatalf("the users file is %v after the invitation, want 0600", fi.Mode().Perm())
	}
	// spent: the same link again shows no form, and a second press is refused
	if w := get("/invite?code=" + url.QueryEscape(code)); strings.Contains(w.Body.String(), `name="password"`) {
		t.Fatal("a spent invitation still shows the form")
	}
	if w := post(url.Values{"code": {code}, "password": {pw}, "again": {pw}}); w.Code == http.StatusSeeOther {
		t.Fatal("a spent invitation was accepted twice")
	}
	if list, _ := iv.read(); len(list) != 0 {
		t.Fatalf("the spent invitation is still in the file: %+v", list)
	}
}

func TestMintingRefusesWhatWouldBreakTheUsersFile(t *testing.T) {
	_, iv, _ := inviteOffice(t)
	now := time.Now()
	for _, line := range []string{
		"owner owner2@example.com",        // already a user
		"Galit Cohen galit@example.com",   // a two-word name reads as a name and an «email» with no @
		"galit not-an-email",              // no @
		"galit ga\x1blit@example.com",     // a control character would reach the header and --list
		"galit galit@example.com\x00",     // …and so would a NUL
		"galit galit@example.com רות כהן", // a display of two words splits the users-file line
		"galit galit@example.com רות כהן", // a no-break space is a space to strings.Fields
		"",                                // nothing
		"g/alit galit@example.com",        // not a user name
	} {
		if code, rc := mint(t, iv, line, now); rc == 0 {
			t.Fatalf("-invite %q = 0 (code %q); want a refusal", line, code)
		}
	}
	if list, _ := iv.read(); len(list) != 0 {
		t.Fatalf("a refused invitation was kept: %+v", list)
	}
	// no owner yet: the first-run link comes first
	noOwner := &invites{path: filepath.Join(t.TempDir(), "invites"), usersFile: filepath.Join(t.TempDir(), "users")}
	if _, rc := mint(t, noOwner, "galit galit@example.com", now); rc == 0 {
		t.Fatal("an office with no owner minted an invitation")
	}
}

func TestAnInvitationExpiresAndANewOneReplacesTheOld(t *testing.T) {
	s, iv, _ := inviteOffice(t)
	past := time.Now().Add(-inviteTTL - time.Minute)
	old, rc := mint(t, iv, "moshe moshe@example.com משה", past)
	if rc != 0 {
		t.Fatal("minting failed")
	}
	if _, ok := iv.find(old, time.Now()); ok {
		t.Fatal("an invitation older than its TTL still opens")
	}
	first, _ := mint(t, iv, "moshe moshe@example.com משה", time.Now())
	second, _ := mint(t, iv, "moshe moshe@example.com משה", time.Now())
	if _, ok := iv.find(first, time.Now()); ok {
		t.Fatal("a second invitation for the same person must replace the first")
	}
	if _, ok := iv.find(second, time.Now()); !ok {
		t.Fatal("the newest invitation does not open")
	}
	if list, _ := iv.read(); len(list) != 1 {
		t.Fatalf("want one live invitation for moshe, have %d", len(list))
	}
	var out bytes.Buffer
	if rc := listInvites(iv, &out, time.Now()); rc != 0 || !strings.HasPrefix(out.String(), "moshe moshe@example.com משה ") ||
		strings.Contains(out.String(), second) {
		t.Fatalf("-invites = %d %q; want moshe's line and never a code", rc, out.String())
	}
	out.Reset()
	if rc := revokeInvite(iv, strings.NewReader("moshe\n"), &out, time.Now()); rc != 0 || strings.TrimSpace(out.String()) != "revoked" {
		t.Fatalf("-revoke-invite = %d %q", rc, out.String())
	}
	w := httptest.NewRecorder()
	s.routes().ServeHTTP(w, httptest.NewRequest("GET", "/invite?code="+url.QueryEscape(second), nil))
	if strings.Contains(w.Body.String(), `name="password"`) {
		t.Fatal("a revoked invitation still shows the form")
	}
}

func TestWrongInvitationCodesAreLimitedPerAddress(t *testing.T) {
	s, iv, _ := inviteOffice(t)
	code, _ := mint(t, iv, "dana dana@example.com ברוך", time.Now())
	limited := false
	for i := 0; i < 40 && !limited; i++ {
		r := httptest.NewRequest("POST", "/invite", strings.NewReader(url.Values{"code": {"guess"}}.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, r)
		limited = w.Code == http.StatusTooManyRequests
	}
	if !limited {
		t.Fatal("forty wrong codes from one address were never limited")
	}
	// the right code still goes through from that address: a limit never locks the invited person out
	const pw = "a passphrase long enough"
	r := httptest.NewRequest("POST", "/invite", strings.NewReader(url.Values{"code": {code}, "password": {pw}, "again": {pw}}.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	s.routes().ServeHTTP(w, r)
	if w.Code != http.StatusSeeOther {
		t.Fatalf("the right code after the limit = %d, want 303", w.Code)
	}
}

func TestAnInvitationNeverOverwritesAUserAddedSinceItWasMade(t *testing.T) {
	s, iv, usersFile := inviteOffice(t)
	code, _ := mint(t, iv, "galit galit@example.com רות", time.Now())
	// someone with the same name became a user after the invitation was made (a restore, a second link)
	hash, _ := hashPassword(testPassword)
	f, _ := os.OpenFile(usersFile, os.O_APPEND|os.O_WRONLY, 0o600)
	_, _ = f.WriteString("galit other@example.com אחרת 9 - " + hash + "\n")
	f.Close()
	before, _ := os.ReadFile(usersFile)
	const pw = "a passphrase long enough"
	r := httptest.NewRequest("POST", "/invite", strings.NewReader(url.Values{"code": {code}, "password": {pw}, "again": {pw}}.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	s.routes().ServeHTTP(w, r)
	if w.Code == http.StatusSeeOther {
		t.Fatal("an invitation was accepted over an existing user of the same name")
	}
	after, _ := os.ReadFile(usersFile)
	if !bytes.Equal(before, after) {
		t.Fatal("a refused acceptance changed the users file")
	}
}

// accept re-checks UNDER THE LOCK — a page shown before another tab spent the link must not add the person twice,
// and an acceptance whose spend was cut after the users file was in place is spent at the link's next use.
func TestAcceptRechecksUnderTheLock(t *testing.T) {
	_, iv, usersFile := inviteOffice(t)
	now := time.Now()
	hash, _ := hashPassword("a passphrase long enough")
	line := func(u string) string { return u + " " + u + "@example.com " + u + " 7 - " + hash }

	if _, err := iv.accept("no-such-code", line("ghost"), now); err != errInviteGone {
		t.Fatalf("accept of a code that is not there = %v, want errInviteGone", err)
	}
	code, _ := mint(t, iv, "galit galit@example.com רות", now)
	if _, err := iv.accept(code, line("galit"), now); err != nil {
		t.Fatalf("the first accept: %v", err)
	}
	before, _ := os.ReadFile(usersFile)
	if _, err := iv.accept(code, line("galit"), now); err != errInviteGone {
		t.Fatalf("a second accept of the same code = %v, want errInviteGone (no second line)", err)
	}
	if after, _ := os.ReadFile(usersFile); !bytes.Equal(before, after) {
		t.Fatal("a second accept changed the users file")
	}

	// the half state: the person is a user and the invitation is still listed (its spend was cut)
	code2, _ := mint(t, iv, "moshe moshe@example.com משה", now)
	f, _ := os.OpenFile(usersFile, os.O_APPEND|os.O_WRONLY, 0o600)
	_, _ = f.WriteString(line("moshe") + "\n")
	f.Close()
	if _, err := iv.accept(code2, line("moshe"), now); err != errInviteGone {
		t.Fatalf("accept for a person who is already a user = %v, want errInviteGone", err)
	}
	if _, ok := iv.find(code2, now); ok {
		t.Fatal("the half-spent invitation is still live after its next use")
	}
	if st, err := loadUsers(usersFile); err != nil || len(st.byName) != 3 {
		t.Fatalf("the users file after the half state: %v, %d users (want owner, galit, moshe)", err, len(st.byName))
	}
}

func TestNoInvitationsConfiguredMeansNoPage(t *testing.T) {
	s := testServer(t)
	w := httptest.NewRecorder()
	s.routes().ServeHTTP(w, httptest.NewRequest("GET", "/invite?code=x", nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("/invite with no invitations configured = %d, want 404", w.Code)
	}
}

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

// First-run setup (setup.go, DGO-1090): how a fresh office gets its owner, once.

const firstRunCode = "the-one-time-first-run-code"

func setupServer(t *testing.T) (*server, string) {
	t.Helper()
	dir := t.TempDir()
	users, codeFile := filepath.Join(dir, "users"), filepath.Join(dir, "setup")
	h := sha256.Sum256([]byte(firstRunCode))
	if err := os.WriteFile(codeFile, []byte(hex.EncodeToString(h[:])+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	fr, err := loadSetup(users, codeFile)
	if err != nil || !fr.pending() {
		t.Fatalf("a fresh office with a code is not in setup: %v", err)
	}
	live, err := newLiveUsers(users, true)
	if err != nil {
		t.Fatal(err)
	}
	s := testServer(t)
	s.live, s.firstRun = live, fr
	return s, users
}

func TestFirstRunSetupMakesTheOwnerOnce(t *testing.T) {
	s, users := setupServer(t)
	get := func(target string) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, httptest.NewRequest("GET", target, nil))
		return w
	}
	post := func(v url.Values) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/setup", strings.NewReader(v.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, r)
		return w
	}
	const pw = "a passphrase long enough"

	for _, target := range []string{"/setup", "/setup?code=wrong"} {
		if w := get(target); w.Code != http.StatusOK || strings.Contains(w.Body.String(), `name="password"`) {
			t.Fatalf("%s = %d with a form; want the page that says to open the device's link", target, w.Code)
		}
	}
	if w := get("/login"); w.Code != http.StatusFound || !strings.HasPrefix(w.Header().Get("Location"), "/setup") {
		t.Fatalf("an office with no owner: /login = %d to %q, want the setup page", w.Code, w.Header().Get("Location"))
	}
	if w := get("/setup?code=" + firstRunCode); !strings.Contains(w.Body.String(), `name="password"`) {
		t.Fatal("the right code does not show the form")
	}
	if w := post(url.Values{"code": {"wrong"}, "user": {"boss"}, "password": {pw}, "again": {pw}}); w.Code != http.StatusForbidden {
		t.Fatalf("a wrong code = %d, want 403", w.Code)
	}
	if w := post(url.Values{"code": {firstRunCode}, "user": {"boss"}, "password": {"short"}, "again": {"short"}}); w.Code != http.StatusBadRequest {
		t.Fatalf("a short password = %d, want 400", w.Code)
	}
	if w := post(url.Values{"code": {firstRunCode}, "user": {"Boss Man"}, "password": {pw}, "again": {pw}}); w.Code != http.StatusBadRequest {
		t.Fatalf("a name with a space = %d, want 400", w.Code)
	}
	// a no-break space would split the users-file line into seven fields (the third reader)
	if w := post(url.Values{"code": {firstRunCode}, "user": {"boss"}, "email": {"boss x@example.com"},
		"password": {pw}, "again": {pw}}); w.Code != http.StatusBadRequest {
		t.Fatalf("an email with a no-break space = %d, want 400", w.Code)
	}
	if _, err := os.Stat(users); err == nil {
		t.Fatal("a refused setup wrote the users file")
	}

	w := post(url.Values{"code": {firstRunCode}, "user": {"boss"}, "password": {pw}, "again": {pw},
		"rd": {"http://console.localhost/"}})
	if w.Code != http.StatusSeeOther || w.Header().Get("Location") != "http://console.localhost/" {
		t.Fatalf("setup = %d to %q, want 303 to the return-to", w.Code, w.Header().Get("Location"))
	}
	signedIn := false
	for _, c := range w.Result().Cookies() {
		signedIn = signedIn || (c.Name == cookieName && c.Value != "")
	}
	if !signedIn {
		t.Error("setup did not sign the owner in")
	}
	if _, ok := s.store().verify("boss", pw); !ok {
		t.Fatal("the owner setup wrote does not sign in")
	}
	if fi, err := os.Stat(users); err != nil || fi.Mode().Perm() != 0o600 {
		t.Fatalf("the users file: %v, mode %v; want 0600", err, fi)
	}

	if w := get("/setup?code=" + firstRunCode + "&rd=http://console.localhost/"); w.Code != http.StatusFound ||
		w.Header().Get("Location") != "http://console.localhost/" {
		t.Fatalf("the first-run link after the owner exists = %d to %q, want on to the return-to", w.Code, w.Header().Get("Location"))
	}
	if w := get("/setup"); w.Code != http.StatusFound || w.Header().Get("Location") != "http://auth.localhost/login" {
		t.Fatalf("setup after the owner exists = %d to %q, want the sign-in page", w.Code, w.Header().Get("Location"))
	}
	if w := post(url.Values{"code": {firstRunCode}, "user": {"second"}, "password": {pw}, "again": {pw}}); w.Code != http.StatusNotFound {
		t.Fatalf("a second setup = %d, want 404", w.Code)
	}
	if fr, err := loadSetup(users, filepath.Join(filepath.Dir(users), "setup")); err != nil || fr.pending() {
		t.Fatalf("after a restart the office is in setup again: %v", err)
	}
}

// A users file that appeared after boot (a restore, another writer) is never overwritten by setup.
func TestSetupNeverOverwritesAUsersFile(t *testing.T) {
	s, users := setupServer(t)
	theirs := []byte("# somebody else's\n")
	if err := os.WriteFile(users, theirs, 0o600); err != nil {
		t.Fatal(err)
	}
	const pw = "a passphrase long enough"
	r := httptest.NewRequest("POST", "/setup", strings.NewReader(url.Values{"code": {firstRunCode}, "user": {"boss"},
		"password": {pw}, "again": {pw}}.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	s.routes().ServeHTTP(w, r)
	if w.Code == http.StatusSeeOther {
		t.Fatal("setup succeeded over a users file that was already there")
	}
	if got, _ := os.ReadFile(users); string(got) != string(theirs) {
		t.Fatalf("the users file was overwritten: %q", got)
	}
}

// On a phone no app may make a hard link (DGO-1090): the owner is still made — the users file placed by
// a rename where there was none — and a users file already there is still never overwritten.
func TestSetupWhereLinksAreRefused(t *testing.T) {
	was := link
	link = func(_, _ string) error { return &os.LinkError{Op: "link", Err: syscall.EACCES} }
	t.Cleanup(func() { link = was })
	s, users := setupServer(t)
	const pw = "a passphrase long enough"
	post := func() int {
		r := httptest.NewRequest("POST", "/setup", strings.NewReader(url.Values{"code": {firstRunCode}, "user": {"boss"},
			"password": {pw}, "again": {pw}}.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, r)
		return w.Code
	}
	if code := post(); code != http.StatusSeeOther {
		t.Fatalf("setup where links are refused = %d, want the owner made (303)", code)
	}
	if got, err := loadUsers(users); err != nil || len(got.byName) != 1 {
		t.Fatalf("the users file: %v, %v", got, err)
	}
	dir := t.TempDir()
	dst, tmp := filepath.Join(dir, "users"), filepath.Join(dir, ".users-x")
	for p, body := range map[string]string{dst: "theirs\n", tmp: "mine\n"} {
		if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	if err := placeNew(tmp, dst); err == nil {
		t.Fatal("placeNew overwrote a users file that was there")
	}
	if b, _ := os.ReadFile(dst); string(b) != "theirs\n" {
		t.Fatalf("the users file that was there: %q", b)
	}
}

// `forward-auth -first-run`, the prepare hook's way into the volume: it keeps the code's hash, never
// the code, says "pending" — and once the owner exists writes nothing and says so.
func TestFirstRunKeepsOnlyTheCodesHash(t *testing.T) {
	dir := t.TempDir()
	users, codeFile := filepath.Join(dir, "users"), filepath.Join(dir, "setup")
	run := func(in string) (int, string) {
		var out strings.Builder
		return writeFirstRun(users, codeFile, strings.NewReader(in), &out), strings.TrimSpace(out.String())
	}
	if rc, _ := run("short\n"); rc != 2 {
		t.Fatalf("a code too short = %d, want 2", rc)
	}
	code := strings.Repeat("ab", 24)
	for i := 0; i < 2; i++ { // the second run, with the same code, finds the same hash
		if rc, said := run(code + "\n"); rc != 0 || said != "pending" {
			t.Fatalf("run %d = %d %q, want 0 pending", i+1, rc, said)
		}
	}
	raw, err := os.ReadFile(codeFile)
	if err != nil || strings.Contains(string(raw), code) {
		t.Fatalf("the setup file: %v, %q — want the hash, never the code", err, raw)
	}
	if fi, _ := os.Stat(codeFile); fi.Mode().Perm() != 0o600 {
		t.Fatalf("the setup file is %v, want 0600", fi.Mode().Perm())
	}
	fr, err := loadSetup(users, codeFile)
	if err != nil || !fr.check(code) {
		t.Fatalf("the service does not take the code the hook printed: %v", err)
	}
	if err := os.WriteFile(users, []byte("# made\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if rc, said := run(strings.Repeat("cd", 24) + "\n"); rc != 0 || said != "owner-exists" {
		t.Fatalf("with an owner = %d %q, want 0 owner-exists", rc, said)
	}
	if again, _ := os.ReadFile(codeFile); string(again) != string(raw) {
		t.Fatal("a run after the owner exists rewrote the setup file")
	}
}

// `forward-auth -import-users`: a users file the migration prepared on the host comes into the volume
// once — only one that loads, 0600, and never over a users file that is there.
func TestImportUsersTakesAnOldFileOnce(t *testing.T) {
	hash, err := hashPassword(testPassword)
	if err != nil {
		t.Fatal(err)
	}
	run := func(users, in string) (int, string) {
		var out strings.Builder
		return importUsers(users, strings.NewReader(in), &out), strings.TrimSpace(out.String())
	}
	bad := filepath.Join(t.TempDir(), "users")
	if rc, _ := run(bad, "not a users line\n"); rc != 2 {
		t.Fatalf("a file that does not load = %d, want 2", rc)
	}
	if _, err := os.Stat(bad); err == nil {
		t.Fatal("a file that does not load was put in place")
	}
	users := filepath.Join(t.TempDir(), "users")
	old := "akadmin a@localhost Owner 1 admins " + hash + "\n"
	if rc, said := run(users, old); rc != 0 || said != "imported" {
		t.Fatalf("the old file = %d %q, want 0 imported", rc, said)
	}
	if fi, err := os.Stat(users); err != nil || fi.Mode().Perm() != 0o600 {
		t.Fatalf("the imported file: %v %v, want 0600", err, fi)
	}
	if st, err := loadUsers(users); err != nil || st.byName["akadmin"] == nil {
		t.Fatalf("the imported file does not load: %v", err)
	}
	if rc, said := run(users, "someone else\n"); rc != 0 || said != "owner-exists" {
		t.Fatalf("a second import = %d %q, want 0 owner-exists", rc, said)
	}
}

// With neither a users file nor a code, nobody could ever sign in: the service refuses to start.
func TestNoUsersAndNoCodeRefusesToStart(t *testing.T) {
	dir := t.TempDir()
	if _, err := loadSetup(filepath.Join(dir, "users"), filepath.Join(dir, "setup")); err == nil {
		t.Fatal("started with no users file and no first-run code")
	}
}

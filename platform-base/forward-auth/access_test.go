package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

// DGO-1755: an app that declares `people: admins` is gated at /auth/traefik/admins. Every case goes through
// the server's own mux (routes()), as traefik's middleware dials it.

// office is a server whose users file holds these lines (name → groups; nil is `-`).
func office(t *testing.T, people map[string][]string) *server {
	t.Helper()
	s := testServer(t)
	st := &userStore{byName: map[string]*user{}}
	for name, groups := range people {
		st.byName[name] = &user{Name: name, Email: name + "@localhost", Display: name, UID: name, Groups: groups}
	}
	s.users = st
	return s
}

// signedIn is a session cookie for `name`, minted by the server's own signer.
func signedIn(t *testing.T, s *server, name string) *http.Cookie {
	t.Helper()
	w := httptest.NewRecorder()
	s.sign.set(w, name, false, "")
	cs := w.Result().Cookies()
	if len(cs) != 1 {
		t.Fatalf("the signer set %d cookies for %s", len(cs), name)
	}
	return cs[0]
}

// ask sends what traefik sends to `path` for host computers.localhost, through the mux.
func ask(s *server, path string, c *http.Cookie) *httptest.ResponseRecorder {
	r := fwdReq("GET", "computers.localhost", "/", c)
	r.URL.Path = path
	w := httptest.NewRecorder()
	s.routes().ServeHTTP(w, r)
	return w
}

func TestAnInvitedPersonIsRefusedTheAdminsAppsAndOpensTheOthers(t *testing.T) {
	s := office(t, map[string][]string{"owner": {"admins"}, "galit": {"people"}})
	galit := signedIn(t, s, "galit")

	w := ask(s, "/auth/traefik/admins", galit)
	if w.Code != http.StatusForbidden {
		t.Fatalf("an invited person at an admins' app = %d, want 403", w.Code)
	}
	if w.Header().Get("X-authentik-username") != "" || w.Header().Get("X-authentik-groups") != "" {
		t.Fatalf("a refusal carries identity headers: %v", w.Header())
	}
	if !strings.Contains(w.Body.String(), "למנהלי הלשכה בלבד") || !strings.Contains(w.Header().Get("Content-Type"), "text/html") {
		t.Fatalf("the refusal is not the card: %q", w.Body.String())
	}
	if w.Header().Get("Cache-Control") != "no-store" {
		t.Errorf("a refusal may be kept by a proxy: Cache-Control %q", w.Header().Get("Cache-Control"))
	}

	w = ask(s, "/auth/traefik", galit)
	if w.Code != http.StatusOK || w.Header().Get("X-authentik-username") != "galit" || w.Header().Get("X-authentik-groups") != "people" {
		t.Fatalf("an invited person at an everyone app = %d, user %q, groups %q", w.Code,
			w.Header().Get("X-authentik-username"), w.Header().Get("X-authentik-groups"))
	}

	w = ask(s, "/auth/traefik/admins", signedIn(t, s, "owner"))
	if w.Code != http.StatusOK || w.Header().Get("X-authentik-username") != "owner" || w.Header().Get("X-authentik-groups") != "admins" {
		t.Fatalf("the owner at an admins' app = %d, groups %q", w.Code, w.Header().Get("X-authentik-groups"))
	}
}

// A migrated office's file names no admin (authentik's «authentik Admins» cannot be written in it): every
// account that was not invited counts as one, and is TOLD it is one; an invited person never is.
func TestAnOfficeThatNamesNoAdminKeepsItsOwnPeopleAndRefusesTheInvited(t *testing.T) {
	s := office(t, map[string][]string{"akadmin": nil, "owner": nil, "moshe": {"people"}})
	for _, name := range []string{"akadmin", "owner"} {
		w := ask(s, "/auth/traefik/admins", signedIn(t, s, name))
		if w.Code != http.StatusOK || w.Header().Get("X-authentik-groups") != "admins" {
			t.Fatalf("%s on an office that names no admin = %d, groups %q", name, w.Code, w.Header().Get("X-authentik-groups"))
		}
		w = ask(s, "/auth/traefik", signedIn(t, s, name))
		if w.Code != http.StatusOK || w.Header().Get("X-authentik-groups") != "admins" {
			t.Fatalf("%s at an everyone app = %d, groups %q: the apps must be told the same", name, w.Code,
				w.Header().Get("X-authentik-groups"))
		}
	}
	if w := ask(s, "/auth/traefik/admins", signedIn(t, s, "moshe")); w.Code != http.StatusForbidden {
		t.Fatalf("an invited person on an office that names no admin = %d, want 403", w.Code)
	}
	// the file is not rewritten: the store's own line still says `-`
	if len(s.users.byName["owner"].Groups) != 0 {
		t.Fatalf("the fallback wrote into the store: %v", s.users.byName["owner"].Groups)
	}
}

// On an office that names no admin, only a line with NO group is the office's own: an imported line with any
// group (incoming-docs-admin, authentik-read-only) is what its group says, never an admin by the fallback.
func TestTheFallbackIsOnlyForALineWithNoGroup(t *testing.T) {
	s := office(t, map[string][]string{"akadmin": nil, "clerk": {"incoming-docs-admin"}, "viewer": {"authentik-read-only"}})
	if w := ask(s, "/auth/traefik/admins", signedIn(t, s, "akadmin")); w.Code != http.StatusOK {
		t.Fatalf("the bare line = %d", w.Code)
	}
	for _, name := range []string{"clerk", "viewer"} {
		if w := ask(s, "/auth/traefik/admins", signedIn(t, s, name)); w.Code != http.StatusForbidden {
			t.Errorf("%s (a group of its own) on an office that names no admin = %d, want 403", name, w.Code)
		}
		if w := ask(s, "/auth/traefik", signedIn(t, s, name)); strings.Contains(w.Header().Get("X-authentik-groups"), "admins") {
			t.Errorf("%s is told it is an admin: %q", name, w.Header().Get("X-authentik-groups"))
		}
	}
}

// The admin group's other name, a migration's `authentik-admins`, is the admin group: it opens the admins' apps,
// and an office whose file names it has named an admin (no fallback).
func TestAuthentiksRenamedAdminGroupIsTheAdminGroup(t *testing.T) {
	s := office(t, map[string][]string{"owner": {"authentik-admins"}, "bare": nil})
	if w := ask(s, "/auth/traefik/admins", signedIn(t, s, "owner")); w.Code != http.StatusOK {
		t.Fatalf("authentik-admins = %d", w.Code)
	}
	if w := ask(s, "/auth/traefik/admins", signedIn(t, s, "bare")); w.Code != http.StatusForbidden {
		t.Fatalf("a bare line where the file names an admin = %d, want 403", w.Code)
	}
}

// Once the file names an admin, the fallback ends: an account without the group is refused, whatever it is.
func TestAnOfficeThatNamesAnAdminRefusesEveryoneElse(t *testing.T) {
	s := office(t, map[string][]string{"owner": {"admins"}, "old-invite": nil, "clerk": {"incoming-docs-admin"}})
	for _, name := range []string{"old-invite", "clerk"} {
		if w := ask(s, "/auth/traefik/admins", signedIn(t, s, name)); w.Code != http.StatusForbidden {
			t.Errorf("%s (no admins group) on an office that names one = %d, want 403", name, w.Code)
		}
		w := ask(s, "/auth/traefik", signedIn(t, s, name))
		if w.Code != http.StatusOK || strings.Contains(w.Header().Get("X-authentik-groups"), "admins") {
			t.Errorf("%s at an everyone app = %d, groups %q", name, w.Code, w.Header().Get("X-authentik-groups"))
		}
	}
}

// Nobody signed in: the admins' gate sends to the sign-in like the other — a 403 would tell a stranger the
// app exists and leave the owner no way in.
func TestTheAdminsGateSendsAStrangerToSignIn(t *testing.T) {
	s := office(t, map[string][]string{"owner": {"admins"}})
	w := ask(s, "/auth/traefik/admins", nil)
	if w.Code != http.StatusFound || !strings.HasPrefix(w.Header().Get("Location"), "http://auth.localhost/login?") {
		t.Fatalf("a stranger at an admins' app = %d %q, want 302 to the sign-in", w.Code, w.Header().Get("Location"))
	}
	for _, m := range []string{"POST", "PUT", "DELETE"} {
		r := fwdReq(m, "computers.localhost", "/", signedIn(t, s, "owner"))
		r.URL.Path = "/auth/traefik/admins"
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, r)
		if w.Code != http.StatusOK {
			t.Errorf("the owner's %s at an admins' app = %d", m, w.Code)
		}
	}
}

// /whoami says the groups the gates go by.
func TestWhoamiSaysTheGroupsTheGatesGoBy(t *testing.T) {
	s := office(t, map[string][]string{"akadmin": nil, "moshe": {"people"}})
	for name, want := range map[string][]string{"akadmin": {"admins"}, "moshe": {"people"}} {
		r := httptest.NewRequest("GET", "/whoami", nil)
		r.AddCookie(signedIn(t, s, name))
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, r)
		var got struct {
			Groups []string `json:"groups"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil || strings.Join(got.Groups, ",") != strings.Join(want, ",") {
			t.Errorf("/whoami of %s: %s, want groups %v", name, w.Body.String(), want)
		}
	}
}

// The phone's machine behind its core: the core's forward-auth wrote the person's groups; the admins' gate
// lets through only a signed identity that names the group.
func TestTheCoresIdentityOpensAnAdminsAppOnlyWithTheGroup(t *testing.T) {
	token := strings.Repeat("t", 40)
	s := office(t, map[string][]string{"owner": {"admins"}})
	s.edgeToken = []byte(token)
	now := time.Now().Unix()
	for i, c := range []struct {
		groups string
		want   int
	}{{"admins", http.StatusOK}, {"people", http.StatusForbidden}, {"", http.StatusForbidden}, {"admins-not", http.StatusForbidden}} {
		ids := map[string]string{"X-authentik-username": "someone", "X-authentik-groups": c.groups}
		nonce := "a-nonce-of-the-core-" + strconv.Itoa(1000+i)
		r := fwdReq("GET", "computers.localhost", "/", nil)
		r.URL.Path = "/auth/traefik/admins"
		r.Header.Set("X-Forwarded-Method", "GET")
		for k, v := range ids {
			r.Header.Set(k, v)
		}
		r.Header.Set(edgeNonceHeader, nonce)
		r.Header.Set(edgeAtHeader, strconv.FormatInt(now, 10))
		r.Header.Set(edgeSigHeader, sign(token, now, nonce, "GET", "computers.localhost", "/", ids))
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, r)
		if w.Code != c.want {
			t.Errorf("the core's identity with groups %q at an admins' app = %d, want %d", c.groups, w.Code, c.want)
		}
	}
}

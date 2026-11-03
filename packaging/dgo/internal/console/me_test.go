package console

import (
	"encoding/json"
	"net/http/httptest"
	"net/netip"
	"testing"
)

// behindTheEdge is the native server trusting the edge httptest's requests come from (192.0.2.1), as the
// phone's core trusts its own socket: the identity headers reach the routes.
func behindTheEdge(t *testing.T, o office) (*Server, *int) {
	t.Helper()
	return counted(t, Config{Static: o.static, Lookup: env(o.env()), Trusted: []netip.Prefix{netip.MustParsePrefix("192.0.2.1/32")}})
}

// TestMeMatchesFlask: /api/me as app.py answers it, byte for byte — nobody, the owner with each header and
// without, empty values (as good as none), groups split on `|` with their empty parts, and the same
// answer compressed and to a HEAD.
func TestMeMatchesFlask(t *testing.T) {
	o := newOffice(t)
	reqs := []request{
		fetch("/api/me"), ask("HEAD", "/api/me"),
		fetch("/api/me", "X-authentik-username", "owner"),
		fetch("/api/me", "X-authentik-username", "owner", "X-authentik-email", "person172@example.com",
			"X-authentik-name", "The Owner", "X-authentik-groups", "admins|staff"),
		fetch("/api/me", "X-authentik-username", "", "X-authentik-name", "", "X-authentik-groups", ""),
		fetch("/api/me", "X-authentik-email", "", "X-authentik-groups", "a||b|"),
		fetch("/api/me", "X-authentik-name", "Only A Name"),
		fetch("/api/me", "X-authentik-username", "owner", "Accept-Encoding", "gzip"),
		fetch("/api/me?x=1", "X-authentik-username", "owner", "Accept-Encoding", "gzip, deflate"),
	}
	want := o.flask(t, o.env(), reqs)
	s, proxied := behindTheEdge(t, o)
	for i, r := range reqs {
		got := serve(s, proxied, r)
		if got == nil {
			t.Errorf("%s %s %v: proxied, expected a native answer", r.Method, r.Path, r.Headers)
			continue
		}
		if d := diff(want[i], got); d != "" {
			t.Errorf("%s %s %v: %s", r.Method, r.Path, r.Headers, d)
		}
	}
}

// TestMeReadsWhatForwardAuthWrites: a display name in Hebrew, as forward-auth writes it (UTF-8), reads as
// itself; a header named twice, or bytes that are not UTF-8, are the container's; and from a caller that
// is not the edge, nobody is anybody — screen() has removed what it claimed.
func TestMeReadsWhatForwardAuthWrites(t *testing.T) {
	o := newOffice(t)
	s, proxied := behindTheEdge(t, o)
	got := serve(s, proxied, fetch("/api/me", "X-authentik-username", "owner", "X-authentik-name", "שלמה בולוטין"))
	if got == nil {
		t.Fatal("a Hebrew display name was left to the container")
	}
	var me map[string]any
	if err := json.Unmarshal(got.Body.Bytes(), &me); err != nil || me["name"] != "שלמה בולוטין" || me["user"] != "owner" {
		t.Fatalf("/api/me = %s (%v), want the name as forward-auth wrote it", got.Body.Bytes(), err)
	}
	for _, r := range []request{
		fetch("/api/me", "X-authentik-username", "a", "X-authentik-username", "b"),
		fetch("/api/me", "X-authentik-name", "\xff\xfe"),
	} {
		if serve(s, proxied, r) != nil {
			t.Errorf("%v: answered natively — must be the container's", r.Headers)
		}
	}
	untrusted, p := counted(t, Config{Static: o.static, Lookup: env(o.env())})
	hr := httptest.NewRequest("GET", "/api/me", nil)
	hr.Header.Set("X-authentik-username", "owner")
	rec := httptest.NewRecorder()
	untrusted.ServeHTTP(rec, hr)
	if *p != 0 {
		t.Fatal("/api/me from an untrusted caller was proxied")
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &me); err != nil || me["user"] != guest {
		t.Fatalf("/api/me from an untrusted caller claiming the owner = %s, want %s", rec.Body.Bytes(), guest)
	}
}

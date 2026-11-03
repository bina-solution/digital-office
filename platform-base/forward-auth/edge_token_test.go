package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

// The machine proves it holds the core's token without saying it: HMAC-SHA256(token, nonce); a forward-auth
// given no token, or a nonce too short to be one, has nothing to prove.
func TestTheMachineProvesItsTokenWithoutSayingIt(t *testing.T) {
	token := strings.Repeat("t", 40)
	s := testServer(t)
	s.edgeToken = []byte(token)
	proof := func(s *server, nonce string) (int, string) {
		w := httptest.NewRecorder()
		s.routes().ServeHTTP(w, httptest.NewRequest("GET", "/edge-proof?nonce="+nonce, nil))
		return w.Code, w.Body.String()
	}
	mac := hmac.New(sha256.New, []byte(token))
	mac.Write([]byte("a-nonce-of-the-core-0123"))
	if code, body := proof(s, "a-nonce-of-the-core-0123"); code != http.StatusOK || body != hex.EncodeToString(mac.Sum(nil)) || strings.Contains(body, token) {
		t.Fatalf("the proof = %d %q", code, body)
	}
	if code, _ := proof(s, "short"); code != http.StatusNotFound {
		t.Fatalf("a short nonce = %d", code)
	}
	if code, _ := proof(testServer(t), "a-nonce-of-the-core-0123"); code != http.StatusNotFound {
		t.Fatalf("no token, a proof = %d", code)
	}
}

// sign is the core's edge's signature of one request (edge.EdgeSigned): when, the request as the
// machine's edge sees it, and the identity, under the token.
func sign(token string, at int64, nonce, method, host, uri string, ids map[string]string) string {
	parts := []string{strconv.FormatInt(at, 10), nonce, method, host, uri}
	for _, k := range edgeIdentity {
		parts = append(parts, ids[k])
	}
	mac := hmac.New(sha256.New, []byte(token))
	mac.Write([]byte(strings.Join(parts, "\n")))
	return hex.EncodeToString(mac.Sum(nil))
}

// The phone's machine, behind its native core (DGO-1090): a request the core signed — for that method,
// host and URI, that identity, within a minute, once — is the core's edge's, and the identity it carries
// is taken as it came. A signature for another request, an old or a spent one, a forged one, none, or a
// forward-auth that was given no token: nothing of the request's identity is taken — sent to sign in.
func TestTheCoresIdentityIsTakenOnlyAsItSigned(t *testing.T) {
	token := strings.Repeat("t", 40)
	owner := map[string]string{"X-authentik-username": "owner", "X-authentik-groups": "admins"}
	const nonce = "a-nonce-of-this-request-0123"
	ask := func(s *server, at int64, sig, uri string, ids map[string]string) *httptest.ResponseRecorder {
		t.Helper()
		r := fwdReq("GET", "n8n.localhost:8080", uri, nil)
		r.Header.Set("X-Forwarded-Method", "GET")
		for k, v := range ids {
			r.Header.Set(k, v)
		}
		r.Header.Set(edgeNonceHeader, nonce)
		r.Header.Set(edgeAtHeader, strconv.FormatInt(at, 10))
		if sig != "" {
			r.Header.Set(edgeSigHeader, sig)
		}
		w := httptest.NewRecorder()
		s.forwardAuth(w, r)
		return w
	}
	s := testServer(t)
	s.edgeToken = []byte(token)
	now := time.Now().Unix()
	good := sign(token, now, nonce, "GET", "n8n.localhost:8080", "/x?y=1", owner)
	if w := ask(s, now, good, "/x?y=1", owner); w.Code != http.StatusOK || w.Header().Get("X-authentik-username") != "owner" ||
		w.Header().Get("X-authentik-groups") != "admins" {
		t.Fatalf("signed by the core: %d, username %q", w.Code, w.Header().Get("X-authentik-username"))
	}
	// each case a signature not spent yet, so it fails for its own reason — never as a replay
	old := now - 120
	unspent := func(uri string) string { return sign(token, now, nonce, "GET", "n8n.localhost:8080", uri, owner) }
	for _, c := range []struct {
		name string
		w    *httptest.ResponseRecorder
	}{
		{"the same signature again", ask(s, now, good, "/x?y=1", owner)},
		{"another URI", ask(s, now, unspent("/a"), "/admin", owner)},
		{"another identity", ask(s, now, unspent("/b"), "/b", map[string]string{"X-authentik-username": "intruder"})},
		{"an old one", ask(s, old, sign(token, old, nonce, "GET", "n8n.localhost:8080", "/x", owner), "/x", owner)},
		{"another token", ask(s, now, sign("u"+token, now, nonce, "GET", "n8n.localhost:8080", "/z", owner), "/z", owner)},
		{"none", ask(s, now, "", "/x", owner)},
		{"a forward-auth with no token", ask(testServer(t), now, unspent("/w"), "/w", owner)},
		{"naming nobody", ask(s, now, sign(token, now, nonce, "GET", "n8n.localhost:8080", "/v", nil), "/v", nil)},
	} {
		if c.w.Code == http.StatusOK || c.w.Header().Get("X-authentik-username") != "" {
			t.Errorf("%s: %d, username %q — taken", c.name, c.w.Code, c.w.Header().Get("X-authentik-username"))
		}
	}
	// two alike in one second, each with a nonce of its own, are two
	for i, n := range []string{"the-first-nonce-0123", "the-second-nonce-012"} {
		r := fwdReq("GET", "n8n.localhost:8080", "/poll", nil)
		r.Header.Set("X-Forwarded-Method", "GET")
		r.Header.Set("X-authentik-username", "owner")
		r.Header.Set("X-authentik-groups", "admins")
		r.Header.Set(edgeNonceHeader, n)
		r.Header.Set(edgeAtHeader, strconv.FormatInt(now, 10))
		r.Header.Set(edgeSigHeader, sign(token, now, n, "GET", "n8n.localhost:8080", "/poll", owner))
		w := httptest.NewRecorder()
		s.forwardAuth(w, r)
		if w.Code != http.StatusOK {
			t.Fatalf("the request %d of two alike in one second: %d", i+1, w.Code)
		}
	}
}

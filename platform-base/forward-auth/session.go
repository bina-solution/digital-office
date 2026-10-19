package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// The session is a SIGNED COOKIE and nothing else — no server-side store, no Redis, no database.
// WHY that is enough here: the cookie carries only two facts (who, and until when), this office runs
// ONE identity service, and a store that had to be asked "is this session still valid" would be the
// authentik-shaped thing we are removing. The cost is stated plainly in the design note: logout
// cannot reach other devices, and there is no server-side revocation — to end every session, rotate
// FORWARD_AUTH_SECRET and restart.

const cookieName = "dgo_session"

// errBadCookie is deliberately one error for every way a cookie can be wrong: absent, expired,
// tampered, unsigned, or minted by another office. Distinguishing them in the refusal would tell an
// unauthenticated caller which half of a forgery to work on.
var errBadCookie = errors.New("forward-auth: invalid session cookie")

type session struct {
	User *user
	Exp  time.Time
}

// signer mints and reads sessions. It holds exactly one secret, and the entire integrity of every
// session in the estate rests on that one value — which is why main() refuses to start without it.
type signer struct {
	key []byte
	ttl time.Duration
}

// issue returns the cookie value and its expiry. The signed body is "<name>\n<unix expiry>",
// base64url-encoded as a whole; base64url has no '\n', so the split is unambiguous even for a name
// that contains one.
func (s *signer) issue(name string, now time.Time) (string, time.Time) {
	exp := now.Add(s.ttl)
	enc := base64.RawURLEncoding.EncodeToString([]byte(name + "\n" + strconv.FormatInt(exp.Unix(), 10)))
	return enc + "." + s.mac(enc), exp
}

func (s *signer) mac(enc string) string {
	m := hmac.New(sha256.New, s.key)
	m.Write([]byte(enc))
	return base64.RawURLEncoding.EncodeToString(m.Sum(nil))
}

// read validates the cookie and resolves it to a live account. Every refusal is the same error.
func (s *signer) read(r *http.Request, now time.Time, store *userStore) (*session, error) {
	c, err := r.Cookie(cookieName)
	if err != nil {
		return nil, errBadCookie
	}
	enc, sig, ok := strings.Cut(c.Value, ".")
	if !ok {
		return nil, errBadCookie
	}
	// hmac.Equal IS the constant-time comparison; a plain == on a MAC is a timing oracle that hands
	// out the correct signature one byte at a time.
	if !hmac.Equal([]byte(sig), []byte(s.mac(enc))) {
		return nil, errBadCookie
	}
	body, err := base64.RawURLEncoding.DecodeString(enc)
	if err != nil {
		return nil, errBadCookie
	}
	name, expStr, ok := strings.Cut(string(body), "\n")
	if !ok {
		return nil, errBadCookie
	}
	expUnix, err := strconv.ParseInt(expStr, 10, 64)
	if err != nil {
		return nil, errBadCookie
	}
	exp := time.Unix(expUnix, 0)
	// A signature proves THIS office minted the cookie; it does not prove the account still exists.
	// Re-reading the store on every request is what makes deleting a line from the users file take
	// effect at once, instead of whenever that person's TTL happens to run out.
	u, ok := store.byName[name]
	if !ok || !now.Before(exp) {
		return nil, errBadCookie
	}
	return &session{User: u, Exp: exp}, nil
}

// set writes the cookie. `secure` is derived from the external URL and never hard-coded true: on a
// `.localhost` office the edge is plain HTTP, and a Secure cookie is simply never stored — the
// symptom is a login page that accepts the right password and then asks for it again, for ever.
func (s *signer) set(w http.ResponseWriter, name string, secure bool, domain string) time.Time {
	tok, exp := s.issue(name, time.Now())
	http.SetCookie(w, &http.Cookie{
		Name:     cookieName,
		Value:    tok,
		Path:     "/",
		Domain:   domain,
		Expires:  exp,
		HttpOnly: true, // no script has any business reading an identity cookie
		Secure:   secure,
		// Lax, not None: the cookie is not attached to a cross-site POST, which is what stops a
		// third-party page from making a signed-in browser act here.
		SameSite: http.SameSiteLaxMode,
	})
	return exp
}

// clear is logout, as far as a cookie-only session can be. It ends THIS browser's session only —
// see the design note's migration/rollback section for what that does and does not buy.
func (s *signer) clear(w http.ResponseWriter, secure bool, domain string) {
	http.SetCookie(w, &http.Cookie{
		Name: cookieName, Value: "", Path: "/", Domain: domain,
		MaxAge: -1, HttpOnly: true, Secure: secure, SameSite: http.SameSiteLaxMode,
	})
}

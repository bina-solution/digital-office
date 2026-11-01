package main

// Reading authentik's OWN session cookie, so that a browser signed in before the swap stays signed
// in after it. Requirement 1 of `core-006`: "a cookie minted by authentik today must still
// authenticate after the swap … otherwise every office is logged out at once".
//
// WHAT THE COOKIE ACTUALLY IS — read out of the live image (ghcr.io/goauthentik/server:2024.12,
// `/authentik/root/middleware.py` and `/authentik/root/settings.py`), not remembered:
//
//	name      `authentik_session`   (settings.SESSION_COOKIE_NAME)
//	value     a JWT, HS256, signed with `sha512(SECRET_KEY.encode()).hexdigest()` as the HMAC key
//	          (`SIGNING_HASH` in the same file — a 128-character hex string, used AS the key)
//	claims    {"sid": <32-char session key>, "iss": "authentik", "sub": <user uid | "anonymous">,
//	           "authenticated": <bool>, "acr": "goauthentik.io/core/default"}
//	expiry    NO `exp` claim. The browser cookie is a SESSION cookie
//	          (`SESSION_EXPIRE_AT_BROWSER_CLOSE = True` → no Max-Age/Expires), and the real lifetime
//	          is server-side: a `django_session` row / Redis entry plus an
//	          `authentik_core_authenticatedsession` row whose `expires` is 14 days out.
//
// THE TWO CONSEQUENCES, and they are why this file needs TWO inputs and not one:
//
//  1. **The signature needs the authentik secret.** Without `AUTHENTIK_SECRET_KEY` the JWT cannot be
//     verified at all, and accepting an unverified one would mean anybody on the office network can
//     mint `{"authenticated":true,"sub":<the owner's uid>}` and be let in. So this is not a
//     limitation to work around: it is the reason the acceptance is OPT-IN, and off unless the
//     operator has deliberately handed this service that one value for the length of the migration.
//     If the owner will not, the compatible fallback is in the design note: the legacy cookie is
//     simply not accepted, the browser is challenged at `/login`, and the SAME password signs the
//     person back in — because the imported `pbkdf2_sha256` hash verifies (users.go). Nothing is
//     re-authorized and nothing is reset; that is the whole of "no reconnection".
//
//  2. **A verified JWT is not a LIVE session.** Because there is no `exp`, a page left open for a
//     month would still carry a perfectly valid signature over a session authentik retired long
//     ago. So a `sid` is accepted only while a snapshot of authentik's OWN session table says it is
//     live — one read-only query at the window, one file. The snapshot is deliberate: after step 7
//     authentik is stopped and nothing can refresh it, and a stale snapshot fails CLOSED (a session
//     it does not name is refused), which is the only safe direction for a cutover.
//
// `sub` is the join key, and it is the same value the users file must carry as its `<uid>` field:
// `User.uid` in authentik (`sha256("<user.id>-<install_id>")`, hex, 64 chars), which is exactly what
// the outpost sends as `X-authentik-uid`. Verified against the live office 2026-10-09 through the
// core API and by recomputing it from `authentik_core_user.id` + `authentik_install_id.id`.

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

// legacyCookieName is authentik's session cookie. Named here so the swap's one irreversible-looking
// fact — "the browser is holding THEIR cookie" — is visible in one place.
const legacyCookieName = "authentik_session"

// legacyIssuer is what authentik puts in `iss`. Checked, because a JWT this program can verify is
// not automatically a JWT from the identity service we are migrating FROM.
const legacyIssuer = "authentik"

// legacySigningKey derives the HMAC key from authentik's own secret, exactly as its middleware does:
// `SIGNING_HASH = sha512(settings.SECRET_KEY.encode()).hexdigest()`, and PyJWT is handed that string
// as an HS256 key. Reproduced here rather than asking the operator for the derived value, so the one
// secret that has to move is the one authentik already holds and `.env` already names.
func legacySigningKey(secretKey string) []byte {
	sum := sha512.Sum512([]byte(secretKey))
	return []byte(hex.EncodeToString(sum[:]))
}

// legacyEntry is one live authentik session: who it belongs to and when authentik itself would have
// stopped honouring it.
type legacyEntry struct {
	username string
	exp      time.Time
}

// legacySessions is the snapshot, held in memory from boot to the end of the process — the same
// lifetime as the user store, for the same reason (one read, no store to ask).
type legacySessions struct {
	bySID map[string]legacyEntry
	// latest is the newest expiry in the file. Once the clock passes it, no legacy cookie can be
	// accepted any more, so the whole reader is dead weight and says so once.
	latest time.Time
}

// loadLegacySessions reads the snapshot. Format, one session per line, `#` comments and blanks
// ignored:
//
//	<sid> <username> <expiry-unix-seconds>
//
// `<sid>` is authentik's session key (32 characters, `[a-z0-9]`). The file is produced by ONE
// read-only query against authentik's Postgres at the window; the query is in the design note.
// A malformed line is fatal, for the same reason a malformed users line is fatal: a snapshot that
// silently lost the line you are standing in front of looks exactly like "your session expired".
func loadLegacySessions(path string) (*legacySessions, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	ls := &legacySessions{bySID: map[string]legacyEntry{}}
	for i, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		f := strings.Fields(line)
		if len(f) != 3 {
			return nil, fmt.Errorf("%s:%d: want 3 fields (sid username expiry-unix), got %d", path, i+1, len(f))
		}
		secs, err := strconv.ParseInt(f[2], 10, 64)
		if err != nil {
			return nil, fmt.Errorf("%s:%d: expiry %q is not a unix timestamp", path, i+1, f[2])
		}
		if _, dup := ls.bySID[f[0]]; dup {
			return nil, fmt.Errorf("%s:%d: duplicate session %q", path, i+1, f[0])
		}
		e := legacyEntry{username: f[1], exp: time.Unix(secs, 0)}
		ls.bySID[f[0]] = e
		if e.exp.After(ls.latest) {
			ls.latest = e.exp
		}
	}
	if len(ls.bySID) == 0 {
		return nil, fmt.Errorf("%s: no sessions — accepting nothing is the same as not being configured", path)
	}
	return ls, nil
}

// read answers with the identity behind an authentik session cookie, or with errBadCookie — the SAME
// error every other refusal returns, so a caller cannot learn which half of a forgery to work on.
//
// The order is the order of what an attacker can influence: signature first (forging it needs the
// secret), then the claims that are ours to trust only once the signature holds, then the liveness
// snapshot, and only then the user store.
func (l *legacySessions) read(r *http.Request, now time.Time, key []byte, store *userStore) (*session, error) {
	c, err := r.Cookie(legacyCookieName)
	if err != nil {
		return nil, errBadCookie
	}
	claims, err := verifyLegacyJWT(c.Value, key)
	if err != nil {
		return nil, errBadCookie
	}
	if iss, _ := claims["iss"].(string); iss != legacyIssuer {
		return nil, errBadCookie
	}
	// An anonymous session (one that has not signed in) is a real, valid cookie — `sub` is literally
	// "anonymous" and `authenticated` is false. It is not a session anybody may be let in on.
	if authed, _ := claims["authenticated"].(bool); !authed {
		return nil, errBadCookie
	}
	sid, _ := claims["sid"].(string)
	sub, _ := claims["sub"].(string)
	if sid == "" || sub == "" || sub == "anonymous" {
		return nil, errBadCookie
	}
	e, live := l.bySID[sid]
	if !live || !now.Before(e.exp) {
		return nil, errBadCookie
	}
	u, ok := store.byName[e.username]
	if !ok {
		return nil, errBadCookie
	}
	// The JWT names the user by uid and the snapshot names them by username. Both must agree, so a
	// snapshot line that was copied next to the wrong sid is refused instead of trusted.
	if u.UID != sub {
		return nil, errBadCookie
	}
	return &session{User: u, Exp: e.exp}, nil
}

// verifyLegacyJWT is an HS256-only JWT check, written out rather than pulled in: the module is
// stdlib-only on purpose (it is what makes one host cross-compile the office's identity service to
// every OS), and this is forty lines of a published construction (RFC 7519 §3.1, RFC 7515 §5.2).
//
// `alg` is REQUIRED to be HS256 and matched by exact string. That single check is what refuses the
// classic JWT forgery — a token whose header says `none`, or `RS256` verified as if the public key
// were the HMAC secret — so it is the first thing looked at and the one thing never relaxed.
func verifyLegacyJWT(token string, key []byte) (map[string]any, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, errors.New("legacy jwt: not three dot-separated parts")
	}
	headerRaw, err := b64urlDecode(parts[0])
	if err != nil {
		return nil, fmt.Errorf("legacy jwt: header: %w", err)
	}
	var header struct {
		Alg string `json:"alg"`
		Typ string `json:"typ"`
	}
	if err := json.Unmarshal(headerRaw, &header); err != nil {
		return nil, fmt.Errorf("legacy jwt: header: %w", err)
	}
	if header.Alg != "HS256" {
		return nil, fmt.Errorf("legacy jwt: alg is %q, only HS256 is accepted", header.Alg)
	}
	sig, err := b64urlDecode(parts[2])
	if err != nil {
		return nil, fmt.Errorf("legacy jwt: signature: %w", err)
	}
	mac := hmac.New(sha256.New, key) // HS256: HMAC-SHA256 over "<header>.<payload>", verbatim
	mac.Write([]byte(parts[0] + "." + parts[1]))
	if !hmac.Equal(sig, mac.Sum(nil)) {
		return nil, errors.New("legacy jwt: signature does not verify")
	}
	payloadRaw, err := b64urlDecode(parts[1])
	if err != nil {
		return nil, fmt.Errorf("legacy jwt: payload: %w", err)
	}
	var claims map[string]any
	if err := json.Unmarshal(payloadRaw, &claims); err != nil {
		return nil, fmt.Errorf("legacy jwt: payload: %w", err)
	}
	return claims, nil
}

// b64urlDecode accepts the unpadded base64url PyJWT writes AND the padded spelling, because a
// signature is not a formatting contest — the HMAC comparison right after it is what decides.
func b64urlDecode(s string) ([]byte, error) {
	return base64.RawURLEncoding.DecodeString(strings.TrimRight(s, "="))
}

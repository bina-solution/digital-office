package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// The per-host hand-off (review finding F1, .claude/needs-azaria.md §2).
//
// WHY IT EXISTS: the session cookie is minted by `POST auth.<domain>/login`, so it is a cookie OF the
// auth host. On a `.localhost` office a browser never sends it to `console.localhost` — Chromium and
// Firefox refuse a Domain cookie on a single-label domain, so FORWARD_AUTH_COOKIE_DOMAIN=.localhost
// cannot rescue it — and every gated host would answer 302 → login → 303 → 302 for ever.
//
// THE SHAPE: the sign-in page sends the browser back to the app with `?dgo_code=<code>`. The code
// names the person and the ONE host it is for, lives 60 s, and is good once. When traefik asks
// /auth/traefik about that request, this service redeems the code and answers 302 to the same URL
// without it, WITH `Set-Cookie: dgo_session` — traefik hands a non-2xx auth answer to the browser
// verbatim, so the cookie lands on the app host, host-only. The next host the person opens does the
// same round trip; the auth host still holds its own cookie, so the sign-in page answers with a code
// at once instead of asking again. No host table, no domain cookie.

// THE STATE (the OAuth `state` pattern; the second reader's login-CSRF finding): when an app host sends
// a browser to sign in, it also gives that browser a short-lived host-only cookie, `dgo_state`, and
// passes only its SHA-256 (`st`) to the sign-in page. A code carries that hash, and redeems only for a
// browser that holds the matching cookie. So a code is good in the ONE browser that started the round
// trip: somebody who is a user here cannot mint a code of their own and plant it in a victim's
// browser by a link, because they cannot know the hash of a cookie that lives in the victim's browser.
// It is also why a code that leaked (a log, an address bar) is useless anywhere else.

const (
	codeParam  = "dgo_code"
	codeTTL    = 60 * time.Second
	stateName  = "dgo_state"
	stateParam = "st"
	stateTTL   = 10 * time.Minute
)

// stateCookie is the state cookie's name: `__Host-dgo_state` wherever cookies are Secure (an https
// edge), which the browser accepts only from this very host, with no Domain — so on a real domain a
// sibling app cannot plant one whose value it knows and bring login CSRF back (the third reader). On a
// plain-http `.localhost` edge the prefix is unavailable, and every host is its own site anyway.
func (s *server) stateCookie() string {
	if s.secureCookie {
		return "__Host-" + stateName
	}
	return stateName
}

// stateHash is what travels for a state cookie's value: its SHA-256, hex.
func stateHash(token string) string {
	h := sha256.Sum256([]byte(token))
	return hex.EncodeToString(h[:])
}

// okState is a state hash as it may travel: 64 lowercase hex characters.
func okState(st string) bool {
	if len(st) != 2*sha256.Size {
		return false
	}
	for _, c := range st {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

// handoff mints and redeems the codes. Its key is DERIVED from the session key rather than equal to
// it, so a code can never be presented as a session cookie or the other way round.
type handoff struct {
	key  []byte
	mu   sync.Mutex
	used map[string]time.Time // a redeemed code's MAC → when it would have expired anyway
}

func newHandoff(sessionKey []byte) *handoff {
	m := hmac.New(sha256.New, sessionKey)
	m.Write([]byte("forward-auth per-host hand-off code v1"))
	return &handoff{key: m.Sum(nil), used: map[string]time.Time{}}
}

func (h *handoff) mac(enc string) string {
	m := hmac.New(sha256.New, h.key)
	m.Write([]byte(enc))
	return base64.RawURLEncoding.EncodeToString(m.Sum(nil))
}

// mint returns a code for name on host, bound to the browser whose state cookie hashes to st. The body
// is "<name>\n<host>\n<unix expiry>\n<st>\n<nonce>", base64url as a whole, then "." and its MAC: every
// character is URL-safe, so it is appended to a query string as it is.
func (h *handoff) mint(name, host, st string, now time.Time) string {
	body := name + "\n" + strings.ToLower(host) + "\n" + strconv.FormatInt(now.Add(codeTTL).Unix(), 10) +
		"\n" + st + "\n" + randomToken(12)
	enc := base64.RawURLEncoding.EncodeToString([]byte(body))
	return enc + "." + h.mac(enc)
}

// redeem answers the name a code was minted for — only if it is genuine, for THIS host, for the
// browser holding the state cookie whose value is stateToken, unexpired, and not redeemed before.
// Every refusal is the same "", false.
func (h *handoff) redeem(code, host, stateToken string, now time.Time) (string, bool) {
	name, _, ok := h.redeemAt(code, host, stateToken, now)
	return name, ok
}

// redeemAt is redeem, also answering the second the code was minted in — what sign-out compares it to.
func (h *handoff) redeemAt(code, host, stateToken string, now time.Time) (string, time.Time, bool) {
	enc, sig, ok := strings.Cut(code, ".")
	if !ok || !hmac.Equal([]byte(sig), []byte(h.mac(enc))) {
		return "", time.Time{}, false
	}
	raw, err := base64.RawURLEncoding.DecodeString(enc)
	if err != nil {
		return "", time.Time{}, false
	}
	f := strings.Split(string(raw), "\n")
	if len(f) != 5 {
		return "", time.Time{}, false
	}
	expUnix, err := strconv.ParseInt(f[2], 10, 64)
	if err != nil {
		return "", time.Time{}, false
	}
	exp := time.Unix(expUnix, 0)
	if !now.Before(exp) || f[1] != strings.ToLower(host) {
		return "", time.Time{}, false
	}
	if stateToken == "" || subtle.ConstantTimeCompare([]byte(f[3]), []byte(stateHash(stateToken))) != 1 {
		return "", time.Time{}, false
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	// Single use. The set holds only live codes: one a minute is what a person makes, and an
	// expired one is refused by its own clock before it is ever looked up here.
	for c, e := range h.used {
		if !now.Before(e) {
			delete(h.used, c)
		}
	}
	if _, seen := h.used[sig]; seen {
		return "", time.Time{}, false
	}
	h.used[sig] = exp
	return f[0], exp.Add(-codeTTL), true
}

// burn spends a genuine code without redeeming it: it is refused for the rest of its minute.
func (h *handoff) burn(code string) {
	enc, sig, ok := strings.Cut(code, ".")
	if !ok || !hmac.Equal([]byte(sig), []byte(h.mac(enc))) {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	h.used[sig] = time.Now().Add(codeTTL)
}

// withCode appends the code to a return-to URL, keeping its own query exactly as it was.
func withCode(rd, code string) string {
	u, err := url.Parse(rd)
	if err != nil {
		return rd
	}
	if u.RawQuery == "" {
		u.RawQuery = codeParam + "=" + code
	} else {
		u.RawQuery += "&" + codeParam + "=" + code
	}
	return u.String()
}

// takeCode splits a request URI into the URI without any dgo_code and the LAST code it carried (a
// stale code from an earlier round trip is dropped with the rest). The other parameters keep their
// order and their spelling: the app gets back exactly the URL it was asked for.
func takeCode(uri string) (clean, code string) {
	path, query, hasQuery := strings.Cut(uri, "?")
	if !hasQuery {
		return uri, ""
	}
	var kept []string
	for _, p := range strings.Split(query, "&") {
		if v, ok := strings.CutPrefix(p, codeParam+"="); ok {
			code = v
			continue
		}
		if p == codeParam {
			continue
		}
		kept = append(kept, p)
	}
	if len(kept) == 0 {
		return path, code
	}
	return path + "?" + strings.Join(kept, "&"), code
}

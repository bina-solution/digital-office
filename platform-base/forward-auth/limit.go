package main

import (
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
)

// The brute-force limit on POST /login and POST /setup (review finding F2, .claude/needs-azaria.md §2).
//
// WHY: authentik had lockout and reputation; without a limit every attempt here costs a full password
// check (210k–720k PBKDF2 iterations) on a host the VPS exposes to the internet, with no backoff. So
// attempts are counted per CLIENT ADDRESS and per (NAME, ADDRESS): 5 failures block that key for 60 s,
// each later block doubles, up to an hour. While a key is blocked the answer is 429 + Retry-After and
// the password is not even checked — the right one included: a guesser who hits the right password
// inside a block learns nothing.
//
// Deliberately NOT per name alone: that would let any stranger lock the owner out of his own office
// with five requests (the second reader of the first version). A distributed guesser gets five tries
// per address per window, each costing a full PBKDF2 — against a 12-character minimum.
//
// ATTEMPTS, not just failures, are counted while they run: an attempt reserves its place before the
// password is checked (begin) and settles after (end), so N parallel requests cannot all slip in under
// one window's five.
//
// In memory, on purpose: one identity service per office, and a restart that forgets the counts costs
// an attacker one restart per five guesses, which is not something they can cause.

const (
	limitFails = 5
	limitFirst = time.Minute
	limitMax   = time.Hour
	// a key that is not blocked and has been quiet this long — counted from the END of its last block,
	// or from its last failure when it never had one — is forgotten
	limitForget = time.Hour
	// the map is pruned of forgotten keys whenever it grows past this…
	limitPrune = 4096
	// …and past this, of every key that is not blocked right now (a flood of fresh addresses must not
	// grow the map without bound; it cannot unblock anyone either)
	limitHard = 100000
	// a name longer than this is not a name; it is keyed by its first bytes
	limitName = 64
)

type strike struct {
	fails    int       // failures since the last block (or since the first one)
	inflight int       // attempts that reserved a place and have not settled
	level    int       // how many blocks this key has had; the next lasts limitFirst << level
	until    time.Time // blocked until
	last     time.Time // the last failure
}

// quiet is when this key stopped being interesting: the end of its block, or its last failure.
func (s *strike) quiet() time.Time {
	if s.until.After(s.last) {
		return s.until
	}
	return s.last
}

type limiter struct {
	mu sync.Mutex
	by map[string]*strike
}

func newLimiter() *limiter { return &limiter{by: map[string]*strike{}} }

// begin reserves an attempt against every key. It answers 0 and the attempt may go ahead (and must be
// settled with end), or how long the longest block still runs — a key blocked, or a key whose failures
// plus running attempts already fill its window — and nothing is reserved.
func (l *limiter) begin(now time.Time, keys ...string) time.Duration {
	l.mu.Lock()
	defer l.mu.Unlock()
	var left time.Duration
	for _, k := range keys {
		s, ok := l.by[k]
		if !ok {
			continue
		}
		if now.Before(s.until) {
			if d := s.until.Sub(now); d > left {
				left = d
			}
		} else if s.fails+s.inflight >= limitFails && left < time.Second {
			left = time.Second // the window is full of attempts still running; try again in a moment
		}
	}
	if left > 0 {
		return left
	}
	l.prune(now)
	for _, k := range keys {
		s, ok := l.by[k]
		if !ok || (!now.Before(s.until) && s.inflight == 0 && now.Sub(s.quiet()) > limitForget) {
			s = &strike{}
			l.by[k] = s
		}
		s.inflight++
	}
	return 0
}

// end settles an attempt begin reserved: a failure counts against every key, and the fifth since the
// last block starts the next; a success ends the count for every key.
func (l *limiter) end(now time.Time, ok bool, keys ...string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	for _, k := range keys {
		s, found := l.by[k]
		if !found {
			continue
		}
		if s.inflight > 0 {
			s.inflight--
		}
		if ok {
			if s.inflight == 0 {
				delete(l.by, k)
			} else {
				s.fails, s.level, s.until = 0, 0, time.Time{}
			}
			continue
		}
		s.fails++
		s.last = now
		if s.fails >= limitFails {
			d := limitFirst << s.level
			if d > limitMax || d <= 0 {
				d = limitMax
			} else {
				s.level++
			}
			s.until = now.Add(d)
			s.fails = 0
		}
	}
}

// prune keeps the map bounded. Called with the lock held.
func (l *limiter) prune(now time.Time) {
	if len(l.by) <= limitPrune {
		return
	}
	for k, s := range l.by {
		if !now.Before(s.until) && s.inflight == 0 && now.Sub(s.quiet()) > limitForget {
			delete(l.by, k)
		}
	}
	if len(l.by) <= limitHard {
		return
	}
	for k, s := range l.by {
		if !now.Before(s.until) && s.inflight == 0 {
			delete(l.by, k)
		}
	}
}

// limitKeys are what an attempt is counted against: the address, and the name at that address.
func limitKeys(name string, r *http.Request) []string {
	name = strings.ToLower(name)
	if len(name) > limitName {
		name = name[:limitName]
	}
	ip := clientKey(clientIP(r))
	return []string{"ip:" + ip, "user:" + name + "|" + ip}
}

// clientIP is the address the request came from: the LAST hop of X-Forwarded-For, which is the peer
// the edge in front of this service saw — the one entry a client cannot write. (traefik, trusting no
// forwarded headers by default, replaces the header outright; were it ever told to trust some, the
// client-written hops would come FIRST.) Without the header, the socket's peer.
func clientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		hops := strings.Split(xff, ",")
		if ip := strings.TrimSpace(hops[len(hops)-1]); ip != "" {
			return ip
		}
	}
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return host
	}
	return r.RemoteAddr
}

// clientKey is the address as a limit counts it: an IPv6 address by its /64 (one subscriber gets a
// whole /64, and counting each of its 2^64 addresses apart would be no limit at all); anything else as
// it is.
func clientKey(ip string) string {
	if a := net.ParseIP(ip); a != nil && a.To4() == nil {
		return a.Mask(net.CIDRMask(64, 128)).String() + "/64"
	}
	return ip
}

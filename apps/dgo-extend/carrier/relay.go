package main

// relay.go — the hub's relay (DGO-1097): two offices that cannot reach each other, both of which reach
// the hub's link door over HTTPS, meet THERE. The door joins the two connections of one pair and copies
// bytes between them. The pair's own handshake (wire.go) and WireGuard run end to end over the joined
// connection, so the hub holds no key of the pair, sees no plaintext and routes nothing: its firewall's
// `forward` chain stays `policy drop` (firewall.py, "no relay between two peers" at the IP layer). It is
// the role Tailscale's DERP plays, for the MacBook away from home and the HP and the Dell left there
// (the owner, 2026-11-01: «no matter where I am, everything keeps working»).
//
// THE PROTOCOL. `GET /relay?tag=<64 hex>&side=dial|accept`, upgraded to a websocket (ws.go). The tag is
// the pair's own (`pairTag`: the dialer's key, then the acceptor's), so both ends name the same meeting
// without telling the hub anything it could not compute from two public keys. The door joins a `dial`
// with an `accept` of the same tag, writes `relayMatched` to both, and from then on only copies. A side
// that arrives first waits up to `parkFor` and is then let go to come again (an edge closes a connection
// that says nothing for long). A newer connection of the same side replaces the one that waits, and a
// newer join of a pair replaces its older one: a peer that came back from another address, the same
// rule as `attach`'s — the newest wins.
//
// DECLARED, NOT OPEN, AND BOUNDED. The door joins only the tags its plan lists (`relay_tags`, rendered by
// the app from `DGO_RELAY_FOR`); any other is refused with 403 before the upgrade, and counted. A tag is
// no secret (two public keys make it, and a dialer says it to every address it tries), so whoever knows
// one is bounded like everybody: one live join per pair, `maxJoined` joins and `maxParked` waiting sides
// over all, `maxParkedPerSource` waiting sides per address (503 before the upgrade), and a join that
// carries nothing for `relayIdle` is ended — a live pair pings every 10 s (carry.go). What he cannot do
// is take a pair's place: the pair's handshake refuses him, and the real side's next connection replaces
// him.
//
// THE PAIR'S SIDE. A pair whose plan names a `fallback_relay` takes it when it has gone `relayAfter`
// without a session, while its direct way (an address, a LAN search, or the peer dialing in) goes on
// being tried. A relayed dialer tries its direct way again every `upgradeEvery`; a direct session always
// replaces a relayed one and a relayed one never replaces a live direct one (`attach`): the pair is back
// on its LAN with nobody doing anything.

import (
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// relayMatched is what the door says to both sides once it has joined them: from here on, the bytes are
// the other side's.
const relayMatched = "DGORLY1\n"

var (
	// parkFor bounds how long a side waits at the hub for the other one before it is let go.
	parkFor = 90 * time.Second
	// relayAfter is how long a pair goes without a session before it takes the hub's relay. Its direct
	// way is not given up: a LAN peer that answers in this time never touches the hub.
	relayAfter = 20 * time.Second
	// upgradeEvery is how often a relayed dialer tries its direct way again.
	upgradeEvery = 30 * time.Second
	// relayIdle ends a join that carried nothing this long, in either direction.
	relayIdle = 60 * time.Second
	// maxParked, maxJoined and maxParkedPerSource bound what the door holds for other offices.
	maxParked          = 256
	maxJoined          = 256
	maxParkedPerSource = 8
)

// errNobodyCame is the ordinary end of a wait at the hub: the other side was not there within parkFor.
var errNobodyCame = errors.New("nobody came")

type parked struct {
	conn  net.Conn
	src   string
	taken chan struct{} // closed when the connection stops waiting: joined, replaced or let go
}

type joinedPair struct{ a, b net.Conn }

func (j *joinedPair) close() {
	_ = j.a.Close()
	_ = j.b.Close()
}

// relayHub is the door's meeting place: per tag, at most one waiting connection per side and one join.
type relayHub struct {
	mu      sync.Mutex
	waiting map[[tagLen]byte]map[string]*parked
	count   int
	bySrc   map[string]int
	live    map[[tagLen]byte]*joinedPair
	joined  atomic.Uint64
	refused atomic.Uint64
}

func newRelayHub() *relayHub {
	return &relayHub{waiting: map[[tagLen]byte]map[string]*parked{}, bySrc: map[string]int{},
		live: map[[tagLen]byte]*joinedPair{}}
}

// parseRelay reads the meeting a request names: its tag and its side.
func parseRelay(r *http.Request) (tag [tagLen]byte, side string, ok bool) {
	q := r.URL.Query()
	side = q.Get("side")
	raw, err := hex.DecodeString(q.Get("tag"))
	if err != nil || len(raw) != tagLen || (side != "dial" && side != "accept") {
		return tag, "", false
	}
	copy(tag[:], raw)
	return tag, side, true
}

func otherSide(side string) string {
	if side == "dial" {
		return "accept"
	}
	return "dial"
}

// full says whether the door can take one more side from src now.
func (h *relayHub) full(src string) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.count >= maxParked || len(h.live) >= maxJoined || h.bySrc[src] >= maxParkedPerSource
}

// meet takes conn into the meeting place of tag: joined with the other side if it waits there, waiting
// otherwise. It returns at once; the join, or the wait, goes on in a goroutine of its own.
func (h *relayHub) meet(conn net.Conn, tag [tagLen]byte, side, src string) {
	h.mu.Lock()
	place := h.waiting[tag]
	if w := place[otherSide(side)]; w != nil {
		h.drop(tag, otherSide(side))
		j := &joinedPair{a: w.conn, b: conn}
		older := h.live[tag]
		h.live[tag] = j
		h.mu.Unlock()
		close(w.taken)
		if older != nil {
			older.close() // the newest join of a pair wins
		}
		h.joined.Add(1)
		go h.splice(tag, j)
		return
	}
	old := place[side]
	if old == nil && (h.count >= maxParked || h.bySrc[src] >= maxParkedPerSource) {
		h.mu.Unlock()
		h.refused.Add(1)
		_ = conn.Close()
		return
	}
	if place == nil {
		place = map[string]*parked{}
		h.waiting[tag] = place
	}
	if old == nil {
		h.count++
	} else {
		h.forget(old.src)
	}
	h.bySrc[src]++
	p := &parked{conn: conn, src: src, taken: make(chan struct{})}
	place[side] = p
	h.mu.Unlock()
	if old != nil {
		close(old.taken)
		_ = old.conn.Close()
	}
	go func() {
		t := time.NewTimer(parkFor)
		defer t.Stop()
		select {
		case <-p.taken:
		case <-t.C:
			h.mu.Lock()
			mine := h.waiting[tag][side] == p
			if mine {
				h.drop(tag, side)
			}
			h.mu.Unlock()
			if mine {
				_ = conn.Close()
			}
		}
	}()
}

// drop removes one waiting side; the caller holds h.mu.
func (h *relayHub) drop(tag [tagLen]byte, side string) {
	place := h.waiting[tag]
	p := place[side]
	if p == nil {
		return
	}
	delete(place, side)
	h.count--
	h.forget(p.src)
	if len(place) == 0 {
		delete(h.waiting, tag)
	}
}

// forget takes one waiting side off src's count; the caller holds h.mu.
func (h *relayHub) forget(src string) {
	if h.bySrc[src]--; h.bySrc[src] <= 0 {
		delete(h.bySrc, src)
	}
}

func (h *relayHub) waitingNow() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.count
}

// splice runs one join: each side is told it met the other, then bytes are copied both ways until either
// end goes or the join carries nothing for relayIdle, and both are closed.
func (h *relayHub) splice(tag [tagLen]byte, j *joinedPair) {
	defer func() {
		j.close()
		h.mu.Lock()
		if h.live[tag] == j {
			delete(h.live, tag)
		}
		h.mu.Unlock()
	}()
	for _, c := range []net.Conn{j.a, j.b} {
		_ = c.SetWriteDeadline(time.Now().Add(writeTimeout))
		if _, err := io.WriteString(c, relayMatched); err != nil {
			return
		}
		_ = c.SetWriteDeadline(time.Time{})
	}
	done := make(chan struct{}, 2)
	go func() { copyIdle(j.a, j.b); done <- struct{}{} }()
	go func() { copyIdle(j.b, j.a); done <- struct{}{} }()
	<-done
}

// copyIdle copies src to dst until either fails or src says nothing for relayIdle.
func copyIdle(dst, src net.Conn) {
	buf := make([]byte, 32<<10)
	for {
		_ = src.SetReadDeadline(time.Now().Add(relayIdle))
		n, err := src.Read(buf)
		if n > 0 {
			_ = dst.SetWriteDeadline(time.Now().Add(writeTimeout))
			if _, werr := dst.Write(buf[:n]); werr != nil {
				return
			}
		}
		if err != nil {
			return
		}
	}
}

// relay is the door's `/relay`: a declared pair's side, taken into its meeting place.
func (d *door) relay(w http.ResponseWriter, r *http.Request, src string) {
	tag, side, ok := parseRelay(r)
	if !ok {
		http.Error(w, "a relay names its pair's tag (64 hex) and its side (dial or accept)", http.StatusBadRequest)
		return
	}
	if !d.c.relays(tag) {
		d.c.hub.refused.Add(1)
		http.Error(w, "this door relays no such pair", http.StatusForbidden)
		return
	}
	if d.c.hub.full(src) {
		d.c.hub.refused.Add(1)
		w.Header().Set("Retry-After", "30")
		http.Error(w, "the relay holds all it may now — try again shortly", http.StatusServiceUnavailable)
		return
	}
	conn, err := acceptWS(w, r, src)
	if err != nil {
		return
	}
	d.c.hub.meet(conn, tag, side, src)
}

// relays says whether the plan declares tag as a pair this office's door may join.
func (c *Carrier) relays(tag [tagLen]byte) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.relayTags[tag]
}

// relayTagsOf reads the plan's `relay_tags`; a tag that is not 64 hex is named and left out.
func relayTagsOf(raw []string) (map[[tagLen]byte]bool, []string) {
	out, bad := map[[tagLen]byte]bool{}, []string(nil)
	for _, s := range raw {
		b, err := hex.DecodeString(s)
		if err != nil || len(b) != tagLen {
			bad = append(bad, s)
			continue
		}
		var t [tagLen]byte
		copy(t[:], b)
		out[t] = true
	}
	return out, bad
}

// viaRelay meets the pair's peer at the hub: it waits there for the other side, then runs the pair's own
// handshake over the joined connection, in this side's role. A pair let go meanwhile (ctx) stops waiting
// at once.
func (p *pair) viaRelay(ctx context.Context, base string) (net.Conn, error) {
	dialer := p.dials()
	tag, side := pairTag(p.peerPub, p.keys.Public()), "accept"
	if dialer {
		tag, side = pairTag(p.keys.Public(), p.peerPub), "dial"
	}
	c, err := dialWS(ctx, fmt.Sprintf("%s?tag=%x&side=%s", base, tag[:], side), relayDialTimeout)
	if err != nil {
		return nil, err
	}
	stop := context.AfterFunc(ctx, func() { _ = c.Close() })
	began := time.Now()
	_ = c.SetReadDeadline(time.Now().Add(parkFor + relayDialTimeout))
	got := make([]byte, len(relayMatched))
	if _, err := io.ReadFull(c, got); err != nil {
		stop()
		_ = c.Close()
		if waited := time.Since(began); waited < parkFor/2 {
			// let go at once (the door was full, or another connection took this side's place): not a wait
			// that ended, so not to be repeated at once
			return nil, fmt.Errorf("%s let this side go after %s (%v)", base, waited.Round(time.Millisecond), err)
		}
		return nil, errNobodyCame
	}
	_ = c.SetReadDeadline(time.Time{})
	if string(got) != relayMatched {
		stop()
		_ = c.Close()
		return nil, fmt.Errorf("%s is not a relay this carrier speaks (%q)", base, got)
	}
	if dialer {
		err = DialHandshake(c, p.keys, p.peerPub, 0)
	} else {
		_, err = AcceptHandshake(c, p.keys, func(t [tagLen]byte) []byte {
			if t == tag {
				return p.peerPub
			}
			return nil
		})
	}
	if !stop() {
		_ = c.Close()
		return nil, errors.New("the pair was let go while it met its peer")
	}
	if err != nil {
		_ = c.Close()
		return nil, fmt.Errorf("the side met at %s does not hold this pair (%v)", base, err)
	}
	return c, nil
}

// relayLoop takes the hub's relay for a pair whose plan names one, whenever the pair has gone
// relayAfter without a session (see the top of this file).
func (p *pair) relayLoop() {
	backoff := minBackoff
	lost := time.Now()
	for {
		select {
		case <-p.stop:
			return
		default:
		}
		if s := p.current(); s != nil {
			select {
			case <-s.done:
				lost = time.Now()
			case <-p.stop:
				return
			}
			continue
		}
		p.mu.Lock()
		base := p.fallback
		p.mu.Unlock()
		if wait := relayAfter - time.Since(lost); base == "" || wait > 0 {
			if base == "" || wait > time.Second {
				wait = time.Second // a plan may add a relay, or a session may come up; looked at again soon
			}
			select {
			case <-time.After(wait):
			case <-p.stop:
				return
			}
			continue
		}
		ctx, cancel := context.WithCancel(context.Background())
		go func() {
			select {
			case <-p.stop:
				cancel()
			case <-ctx.Done():
			}
		}()
		conn, err := p.viaRelay(ctx, base)
		cancel()
		if errors.Is(err, errNobodyCame) {
			backoff = minBackoff
			continue // the other side was not there: wait for it again at once
		}
		if err != nil {
			p.mu.Lock()
			if p.sess == nil {
				p.lastErr = "relay: " + err.Error()
			}
			p.mu.Unlock()
			select {
			case <-time.After(backoff):
			case <-p.stop:
				return
			}
			if backoff *= 2; backoff > maxBackoff {
				backoff = maxBackoff
			}
			continue
		}
		backoff = minBackoff
		s := newSession(conn, p.dials())
		s.relayed = true
		p.attach(s) // refused (closed) by attach if a direct session came up meanwhile
	}
}

// checkFallback says why a pair's `fallback_relay` cannot be used ("" = it can). Unlike checkPair's
// refusals it costs the pair nothing: the pair is carried by its direct way, without the hub.
func checkFallback(p *pairConfig) string {
	if p.FallbackRelay == "" {
		return ""
	}
	u, err := url.Parse(p.FallbackRelay)
	if err != nil || (u.Scheme != "wss" && u.Scheme != "ws") || u.Hostname() == "" || u.User != nil ||
		!strings.HasPrefix(u.Path, "/") || u.RawQuery != "" || u.Fragment != "" {
		return fmt.Sprintf("fallback_relay %q is not a wss://host/path address", p.FallbackRelay)
	}
	if p.Relay != "" {
		return "a pair that rides a door already meets its peer at an edge: it takes no fallback relay"
	}
	return ""
}

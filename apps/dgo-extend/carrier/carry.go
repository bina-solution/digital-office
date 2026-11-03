package main

// carry.go — the pairs this office carries, the TCP connection each one rides, and how a dialing
// side finds its peer again.
//
// ONE CONNECTION PER PAIR, THE NEWEST WINS. A pair has at most one live session. When a second one
// is authenticated for the same pair (the peer reconnected from a new address while the old
// connection is still half-open, which is what a laptop that changed networks looks like from the
// other end), the new one replaces the old one. That rule is what makes roaming work with no
// coordination; it is safe because only one side of a pair dials (net.py renders it so).
//
// A DATAGRAM NEVER WAITS. WireGuard is built for a path that drops packets, and it retransmits what
// matters itself. So a datagram that finds no session, or a session whose send queue is full, is
// dropped and counted — never queued behind a slow connection, which would turn one stalled pair
// into a stalled interface.

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"log"
	"net"
	"net/netip"
	"sync"
	"sync/atomic"
	"time"
)

var (
	pingEvery    = 10 * time.Second
	deadAfter    = 35 * time.Second // three pings and then some: WireGuard's own keepalive is 25 s
	writeTimeout = 15 * time.Second
	dialTimeout  = 3 * time.Second
	minBackoff   = 2 * time.Second
	maxBackoff   = 30 * time.Second
	// A search sweeps every address of the office's LAN. Once per this interval at most: it is a few
	// hundred connection attempts, harmless on the owner's own network and not to be repeated by the
	// second anywhere else.
	scanEvery       = 30 * time.Second
	scanConnTimeout = 800 * time.Millisecond
	scanHandshake   = 3 * time.Second
	scanWorkers     = 64
	sendQueue       = 512
)

type session struct {
	conn   net.Conn
	via    string
	dialed bool
	since  time.Time
	out    chan []byte
	done   chan struct{}
	once   sync.Once
	lastRx atomic.Int64
	rttNs  atomic.Int64
	// relayed: the session crosses the hub's relay (relay.go), and the direct way is still looked for.
	relayed bool
}

func newSession(c net.Conn, dialed bool) *session {
	s := &session{conn: c, via: c.RemoteAddr().String(), dialed: dialed, since: time.Now(),
		out: make(chan []byte, sendQueue), done: make(chan struct{})}
	s.lastRx.Store(time.Now().UnixNano())
	if tc := tcpOf(c); tc != nil {
		_ = tc.SetNoDelay(true)
		_ = tc.SetKeepAlive(true)
		_ = tc.SetKeepAlivePeriod(15 * time.Second)
	}
	return s
}

func (s *session) close() {
	s.once.Do(func() {
		close(s.done)
		_ = s.conn.Close()
	})
}

func (s *session) alive() bool {
	select {
	case <-s.done:
		return false
	default:
		return true
	}
}

// send queues one frame and reports whether it was queued (a full queue drops it).
func (s *session) send(kind byte, payload []byte) bool {
	f := appendFrame(make([]byte, 0, frameHeadLen+len(payload)), kind, payload)
	select {
	case <-s.done:
		return false
	default:
	}
	select {
	case s.out <- f:
		return true
	default:
		return false
	}
}

func (s *session) writeLoop() {
	w := bufio.NewWriterSize(s.conn, 64<<10)
	for {
		select {
		case <-s.done:
			return
		case f := <-s.out:
			_ = s.conn.SetWriteDeadline(time.Now().Add(writeTimeout))
			_, _ = w.Write(f)
			// Whatever else is already queued goes out with it: one flush per burst, not per datagram.
			for more := true; more; {
				select {
				case g := <-s.out:
					_, _ = w.Write(g)
				default:
					more = false
				}
			}
			if err := w.Flush(); err != nil {
				s.close()
				return
			}
		}
	}
}

func (s *session) readLoop(deliver func([]byte)) {
	r := bufio.NewReaderSize(s.conn, 64<<10)
	buf := make([]byte, maxDatagram)
	for {
		kind, p, err := readFrame(r, buf)
		if err != nil {
			s.close()
			return
		}
		s.lastRx.Store(time.Now().UnixNano())
		switch kind {
		case frameData:
			deliver(p)
		case framePing:
			s.send(framePong, p)
		case framePong:
			if len(p) == 8 {
				s.rttNs.Store(time.Now().UnixNano() - int64(binary.BigEndian.Uint64(p)))
			}
		}
	}
}

func (s *session) keepalive() {
	t := time.NewTicker(pingEvery)
	defer t.Stop()
	for {
		select {
		case <-s.done:
			return
		case <-t.C:
			if time.Since(time.Unix(0, s.lastRx.Load())) > deadAfter {
				log.Printf("%s: nothing heard for %s — closed", s.via, deadAfter)
				s.close()
				return
			}
			var b [8]byte
			binary.BigEndian.PutUint64(b[:], uint64(time.Now().UnixNano()))
			s.send(framePing, b[:])
		}
	}
}

// pair is one WireGuard pair this office carries over TCP.
type pair struct {
	cfg     pairConfig
	peerPub []byte
	keys    *Keys
	udp     *net.UDPConn
	wg      *net.UDPAddr

	mu       sync.Mutex
	sess     *session
	dial     []string
	scan     []netip.Prefix
	port     int
	relay    string
	lastGood string
	lastScan time.Time
	lastErr  string
	ups      int
	// fallback is the hub's relay this pair takes when its direct way stays silent (relay.go).
	fallback string

	rx      atomic.Uint64 // bytes handed to the interface
	tx      atomic.Uint64 // bytes sent to the peer
	dropped atomic.Uint64 // datagrams with no session to ride, or a full queue
	stop    chan struct{}
	wake    chan struct{}
}

func startPair(cfg pairConfig, keys *Keys, remembered string) (*pair, error) {
	peerPub, err := decodeKey(cfg.PeerKey)
	if err != nil {
		return nil, err
	}
	udp, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: cfg.UDPPort})
	if err != nil {
		return nil, fmt.Errorf("%s: cannot hold 127.0.0.1:%d for the interface's endpoint: %w", cfg.Iface, cfg.UDPPort, err)
	}
	p := &pair{cfg: cfg, peerPub: peerPub, keys: keys, udp: udp,
		wg:   &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: cfg.WGPort},
		stop: make(chan struct{}), wake: make(chan struct{}, 1), lastGood: remembered}
	p.update(cfg)
	go p.udpLoop()
	go p.dialLoop()
	go p.relayLoop()
	return p, nil
}

// update takes a new plan's addresses for a pair whose identity did not change. `p.cfg` itself is
// never written after start (the logs read it unlocked); what a plan may change lives in the fields
// below, under p.mu.
func (p *pair) update(cfg pairConfig) {
	prefixes := make([]netip.Prefix, 0, len(cfg.Scan))
	for _, s := range cfg.Scan {
		if pfx, err := netip.ParsePrefix(s); err == nil {
			prefixes = append(prefixes, pfx.Masked())
		}
	}
	p.mu.Lock()
	p.dial = append([]string(nil), cfg.Dial...)
	p.scan = prefixes
	p.port = cfg.Port
	p.relay = cfg.Relay
	p.fallback = cfg.FallbackRelay
	if len(p.dial) == 0 && len(p.scan) == 0 || p.relay != "" {
		// This side waits to be dialed now. A remembered address is a dialer's memory: kept, an
		// office that became the one that accepts would go on dialing, and two ends that both dial
		// replace each other's session for ever (newest wins on both sides). A side that dials a
		// relay has no address of the peer's to remember either: the edge is the only way in.
		p.lastGood = ""
	}
	p.mu.Unlock()
	p.nudge()
}

func (p *pair) sameIdentity(cfg pairConfig) bool {
	return p.cfg.Iface == cfg.Iface && p.cfg.PeerKey == cfg.PeerKey && p.cfg.WGPort == cfg.WGPort &&
		p.cfg.UDPPort == cfg.UDPPort && p.cfg.Office == cfg.Office
}

func (p *pair) nudge() {
	select {
	case p.wake <- struct{}{}:
	default:
	}
}

func (p *pair) close() {
	select {
	case <-p.stop:
		return
	default:
	}
	close(p.stop)
	_ = p.udp.Close()
	p.mu.Lock()
	s := p.sess
	p.sess = nil
	p.mu.Unlock()
	if s != nil {
		s.close()
	}
}

func (p *pair) current() *session {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.sess
}

// dials says whether this side is the one that dials: the plan gave it an address, a LAN to search
// or a relay.
func (p *pair) dials() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return len(p.dial) > 0 || len(p.scan) > 0 || p.relay != ""
}

// attach makes s the pair's session (the newest wins). A pair that was let go in the meantime (a plan
// reload replaced it) takes nothing: the session is closed, so its peer redials the pair that is live.
func (p *pair) attach(s *session) {
	p.mu.Lock()
	select {
	case <-p.stop:
		p.mu.Unlock()
		s.close()
		return
	default:
	}
	old := p.sess
	if s.relayed && old != nil && !old.relayed && old.alive() {
		// The hub's relay is the way of last resort: it never replaces a pair's own way that answers.
		p.mu.Unlock()
		s.close()
		return
	}
	p.sess = s
	p.lastErr = ""
	p.ups++
	if _, relayed := s.conn.(*wsConn); s.dialed && !relayed {
		p.lastGood = s.via
	}
	p.mu.Unlock()
	if old != nil {
		old.close()
	}
	how := "accepted"
	if s.dialed {
		how = "dialed"
	}
	log.Printf("%s ⇄ %s: up via %s (%s)", p.cfg.Iface, p.cfg.Office, s.via, how)
	go s.writeLoop()
	go s.keepalive()
	go func() {
		s.readLoop(p.deliver)
		p.mu.Lock()
		mine := p.sess == s
		if mine {
			p.sess = nil
		}
		p.mu.Unlock()
		if mine {
			log.Printf("%s ⇄ %s: down after %s (via %s)", p.cfg.Iface, p.cfg.Office,
				time.Since(s.since).Round(time.Second), s.via)
			p.nudge()
		}
	}()
}

func (p *pair) deliver(datagram []byte) {
	if _, err := p.udp.WriteToUDP(datagram, p.wg); err == nil {
		p.rx.Add(uint64(len(datagram)))
	}
}

func (p *pair) udpLoop() {
	buf := make([]byte, maxDatagram)
	for {
		n, from, err := p.udp.ReadFromUDP(buf)
		if err != nil {
			select {
			case <-p.stop:
				return
			default:
			}
			time.Sleep(50 * time.Millisecond)
			continue
		}
		// Only the pair's own interface speaks to this socket. Anything else in the namespace that
		// sends here is not WireGuard, and the peer must never receive it.
		if from.Port != p.wg.Port || !from.IP.IsLoopback() {
			continue
		}
		s := p.current()
		if s == nil || !s.send(frameData, buf[:n]) {
			p.dropped.Add(1)
			continue
		}
		p.tx.Add(uint64(n))
	}
}

func (p *pair) dialLoop() {
	backoff := minBackoff
	for {
		select {
		case <-p.stop:
			return
		default:
		}
		if s := p.current(); s != nil {
			if !s.relayed || !p.dials() {
				select {
				case <-s.done:
				case <-p.stop:
					return
				}
				continue
			}
			// A session through the hub's relay: the direct way is tried again on its own clock, and an
			// answer replaces the relayed session (the newest wins) — the pair is back on its LAN.
			select {
			case <-s.done:
				continue
			case <-p.stop:
				return
			case <-time.After(upgradeEvery):
			}
			if conn, err := p.find(); err == nil {
				p.attach(newSession(conn, true))
			}
			continue
		}
		if !p.dials() {
			// This side waits to be dialed. A plan that adds an address to dial wakes it.
			select {
			case <-p.wake:
			case <-p.stop:
				return
			}
			continue
		}
		conn, err := p.find()
		if err != nil {
			p.mu.Lock()
			p.lastErr = err.Error()
			p.mu.Unlock()
			select {
			case <-time.After(backoff):
			case <-p.wake:
			case <-p.stop:
				return
			}
			if backoff *= 2; backoff > maxBackoff {
				backoff = maxBackoff
			}
			continue
		}
		backoff = minBackoff
		if cur := p.current(); cur != nil && !cur.relayed {
			_ = conn.Close() // the peer dialed in while we searched: its session stands
			continue
		}
		p.attach(newSession(conn, true)) // a direct way found while the pair rode the hub replaces it
	}
}

func dialPeer(ctx context.Context, addr string, keys *Keys, peerPub []byte, connect, handshake time.Duration) (net.Conn, error) {
	d := net.Dialer{Timeout: connect}
	c, err := d.DialContext(ctx, "tcp", addr)
	if err != nil {
		return nil, err
	}
	if err := DialHandshake(c, keys, peerPub, handshake); err != nil {
		_ = c.Close()
		return nil, fmt.Errorf("%s answered but does not hold this pair (%v)", addr, err)
	}
	return c, nil
}

// relayDialTimeout bounds the opening of a relayed connection: a proxy, TLS and the upgrade, over a
// path that may cross a continent.
var relayDialTimeout = 20 * time.Second

// dialRelay opens the pair's connection through the peer's HTTPS edge (ws.go) and proves the pair
// over it, exactly as over a TCP connection.
func dialRelay(ctx context.Context, relay string, keys *Keys, peerPub []byte) (net.Conn, error) {
	c, err := dialWS(ctx, relay, relayDialTimeout)
	if err != nil {
		return nil, err
	}
	if err := DialHandshake(c, keys, peerPub, handshakeTimeout); err != nil {
		_ = c.Close()
		return nil, fmt.Errorf("%s answered but does not hold this pair (%v)", relay, err)
	}
	return c, nil
}

// find dials the addresses this pair knows, then searches the LAN for the peer — or, for a pair
// whose peer is behind an HTTPS edge, dials the relay and nothing else.
func (p *pair) find() (net.Conn, error) {
	p.mu.Lock()
	relay := p.relay
	p.mu.Unlock()
	if relay != "" {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		go func() {
			select {
			case <-p.stop:
				cancel()
			case <-ctx.Done():
			}
		}()
		return dialRelay(ctx, relay, p.keys, p.peerPub)
	}
	p.mu.Lock()
	cands := uniq(append([]string{p.lastGood}, p.dial...))
	scan := append([]netip.Prefix(nil), p.scan...)
	port := p.port
	due := len(scan) > 0 && time.Since(p.lastScan) >= scanEvery
	if due {
		p.lastScan = time.Now()
	}
	p.mu.Unlock()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() {
		select {
		case <-p.stop:
			cancel()
		case <-ctx.Done():
		}
	}()
	var last error
	for _, a := range cands {
		c, err := dialPeer(ctx, a, p.keys, p.peerPub, dialTimeout, handshakeTimeout)
		if err == nil {
			return c, nil
		}
		last = err
	}
	if due {
		c, addr, err := scanFor(ctx, scan, port, p.keys, p.peerPub, cands)
		if err == nil {
			log.Printf("%s ⇄ %s: found at %s", p.cfg.Iface, p.cfg.Office, addr)
			return c, nil
		}
		last = err
	}
	if last == nil {
		last = errors.New("no address to dial yet — the next search is due shortly")
	}
	return nil, last
}

// scanFor connects to every address of `prefixes` on `port` and returns the first that proves it
// holds this pair. Addresses in `skip` were just tried.
func scanFor(ctx context.Context, prefixes []netip.Prefix, port int, keys *Keys, peerPub []byte,
	skip []string) (net.Conn, string, error) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	tried := map[string]bool{}
	for _, s := range skip {
		tried[s] = true
	}
	jobs := make(chan string)
	type hit struct {
		c    net.Conn
		addr string
	}
	hits := make(chan hit, 1)
	var wg sync.WaitGroup
	for i := 0; i < scanWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for a := range jobs {
				c, err := dialPeer(ctx, a, keys, peerPub, scanConnTimeout, scanHandshake)
				if err != nil {
					continue
				}
				select {
				case hits <- hit{c, a}:
					cancel()
				default:
					_ = c.Close() // a second answer to the same search: the first one stands
				}
			}
		}()
	}
	n := 0
feed:
	for _, pfx := range prefixes {
		for _, ip := range hostsOf(pfx) {
			a := netip.AddrPortFrom(ip, uint16(port)).String()
			if tried[a] {
				continue
			}
			n++
			select {
			case jobs <- a:
			case <-ctx.Done():
				break feed
			}
		}
	}
	close(jobs)
	wg.Wait()
	select {
	case h := <-hits:
		return h.c, h.addr, nil
	default:
	}
	return nil, "", fmt.Errorf("searched %d address(es) on %v: the peer did not answer on port %d", n, prefixes, port)
}

// hostsOf lists the host addresses of an IPv4 prefix (network and broadcast left out).
func hostsOf(pfx netip.Prefix) []netip.Addr {
	if !pfx.Addr().Is4() || pfx.Bits() < 16 {
		return nil
	}
	var out []netip.Addr
	first := pfx.Masked().Addr()
	size := 1 << (32 - pfx.Bits())
	a := first
	for i := 0; i < size; i++ {
		if (i != 0 && i != size-1) || size <= 2 {
			out = append(out, a)
		}
		a = a.Next()
	}
	return out
}

func uniq(in []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range in {
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}

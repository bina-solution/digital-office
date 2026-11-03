package main

// The carrier's contract, as tests: the handshake admits exactly the two holders of a pair's keys,
// a datagram crosses in both directions, a dialing side comes back after its connection dies, a
// dialing side that knows no address FINDS its peer by searching, and one bad pair in a plan leaves
// the others carried. Everything runs on loopback with real sockets and real keys — nothing is
// stubbed, because what breaks in a path is the sockets.

import (
	"bufio"
	"bytes"
	"context"
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestMain(m *testing.M) {
	minBackoff = 100 * time.Millisecond
	maxBackoff = 400 * time.Millisecond
	reloadEvery = 100 * time.Millisecond
	stateEvery = 100 * time.Millisecond
	scanConnTimeout = 300 * time.Millisecond
	// A search that found nothing is repeated on this clock: in a test, the peer's carrier may start
	// a moment after the dialer's first search.
	scanEvery = 300 * time.Millisecond
	// The hub's relay (relay.go) on a test's clock: a side waits a second at the hub, a pair takes the
	// relay after 300 ms without a session, and a relayed dialer looks for its direct way as often.
	parkFor = time.Second
	relayAfter = 300 * time.Millisecond
	upgradeEvery = 300 * time.Millisecond
	os.Exit(m.Run())
}

func newKeys(t *testing.T) (*Keys, []byte) {
	t.Helper()
	priv, err := ecdh.X25519().GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	k, err := NewKeys(priv.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	return k, priv.Bytes()
}

func b64(b []byte) string { return base64.StdEncoding.EncodeToString(b) }

func TestHandshakeAdmitsThePair(t *testing.T) {
	a, _ := newKeys(t)
	b, _ := newKeys(t)
	ca, cb := net.Pipe()
	done := make(chan error, 1)
	go func() { done <- DialHandshake(ca, a, b.Public(), 0) }()
	got, err := AcceptHandshake(cb, b, func(tag [tagLen]byte) []byte {
		if tag == pairTag(a.Public(), b.Public()) {
			return a.Public()
		}
		return nil
	})
	if err != nil {
		t.Fatalf("acceptor refused its own pair: %v", err)
	}
	if !bytes.Equal(got, a.Public()) {
		t.Fatal("the acceptor named the wrong peer")
	}
	if err := <-done; err != nil {
		t.Fatalf("dialer refused its own pair: %v", err)
	}
}

func TestHandshakeRefusesAnOfficeOutsideThePair(t *testing.T) {
	a, _ := newKeys(t)
	b, _ := newKeys(t)
	stranger, _ := newKeys(t)
	ca, cb := net.Pipe()
	done := make(chan error, 1)
	go func() {
		// The stranger dials B naming A's pair: it can compute the tag (both keys are public to it
		// here), but not the secret behind the proof.
		done <- func() error {
			defer ca.Close()
			tag := pairTag(a.Public(), b.Public())
			hello := append(append([]byte(magic), tag[:]...), make([]byte, nonceLen)...)
			if _, err := ca.Write(hello); err != nil {
				return err
			}
			reply := make([]byte, replyLen)
			if _, err := ca.Read(reply); err != nil {
				return err
			}
			forged, _ := pairSecret(stranger, b.Public(), tag)
			_, err := ca.Write(proofOf(forged, "dialer", make([]byte, nonceLen), reply[len(magic):len(magic)+nonceLen]))
			return err
		}()
	}()
	if _, err := AcceptHandshake(cb, b, func(tag [tagLen]byte) []byte {
		if tag == pairTag(a.Public(), b.Public()) {
			return a.Public()
		}
		return nil
	}); err == nil {
		t.Fatal("the acceptor admitted a dialer that does not hold A's key")
	}
	<-done
}

func TestHandshakeIsSilentToAnUnknownTag(t *testing.T) {
	a, _ := newKeys(t)
	b, _ := newKeys(t)
	other, _ := newKeys(t)
	ca, cb := net.Pipe()
	go func() {
		_, _ = AcceptHandshake(cb, b, func(tag [tagLen]byte) []byte { return nil })
		cb.Close()
	}()
	// A searching dialer reaches an office that holds no pair with it: the dialer must fail, and the
	// acceptor must not have written a byte of its own (no proof, no nonce).
	err := DialHandshake(ca, a, other.Public(), time.Second)
	if err == nil {
		t.Fatal("a dialer completed a handshake with an office that does not hold its pair")
	}
}

func TestFrames(t *testing.T) {
	var wire []byte
	wire = appendFrame(wire, frameData, []byte("wireguard"))
	wire = appendFrame(wire, framePing, []byte{1, 2, 3, 4, 5, 6, 7, 8})
	wire = appendFrame(wire, frameData, nil)
	r := bufio.NewReader(bytes.NewReader(wire))
	buf := make([]byte, maxDatagram)
	for i, want := range []struct {
		kind byte
		p    string
	}{{frameData, "wireguard"}, {framePing, "\x01\x02\x03\x04\x05\x06\x07\x08"}, {frameData, ""}} {
		kind, p, err := readFrame(r, buf)
		if err != nil || kind != want.kind || string(p) != want.p {
			t.Fatalf("frame %d: got %d %q %v", i, kind, p, err)
		}
	}
	bad := appendFrame(nil, 9, []byte("x"))
	if _, _, err := readFrame(bufio.NewReader(bytes.NewReader(bad)), buf); err == nil {
		t.Fatal("an unknown frame type was accepted")
	}
}

func TestHostsOf(t *testing.T) {
	for _, c := range []struct {
		pfx  string
		want int
	}{{"192.168.16.0/24", 254}, {"192.168.16.77/24", 254}, {"10.0.0.0/30", 2}, {"10.0.0.9/32", 1}, {"10.0.0.0/8", 0}} {
		if got := len(hostsOf(netip.MustParsePrefix(c.pfx))); got != c.want {
			t.Errorf("%s: %d hosts, want %d", c.pfx, got, c.want)
		}
	}
}

// office is one side of a test pair: its tunnel directory, its key, and a socket standing in for
// its WireGuard interface.
type office struct {
	dir  string
	keys *Keys
	wg   *net.UDPConn
	udp  int
	c    *Carrier
	stop context.CancelFunc
}

func freeUDP(t *testing.T) int {
	t.Helper()
	c, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	return c.LocalAddr().(*net.UDPAddr).Port
}

func freeTCP(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

func newOffice(t *testing.T) *office {
	t.Helper()
	k, raw := newKeys(t)
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "wg-private.key"), []byte(b64(raw)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	wg, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { wg.Close() })
	return &office{dir: dir, keys: k, wg: wg, udp: freeUDP(t)}
}

func (o *office) wgPort() int { return o.wg.LocalAddr().(*net.UDPAddr).Port }

func (o *office) plan(t *testing.T, listen string, pairs ...pairConfig) {
	t.Helper()
	raw, _ := json.Marshal(planDoc{V: 1, Listen: listen, Pairs: pairs})
	tmp := filepath.Join(o.dir, "carry.json.tmp")
	if err := os.WriteFile(tmp, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, filepath.Join(o.dir, "carry.json")); err != nil {
		t.Fatal(err)
	}
}

func (o *office) start(t *testing.T) {
	t.Helper()
	o.c = NewCarrier(filepath.Join(o.dir, "carry.json"), filepath.Join(o.dir, "wg-private.key"),
		filepath.Join(o.dir, "carry-state.json"))
	ctx, cancel := context.WithCancel(context.Background())
	o.stop = cancel
	done := make(chan struct{})
	go func() { o.c.Run(ctx); close(done) }()
	t.Cleanup(func() { cancel(); <-done })
}

func (o *office) state(t *testing.T) stateDoc {
	t.Helper()
	return o.c.snapshot()
}

func waitFor(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

// send writes a datagram from o's "WireGuard" to o's carrier and reads what arrives at the peer's.
func crosses(t *testing.T, from, to *office, payload string) bool {
	t.Helper()
	if _, err := from.wg.WriteToUDP([]byte(payload), &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: from.udp}); err != nil {
		t.Fatal(err)
	}
	buf := make([]byte, 2048)
	_ = to.wg.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	n, src, err := to.wg.ReadFromUDP(buf)
	if err != nil {
		return false
	}
	if src.Port != to.udp {
		t.Fatalf("the datagram arrived from %v, not from the carrier's socket :%d", src, to.udp)
	}
	return string(buf[:n]) == payload
}

func pairOf(self, peer *office, iface, office string) pairConfig {
	return pairConfig{Iface: iface, Office: office, PeerKey: b64(peer.keys.Public()),
		WGPort: self.wgPort(), UDPPort: self.udp}
}

func TestADatagramCrossesBothWaysAndTheDialerComesBack(t *testing.T) {
	mac, hp := newOffice(t), newOffice(t)
	port := freeTCP(t)
	mac.plan(t, fmt.Sprintf("127.0.0.1:%d", port), pairOf(mac, hp, "wg5", "hp-laptop"))
	hpPair := pairOf(hp, mac, "wg5", "macbook")
	hpPair.Dial = []string{fmt.Sprintf("127.0.0.1:%d", port)}
	hp.plan(t, "", hpPair)
	mac.start(t)
	hp.start(t)
	waitFor(t, "the pair to come up", func() bool {
		return hp.state(t).Pairs["wg5"].State == "up" && mac.state(t).Pairs["wg5"].State == "up"
	})
	waitFor(t, "hp → mac", func() bool { return crosses(t, hp, mac, "from the HP") })
	waitFor(t, "mac → hp", func() bool { return crosses(t, mac, hp, "from the MacBook") })
	if st := hp.state(t).Pairs["wg5"]; !st.Dialed || st.Remember == "" {
		t.Fatalf("the dialing side does not remember where it found its peer: %+v", st)
	}

	// The connection dies under the pair (a laptop slept, a Wi-Fi dropped): the dialer comes back.
	hp.c.mu.Lock()
	s := hp.c.pairs["wg5"].current()
	hp.c.mu.Unlock()
	s.close()
	waitFor(t, "the dialer to come back", func() bool {
		st := hp.state(t).Pairs["wg5"]
		return st.State == "up" && st.Ups >= 2
	})
	waitFor(t, "traffic after the reconnect", func() bool { return crosses(t, mac, hp, "again") })

	// Only the pair's own interface may speak to the carrier's socket.
	stranger, _ := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	defer stranger.Close()
	_, _ = stranger.WriteToUDP([]byte("not wireguard"), &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: mac.udp})
	buf := make([]byte, 64)
	_ = hp.wg.SetReadDeadline(time.Now().Add(300 * time.Millisecond))
	if n, _, err := hp.wg.ReadFromUDP(buf); err == nil {
		t.Fatalf("a datagram from outside the interface crossed the link: %q", buf[:n])
	}
}

func TestADialerThatKnowsNoAddressFindsItsPeer(t *testing.T) {
	mac, hp := newOffice(t), newOffice(t)
	port := freeTCP(t)
	mac.plan(t, fmt.Sprintf("127.0.0.1:%d", port), pairOf(mac, hp, "wg5", "hp-laptop"))
	hpPair := pairOf(hp, mac, "wg5", "macbook")
	hpPair.Scan = []string{"127.0.0.0/30"} // 127.0.0.1 and .2: the peer is one of them
	hpPair.Port = port
	hp.plan(t, "", hpPair)
	mac.start(t)
	hp.start(t)
	waitFor(t, "the search to find the peer", func() bool { return hp.state(t).Pairs["wg5"].State == "up" })
	waitFor(t, "traffic over what was found", func() bool { return crosses(t, hp, mac, "found you") })
}

func TestAWrongPeerIsNeverAdopted(t *testing.T) {
	mac, hp, other := newOffice(t), newOffice(t), newOffice(t)
	port := freeTCP(t)
	// `other` accepts, but holds a pair with somebody else: the HP must not take it for the MacBook.
	other.plan(t, fmt.Sprintf("127.0.0.1:%d", port), pairOf(other, mac, "wg7", "macbook"))
	hpPair := pairOf(hp, mac, "wg5", "macbook")
	hpPair.Dial = []string{fmt.Sprintf("127.0.0.1:%d", port)}
	hp.plan(t, "", hpPair)
	other.start(t)
	hp.start(t)
	time.Sleep(time.Second)
	if st := hp.state(t).Pairs["wg5"]; st.State == "up" {
		t.Fatalf("the HP adopted an office that does not hold its pair: %+v", st)
	}
}

func TestOneBadPairLeavesTheOthersCarried(t *testing.T) {
	mac, hp := newOffice(t), newOffice(t)
	port := freeTCP(t)
	bad := pairOf(mac, hp, "wg9", "nobody")
	bad.PeerKey = "not-a-key"
	mac.plan(t, fmt.Sprintf("127.0.0.1:%d", port), bad, pairOf(mac, hp, "wg5", "hp-laptop"))
	hpPair := pairOf(hp, mac, "wg5", "macbook")
	hpPair.Dial = []string{fmt.Sprintf("127.0.0.1:%d", port)}
	hp.plan(t, "", hpPair)
	mac.start(t)
	hp.start(t)
	waitFor(t, "the good pair", func() bool { return mac.state(t).Pairs["wg5"].State == "up" })
	if st := mac.state(t).Pairs["wg9"]; st.State != "refused" || st.Error == "" {
		t.Fatalf("the bad pair is not reported as refused: %+v", st)
	}
}

func TestAPlanChangeIsApplied(t *testing.T) {
	mac, hp := newOffice(t), newOffice(t)
	port := freeTCP(t)
	mac.plan(t, fmt.Sprintf("127.0.0.1:%d", port), pairOf(mac, hp, "wg5", "hp-laptop"))
	hpPair := pairOf(hp, mac, "wg5", "macbook")
	hp.plan(t, "", hpPair) // no address yet: the HP waits
	mac.start(t)
	hp.start(t)
	time.Sleep(300 * time.Millisecond)
	if st := hp.state(t).Pairs["wg5"]; st.State != "waiting" {
		t.Fatalf("a pair with nothing to dial should wait, got %+v", st)
	}
	time.Sleep(20 * time.Millisecond) // a new mtime
	hpPair.Dial = []string{fmt.Sprintf("127.0.0.1:%d", port)}
	hp.plan(t, "", hpPair)
	waitFor(t, "the new address to be dialed", func() bool { return hp.state(t).Pairs["wg5"].State == "up" })
	// …and a pair that leaves the plan is let go.
	hp.plan(t, "")
	waitFor(t, "the pair to be let go", func() bool { _, ok := hp.state(t).Pairs["wg5"]; return !ok })
}

func TestHealthReadsTheStateFile(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "carry-state.json")
	if health(p) == 0 {
		t.Fatal("healthy with no state file")
	}
	raw, _ := json.Marshal(stateDoc{At: time.Now().Unix()})
	_ = os.WriteFile(p, raw, 0o644)
	if health(p) != 0 {
		t.Fatal("unhealthy with a fresh state file")
	}
	raw, _ = json.Marshal(stateDoc{At: time.Now().Unix() - 120})
	_ = os.WriteFile(p, raw, 0o644)
	if health(p) == 0 {
		t.Fatal("healthy with a state file two minutes old")
	}
}

func TestAPairThatWasLetGoTakesNoSession(t *testing.T) {
	k, _ := newKeys(t)
	peer, _ := newKeys(t)
	p, err := startPair(pairConfig{Iface: "wg5", Office: "x", PeerKey: b64(peer.Public()), WGPort: freeUDP(t),
		UDPPort: freeUDP(t)}, k, "")
	if err != nil {
		t.Fatal(err)
	}
	p.close()
	a, b := net.Pipe()
	defer b.Close()
	s := newSession(a, false)
	p.attach(s)
	if p.current() != nil || s.alive() {
		t.Fatal("a pair that was let go took a session: its peer would ride a pair nobody reads")
	}
}

func TestAnAcceptingSideForgetsWhereItOnceDialed(t *testing.T) {
	k, _ := newKeys(t)
	peer, _ := newKeys(t)
	cfg := pairConfig{Iface: "wg5", Office: "x", PeerKey: b64(peer.Public()), WGPort: freeUDP(t), UDPPort: freeUDP(t),
		Dial: []string{"192.0.2.1:51443"}}
	p, err := startPair(cfg, k, "192.0.2.7:51443")
	if err != nil {
		t.Fatal(err)
	}
	defer p.close()
	if !p.dials() {
		t.Fatal("a pair with an address to dial dials")
	}
	cfg.Dial = nil
	p.update(cfg)
	p.mu.Lock()
	remembered := p.lastGood
	p.mu.Unlock()
	if p.dials() || remembered != "" {
		t.Fatalf("a pair whose plan says 'wait to be dialed' neither dials nor remembers (got %q)", remembered)
	}
}

func TestOneAddressCannotHoldEverySlot(t *testing.T) {
	mac := newOffice(t)
	port := freeTCP(t)
	hp := newOffice(t)
	mac.plan(t, fmt.Sprintf("127.0.0.1:%d", port), pairOf(mac, hp, "wg5", "hp-laptop"))
	mac.start(t)
	waitFor(t, "the listener", func() bool { return mac.state(t).Accepting })
	// Silent connections from one address: past maxPerSource they are closed at once.
	var held []net.Conn
	defer func() {
		for _, c := range held {
			c.Close()
		}
	}()
	for i := 0; i < maxPerSource+3; i++ {
		c, err := net.Dial("tcp", fmt.Sprintf("127.0.0.1:%d", port))
		if err != nil {
			t.Fatal(err)
		}
		held = append(held, c)
	}
	time.Sleep(200 * time.Millisecond)
	closed := 0
	for _, c := range held {
		_ = c.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
		if _, err := c.Read(make([]byte, 1)); err != nil && !isTimeout(err) {
			closed++
		}
	}
	if closed < 3 {
		t.Fatalf("one address held more than %d unfinished handshakes (%d of %d closed)", maxPerSource, closed, len(held))
	}
}

func isTimeout(err error) bool {
	ne, ok := err.(net.Error)
	return ok && ne.Timeout()
}

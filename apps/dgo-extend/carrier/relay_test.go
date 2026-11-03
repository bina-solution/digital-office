package main

// The hub's relay (relay.go), as tests: two offices that cannot reach each other meet at a third one's
// door and carry datagrams both ways; the direct way wins the pair back the moment it answers; the door
// joins only the pairs its plan declares; a newer side replaces the one that waits, a newer join the older
// one, and a wait nobody joins ends; one address's share is bounded, and a silent join is ended.

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"testing"
	"time"
)

func relayTag(dialer, acceptor *office) string {
	t := pairTag(dialer.keys.Public(), acceptor.keys.Public())
	return hex.EncodeToString(t[:])
}

// hubDoor starts an office that holds no pair of these and only opens its door, relaying tags.
func hubDoor(t *testing.T, tags ...string) (*office, string) {
	t.Helper()
	hub := newOffice(t)
	port := freeTCP(t)
	writePlanDoc(t, hub, planDoc{V: 1, Door: fmt.Sprintf("127.0.0.1:%d", port), RelayTags: tags})
	hub.start(t)
	waitFor(t, "the hub's door to open", func() bool { return hub.state(t).DoorOpen })
	return hub, fmt.Sprintf("ws://127.0.0.1:%d/relay", port)
}

// The MacBook away from home (it takes no LAN connection there) and the HP at home (it dials the Mac's
// LAN door, which nothing answers): neither reaches the other, both reach the hub.
func awayPair(t *testing.T, relay, lan string) (hp, mac *office, hpPair, macPair pairConfig) {
	t.Helper()
	hp, mac = newOffice(t), newOffice(t)
	hpPair = pairOf(hp, mac, "wg5", "macbook")
	hpPair.Dial = []string{lan}
	hpPair.FallbackRelay = relay
	macPair = pairOf(mac, hp, "wg5", "hp-laptop")
	macPair.FallbackRelay = relay
	return hp, mac, hpPair, macPair
}

func TestTwoOfficesThatCannotReachEachOtherMeetAtTheHub(t *testing.T) {
	hp, mac := newOffice(t), newOffice(t)
	hub, relay := hubDoor(t, relayTag(hp, mac))
	hpPair := pairOf(hp, mac, "wg5", "macbook")
	hpPair.Dial = []string{fmt.Sprintf("127.0.0.1:%d", freeTCP(t))}
	hpPair.FallbackRelay = relay
	macPair := pairOf(mac, hp, "wg5", "hp-laptop")
	macPair.FallbackRelay = relay
	hp.plan(t, "", hpPair)
	mac.plan(t, "", macPair)
	hp.start(t)
	mac.start(t)

	waitFor(t, "the pair to come up through the hub", func() bool {
		return hp.state(t).Pairs["wg5"].State == "up" && mac.state(t).Pairs["wg5"].State == "up"
	})
	if h, m := hp.state(t).Pairs["wg5"], mac.state(t).Pairs["wg5"]; !h.Relayed || !m.Relayed || !h.Dialed || m.Dialed {
		t.Fatalf("both sides say relayed, the HP dialed and the Mac accepted: hp %+v, mac %+v", h, m)
	}
	waitFor(t, "HP → Mac", func() bool { return crosses(t, hp, mac, "from the HP at home") })
	waitFor(t, "Mac → HP", func() bool { return crosses(t, mac, hp, "from the café") })
	if st := hub.state(t).Relay; st == nil || st.Joined < 1 || st.Tags != 1 {
		t.Fatalf("the hub counts the join of its one declared pair: %+v", st)
	}
	if len(hub.state(t).Pairs) != 0 {
		t.Fatal("the hub holds no pair of its own in this: it only joins two others")
	}

	// The relayed connection dies (the hub restarted, a café's network dropped it): both come back by
	// themselves, through the hub again.
	hp.c.mu.Lock()
	s := hp.c.pairs["wg5"].current()
	hp.c.mu.Unlock()
	s.close()
	waitFor(t, "the pair back through the hub", func() bool {
		st := hp.state(t).Pairs["wg5"]
		return st.State == "up" && st.Relayed && st.Ups >= 2
	})
	waitFor(t, "traffic after the reconnect", func() bool { return crosses(t, mac, hp, "again") })
}

func TestTheDirectWayWinsThePairBackFromTheHub(t *testing.T) {
	lan := freeTCP(t)
	hp, mac, hpPair, macPair := awayPair(t, "", fmt.Sprintf("127.0.0.1:%d", lan))
	_, relay := hubDoor(t, relayTag(hp, mac))
	hpPair.FallbackRelay, macPair.FallbackRelay = relay, relay
	hp.plan(t, "", hpPair)
	mac.plan(t, "", macPair) // away: the Mac's LAN door is closed
	hp.start(t)
	mac.start(t)
	waitFor(t, "the pair up through the hub", func() bool {
		st := hp.state(t).Pairs["wg5"]
		return st.State == "up" && st.Relayed
	})

	// Home again: the Mac's LAN door opens, and the HP's next look finds it.
	mac.plan(t, fmt.Sprintf("127.0.0.1:%d", lan), macPair)
	waitFor(t, "the pair back on its LAN, the relayed session replaced", func() bool {
		h, m := hp.state(t).Pairs["wg5"], mac.state(t).Pairs["wg5"]
		return h.State == "up" && !h.Relayed && strings.HasSuffix(h.Via, fmt.Sprintf(":%d", lan)) &&
			m.State == "up" && !m.Relayed
	})
	waitFor(t, "traffic on the LAN", func() bool { return crosses(t, hp, mac, "home") })
	time.Sleep(3 * relayAfter)
	if h := hp.state(t).Pairs["wg5"]; h.Relayed || h.State != "up" {
		t.Fatalf("a pair on its LAN does not go back to the hub: %+v", h)
	}
}

func TestTheDoorJoinsOnlyTheDeclaredPairs(t *testing.T) {
	hp, mac, stranger := newOffice(t), newOffice(t), newOffice(t)
	hub, relay := hubDoor(t, relayTag(hp, mac))
	base := strings.Replace(relay, "ws://", "http://", 1)
	for _, c := range []struct {
		query string
		want  int
	}{
		{"?tag=" + relayTag(hp, stranger) + "&side=dial", http.StatusForbidden},
		{"?tag=" + relayTag(hp, mac) + "&side=both", http.StatusBadRequest},
		{"?tag=zz&side=dial", http.StatusBadRequest},
		{"", http.StatusBadRequest},
		// a declared pair, but no websocket upgrade: nothing is taken in
		{"?tag=" + relayTag(hp, mac) + "&side=dial", http.StatusBadRequest},
	} {
		resp, err := http.Get(base + c.query)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp.StatusCode != c.want {
			t.Fatalf("/relay%s answered %d, want %d", c.query, resp.StatusCode, c.want)
		}
	}
	if st := hub.state(t).Relay; st == nil || st.Refused < 1 || st.Waiting != 0 {
		t.Fatalf("the undeclared pair is refused and counted, and nobody waits: %+v", st)
	}

	// A door that declares no pair relays nothing, and says nothing about relaying.
	plain, other := hubDoor(t)
	resp, err := http.Get(strings.Replace(other, "ws://", "http://", 1) + "?tag=" + relayTag(hp, mac) + "&side=dial")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusForbidden || plain.state(t).Relay != nil {
		t.Fatalf("a door with no relay_tags refuses every relay (%d) and shows no relay state", resp.StatusCode)
	}
}

// The hub's app renders the tags its door may join (net.relay_tags), the carriers compute them: one vector
// in both test suites (net.py's selftest holds the same) keeps the two from naming a pair differently.
func TestTheAppAndTheCarrierNameAPairAlike(t *testing.T) {
	tag := pairTag(bytes.Repeat([]byte{1}, 32), bytes.Repeat([]byte{2}, 32))
	if got := hex.EncodeToString(tag[:]); got != "278350ca866de1baf4e1c29395b2a3d24c1e42de9c8b4fba4097f515560a7bb1" {
		t.Fatalf("pairTag(dialer 0x01…, acceptor 0x02…) = %s", got)
	}
}

func TestANewerSideReplacesTheOneThatWaitsAndAWaitEnds(t *testing.T) {
	h := newRelayHub()
	var tag [tagLen]byte
	first, firstFar := net.Pipe()
	h.meet(first, tag, "accept", "10.0.0.1")
	second, secondFar := net.Pipe()
	h.meet(second, tag, "accept", "10.0.0.2")
	_ = firstFar.SetReadDeadline(time.Now().Add(time.Second))
	if _, err := firstFar.Read(make([]byte, 1)); err != io.EOF {
		t.Fatalf("the side a newer one replaced is let go (closed, not left to time out): %v", err)
	}
	if h.waitingNow() != 1 || h.bySrc["10.0.0.1"] != 0 || h.bySrc["10.0.0.2"] != 1 {
		t.Fatalf("one side waits, counted against its own address: %d %v", h.waitingNow(), h.bySrc)
	}
	dialer, dialerFar := net.Pipe()
	h.meet(dialer, tag, "dial", "10.0.0.3")
	for _, far := range []net.Conn{secondFar, dialerFar} {
		got := make([]byte, len(relayMatched))
		_ = far.SetReadDeadline(time.Now().Add(2 * time.Second))
		if _, err := io.ReadFull(far, got); err != nil || string(got) != relayMatched {
			t.Fatalf("both sides are told they met: %q, %v", got, err)
		}
	}
	if h.waitingNow() != 0 || h.joined.Load() != 1 {
		t.Fatalf("a join leaves nobody waiting: waiting %d, joined %d", h.waitingNow(), h.joined.Load())
	}
	go func() { _, _ = dialerFar.Write([]byte("hello")) }()
	got := make([]byte, 5)
	_ = secondFar.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, err := io.ReadFull(secondFar, got); err != nil || string(got) != "hello" {
		t.Fatalf("bytes cross the join: %q, %v", got, err)
	}

	// A newer join of the same pair replaces the older one: both ends of the older are closed.
	a2, a2Far := net.Pipe()
	d2, d2Far := net.Pipe()
	h.meet(a2, tag, "accept", "10.0.0.2")
	h.meet(d2, tag, "dial", "10.0.0.3")
	for _, far := range []net.Conn{a2Far, d2Far} {
		got := make([]byte, len(relayMatched))
		_ = far.SetReadDeadline(time.Now().Add(2 * time.Second))
		if _, err := io.ReadFull(far, got); err != nil {
			t.Fatalf("the newer join is told it met: %v", err)
		}
	}
	_ = secondFar.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, err := secondFar.Read(make([]byte, 1)); err != io.EOF {
		t.Fatalf("the older join of the same pair is closed: %v", err)
	}

	lone, loneFar := net.Pipe()
	h.meet(lone, [tagLen]byte{1}, "dial", "10.0.0.4")
	_ = loneFar.SetReadDeadline(time.Now().Add(parkFor + 2*time.Second))
	if _, err := loneFar.Read(make([]byte, 1)); err != io.EOF {
		t.Fatalf("a side nobody joins is let go after parkFor (closed): %v", err)
	}
	if h.waitingNow() != 0 || len(h.bySrc) != 0 {
		t.Fatalf("nobody waits after the wait ended, and no address is counted: %d %v", h.waitingNow(), h.bySrc)
	}
}

func TestTheHubBoundsWhatOneAddressHoldsAndEndsASilentJoin(t *testing.T) {
	h := newRelayHub()
	old := maxParkedPerSource
	maxParkedPerSource = 2
	t.Cleanup(func() { maxParkedPerSource = old })
	var fars []net.Conn
	for i := 0; i < 2; i++ {
		c, far := net.Pipe()
		fars = append(fars, far)
		h.meet(c, [tagLen]byte{byte(10 + i)}, "accept", "203.0.113.7")
	}
	if !h.full("203.0.113.7") || h.full("198.51.100.1") {
		t.Fatal("an address that holds its share is full; another address is not")
	}
	extra, extraFar := net.Pipe()
	h.meet(extra, [tagLen]byte{12}, "accept", "203.0.113.7")
	_ = extraFar.SetReadDeadline(time.Now().Add(time.Second))
	if _, err := extraFar.Read(make([]byte, 1)); err != io.EOF || h.waitingNow() != 2 || h.refused.Load() != 1 {
		t.Fatalf("one more side from the same address is refused and counted: %v, waiting %d", err, h.waitingNow())
	}

	idle := relayIdle
	relayIdle = 300 * time.Millisecond
	t.Cleanup(func() { relayIdle = idle })
	d, dFar := net.Pipe()
	h.meet(d, [tagLen]byte{10}, "dial", "198.51.100.1")
	got := make([]byte, len(relayMatched))
	for _, far := range []net.Conn{fars[0], dFar} {
		_ = far.SetReadDeadline(time.Now().Add(2 * time.Second))
		if _, err := io.ReadFull(far, got); err != nil {
			t.Fatalf("joined: %v", err)
		}
	}
	_ = dFar.SetReadDeadline(time.Now().Add(3 * time.Second))
	if _, err := dFar.Read(make([]byte, 1)); err != io.EOF {
		t.Fatalf("a join that carries nothing for relayIdle is ended: %v", err)
	}
}

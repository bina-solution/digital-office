// Command dgo-carry is WireGuard's TCP path between two offices: DGO Extend's link, wherever UDP
// cannot pass.
//
// WHY IT EXISTS. A link is a WireGuard pair, and WireGuard speaks UDP. Some pairs of machines can
// never exchange a UDP packet. Measured 2026-10-19 on the owner's own LAN: the MacBook's engine (a
// Lima guest) receives no inbound UDP at all, and the HP (WSL behind Windows' Hyper-V firewall)
// drops every inbound packet, so each side could dial the other forever and neither would hear a
// reply. Both CAN make or take a TCP connection (the MacBook takes one on its LAN address, the HP
// makes one). So this program gives the pair's WireGuard a TCP path. The interface's `Endpoint` is
// a UDP socket of this process on 127.0.0.1, and every datagram WireGuard sends there crosses one TCP
// connection to the peer's dgo-carry, which hands it to the peer's WireGuard the same way.
//
// WHAT IT IS NOT. It is not a second tunnel and not a second trust. WireGuard still encrypts and
// authenticates every packet end to end, and this program never sees a plaintext byte: it is the
// path, the role Tailscale's DERP plays over HTTPS. The TCP connection is authenticated by the pair's
// own WireGuard keys anyway (wire.go), so a stranger on the LAN can neither take a pair's connection
// over nor learn which keys it carries.
//
// WHAT IT READS AND WRITES. The plan (`carry.json`) is rendered by the app (`net.carry_plan`) from the
// pair records it owns, into the tunnel volume this process mounts READ-ONLY; it only applies the
// plan, and re-reads it when it changes. Its answer is a file too (`carry-state.json`, on a volume of
// its own that the app reads), written every few seconds — the contract the rest of `dgo-net` already
// follows (`wg-state.json`, `scan.result`). Standard library only, CGO off, like every Go binary in
// this repository.
package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"
)

// defaultPort is where an office that accepts takes its peers' connections (dgo-net publishes it).
const defaultPort = 51443

// How often the plan is looked at, and how often the state file is written.
var (
	reloadEvery = 2 * time.Second
	stateEvery  = 5 * time.Second
)

// pairConfig is one pair of the plan, exactly as net.carry_plan renders it.
type pairConfig struct {
	Iface   string   `json:"iface"`    // the pair's WireGuard interface (wg<slot>)
	Office  string   `json:"office"`   // the peer office, for the log and the state file
	PeerKey string   `json:"peer_key"` // the peer's WireGuard public key, base64
	WGPort  int      `json:"wg_port"`  // the interface's ListenPort: where datagrams are handed to it
	UDPPort int      `json:"udp_port"` // this process's socket, 127.0.0.1: the interface's Endpoint
	Dial    []string `json:"dial"`     // host:port of the peer's carrier, when this side dials
	Scan    []string `json:"scan"`     // IPv4 prefixes to search for the peer when those fail
	Port    int      `json:"port"`     // the peer's carrier port when searching (default 51443)
	// Relay is where this side dials when the peer is behind an HTTPS edge: `wss://link.<domain>/carry`
	// (ws.go). A pair with a relay neither dials an address nor searches: the edge is the address.
	Relay string `json:"relay,omitempty"`
	// FallbackRelay is the herd's hub (`wss://link.<domain>/relay`, relay.go): where the pair meets its
	// peer when its own way stays silent — a laptop away from the LAN its peer is on. "" = never.
	FallbackRelay string `json:"fallback_relay,omitempty"`
}

type planDoc struct {
	V      int    `json:"v"`
	Listen string `json:"listen"` // "" = this office takes no connection
	// Door is where the public link door listens (door.go) — behind the edge's `link.<domain>`, for
	// the offices that reach this one over HTTPS only. "" = this office has no such door.
	Door  string       `json:"door,omitempty"`
	Pairs []pairConfig `json:"pairs"`
	// RelayTags are the pairs of OTHER offices this office's door joins at its `/relay` (relay.go),
	// as 64-hex pair tags: the hub's declaration, `DGO_RELAY_FOR`. Empty = the door relays nothing.
	RelayTags []string `json:"relay_tags,omitempty"`
}

var ifaceRE = regexp.MustCompile(`^wg[0-9]{1,3}$`)

func decodeKey(s string) ([]byte, error) {
	b, err := base64.StdEncoding.DecodeString(strings.TrimSpace(s))
	if err != nil || len(b) != 32 {
		return nil, errors.New("not a WireGuard key (base64 of 32 bytes)")
	}
	return b, nil
}

// checkPair says why a pair of the plan cannot be carried ("" = it can). A pair is refused alone:
// one bad record must not take the office's other links down with it.
func checkPair(p *pairConfig) string {
	if !ifaceRE.MatchString(p.Iface) {
		return fmt.Sprintf("interface %q is not wg<slot>", p.Iface)
	}
	if _, err := decodeKey(p.PeerKey); err != nil {
		return "peer_key: " + err.Error()
	}
	for _, port := range []int{p.WGPort, p.UDPPort} {
		if port < 1 || port > 65535 {
			return fmt.Sprintf("port %d is outside 1-65535", port)
		}
	}
	if p.WGPort == p.UDPPort {
		return "the interface and the carrier cannot share one UDP port"
	}
	if p.Port == 0 {
		p.Port = defaultPort
	}
	if p.Port < 1 || p.Port > 65535 {
		return fmt.Sprintf("port %d is outside 1-65535", p.Port)
	}
	for _, d := range p.Dial {
		if _, _, err := net.SplitHostPort(d); err != nil {
			return fmt.Sprintf("dial %q is not host:port", d)
		}
	}
	for _, s := range p.Scan {
		pfx, err := netip.ParsePrefix(s)
		if err != nil || !pfx.Addr().Is4() || pfx.Bits() < 22 {
			return fmt.Sprintf("scan %q is not an IPv4 prefix of /22 or narrower", s)
		}
	}
	if p.Relay != "" {
		u, err := url.Parse(p.Relay)
		if err != nil || (u.Scheme != "wss" && u.Scheme != "ws") || u.Hostname() == "" || u.User != nil ||
			!strings.HasPrefix(u.Path, "/") {
			return fmt.Sprintf("relay %q is not a wss://host/path address", p.Relay)
		}
		if len(p.Dial) > 0 || len(p.Scan) > 0 {
			return "a pair that dials a relay neither dials an address nor searches"
		}
	}
	return ""
}

func readKey(path string) ([]byte, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return decodeKey(string(raw))
}

// Carrier is this office's whole TCP path: every pair it carries, and the listener it accepts on.
type Carrier struct {
	planPath, keyPath, statePath string

	mu         sync.Mutex
	keys       *Keys
	keyRaw     []byte
	planSig    string
	pairs      map[string]*pair
	byTag      map[[tagLen]byte]*pair
	refused    map[string]string
	planErr    string
	listen     string
	ln         net.Listener
	listenErr  string
	doorAddr   string
	door       *http.Server
	doorErr    string
	app        *url.URL // where the door passes join requests (the app); nil = it takes none
	remembered map[string]string
	pending    chan struct{}
	// doorPending is the DOOR's own budget of unfinished handshakes: the internet reaches the door,
	// and must not be able to take the slots a LAN peer's reconnect needs (`pending`), nor the other
	// way round.
	doorPending chan struct{}
	perSource   map[string]int // unfinished handshakes, by remote address
	logged      map[string]bool
	// relayTags are the other offices' pairs the door may join (planDoc.RelayTags); hub is where they
	// meet (relay.go).
	relayTags map[[tagLen]byte]bool
	hub       *relayHub
}

// maxPerSource bounds the unfinished handshakes ONE address may hold, so a single device on the LAN
// cannot take every slot (`pending`) and lock the real peer out.
const maxPerSource = 4

// NewCarrier builds a carrier over the three files it reads and writes.
func NewCarrier(planPath, keyPath, statePath string) *Carrier {
	c := &Carrier{planPath: planPath, keyPath: keyPath, statePath: statePath,
		pairs: map[string]*pair{}, byTag: map[[tagLen]byte]*pair{}, refused: map[string]string{},
		remembered: map[string]string{}, pending: make(chan struct{}, 32), doorPending: make(chan struct{}, 16),
		relayTags: map[[tagLen]byte]bool{}, hub: newRelayHub(),
		perSource: map[string]int{},
		logged:    map[string]bool{}}
	// Where each dialing pair last found its peer: the first place to look after a restart.
	if raw, err := os.ReadFile(statePath); err == nil {
		var prev stateDoc
		if json.Unmarshal(raw, &prev) == nil {
			for iface, st := range prev.Pairs {
				if st.Remember != "" {
					c.remembered[iface] = st.Remember
				}
			}
		}
	}
	return c
}

func (c *Carrier) once(msg string) {
	if !c.logged[msg] {
		c.logged[msg] = true
		log.Print(msg)
	}
}

// Run applies the plan until ctx ends.
func (c *Carrier) Run(ctx context.Context) {
	c.reload()
	c.writeState()
	plan := time.NewTicker(reloadEvery)
	state := time.NewTicker(stateEvery)
	defer plan.Stop()
	defer state.Stop()
	for {
		select {
		case <-ctx.Done():
			c.shutdown()
			return
		case <-plan.C:
			c.reload()
		case <-state.C:
			c.writeState()
		}
	}
}

func (c *Carrier) shutdown() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.ln != nil {
		_ = c.ln.Close()
		c.ln = nil
	}
	c.stopDoor()
	for iface, p := range c.pairs {
		p.close()
		delete(c.pairs, iface)
	}
}

// reload re-reads the key and the plan when either changed, and brings the pairs and the listener
// to what they say.
func (c *Carrier) reload() {
	keyRaw, keyErr := readKey(c.keyPath)
	sig := "absent"
	if fi, err := os.Stat(c.planPath); err == nil {
		sig = fmt.Sprintf("%d/%d", fi.ModTime().UnixNano(), fi.Size())
	}
	sig += fmt.Sprintf("|%x|%v", keyRaw, keyErr != nil)
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.listen != "" && c.ln == nil {
		c.startListener() // a port that was taken a moment ago may be free now
	}
	if c.doorAddr != "" && c.door == nil {
		c.startDoor()
	}
	if sig == c.planSig {
		return
	}
	c.planSig = sig
	doc := &planDoc{V: 1}
	if raw, err := os.ReadFile(c.planPath); err == nil {
		if err := json.Unmarshal(raw, doc); err != nil {
			c.planErr = fmt.Sprintf("%s is not JSON (%v) — the pairs carried so far keep running", c.planPath, err)
			c.once(c.planErr)
			return
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		c.planErr = err.Error()
		return
	}
	if doc.V != 1 {
		c.planErr = fmt.Sprintf("%s is version %d; this carrier reads version 1", c.planPath, doc.V)
		c.once(c.planErr)
		return
	}
	c.planErr = ""
	// The listener and the door follow the plan FIRST: they do not need the key to be open (a
	// connection that arrives before it exists is refused in `handle`), and a hub that declares a link
	// host before it holds any pair has no key file at all — its door must still take the join that
	// will give it its first pair.
	c.applyListeners(doc)
	// The relay is the door's too, and needs no key of this office either: a hub joins two OTHER offices.
	tags, bad := relayTagsOf(doc.RelayTags)
	for _, b := range bad {
		c.once(fmt.Sprintf("relay tag %q is not 64 hex: left out", b))
	}
	c.relayTags = tags
	if keyErr != nil {
		if len(doc.Pairs) > 0 {
			c.planErr = "no WireGuard private key in " + c.keyPath + " yet — waiting for the app to render it"
			c.once(c.planErr)
		}
		c.stopPairs()
		return
	}
	if !bytes.Equal(keyRaw, c.keyRaw) {
		keys, err := NewKeys(keyRaw)
		if err != nil {
			c.planErr = err.Error()
			c.once(c.planErr)
			c.stopPairs()
			return
		}
		c.stopPairs() // every session was authenticated with the key that just changed
		c.keys, c.keyRaw = keys, keyRaw
	}
	want := map[string]pairConfig{}
	c.refused = map[string]string{}
	usedUDP := map[int]string{}
	for _, pc := range doc.Pairs {
		pc := pc
		if why := checkFallback(&pc); why != "" {
			c.once(fmt.Sprintf("%s ⇄ %s: carried without the hub's relay — %s", pc.Iface, pc.Office, why))
			pc.FallbackRelay = ""
		}
		if why := checkPair(&pc); why != "" {
			c.refused[pc.Iface] = why
			c.once(fmt.Sprintf("%s ⇄ %s: not carried — %s", pc.Iface, pc.Office, why))
			continue
		}
		if other, dup := usedUDP[pc.UDPPort]; dup || want[pc.Iface].Iface != "" {
			c.refused[pc.Iface] = fmt.Sprintf("udp_port %d or interface already used by %s", pc.UDPPort, other)
			continue
		}
		usedUDP[pc.UDPPort] = pc.Iface
		want[pc.Iface] = pc
	}
	for iface, p := range c.pairs {
		if pc, ok := want[iface]; !ok || !p.sameIdentity(pc) {
			p.close()
			delete(c.pairs, iface)
			log.Printf("%s ⇄ %s: no longer carried", iface, p.cfg.Office)
		}
	}
	for iface, pc := range want {
		if p, ok := c.pairs[iface]; ok {
			p.update(pc)
			continue
		}
		p, err := startPair(pc, c.keys, c.remembered[iface])
		if err != nil {
			c.refused[iface] = err.Error()
			c.once(err.Error())
			continue
		}
		c.pairs[iface] = p
		role := "waits to be dialed"
		switch {
		case pc.Relay != "":
			role = "dials the relay " + pc.Relay
		case p.dials():
			role = fmt.Sprintf("dials %v, searches %v", pc.Dial, pc.Scan)
		}
		log.Printf("%s ⇄ %s: carried (wireguard :%d ⇄ 127.0.0.1:%d), %s", iface, pc.Office, pc.WGPort, pc.UDPPort, role)
	}
	c.byTag = map[[tagLen]byte]*pair{}
	for _, p := range c.pairs {
		// The PEER dials this office, so the tag names the peer's key first.
		c.byTag[pairTag(p.peerPub, c.keys.pub)] = p
	}
}

// applyListeners opens, moves or closes the TCP listener and the door to what the plan says; the
// caller holds c.mu.
func (c *Carrier) applyListeners(doc *planDoc) {
	if doc.Listen != c.listen {
		if c.ln != nil {
			_ = c.ln.Close()
			c.ln = nil
		}
		c.listen = doc.Listen
		c.listenErr = ""
		if c.listen != "" {
			c.startListener()
		}
	}
	if doc.Door != c.doorAddr {
		c.stopDoor()
		c.doorAddr, c.doorErr = doc.Door, ""
		if c.doorAddr != "" {
			c.startDoor()
		}
	}
}

func (c *Carrier) stopPairs() {
	for iface, p := range c.pairs {
		p.close()
		delete(c.pairs, iface)
	}
	c.byTag = map[[tagLen]byte]*pair{}
}

// startListener binds c.listen; the caller holds c.mu.
func (c *Carrier) startListener() {
	ln, err := net.Listen("tcp", c.listen)
	if err != nil {
		c.listenErr = err.Error()
		c.once(fmt.Sprintf("cannot accept on %s: %v — retrying", c.listen, err))
		return
	}
	c.ln, c.listenErr = ln, ""
	log.Printf("accepting peers on %s", c.listen)
	go c.acceptLoop(ln)
}

func (c *Carrier) acceptLoop(ln net.Listener) {
	for {
		conn, err := ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			time.Sleep(100 * time.Millisecond)
			continue
		}
		src := conn.RemoteAddr().String()
		if host, _, err := net.SplitHostPort(src); err == nil {
			src = host
		}
		if !c.admit(src, c.pending) {
			_ = conn.Close() // too many unfinished handshakes: from this address, or in all
			continue
		}
		go func() {
			defer c.release(src, c.pending)
			c.handle(conn)
		}()
	}
}

// admit counts one more unfinished handshake from src, or refuses it: past maxPerSource from one
// address (one device must not take every slot and lock the real peer out), or past the budget it
// draws on (`pending` for the TCP listener, `doorPending` for the door) in all. Every admit is paired
// with one release on the same budget.
func (c *Carrier) admit(src string, slots chan struct{}) bool {
	c.mu.Lock()
	if c.perSource[src] >= maxPerSource {
		c.mu.Unlock()
		return false
	}
	c.perSource[src]++
	c.mu.Unlock()
	select {
	case slots <- struct{}{}:
		return true
	default:
		c.mu.Lock()
		c.forget(src)
		c.mu.Unlock()
		return false
	}
}

func (c *Carrier) release(src string, slots chan struct{}) {
	<-slots
	c.mu.Lock()
	c.forget(src)
	c.mu.Unlock()
}

// forget takes one unfinished handshake of src off the count; the caller holds c.mu.
func (c *Carrier) forget(src string) {
	if c.perSource[src]--; c.perSource[src] <= 0 {
		delete(c.perSource, src)
	}
}

func (c *Carrier) handle(conn net.Conn) {
	c.mu.Lock()
	keys := c.keys
	c.mu.Unlock()
	if keys == nil {
		_ = conn.Close()
		return
	}
	var target *pair
	_, err := AcceptHandshake(conn, keys, func(tag [tagLen]byte) []byte {
		c.mu.Lock()
		defer c.mu.Unlock()
		if p := c.byTag[tag]; p != nil {
			target = p
			return p.peerPub
		}
		return nil
	})
	if err != nil {
		_ = conn.Close() // a scanner, a stranger, or a peer of a pair this office no longer holds
		return
	}
	c.mu.Lock()
	still := c.pairs[target.cfg.Iface] == target
	c.mu.Unlock()
	if !still {
		_ = conn.Close()
		return
	}
	target.attach(newSession(conn, false))
}

type pairState struct {
	Office   string  `json:"office"`
	State    string  `json:"state"` // up | searching | waiting | refused
	Via      string  `json:"via,omitempty"`
	Dialed   bool    `json:"dialed,omitempty"`
	Since    int64   `json:"since,omitempty"`
	HeardS   *int64  `json:"heard_s,omitempty"`
	RTTMs    float64 `json:"rtt_ms,omitempty"`
	RX       uint64  `json:"rx"`
	TX       uint64  `json:"tx"`
	Dropped  uint64  `json:"dropped"`
	Ups      int     `json:"ups"`
	Remember string  `json:"remember,omitempty"`
	Error    string  `json:"error,omitempty"`
	// Relayed: the session crosses the hub's relay, not a path of its own (relay.go).
	Relayed bool `json:"relayed,omitempty"`
}

// relayState is what this office's door relays for OTHER offices: the pairs it may join, the sides
// waiting now, and the joins and refusals since it started.
type relayState struct {
	Tags    int    `json:"tags"`
	Waiting int    `json:"waiting"`
	Joined  uint64 `json:"joined"`
	Refused uint64 `json:"refused"`
}

type stateDoc struct {
	At        int64                `json:"at"`
	Listen    string               `json:"listen,omitempty"`
	Accepting bool                 `json:"accepting"`
	Door      string               `json:"door,omitempty"`
	DoorOpen  bool                 `json:"door_open,omitempty"`
	Error     string               `json:"error,omitempty"`
	Pairs     map[string]pairState `json:"pairs"`
	// Relay is said only by a door that relays (a hub).
	Relay *relayState `json:"relay,omitempty"`
}

func (c *Carrier) snapshot() stateDoc {
	c.mu.Lock()
	defer c.mu.Unlock()
	doc := stateDoc{At: time.Now().Unix(), Listen: c.listen, Accepting: c.ln != nil, Door: c.doorAddr,
		DoorOpen: c.door != nil, Pairs: map[string]pairState{}}
	doc.Error = c.planErr
	if doc.Error == "" {
		doc.Error = c.listenErr
	}
	if doc.Error == "" {
		doc.Error = c.doorErr
	}
	for iface, why := range c.refused {
		doc.Pairs[iface] = pairState{State: "refused", Error: why}
	}
	for iface, p := range c.pairs {
		st := pairState{Office: p.cfg.Office, RX: p.rx.Load(), TX: p.tx.Load(), Dropped: p.dropped.Load()}
		p.mu.Lock()
		s := p.sess
		st.Ups, st.Remember, st.Error = p.ups, p.lastGood, p.lastErr
		dials := len(p.dial) > 0 || len(p.scan) > 0 || p.relay != ""
		p.mu.Unlock()
		switch {
		case s != nil && s.alive():
			st.State, st.Via, st.Dialed, st.Since, st.Error = "up", s.via, s.dialed, s.since.Unix(), ""
			st.Relayed = s.relayed
			heard := int64(time.Since(time.Unix(0, s.lastRx.Load())).Seconds())
			st.HeardS = &heard
			st.RTTMs = float64(s.rttNs.Load()) / 1e6
		case dials:
			st.State = "searching"
		default:
			st.State = "waiting"
		}
		doc.Pairs[iface] = st
	}
	if len(c.relayTags) > 0 {
		doc.Relay = &relayState{Tags: len(c.relayTags), Waiting: c.hub.waitingNow(),
			Joined: c.hub.joined.Load(), Refused: c.hub.refused.Load()}
	}
	return doc
}

func (c *Carrier) writeState() {
	raw, err := json.Marshal(c.snapshot())
	if err != nil {
		return
	}
	tmp := c.statePath + ".tmp"
	if err := os.WriteFile(tmp, append(raw, '\n'), 0o644); err != nil {
		c.once(fmt.Sprintf("cannot write %s: %v", tmp, err))
		return
	}
	_ = os.Rename(tmp, c.statePath)
}

// health is the container's healthcheck: the state file was written in the last 30 seconds.
func health(statePath string) int {
	raw, err := os.ReadFile(statePath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	var doc stateDoc
	if err := json.Unmarshal(raw, &doc); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if age := time.Now().Unix() - doc.At; age > 30 {
		fmt.Fprintf(os.Stderr, "the state is %d s old\n", age)
		return 1
	}
	return 0
}

func main() {
	log.SetFlags(0)
	log.SetPrefix("[dgo-carry] ")
	// The tunnel volume is READ here (the plan and the key) and mounted read-only: what this process
	// writes is its own state, on a volume of its own, so a carrier that went wrong cannot rewrite the
	// pairs, the firewall or the key that dgo-net applies as root.
	dir := flag.String("dir", "/tunnel", "the tunnel volume, read-only: carry.json and wg-private.key")
	statePath := flag.String("state", "/carry/carry-state.json", "where the carrier says what it measured")
	check := flag.Bool("health", false, "exit 0 when the state file is fresh (the container's healthcheck)")
	app := flag.String("app", os.Getenv("DGO_CARRY_APP"),
		"the app the link door passes join requests to (http://dgo-extend:8983); empty = it takes none")
	flag.Parse()
	if *check {
		os.Exit(health(*statePath))
	}
	var appURL *url.URL
	if *app != "" {
		u, err := url.Parse(*app)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			log.Fatalf("-app %q is not an http(s)://host address", *app)
		}
		appURL = u
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	c := NewCarrier(filepath.Join(*dir, "carry.json"), filepath.Join(*dir, "wg-private.key"), *statePath)
	c.app = appURL
	log.Printf("started; plan %s", c.planPath)
	c.Run(ctx)
	c.writeState()
	log.Print("stopped")
}

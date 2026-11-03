package main

// door.go — the office's public link door: ONE HTTP listener behind the edge (traefik routes
// `link.<domain>` here, TLS terminated there), for the offices that can reach this one only over
// HTTPS. It answers exactly four things:
//
//	GET  /carry        a carrier's connection, upgraded to a websocket (ws.go) and then handled like
//	                   one accepted on the TCP port: the pair is proved before a datagram moves
//	GET  /relay        one side of ANOTHER pair, met here by its other side (relay.go) — only the
//	                   pairs the plan declares (`relay_tags`); this office takes no part in them
//	POST /join         a request to join this office — passed to the app (dgo-extend), which owns
//	                   enrollment (an invite, or a request a person approves)
//	GET  /join/<id>    that request's state, for the office that asked
//
// and 404 to everything else. The app's own API is never reachable through this address, whatever
// the edge's rule says: the door names the paths, not the rule.
//
// Behind the edge every connection arrives from the edge's address, so the door limits by the
// address the edge says the request came from (X-Real-Ip), and believes it only from a private
// address — the edge's own network.

import (
	"net"
	"net/http"
	"net/http/httputil"
	"net/netip"
	"net/url"
	"regexp"
	"sync"
	"time"
)

// joinPerMinute bounds the join requests one address may send: a joiner polls every few seconds
// while it waits for a person to approve it, and nothing honest needs more.
const joinPerMinute = 30

// joinBodyLimit bounds a join request's body: an offer is a few hundred bytes.
const joinBodyLimit = 64 << 10

var joinPathRE = regexp.MustCompile(`^/join/[A-Za-z0-9_-]{8,64}$`)

type door struct {
	c     *Carrier
	app   *url.URL // where join requests go; nil = this office takes none
	proxy *httputil.ReverseProxy

	mu   sync.Mutex
	hits map[string][]time.Time
}

func newDoor(c *Carrier, app *url.URL) *door {
	d := &door{c: c, app: app, hits: map[string][]time.Time{}}
	if app != nil {
		d.proxy = &httputil.ReverseProxy{Rewrite: func(pr *httputil.ProxyRequest) {
			// Rewrite starts from a request with every X-Forwarded-* header removed; what the app
			// is told about the caller is the one address this door established.
			pr.SetURL(app)
			pr.Out.Host = app.Host
			pr.Out.Header.Set("X-Real-Ip", sourceOf(pr.In))
			pr.Out.Header.Del("Cookie")
			pr.Out.Header.Del("Authorization")
		}}
	}
	return d
}

// sourceOf is the address a request came from: the edge's X-Real-Ip when the request arrived from
// a private address (the edge, on the office's own network), the connection's address otherwise.
func sourceOf(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	peer, err := netip.ParseAddr(host)
	if err != nil {
		return host
	}
	if peer.IsPrivate() || peer.IsLoopback() {
		if real, err := netip.ParseAddr(r.Header.Get("X-Real-Ip")); err == nil {
			return real.Unmap().String()
		}
	}
	return peer.Unmap().String()
}

func (d *door) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	src := sourceOf(r)
	switch {
	case r.URL.Path == "/carry":
		d.carry(w, r, src)
	case r.URL.Path == "/relay":
		d.relay(w, r, src)
	case r.URL.Path == "/join" && r.Method == http.MethodPost,
		joinPathRE.MatchString(r.URL.Path) && r.Method == http.MethodGet:
		d.join(w, r, src)
	default:
		http.NotFound(w, r)
	}
}

func (d *door) carry(w http.ResponseWriter, r *http.Request, src string) {
	if !d.c.admit(src, d.c.doorPending) {
		http.Error(w, "too many unfinished connections from this address", http.StatusServiceUnavailable)
		return
	}
	defer d.c.release(src, d.c.doorPending)
	conn, err := acceptWS(w, r, src)
	if err != nil {
		return
	}
	d.c.handle(conn) // returns once the pair is proved and its session runs, or the stranger is gone
}

func (d *door) join(w http.ResponseWriter, r *http.Request, src string) {
	if d.proxy == nil {
		http.NotFound(w, r)
		return
	}
	if !d.allow(src) {
		w.Header().Set("Retry-After", "60")
		http.Error(w, "too many join requests from this address — try again in a minute", http.StatusTooManyRequests)
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, joinBodyLimit)
	d.proxy.ServeHTTP(w, r)
}

// allow counts one join request from src and says whether it is within joinPerMinute.
func (d *door) allow(src string) bool {
	now := time.Now()
	d.mu.Lock()
	defer d.mu.Unlock()
	kept := d.hits[src][:0]
	for _, t := range d.hits[src] {
		if now.Sub(t) < time.Minute {
			kept = append(kept, t)
		}
	}
	if len(kept) >= joinPerMinute {
		d.hits[src] = kept
		return false
	}
	d.hits[src] = append(kept, now)
	if len(d.hits) > 4096 { // a flood of addresses forgets the oldest picture rather than growing
		for k, v := range d.hits {
			if len(v) == 0 || now.Sub(v[len(v)-1]) >= time.Minute {
				delete(d.hits, k)
			}
		}
	}
	return true
}

// startDoor binds the door's listener; the caller holds c.mu.
func (c *Carrier) startDoor() {
	ln, err := net.Listen("tcp", c.doorAddr)
	if err != nil {
		c.doorErr = err.Error()
		c.once("cannot open the link door on " + c.doorAddr + ": " + err.Error() + " — retrying")
		return
	}
	srv := &http.Server{Handler: newDoor(c, c.app), ReadHeaderTimeout: 10 * time.Second,
		MaxHeaderBytes: 16 << 10, IdleTimeout: 60 * time.Second}
	c.door, c.doorErr = srv, ""
	c.once("the link door is open on " + c.doorAddr)
	go func() { _ = srv.Serve(ln) }()
}

// stopDoor closes the door's listener. Connections it already handed to pairs live on: they are
// sessions now, not requests. The caller holds c.mu.
func (c *Carrier) stopDoor() {
	if c.door != nil {
		_ = c.door.Close()
		c.door = nil
	}
}

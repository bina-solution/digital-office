package main

// netns.go — a carrier left in a namespace that is gone ends, so that its restart joins the live one (DGO-1753).
//
// The carrier runs in dgo-net's network namespace (`network_mode: service:dgo-net`). When dgo-net is restarted —
// by hand, or by Docker after a crash — it gets a NEW namespace, and this process stays in the old one. Docker
// took that namespace's endpoint (eth0) away with it, so every TCP pair of the office is down while this container
// still reads «healthy». Measured on the Dell, 2026-11-10: wg3 received 0 bytes until a person restarted the
// carrier. Nothing else covers it: autoheal's reviver starts only a container that EXITED, and the heal timer runs
// only after a boot.
//
// WHAT «GONE» MEANS: no default route, IPv4 or IPv6, other than through `lo`. Docker gives a namespace its
// endpoint and that endpoint's default route together, and takes them away together. Devices that are not
// Docker's can outlive dgo-net in the old namespace — a kernel WireGuard interface with its /24, the tunl0 or
// ip6tnl0 a kernel adds to every namespace — so «nothing but loopback» could never be seen there (the second
// reader of DGO-1753); none of them carries a default route here (a pair's route is its /24).
//
// So the carrier looks every 5 s: no default route for `after`, past a `grace` after it started, and it exits
// non-zero. Its restart policy (unless-stopped) starts it again, and a start joins the namespace dgo-net holds NOW.
// A look that fails, or finds a default route, ends the run — a live namespace is never left. No engine socket.

import (
	"context"
	"log"
	"os"
	"strings"
	"time"
)

// strandedExit is the exit status that says why: the namespace this process was started in is gone.
const strandedExit = 3

// noDefaultRoute reads /proc/net/route and /proc/net/ipv6_route: true when neither holds a default route through
// anything but `lo` (IPv6 keeps a reject route for ::/0 on lo in every namespace; it is not a way out).
func noDefaultRoute(route4, route6 string) bool {
	for i, line := range strings.Split(route4, "\n") {
		f := strings.Fields(line)
		// Iface Destination Gateway Flags RefCnt Use Metric Mask …; the first line is the header
		if i > 0 && len(f) >= 8 && f[0] != "lo" && f[1] == "00000000" && f[7] == "00000000" {
			return false
		}
	}
	zero := strings.Repeat("0", 32)
	for _, line := range strings.Split(route6, "\n") {
		f := strings.Fields(line)
		// destination prefix-length source prefix-length next-hop metric refcnt use flags iface
		if len(f) >= 10 && f[0] == zero && f[1] == "00" && f[9] != "lo" {
			return false
		}
	}
	return true
}

// lookRoutes reads this process's own routing tables. The IPv6 table may be missing (IPv6 off); the IPv4 one
// always exists, so a failed IPv4 read is a look that failed — read alone, the IPv6 table (lo's reject route
// only) would say «gone» about a live namespace (the third reader of DGO-1753).
func lookRoutes() (bool, error) {
	r4, err4 := os.ReadFile("/proc/self/net/route")
	if err4 != nil {
		return false, err4
	}
	r6, _ := os.ReadFile("/proc/self/net/ipv6_route")
	return noDefaultRoute(string(r4), string(r6)), nil
}

// stranded decides, one look at a time, whether this process is left in a dead namespace.
type stranded struct {
	start time.Time     // when the carrier started: nothing is decided inside the grace
	grace time.Duration // dgo-net may still be setting up when the carrier starts
	after time.Duration // how long «no default route» must last
	since time.Time     // the first look of the current run; zero when there is none
}

// step takes one look (no default route?, or the error reading the tables) and says whether to end now. A look
// that fails, or that finds a default route, ends the run: only a run of clear answers counts.
func (s *stranded) step(now time.Time, gone bool, err error) bool {
	if err != nil || !gone || now.Sub(s.start) < s.grace {
		s.since = time.Time{}
		return false
	}
	if s.since.IsZero() {
		s.since = now
	}
	return now.Sub(s.since) >= s.after
}

// watchNamespace looks every `every` until ctx ends, and calls `exit` once when the namespace is gone.
func watchNamespace(ctx context.Context, s *stranded, every time.Duration, look func() (bool, error), exit func(int)) {
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-t.C:
			gone, err := look()
			if s.step(now, gone, err) {
				log.Printf("no default route in this namespace for %s: dgo-net was restarted under this carrier — "+
					"ending, so that its restart joins the namespace dgo-net holds now", now.Sub(s.since).Round(time.Second))
				exit(strandedExit)
				return
			}
		}
	}
}

package main

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"
)

const header4 = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"

// a live dgo-net namespace: Docker's endpoint with its default route, and a pair's /24 on wg3
const live4 = header4 +
	"eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n" +
	"eth0\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n" +
	"wg3\t00034F0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"

// the namespace left behind: eth0 is gone with its routes; the kernel WireGuard device and tunl0 outlived dgo-net
const stale4 = header4 + "wg3\t00034F0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"

// IPv6: the reject route ::/0 on lo is in every namespace; a real default goes through eth0
const lo6 = "00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00200200       lo\n"
const live6 = lo6 + "00000000000000000000000000000000 00 00000000000000000000000000000000 00 fd000000000000000000000000000001 00000400 00000001 00000000 00000003     eth0\n"

func TestNoDefaultRoute(t *testing.T) {
	cases := []struct {
		name           string
		route4, route6 string
		want           bool
	}{
		{"live IPv4", live4, lo6, false},
		{"stale: a wg /24 left, no default", stale4, lo6, true},
		{"stale: nothing at all", header4, "", true},
		{"IPv6-only default", header4, live6, false},
		{"a default through lo is no way out", header4 + "lo\t00000000\t00000000\t0001\t0\t0\t0\t00000000\t0\t0\t0\n", lo6, true},
	}
	for _, c := range cases {
		if got := noDefaultRoute(c.route4, c.route6); got != c.want {
			t.Errorf("%s: noDefaultRoute = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestStrandedNeedsGraceAndARun(t *testing.T) {
	t0 := time.Unix(1_000_000, 0)
	s := &stranded{start: t0, grace: 30 * time.Second, after: 20 * time.Second}
	for i := 0; i <= 25; i += 5 {
		if s.step(t0.Add(time.Duration(i)*time.Second), true, nil) {
			t.Fatalf("ended inside the grace at %ds", i)
		}
	}
	if s.step(t0.Add(35*time.Second), true, nil) || s.step(t0.Add(50*time.Second), true, nil) {
		t.Fatal("ended before 20 s without a default route")
	}
	if !s.step(t0.Add(55*time.Second), true, nil) {
		t.Fatal("did not end after 20 s without a default route")
	}
}

func TestStrandedRunIsBrokenByARouteOrAFailedLook(t *testing.T) {
	t0 := time.Unix(1_000_000, 0)
	s := &stranded{start: t0, grace: 0, after: 20 * time.Second}
	s.step(t0, true, nil)
	s.step(t0.Add(15*time.Second), false, nil) // the default route is back: the run ends
	if s.step(t0.Add(25*time.Second), true, nil) {
		t.Fatal("a run broken by a default route still counted its start")
	}
	if !s.step(t0.Add(45*time.Second), true, nil) {
		t.Fatal("a new run of 20 s did not end")
	}
	s2 := &stranded{start: t0, grace: 0, after: 20 * time.Second}
	s2.step(t0, true, nil)
	s2.step(t0.Add(10*time.Second), false, errors.New("cannot read /proc")) // an unanswered look ends the run
	if s2.step(t0.Add(25*time.Second), true, nil) {
		t.Fatal("a failed look did not end the run")
	}
}

func TestWatchNamespaceExitsOnceAndStopsWithItsContext(t *testing.T) {
	var exits, code atomic.Int32
	s := &stranded{start: time.Now().Add(-time.Hour), grace: 0, after: 30 * time.Millisecond}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		watchNamespace(ctx, s, 5*time.Millisecond, func() (bool, error) { return true, nil },
			func(c int) { exits.Add(1); code.Store(int32(c)) })
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("watchNamespace did not return after deciding")
	}
	if exits.Load() != 1 || code.Load() != strandedExit {
		t.Fatalf("exit called %d times with %d, want once with %d", exits.Load(), code.Load(), strandedExit)
	}
	// a namespace with its default route is never left, and the watch ends with its context
	s = &stranded{start: time.Now().Add(-time.Hour), grace: 0, after: 10 * time.Millisecond}
	ctx2, cancel2 := context.WithTimeout(context.Background(), 80*time.Millisecond)
	defer cancel2()
	watchNamespace(ctx2, s, 5*time.Millisecond, func() (bool, error) { return false, nil },
		func(int) { t.Error("left a namespace that has its default route") })
}

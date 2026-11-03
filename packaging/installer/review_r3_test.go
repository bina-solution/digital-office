package main

// Second reader, round 3: the R2-1 design (a revoked key's floor binds the keys listed beside it; only
// a key added later is free), and the R2-3 grace. TestR3Finding* FAIL against the patch; TestR3Probe* PASS.
// go test -count=1 -run '^TestR3' -v .

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust/trusttest"
)

// R3-1 — "a key that list adds" is free of the revoked key's floor, and a RE-added key is added too.
// K1 signed 1.4.0, the lane rotated to K2 (no overlap, as the README allows), the computer took 1.5.0
// from K2. Then K2 goes (leaked, or simply retired) and the list brings back K1 — the owner's older,
// never-leaked key. K1's unexpired 1.4.0 is replayed. With the README's -core-floor it is refused; without
// it — the case the "beside" design was chosen to cover ("a forgotten floor") — it rolls the core back.
func TestR3FindingAReAddedKeyCannotRollBack(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl) // r.Signer = K1
	k2 := trusttest.NewKey(t)
	from, until := trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 1, 0)
	core := dl + "/linux/amd64/dgo-core"
	oldCore, newCore := []byte("DGO core 1.4.0 (known-vulnerable)"), []byte("DGO core 1.5.0")
	k1Old := trusttest.Seal(r.Signer, trust.ManifestType, payloadDoc(r, "1.4.0", core, oldCore))
	l4 := r.KeysDoc()
	l4["version"], l4["keys"] = 4, []any{trusttest.Window(k2, from, until)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l4))
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(k2, trust.ManifestType, payloadDoc(r, "1.5.0", core, newCore)))
	s.serve("/dl/linux/amd64/dgo-core", newCore)
	tmp := t.TempDir()
	in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
	if err := in.run(); err != nil {
		t.Fatalf("precondition: %v", err)
	}
	for i, floor := range []string{"1.5.0", ""} { // with the README's -core-floor first, then without it
		l := r.KeysDoc()
		l["version"], l["keys"] = 5+i, []any{trusttest.Window(r.Signer, from, until)} // K2 gone, K1 back
		if floor != "" {
			l["core_floor"] = floor
		}
		s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l))
		s.serve("/dl/linux/amd64/manifest.json", k1Old)
		s.serve("/dl/linux/amd64/dgo-core", oldCore)
		out := &bytes.Buffer{}
		in.out = out
		err := in.run()
		got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
		if bytes.Equal(got, oldCore) {
			t.Fatalf("core_floor %q: re-adding K1 let its 1.4.0 roll this computer back from 1.5.0 (err %v):\n%s", floor, err, lastLine(out.String()))
		}
		t.Logf("core_floor %q: refused (%v)", floor, err)
	}
}

// R3-2 — the binding never lapses, and no root-signed statement lifts it. The owner follows the README
// after K2 leaked and fast-forwarded this computer to 999999999.0.0: list 4 revokes K2, keeps K1, ADDS
// K3, raises core_floor, and K3 signs the real 1.5.0 — but this computer is off during list 4's life.
// Later the emergency key K3 is retired and the lane returns to K1, which signs 1.6.0. This computer now
// refuses every release K1 will ever sign, and keeps the attacker's core.
func TestR3FindingAKeptKeyIsNotHeldForever(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl) // K1
	k2, k3 := trusttest.NewKey(t), trusttest.NewKey(t)
	from, until := trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 1, 0)
	core := dl + "/linux/amd64/dgo-core"
	l3 := r.KeysDoc()
	l3["keys"] = []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k2, from, until)} // K1 and K2 overlap
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l3))
	evil := []byte("the leaked key's core")
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(k2, trust.ManifestType, payloadDoc(r, "999999999.0.0", core, evil)))
	s.serve("/dl/linux/amd64/dgo-core", evil)
	tmp := t.TempDir()
	in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
	if err := in.run(); err != nil {
		t.Fatalf("precondition (K2 still listed): %v", err)
	}
	// List 4 (README recovery: revoke K2, keep K1, add K3, raise core_floor; K3 signs 1.5.0) comes and
	// goes while this computer is off. List 5 retires K3; K1 signs 1.6.0.
	_ = k3
	l5 := r.KeysDoc()
	l5["version"], l5["core_floor"], l5["keys"] = 5, "1.5.0", []any{trusttest.Window(r.Signer, from, until)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l5))
	real := []byte("DGO core 1.6.0, the owner's")
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, payloadDoc(r, "1.6.0", core, real)))
	s.serve("/dl/linux/amd64/dgo-core", real)
	err := in.run()
	got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
	if err != nil || !bytes.Equal(got, real) {
		t.Fatalf("a computer the leaked key fast-forwarded, which missed list 4, refuses the owner's 1.6.0 by K1 for good: %v; core still %q", err, got)
	}
}

// PROBE — overlaps: whoever stood beside the revoked key stays bound by what it vouched for.
func TestR3ProbeOverlappingKeysStayBound(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl) // K1
	k2, k3, k4 := trusttest.NewKey(t), trusttest.NewKey(t), trusttest.NewKey(t)
	from, until := trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 1, 0)
	core := dl + "/linux/amd64/dgo-core"
	l3 := r.KeysDoc()
	l3["keys"] = []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k2, from, until), trusttest.Window(k3, from, until)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l3))
	newest := []byte("1.5.0 by K3")
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(k3, trust.ManifestType, payloadDoc(r, "1.5.0", core, newest)))
	s.serve("/dl/linux/amd64/dgo-core", newest)
	tmp := t.TempDir()
	in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
	if err := in.run(); err != nil {
		t.Fatal(err)
	}
	for _, step := range []struct {
		name string
		keys []any
		by   *[]byte
	}{
		{"K3 revoked, K1's 1.4.0", []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k2, from, until)}, nil},
		{"K3 revoked, K2's 1.4.5", []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k2, from, until)}, nil},
		{"K3 and K2 revoked, K4 added, K1's 1.4.0", []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k4, from, until)}, nil},
	} {
		l := r.KeysDoc()
		l["version"], l["keys"] = 4, step.keys
		if strings.Contains(step.name, "K4") {
			l["version"] = 5
		}
		s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l))
		signer, ver := r.Signer, "1.4.0"
		if strings.Contains(step.name, "K2's") {
			signer, ver = k2, "1.4.5"
		}
		old := []byte("an older release")
		s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(signer, trust.ManifestType, payloadDoc(r, ver, core, old)))
		s.serve("/dl/linux/amd64/dgo-core", old)
		err := in.run()
		got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
		if err == nil || !bytes.Equal(got, newest) {
			t.Errorf("%s: err %v, core %q", step.name, err, got)
		}
	}
}

// PROBE — the clock grace is the window's start only: 10 minutes early is taken, a second more is not;
// an ended window, an expired key list and an expired manifest get nothing.
func TestR3ProbeTheClockGraceIsOnlyAtAWindowsStart(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	try := func(from, until, listExpires, manExpires time.Time) error {
		kd := r.KeysDoc()
		kd["expires"], kd["keys"] = trusttest.RFC3339(listExpires), []any{trusttest.Window(r.Signer, from, until)}
		c := r.Checker(t)
		kl, err := c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, kd))
		if err != nil {
			return err
		}
		md := r.ManifestDoc()
		md["expires"] = trusttest.RFC3339(manExpires)
		_, err = c.VerifyManifest(trusttest.Seal(r.Signer, trust.ManifestType, md), kl)
		return err
	}
	now, later := trusttest.Now, trusttest.Now.Add(time.Hour)
	for _, tc := range []struct {
		name              string
		from, until, l, m time.Time
		ok                bool
	}{
		{"window opens in 10 minutes", now.Add(10 * time.Minute), later, later, later, true},
		{"window opens in 10 minutes and 1 second", now.Add(10*time.Minute + time.Second), later, later, later, false},
		{"window ended now", now.Add(-time.Hour), now, later, later, false},
		{"window ends in a second", now.Add(-time.Hour), now.Add(time.Second), later, later, true},
		{"window ended 1s ago, opened in grace", now.Add(5 * time.Minute), now.Add(-time.Second), later, later, false},
		{"key list expired now", now.Add(-time.Hour), later, now, later, false},
		{"manifest expired now", now.Add(-time.Hour), later, later, now, false},
	} {
		err := try(tc.from, tc.until, tc.l, tc.m)
		if (err == nil) != tc.ok {
			t.Errorf("%s: err %v, want accepted=%v", tc.name, err, tc.ok)
		}
	}
	// A root-signed window that is empty by its own terms (not_after before not_before, which relsign
	// refuses to write): the grace makes it acceptable for the minutes between them.
	err := try(now.Add(5*time.Minute), now.Add(time.Minute), later, later)
	t.Logf("an inverted window [now+5m, now+1m): accepted=%v (%v)", err == nil, err)
}

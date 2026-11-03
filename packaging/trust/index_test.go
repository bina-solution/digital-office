package trust_test

// The store's index document (index.go), one test per rule: the chain's own rules — the type, a key
// listed for it inside its window, the site, the floor — held to the index, and the two places it
// differs from a core manifest: its bytes are pinned per version, and core_floor is no floor of it.

import (
	"crypto/ed25519"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust/trusttest"
)

const storeSite = "https://apps.net.digital-office.co.il/v1"

// storeChecker is a fresh computer's reader of the store's site: r's roots, nothing accepted yet.
func storeChecker(t *testing.T, r *trusttest.Release) trust.Checker {
	t.Helper()
	c := r.Checker(t)
	c.Site, c.Type = storeSite, trust.IndexType
	return c
}

// forIndex is a keys.json entry trusting k for the store's index, from a month ago for five months.
func forIndex(k ed25519.PrivateKey) map[string]any {
	return trusttest.Listed(k, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0), trust.IndexType)
}

// storeList is the store's key list number version, listing entries (and core_floor, if stated), signed
// by r's root and read by c.
func storeList(t *testing.T, r *trusttest.Release, c trust.Checker, version int, coreFloor string, entries ...any) trust.KeyList {
	t.Helper()
	d := r.KeysDoc()
	d["site"], d["version"], d["keys"] = storeSite, version, entries
	if coreFloor != "" {
		d["core_floor"] = coreFloor
	}
	kl, err := c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d))
	if err != nil {
		t.Fatal(err)
	}
	return kl
}

// index is the store's index document at version, pinning body.
func index(version string, body []byte) map[string]any {
	return map[string]any{"site": storeSite, "version": version, "sha256": trusttest.SHA256Hex(body), "size": len(body)}
}

func TestTheIndexVerifies(t *testing.T) {
	r := trusttest.NewRelease(t, storeSite)
	c := storeChecker(t, r)
	kl := storeList(t, r, c, 3, "", forIndex(r.Signer))
	body := []byte(`{"format":"bina.catalog/v1","version":"1.4.0","entries":[]}`)
	want := trust.IndexDoc{Site: storeSite, Version: "1.4.0", SHA256: trusttest.SHA256Hex(body), Size: int64(len(body))}
	ix, by, err := c.VerifyIndex(trusttest.Seal(r.Signer, trust.IndexType, index("1.4.0", body)), kl)
	if err != nil || ix != want || by != trust.KeyID(trusttest.PubOf(r.Signer)) {
		t.Fatalf("an index signed by a key listed for it must verify: %+v by %s, %v", ix, by, err)
	}
	// The site written with its trailing slash is the same site; a sha256 in capitals is the same hex.
	d := index("1.4.0", body)
	d["site"], d["sha256"] = storeSite+"/", strings.ToUpper(want.SHA256)
	if ix, _, err := c.VerifyIndex(trusttest.Seal(r.Signer, trust.IndexType, d), kl); err != nil || ix.SHA256 != want.SHA256 {
		t.Fatalf("the same site and the same sha256, written otherwise, must verify: %+v %v", ix, err)
	}
	// A key listed for both kinds of document signs each as what it is.
	both := storeList(t, r, c, 4, "", trusttest.Listed(r.Signer, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0),
		trust.ManifestType, trust.IndexType))
	if _, _, err := c.VerifyIndex(trusttest.Seal(r.Signer, trust.IndexType, index("1.4.0", body)), both); err != nil {
		t.Fatalf("a key listed for both kinds must sign an index: %v", err)
	}
}

func TestIndexRefusals(t *testing.T) {
	r := trusttest.NewRelease(t, storeSite)
	c := storeChecker(t, r)
	kl := storeList(t, r, c, 3, "", forIndex(r.Signer))
	coreOnly := storeList(t, r, c, 3, "", trusttest.Window(r.Signer, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0)))
	notYet := storeList(t, r, c, 3, "", trusttest.Listed(r.Signer, trusttest.Now.Add(time.Hour), trusttest.Now.Add(2*time.Hour), trust.IndexType))
	body := []byte("the index")
	good := trusttest.Seal(r.Signer, trust.IndexType, index("1.4.0", body))
	edited := func(f func(map[string]any)) []byte {
		d := index("1.4.0", body)
		f(d)
		return trusttest.Seal(r.Signer, trust.IndexType, d)
	}
	stranger := trusttest.NewKey(t)
	cases := []struct {
		name string
		raw  []byte
		kl   trust.KeyList
		want string
	}{
		{"forged: the sha256 changed after signing", trusttest.Forge(good, func(d map[string]any) { d["sha256"] = strings.Repeat("0", 64) }), kl, "does not verify"},
		{"forged: the version raised after signing", trusttest.Forge(good, func(d map[string]any) { d["version"] = "9.9.9" }), kl, "does not verify"},
		{"signed by a key keys.json does not list", trusttest.Seal(stranger, trust.IndexType, index("1.4.0", body)), kl, "unknown signer"},
		{"signed by a root — roots sign key lists only", trusttest.Seal(r.Root, trust.IndexType, index("1.4.0", body)), kl, "unknown signer"},
		{"signed by a key listed for core manifests only", good, coreOnly, "does not trust that key to sign dgo-app-index"},
		{"signed by a key whose window has not opened", good, notYet, "valid only from"},
		{"a core manifest where the index's signature belongs", r.ManifestJSON(), kl, "payloadType"},
		{"keys.json where the index's signature belongs", r.KeysJSON(), kl, "payloadType"},
		{"another channel's index, under the same roots and key", edited(func(d map[string]any) { d["site"] = "https://staging.example.org/v1" }), kl, "it is the index of https://staging.example.org/v1"},
		{"the store's index over plain http", edited(func(d map[string]any) { d["site"] = "http://apps.net.digital-office.co.il/v1" }), kl, "it is the index of http://"},
		{"no site", edited(func(d map[string]any) { delete(d, "site") }), kl, `"site"`},
		{"a pre-release version, which no floor could order", edited(func(d map[string]any) { d["version"] = "1.5.0-rc.1" }), kl, "not a release version"},
		{"no version", edited(func(d map[string]any) { delete(d, "version") }), kl, `"version"`},
		{"sha256 not hex", edited(func(d map[string]any) { d["sha256"] = "zz" }), kl, "not 64 hex"},
		{"size zero", edited(func(d map[string]any) { d["size"] = 0 }), kl, "size is 0"},
		{"size missing", edited(func(d map[string]any) { delete(d, "size") }), kl, `"size"`},
		{"a signature that is not 64 bytes of strict base64", trusttest.EditEnvelope(good, func(e map[string]any) {
			s := e["signatures"].([]any)[0].(map[string]any)
			s["sig"] = strings.TrimRight(s["sig"].(string), "=")
		}), kl, "64 bytes of base64"},
	}
	for _, tc := range cases {
		_, _, err := c.VerifyIndex(tc.raw, tc.kl)
		if err == nil || !strings.Contains(err.Error(), tc.want) || !strings.HasPrefix(err.Error(), "index.sig.json: ") {
			t.Errorf("%s: err = %v, want an index refusal containing %q", tc.name, err, tc.want)
		}
	}
}

// This computer's floor: an older index is refused, the very index again is no replay, another index
// under that version is refused — one version, one index — and a newer one passes.
func TestTheIndexFloorPinsOneIndexPerVersion(t *testing.T) {
	r := trusttest.NewRelease(t, storeSite)
	c := storeChecker(t, r)
	kl := storeList(t, r, c, 3, "", forIndex(r.Signer))
	two := []byte("index 2.0.0")
	c.Seen = trust.Seen{Keys: 3, Manifest: "2.0.0", ManifestBy: trust.KeyID(trusttest.PubOf(r.Signer)), ManifestSum: trusttest.SHA256Hex(two)}
	for _, tc := range []struct {
		name, version string
		body          []byte
		want          string // "" = accepted
	}{
		{"an older index, replayed", "1.0.0", []byte("index 1.0.0"), "a replayed old index"},
		{"the very index again (a re-run)", "2.0.0", two, ""},
		{"another index under that version", "2.0.0", []byte("index 2.0.0, again"), "one version, one index"},
		{"a newer index", "3.0.0", []byte("index 3.0.0"), ""},
	} {
		_, _, err := c.VerifyIndex(trusttest.Seal(r.Signer, trust.IndexType, index(tc.version, tc.body)), kl)
		if tc.want == "" && err != nil || tc.want != "" && (err == nil || !strings.Contains(err.Error(), tc.want)) {
			t.Errorf("%s: err = %v, want %q", tc.name, err, tc.want)
		}
	}
	// A floor that pins no bytes holds the version only.
	c.Seen.ManifestSum = ""
	if _, _, err := c.VerifyIndex(trusttest.Seal(r.Signer, trust.IndexType, index("2.0.0", []byte("index 2.0.0, again"))), kl); err != nil {
		t.Errorf("a floor without its bytes holds the version, not the bytes: %v", err)
	}
}

// After a leak: k2 signed index 9.0.0 and this computer took it, k1 listed beside it. List 4 revokes k2,
// keeps k1 and adds k3. k1's older index stays refused — it may have signed it before — while k3's real
// 1.5.0 passes; and a core_floor stated in the store's list moves no index floor.
func TestARevokedIndexKeysFloorBindsOnlyTheKeysBesideIt(t *testing.T) {
	r := trusttest.NewRelease(t, storeSite) // r.Signer is k1
	k2, k3 := trusttest.NewKey(t), trusttest.NewKey(t)
	c := storeChecker(t, r)
	l3 := storeList(t, r, c, 3, "", forIndex(r.Signer), forIndex(k2),
		trusttest.Window(trusttest.NewKey(t), trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0)))
	k1, k2id := trust.KeyID(trusttest.PubOf(r.Signer)), trust.KeyID(trusttest.PubOf(k2))
	if got := l3.Besides(k2id); got != k1 {
		t.Fatalf("beside k2 stood k1 alone (the core key signs no index): %q", got)
	}
	c.Seen = trust.Seen{Keys: 3, Manifest: "9.0.0", ManifestBy: k2id, Beside: k1, ManifestSum: trusttest.SHA256Hex([]byte("the leaked key's index"))}
	l4 := storeList(t, r, c, 4, "1.5.0", forIndex(r.Signer), forIndex(k3))
	if s := l4.Settle(c.Seen); s != c.Seen {
		t.Errorf("core_floor names core releases, never an index floor: Settle moved it to %+v", s)
	}
	old := trusttest.Seal(r.Signer, trust.IndexType, index("1.4.0", []byte("index 1.4.0")))
	if _, _, err := c.VerifyIndex(old, l3); err == nil {
		t.Error("while keys.json lists k2, its floor binds every key")
	}
	if _, _, err := c.VerifyIndex(old, l4); err == nil || !strings.Contains(err.Error(), "a replayed old index") {
		t.Errorf("k1 stood beside k2: its 1.4.0, replayed once k2 is revoked, must stay refused: %v", err)
	}
	if _, _, err := c.VerifyIndex(trusttest.Seal(k3, trust.IndexType, index("1.5.0", []byte("index 1.5.0, the real one"))), l4); err != nil {
		t.Errorf("k3 was listed after k2's floor was set, so it is free of it: %v", err)
	}
}

// A reader names the documents its site serves, and a key list read for one kind vouches for no other:
// the floors it settles and binds are that kind's.
func TestAKeyListReadForOneKindVouchesForNoOther(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	c := r.Checker(t)
	c.Type = ""
	if _, err := c.VerifyKeys(r.KeysJSON()); err == nil || !strings.Contains(err.Error(), "names no document") {
		t.Errorf("a reader that names no kind of document must read nothing: %v", err)
	}
	c.Type = trust.IndexType
	forTheIndex, err := c.VerifyKeys(r.KeysJSON())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.VerifyManifest(r.ManifestJSON(), forTheIndex); err == nil || !strings.Contains(err.Error(), "read for") {
		t.Errorf("a key list read for the store's index must not vouch for a core manifest: %v", err)
	}
	c.Type = trust.ManifestType
	forCores, err := c.VerifyKeys(r.KeysJSON())
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := c.VerifyIndex(trusttest.Seal(r.Signer, trust.IndexType, index("1.4.0", []byte("x"))), forCores); err == nil || !strings.Contains(err.Error(), "read for") {
		t.Errorf("a key list read for core manifests must not vouch for an index: %v", err)
	}
}

// The state file pins a document's bytes only where they were pinned: the store's line has a seventh
// field, the stub's keeps its six, and a save keeps every other line of either shape.
func TestOnlyAPinnedLineHasASeventhField(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state")
	const header, dl = "# a test's state\n", "https://digital-office.co.il/dl"
	all := func(string) bool { return true }
	pinned := trust.Seen{Keys: 2, KeysSum: strings.Repeat("a", 64), Manifest: "1.4.0", ManifestBy: "k1", ManifestSum: strings.Repeat("c", 64)}
	stub := trust.Seen{Keys: 3, KeysSum: strings.Repeat("b", 64), Manifest: "1.5.0", ManifestBy: "k9", Beside: "k8"}
	for site, s := range map[string]trust.Seen{storeSite: pinned, dl: stub} {
		if err := trust.SaveSeen(path, header, site, "r1", s, all); err != nil {
			t.Fatal(err)
		}
	}
	raw, _ := os.ReadFile(path)
	for _, line := range []string{
		storeSite + " r1 2 " + pinned.KeysSum + " 1.4.0 k1 " + pinned.ManifestSum, // the store's: its sha256 pinned
		dl + " r1 3 " + stub.KeysSum + " 1.5.0 k9,k8",                             // the stub's: the six fields it always had
	} {
		if !strings.Contains("\n"+string(raw), "\n"+line+"\n") {
			t.Errorf("the state file must hold the line %q, byte for byte:\n%s", line, raw)
		}
	}
	for site, want := range map[string]trust.Seen{storeSite: pinned, dl: stub} {
		if got, err := trust.LoadSeen(path, site, "r1"); err != nil || got != want {
			t.Errorf("%s: read back %+v (%v), want %+v", site, got, err, want)
		}
	}
	// A save that overlapped a newer one keeps the newer floor, its pin with it.
	older := trust.Seen{Keys: 2, KeysSum: pinned.KeysSum, Manifest: "1.3.0", ManifestBy: "k1", ManifestSum: strings.Repeat("d", 64)}
	if err := trust.SaveSeen(path, header, storeSite, "r1", older, all); err != nil {
		t.Fatal(err)
	}
	if got, _ := trust.LoadSeen(path, storeSite, "r1"); got != pinned {
		t.Errorf("the newer floor must stand with its pin: %+v", got)
	}
	if err := os.WriteFile(path, []byte(storeSite+" r1 2 - 1.4.0 k1 "+strings.Repeat("c", 64)+" more\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := trust.LoadSeen(path, storeSite, "r1"); err == nil {
		t.Error("an eight-field line is no line of this file: it must be refused")
	}
}

// TestTheRootsIndexFloorTakesARevokedKeysPlace: index_floor is to the store's index what core_floor is
// to a core — on this computer's memory (Settle), case by case, and on a computer that remembers nothing
// (VerifyIndex). The root's floor pins no bytes, so the pin of the floor it replaces goes with it.
func TestTheRootsIndexFloorTakesARevokedKeysPlace(t *testing.T) {
	r := trusttest.NewRelease(t, storeSite)
	c := storeChecker(t, r)
	k1, gone := trust.KeyID(trusttest.PubOf(r.Signer)), trust.KeyID(trusttest.PubOf(trusttest.NewKey(t)))
	list := func(floor string) trust.KeyList {
		t.Helper()
		d := r.KeysDoc()
		d["keys"] = []any{forIndex(r.Signer)}
		if floor != "" {
			d["index_floor"] = floor
		}
		kl, err := c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d))
		if err != nil {
			t.Fatal(err)
		}
		return kl
	}
	pin := strings.Repeat("a", 64)
	root := func(v string) trust.Seen { return trust.Seen{Manifest: v, ManifestBy: trust.ViaKeysJSON} }
	for _, tc := range []struct {
		name      string
		floor     string
		was, want trust.Seen
	}{
		{"a revoked key's floor gives way to the root's, downward too, its pin with it", "1.5.0",
			trust.Seen{Manifest: "999999999.0.0", ManifestBy: gone, Beside: k1, ManifestSum: pin}, root("1.5.0")},
		{"a listed key's floor above index_floor stays, pinned", "1.5.0",
			trust.Seen{Manifest: "1.6.0", ManifestBy: k1, ManifestSum: pin}, trust.Seen{Manifest: "1.6.0", ManifestBy: k1, ManifestSum: pin}},
		{"a listed key's floor below index_floor rises to it", "1.5.0", trust.Seen{Manifest: "1.4.0", ManifestBy: k1, ManifestSum: pin}, root("1.5.0")},
		{"a computer that remembers nothing takes the root's floor", "1.5.0", trust.Seen{}, root("1.5.0")},
		{"the root's floor never falls to a lower index_floor", "1.4.0", root("1.5.0"), root("1.5.0")},
		{"no index_floor: a revoked key's floor stands", "",
			trust.Seen{Manifest: "1.5.0", ManifestBy: gone, Beside: k1}, trust.Seen{Manifest: "1.5.0", ManifestBy: gone, Beside: k1}},
	} {
		if got := list(tc.floor).Settle(tc.was); got != tc.want {
			t.Errorf("%s: Settle(%+v) = %+v, want %+v", tc.name, tc.was, got, tc.want)
		}
	}
	if list("1.5.0").Binds(gone, k1, k1) {
		t.Error("once the root states index_floor, a revoked key's floor holds no key — not even one beside it")
	}
	if _, _, err := c.VerifyIndex(trusttest.Seal(r.Signer, trust.IndexType, index("1.4.0", []byte("an old index"))), list("1.4.1")); err == nil ||
		!strings.Contains(err.Error(), "the oldest keys.json allows") {
		t.Errorf("an index older than index_floor must be refused, on a computer that remembers nothing too: %v", err)
	}
	if _, _, err := c.VerifyIndex(trusttest.Seal(r.Signer, trust.IndexType, index("1.4.1", []byte("the floor's own index"))), list("1.4.1")); err != nil {
		t.Errorf("an index at index_floor itself must verify: %v", err)
	}
}

// Each root floor holds its own kind of document only — a stub's list stating index_floor holds no core
// release (and the store's stating core_floor no index: TestARevokedIndexKeysFloorBindsOnlyTheKeysBesideIt)
// — and index_floor is read as strictly as core_floor.
func TestARootFloorHoldsOnlyItsOwnKind(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	c := r.Checker(t)
	d := r.KeysDoc()
	d["index_floor"] = "9.0.0"
	kl, err := c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d))
	if err != nil || kl.IndexFloor != "9.0.0" || kl.CoreFloor != "" {
		t.Fatalf("index_floor read: %+v, %v", kl, err)
	}
	if _, err := c.VerifyManifest(r.ManifestJSON(), kl); err != nil {
		t.Errorf("index_floor must hold no core release: %v", err)
	}
	if s := kl.Settle(trust.Seen{Manifest: "1.4.0", ManifestBy: "gone"}); s.ManifestBy == trust.ViaKeysJSON {
		t.Errorf("index_floor must move no core floor: %+v", s)
	}
	for floor, want := range map[any]string{"1.5.0-rc.1": "not a release version", 15: `"index_floor"`, "": `"index_floor"`} {
		d := r.KeysDoc()
		d["index_floor"] = floor
		if _, err := c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d)); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("index_floor %v: err = %v, want a refusal containing %q", floor, err, want)
		}
	}
}

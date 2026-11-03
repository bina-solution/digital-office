package main

// Second reader, round 2 (core-stub.patch after the security round). TestR2Finding* state a property the
// stub should hold and FAIL against the patch; TestR2Probe* are attacks it withstands and PASS.
// go test -count=1 -run '^TestR2' -v .

import (
	"bytes"
	"crypto/ed25519"
	"crypto/x509"
	"encoding/pem"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust/trusttest"
)

// R2-1 — revoking the NEWER of two listed keys reopens rollback to anything the older one signed. The
// floor dropped with the revoked key is not replaced by any other, and an install whose signer was
// revoked is replaced "whatever their numbers" — so a replay of the older key's unexpired 1.4.0 rolls
// back a computer that had 1.5.0. Before this round the same replay was refused by the 1.5.0 floor.
func TestR2FindingRevokingTheNewerKeyDoesNotReopenAnOlderRelease(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl) // r.Signer = K1: the release lane's key before the rotation
	k2 := trusttest.NewKey(t)
	from, until := trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 1, 0)
	overlap := r.KeysDoc() // list 3: K1 and K2 overlap — the README's "(and the old one, if both should overlap)"
	overlap["keys"] = []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k2, from, until)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, overlap))
	core := dl + "/linux/amd64/dgo-core"
	oldCore, newCore := []byte("DGO core 1.4.0 (known-vulnerable)"), []byte("DGO core 1.5.0 (the fix)")
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(k2, trust.ManifestType, payloadDoc(r, "1.5.0", core, newCore)))
	s.serve("/dl/linux/amd64/dgo-core", newCore)
	tmp := t.TempDir()
	in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
	if err := in.run(); err != nil {
		t.Fatalf("precondition: %v", err)
	}
	// K2 leaks; the owner revokes it with list 4, which keeps K1.
	revoked := r.KeysDoc()
	revoked["version"] = 4
	revoked["keys"] = []any{trusttest.Window(r.Signer, from, until)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, revoked))
	// The replay: K1's 1.4.0, signed before the rotation, not yet expired.
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, payloadDoc(r, "1.4.0", core, oldCore)))
	s.serve("/dl/linux/amd64/dgo-core", oldCore)
	out := &bytes.Buffer{}
	in.out = out
	err := in.run()
	got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
	if bytes.Equal(got, oldCore) {
		t.Fatalf("revoking K2 let a replay roll this computer back from 1.5.0 to 1.4.0 (err %v):\n%s", err, out.String())
	}
}

// R2-2 — the roots are not pinned against a build flag: `-X main.rootKeys=…` replaces the embedded
// roots.txt (the linker sets any string variable, a //go:embed one included). main.go says "no build
// flag can put other roots in a stub". (Embedding into a []byte makes -X a build error.)
func TestR2FindingALinkerFlagCannotReplaceTheEmbeddedRoots(t *testing.T) {
	goBin, err := exec.LookPath("go")
	if err != nil {
		t.Skip("go not on PATH")
	}
	bin := filepath.Join(t.TempDir(), "stub")
	if runtime.GOOS == "windows" {
		bin += ".exe"
	}
	injected := trusttest.B64(trusttest.PubOf(trusttest.NewKey(t)))
	build := exec.Command(goBin, "build", "-o", bin, "-ldflags",
		"-X main.siteURL=https://digital-office.co.il/dl -X main.version=1.4.0 -X main.rootKeys="+injected, ".")
	build.Env = append(os.Environ(), "CGO_ENABLED=0")
	if out, err := build.CombinedOutput(); err != nil {
		t.Logf("the build refused the flag (the fix): %v\n%s", err, out)
		return
	}
	raw, _ := os.ReadFile(bin)
	v, _ := exec.Command(bin, "--version").Output()
	if bytes.Contains(raw, []byte(injected)) || !strings.Contains(string(v), "development build") {
		t.Fatalf("a stub built with -X main.rootKeys trusts the injected root (embedded: %v); --version: %s",
			bytes.Contains(raw, []byte(injected)), strings.TrimSpace(string(v)))
	}
}

// R2-3 — every routine re-sign of keys.json (now at least every 60 days) moves the online key's
// not_before to the signing instant, relsign's default, and the stub allows no skew: a computer whose
// clock is a few minutes slow refuses EVERY release until its clock passes that instant, though the key
// was valid all along. (Same for a dual-boot RTC hours off.)
func TestR2FindingARoutineResignDoesNotRefuseASlowClock(t *testing.T) {
	goBin, err := exec.LookPath("go")
	if err != nil {
		t.Skip("go not on PATH")
	}
	dir := t.TempDir()
	bin := filepath.Join(dir, "relsign")
	if runtime.GOOS == "windows" {
		bin += ".exe"
	}
	build := exec.Command(goBin, "build", "-o", bin, ".")
	build.Dir = filepath.Join("..", "relsign")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("building relsign: %v\n%s", err, out)
	}
	relsign := func(args ...string) []byte {
		t.Helper()
		var stderr bytes.Buffer
		cmd := exec.Command(bin, args...)
		cmd.Stderr = &stderr
		out, err := cmd.Output()
		if err != nil {
			t.Fatalf("relsign %v: %v\n%s", args, err, stderr.String())
		}
		return out
	}
	root, signer := filepath.Join(dir, "root.pem"), filepath.Join(dir, "signer.pem")
	relsign("keygen", root)
	relsign("keygen", signer)
	const site = "https://digital-office.co.il/dl"
	keysJSON := relsign("keys", "-signer", root, "-site", site, "-version", "7", "-key", signer, "-types", "dgo-core-manifest")
	roots, err := trust.ParseRoots(strings.TrimSpace(string(relsign("pubkey", root))))
	if err != nil {
		t.Fatal(err)
	}
	pemBytes, _ := os.ReadFile(signer)
	block, _ := pem.Decode(pemBytes)
	k, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	r := &trusttest.Release{Signer: k.(ed25519.PrivateKey), Site: site, Payload: []byte("core")}
	doc := r.ManifestDoc()
	doc["expires"] = trusttest.RFC3339(time.Now().AddDate(0, 0, 30))
	slow := time.Now().Add(-3 * time.Minute) // this computer's clock: three minutes behind
	c := trust.Checker{Type: trust.ManifestType, Roots: roots, Site: site, Now: slow, Stub: "1.2.0", Target: trusttest.Target}
	kl, err := c.VerifyKeys(keysJSON)
	if err != nil {
		t.Fatalf("keys.json itself passes (only its expiry is checked): %v", err)
	}
	if _, err := c.VerifyManifest(trusttest.Seal(r.Signer, trust.ManifestType, doc), kl); err != nil {
		t.Fatalf("a clock three minutes slow refuses a release signed by a key the list has carried all along: %v", err)
	}
}

// PROBE — the floor can only be dropped by the owner's own newer list. An older list without the
// floor's key, another list under the same version, and another site's list numbered ahead are all
// refused at keys.json, and the floor, the record and the core survive each attempt.
func TestR2ProbeAListThatOmitsTheFloorsKeyCannotBeForced(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	k2 := trusttest.NewKey(t)
	from, until := trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 1, 0)
	l3 := r.KeysDoc() // K1 only
	l4 := r.KeysDoc()
	l4["version"] = 4
	l4["keys"] = []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k2, from, until)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l4))
	core := dl + "/linux/amd64/dgo-core"
	newCore, oldCore := []byte("1.5.0"), []byte("1.4.0")
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(k2, trust.ManifestType, payloadDoc(r, "1.5.0", core, newCore)))
	s.serve("/dl/linux/amd64/dgo-core", newCore)
	tmp := t.TempDir()
	in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
	if err := in.run(); err != nil {
		t.Fatal(err)
	}
	before, _ := trust.LoadSeen(in.state, dl, r.RootsID(t))
	l4b := r.KeysDoc()
	l4b["version"] = 4 // the owner's slip: a list changed under the same version
	foreign := r.KeysDoc()
	foreign["site"], foreign["version"] = strings.TrimSuffix(dl, "/dl")+"/beta", 9
	for name, served := range map[string][]byte{
		"an older list without K2":                   trusttest.Seal(r.Root, trust.KeysType, l3),
		"another list under the same version, no K2": trusttest.Seal(r.Root, trust.KeysType, l4b),
		"another site's list, numbered ahead, no K2": trusttest.Seal(r.Root, trust.KeysType, foreign),
		"an older list, signed by the other root":    trusttest.Seal(r.Spare, trust.KeysType, l3),
	} {
		s.serve("/dl/keys.json", served)
		s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, payloadDoc(r, "1.4.0", core, oldCore)))
		s.serve("/dl/linux/amd64/dgo-core", oldCore)
		err := in.run()
		after, _ := trust.LoadSeen(in.state, dl, r.RootsID(t))
		got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
		if err == nil || !strings.HasPrefix(err.Error(), "keys.json: ") || after.Manifest != before.Manifest ||
			after.ManifestBy != before.ManifestBy || !bytes.Equal(got, newCore) {
			t.Errorf("%s: err %v; floor %+v -> %+v; core %q", name, err, before, after, got)
		}
	}
}

// PROBE — another site's line and another set of roots' line are neither read nor lost.
func TestR2ProbeOtherLinesOfTheStateFileAreNotThisOnes(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	s.serve("/dl/keys.json", r.KeysJSON())
	s.serve("/dl/linux/amd64/manifest.json", r.ManifestJSON())
	s.serve("/dl/linux/amd64/dgo-core", r.Payload)
	tmp := t.TempDir()
	state := filepath.Join(tmp, "state")
	id := r.RootsID(t)
	other := strings.Repeat("ab", 8)
	lines := seenHeader +
		dl + " " + other + " 99 " + strings.Repeat("0", 64) + " 999.0.0 " + trust.KeyID(trusttest.PubOf(r.Signer)) + "\n" +
		"https://elsewhere.example/dl " + id + " 99 " + strings.Repeat("0", 64) + " 999.0.0 " + trust.KeyID(trusttest.PubOf(r.Signer)) + "\n"
	if err := os.WriteFile(state, []byte(lines), 0o600); err != nil {
		t.Fatal(err)
	}
	in := freshInstall(dl, r.RootsB64(), state, filepath.Join(tmp, "core"), g)
	if err := in.run(); err != nil {
		t.Fatalf("other sites' and other roots' lines must not be this run's floor: %v", err)
	}
	b, _ := os.ReadFile(state)
	if !strings.Contains(string(b), dl+" "+other+" 99 ") || !strings.Contains(string(b), "https://elsewhere.example/dl "+id+" 99 ") {
		t.Fatalf("the other lines must be kept:\n%s", b)
	}
}

// PROBE — the manifest's site is compared exactly (after one trailing slash), and its payload must be a
// clean https path under it: prefix, case, trailing-dot, port, userinfo and traversal tricks all fail.
// (Every case is signed by the listed key: what is tested is the rule, not the signature.)
func TestR2ProbeSiteAndPayloadTricks(t *testing.T) {
	const site = "https://digital-office.co.il/dl"
	r := trusttest.NewRelease(t, site)
	c := r.Checker(t)
	kl, err := c.VerifyKeys(r.KeysJSON())
	if err != nil {
		t.Fatal(err)
	}
	try := func(siteField, payload string) error {
		d := r.ManifestDoc()
		d["site"], d["payload_url"] = siteField, payload
		_, err := c.VerifyManifest(trusttest.Seal(r.Signer, trust.ManifestType, d), kl)
		return err
	}
	good := site + "/linux/amd64/dgo-core"
	for _, sf := range []string{site + "2", "https://digital-office.co.il/DL", "https://digital-office.co.il./dl",
		"https://digital-office.co.il:443/dl", "https://u@digital-office.co.il/dl", "https://digital-office.co.il.evil/dl",
		site + "/.", site + "//", "https://digital-office.co.il/dl/../beta", "http://digital-office.co.il/dl", site + "/beta"} {
		if err := try(sf, good); err == nil {
			t.Errorf("site field %q accepted", sf)
		}
	}
	if err := try(site+"/", good); err != nil {
		t.Errorf("the site with its trailing slash is the same site: %v", err)
	}
	for _, p := range []string{"https://digital-office.co.il.evil/dl/x", "https://digital-office.co.il@evil.example/dl/x",
		"https://evil.example#@digital-office.co.il/dl/x", "https://evil.example/dl/x?@digital-office.co.il",
		site + "/x/../../beta/x", site + "/%2e%2e/beta/x", site + "/..%2fbeta/x", site + "/./x", site + "//x",
		"https://digital-office.co.il:8443/dl/x", "https://digital-office.co.il./dl/x", site + "2/x", site} {
		if err := try(site, p); err == nil {
			t.Errorf("payload %q accepted", p)
		}
	}
	// Owner-only input (an attacker cannot sign a payload_url): a backslash is no separator to path.Clean,
	// so ..\ passes the clean-path rule though IIS-style servers would climb out on the %5C it is sent as.
	for _, p := range []string{site + `/..\beta\x`, site + "/..%5cbeta/x"} {
		t.Logf("payload %q under the site: %v", p, try(site, p) == nil)
	}
}

// PROBE — two runs racing on the state file: a stale run (still on list 4, which lists K2) saving after a
// fresh one (list 5, K2 revoked) writes K2's floor back, but never lowers the key list, and the next run
// drops K2's floor again. No lasting harm; the lock the author left out is not needed for safety.
func TestR2ProbeARacingStaleRunCannotKeepARevokedFloor(t *testing.T) {
	path := filepath.Join(t.TempDir(), "install-state")
	const site, id = "https://digital-office.co.il/dl", "0123456789abcdef"
	k2 := trust.KeyID(trusttest.PubOf(trusttest.NewKey(t)))
	sum4, sum5 := strings.Repeat("4", 64), strings.Repeat("5", 64)
	never := func(string) bool { return false }
	if err := trust.SaveSeen(path, seenHeader, site, id, trust.Seen{Keys: 5, KeysSum: sum5}, never); err != nil { // the fresh run
		t.Fatal(err)
	}
	stale := func(k string) bool { return k == k2 }
	if err := trust.SaveSeen(path, seenHeader, site, id, trust.Seen{Keys: 4, KeysSum: sum4, Manifest: "1.5.0", ManifestBy: k2}, stale); err != nil {
		t.Fatal(err)
	}
	got, err := trust.LoadSeen(path, site, id)
	if err != nil || got.Keys != 5 || got.KeysSum != sum5 {
		t.Fatalf("the key list floor must never fall: %+v %v", got, err)
	}
	t.Logf("after the race: %+v — K2's floor is back, and run() drops it at once under list 5", got)
}

// NOTE-PROBE — Strict() base64 still skips CR and LF (Go's documented exception), so a signature with a
// line break in it verifies. Harmless (the bytes are the signature), but not "every byte canonical".
func TestR2ProbeStrictBase64StillSkipsLineBreaks(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	broken := trusttest.EditEnvelope(r.KeysJSON(), func(e map[string]any) {
		sig := e["signatures"].([]any)[0].(map[string]any)
		s := sig["sig"].(string)
		sig["sig"] = s[:10] + "\r\n" + s[10:]
	})
	_, err := r.Checker(t).VerifyKeys(broken)
	t.Logf("a signature with CRLF inside: accepted=%v (%v)", err == nil, err)
}

// PROBE — roots.txt parsing: every odd form either reads the intended key or refuses the whole file
// (fail-closed: such a stub installs nothing, and TestReleaseTree refuses to sign over it).
func TestR2ProbeRootsTxtCannotBeConfused(t *testing.T) {
	k := trusttest.B64(trusttest.PubOf(trusttest.NewKey(t)))
	k2 := trusttest.B64(trusttest.PubOf(trusttest.NewKey(t)))
	unpadded := strings.TrimRight(k, "=")
	const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	nonCanon := k[:len(k)-2] + string(alphabet[strings.IndexByte(alphabet, k[len(k)-2])+1]) + "=" // a low bit that must be 0
	for name, text := range map[string]string{
		"comment lines and a key":             "# roots\n" + k + "\n",
		"CRLF line ends":                      "# roots\r\n" + k + "\r\n",
		"a trailing comment":                  k + " # root-a\n",
		"two keys, comma and spaces":          k + " , " + k2 + "\n",
		"a UTF-8 BOM before the first line":   "\xef\xbb\xbf# roots\n" + k + "\n",
		"a non-breaking space after the key":  k + "\xc2\xa0\n",
		"an unpadded key":                     unpadded + "\n",
		"a key with non-canonical last bits":  nonCanon + "\n",
		"a key cut short":                     k[:20] + "\n",
		"only comments (the committed state)": "# no root yet\n#\n",
	} {
		roots, err := trust.ParseRoots(text)
		t.Logf("%-38s -> %d roots, err=%v, dev build=%v", name, len(roots), err != nil, isDevBuild("https://digital-office.co.il/dl", text))
	}
}

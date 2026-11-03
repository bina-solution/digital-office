package trust_test

// The trust chain's rules, one test per refusal: every key is minted at runtime (trusttest), the way an
// owner's ceremony and a release job make them — no key, real or test, lives in the repository.

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust/trusttest"
)

func TestPAEIsDSSEv1(t *testing.T) {
	// The test vector of the DSSE protocol (secure-systems-lab/dsse, protocol.md) — relsign's
	// TestPAEIsDSSEv1 pins the signer to the same bytes.
	got := string(trust.PAE("http://example.com/HelloWorld", []byte("hello world")))
	if want := "DSSEv1 29 http://example.com/HelloWorld 11 hello world"; got != want {
		t.Fatalf("pae = %q, want %q", got, want)
	}
}

func TestKeyIDIsTheKeysSHA256Prefix(t *testing.T) {
	k := trusttest.PubOf(trusttest.NewKey(t))
	s := sha256.Sum256(k)
	if id := trust.KeyID(k); id != hex.EncodeToString(s[:8]) || len(id) != 16 {
		t.Fatalf("keyID = %q", id)
	}
}

func TestParseRoots(t *testing.T) {
	a, b := trusttest.B64(trusttest.PubOf(trusttest.NewKey(t))), trusttest.B64(trusttest.PubOf(trusttest.NewKey(t)))
	if roots, err := trust.ParseRoots(" " + a + " ,," + b + ","); err != nil || len(roots) != 2 {
		t.Fatalf("two roots with stray spaces and commas: %d %v", len(roots), err)
	}
	if roots, err := trust.ParseRoots(""); err != nil || len(roots) != 0 {
		t.Fatalf("no roots is a development build, not an error: %d %v", len(roots), err)
	}
	for _, bad := range []string{"not base64!", trusttest.B64(make([]byte, 31)), a + ",AAAA"} {
		if _, err := trust.ParseRoots(bad); err == nil {
			t.Errorf("%q must be refused: a stub must not run on a root it cannot read", bad)
		}
	}
}

func TestTheChainVerifies(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	c := r.Checker(t)
	kl, err := c.VerifyKeys(r.KeysJSON())
	if err != nil {
		t.Fatalf("a root-signed key list must verify: %v", err)
	}
	if kl.Version != 3 || len(kl.Signers) != 1 {
		t.Fatalf("key list = %+v", kl)
	}
	m, err := c.VerifyManifest(r.ManifestJSON(), kl)
	if err != nil {
		t.Fatalf("a manifest signed by a listed key must verify: %v", err)
	}
	sum := sha256.Sum256(r.Payload)
	if m.Version != "1.4.0" || m.MinBootstrapper != "1.2.0" || m.Target != trusttest.Target || m.Size != int64(len(r.Payload)) ||
		m.SHA256 != hex.EncodeToString(sum[:]) || !m.Expires.Equal(trusttest.Now.AddDate(0, 1, 0)) {
		t.Fatalf("manifest read wrong: %+v", m)
	}
	// The spare root signs too — that is what it is for: one root retires, the stubs keep working.
	if _, err := c.VerifyKeys(trusttest.Seal(r.Spare, trust.KeysType, r.KeysDoc())); err != nil {
		t.Fatalf("a key list signed by the second root must verify: %v", err)
	}
	// A window is half-open: valid from not_before itself.
	d := r.KeysDoc()
	d["keys"] = []any{trusttest.Window(r.Signer, trusttest.Now, trusttest.Now.Add(time.Hour))}
	if kl, err = c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d)); err == nil {
		_, err = c.VerifyManifest(r.ManifestJSON(), kl)
	}
	if err != nil {
		t.Fatalf("a key is valid from its not_before: %v", err)
	}
	// A clock up to trust.ClockSkew slow still takes a key from its start: a key list re-signed this morning.
	d["keys"] = []any{trusttest.Window(r.Signer, trusttest.Now.Add(trust.ClockSkew-time.Second), trusttest.Now.Add(time.Hour))}
	if kl, err = c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d)); err == nil {
		_, err = c.VerifyManifest(r.ManifestJSON(), kl)
	}
	if err != nil {
		t.Fatalf("a key whose window opens inside a slow clock's grace is valid: %v", err)
	}
	// The site's core_floor at the manifest's own version: not older, so accepted.
	d = r.KeysDoc()
	d["core_floor"] = "1.4.0"
	if kl, err = c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d)); err == nil {
		_, err = c.VerifyManifest(r.ManifestJSON(), kl)
	}
	if err != nil || kl.CoreFloor != "1.4.0" {
		t.Fatalf("a manifest at the core_floor itself must verify: %v (core_floor %q)", err, kl.CoreFloor)
	}
}

// TestARevokedKeysFloorBindsOnlyTheKeysBesideIt: this computer accepted 1.5.0 from k2 under list 3,
// where k1 stood beside it; list 4 revokes k2, keeps k1 and adds k3. k1 may have signed older releases,
// so its replayed 1.4.0 stays refused; k3 can only have signed since, so it is free of k2's floor — the
// leaked-key recovery.
func TestARevokedKeysFloorBindsOnlyTheKeysBesideIt(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl") // r.Signer is k1
	k2, k3 := trusttest.NewKey(t), trusttest.NewKey(t)
	from, until := trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 1, 0)
	c := r.Checker(t)
	l3 := r.KeysDoc()
	l3["keys"] = []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k2, from, until), trusttest.Listed(trusttest.NewKey(t), from, until, trust.IndexType)}
	kl3, err := c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, l3))
	if err != nil {
		t.Fatal(err)
	}
	k1, k2id := trust.KeyID(trusttest.PubOf(r.Signer)), trust.KeyID(trusttest.PubOf(k2))
	if got := kl3.Besides(k2id); got != k1 {
		t.Fatalf("beside k2 stood k1 alone (the store's key signs no core manifest): %q", got)
	}
	l4 := r.KeysDoc()
	l4["version"], l4["keys"] = 4, []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k3, from, until)}
	kl4, err := c.VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, l4))
	if err != nil {
		t.Fatal(err)
	}
	c.Seen = trust.Seen{Manifest: "1.5.0", ManifestBy: k2id, Beside: k1}
	replay := r.ManifestJSON() // k1's 1.4.0
	if _, err := c.VerifyManifest(replay, kl3); err == nil {
		t.Error("while keys.json lists k2, its floor binds every key")
	}
	if _, err := c.VerifyManifest(replay, kl4); err == nil || !strings.Contains(err.Error(), "replayed old manifest") {
		t.Errorf("k1 stood beside k2: its 1.4.0, replayed once k2 is revoked, must stay refused: %v", err)
	}
	if _, err := c.VerifyManifest(trusttest.Seal(k3, trust.ManifestType, r.ManifestDoc()), kl4); err != nil {
		t.Errorf("k3 was listed after k2's floor was set, so it is free of it: %v", err)
	}
	if kl4.Binds("", "", k1) {
		t.Error("no floor binds no key")
	}
}

// TestTheRootsCoreFloorTakesARevokedKeysPlace: what a key list stating core_floor does to this
// computer's memory (settle), case by case, and to the install record (binds). k1 is listed throughout.
func TestTheRootsCoreFloorTakesARevokedKeysPlace(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	k1, gone := trust.KeyID(trusttest.PubOf(r.Signer)), trust.KeyID(trusttest.PubOf(trusttest.NewKey(t)))
	list := func(floor string) trust.KeyList {
		t.Helper()
		d := r.KeysDoc()
		if floor != "" {
			d["core_floor"] = floor
		}
		kl, err := r.Checker(t).VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d))
		if err != nil {
			t.Fatal(err)
		}
		return kl
	}
	root := func(v string) trust.Seen { return trust.Seen{Manifest: v, ManifestBy: trust.ViaKeysJSON} }
	for _, tc := range []struct {
		name      string
		floor     string
		was, want trust.Seen
	}{
		{"a revoked key's floor gives way to the root's, downward too", "1.5.0", trust.Seen{Manifest: "999999999.0.0", ManifestBy: gone, Beside: k1}, root("1.5.0")},
		{"a listed key's floor above core_floor stays", "1.5.0", trust.Seen{Manifest: "1.6.0", ManifestBy: k1}, trust.Seen{Manifest: "1.6.0", ManifestBy: k1}},
		{"a listed key's floor below core_floor rises to it", "1.5.0", trust.Seen{Manifest: "1.4.0", ManifestBy: k1}, root("1.5.0")},
		{"a computer that remembers nothing takes the root's floor", "1.5.0", trust.Seen{}, root("1.5.0")},
		{"the root's floor never falls to a lower core_floor", "1.4.0", root("1.5.0"), root("1.5.0")},
		{"no core_floor: a revoked key's floor stands", "", trust.Seen{Manifest: "1.5.0", ManifestBy: gone, Beside: k1}, trust.Seen{Manifest: "1.5.0", ManifestBy: gone, Beside: k1}},
	} {
		if got := list(tc.floor).Settle(tc.was); got != tc.want {
			t.Errorf("%s: settle(%+v) = %+v, want %+v", tc.name, tc.was, got, tc.want)
		}
	}
	if list("1.5.0").Binds(gone, k1, k1) {
		t.Error("once the root states core_floor, a revoked key's install holds no key — not even one beside it")
	}
	if !list("").Binds(gone, k1, k1) {
		t.Error("with no core_floor, a revoked key's install holds the keys beside it")
	}
	if !list("").Binds(trust.ViaKeysJSON, "", k1) {
		t.Error("the root's floor holds every key, whatever a later list states")
	}
}

func TestKeysJSONRefusals(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	stranger := trusttest.NewKey(t)
	edited := func(f func(map[string]any)) []byte {
		d := r.KeysDoc()
		f(d)
		return trusttest.Seal(r.Root, trust.KeysType, d)
	}
	cases := []struct {
		name string
		raw  []byte
		seen int64 // the key list version this computer accepted last
		want string
	}{
		{"forged: a key added after the root signed", trusttest.Forge(r.KeysJSON(), func(d map[string]any) {
			d["keys"] = append(d["keys"].([]any), trusttest.Window(stranger, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(1, 0, 0)))
		}), 0, "does not verify"},
		{"forged: version raised after signing", trusttest.Forge(r.KeysJSON(), func(d map[string]any) { d["version"] = 99 }), 0, "does not verify"},
		{"signed by a key that is no root", trusttest.Seal(stranger, trust.KeysType, r.KeysDoc()), 0, "unknown signer"},
		{"signed by the online signing key itself", trusttest.Seal(r.Signer, trust.KeysType, r.KeysDoc()), 0, "unknown signer"},
		{"a manifest served as keys.json", r.ManifestJSON(), 0, "payloadType"},
		{"expired", edited(func(d map[string]any) { d["expires"] = trusttest.RFC3339(trusttest.Now) }), 0, "expired"},
		{"replayed: older than the list this computer accepted", r.KeysJSON(), 4, "replayed or revoked key list"},
		{"the list of another site, under the same roots", edited(func(d map[string]any) {
			d["site"] = "https://staging.digital-office.co.il/dl"
		}), 0, "key list of https://staging"},
		{"a list that names no site", edited(func(d map[string]any) { delete(d, "site") }), 0, `"site"`},
		{"no signatures", trusttest.EditEnvelope(r.KeysJSON(), func(e map[string]any) { e["signatures"] = []any{} }), 0, "signatures"},
		{"a signature that is not base64", trusttest.EditEnvelope(r.KeysJSON(), func(e map[string]any) {
			e["signatures"].([]any)[0].(map[string]any)["sig"] = "!!!"
		}), 0, "64 bytes of base64"},
		{"a payload that is not base64", trusttest.EditEnvelope(r.KeysJSON(), func(e map[string]any) { e["payload"] = "!!!" }), 0, "not base64"},
		{"not an envelope at all", []byte("<html>404</html>"), 0, "JSON"},
		{"a listed key that is not a key", edited(func(d map[string]any) {
			d["keys"] = []any{map[string]any{"public_key": "AAAA", "not_before": trusttest.RFC3339(trusttest.Now), "not_after": trusttest.RFC3339(trusttest.Now)}}
		}), 0, "not a base64 Ed25519"},
		{"a listed key without its window", edited(func(d map[string]any) {
			d["keys"] = []any{map[string]any{"public_key": trusttest.B64(trusttest.PubOf(r.Signer)), "types": []any{trust.ManifestType}}}
		}), 0, `"not_before"`},
		{"a listed key without the types it may sign", edited(func(d map[string]any) {
			e := trusttest.Window(r.Signer, trusttest.Now, trusttest.Now.Add(time.Hour))
			delete(e, "types")
			d["keys"] = []any{e}
		}), 0, `"types"`},
		{"a listed key whose types are not names", edited(func(d map[string]any) {
			e := trusttest.Window(r.Signer, trusttest.Now, trusttest.Now.Add(time.Hour))
			e["types"] = []any{trust.ManifestType, 7}
			d["keys"] = []any{e}
		}), 0, "names of documents"},
		{"no version", edited(func(d map[string]any) { delete(d, "version") }), 0, `"version"`},
		{"no keys", edited(func(d map[string]any) { d["keys"] = []any{} }), 0, `"keys"`},
		// A core_floor the stub cannot order would be no floor: refused, like a version it cannot order.
		// A root-signed window empty by its own terms is no window — the clock's grace must not open one.
		{"a listed key whose window ends before it starts", edited(func(d map[string]any) {
			d["keys"] = []any{trusttest.Window(r.Signer, trusttest.Now.Add(5*time.Minute), trusttest.Now.Add(time.Minute))}
		}), 0, "ends before it starts"},
		{"a listed key whose window ends as it starts", edited(func(d map[string]any) {
			d["keys"] = []any{trusttest.Window(r.Signer, trusttest.Now, trusttest.Now)}
		}), 0, "ends before it starts"},
		{"a core_floor that is a pre-release", edited(func(d map[string]any) { d["core_floor"] = "1.5.0-rc.1" }), 0, "not a release version"},
		{"a core_floor that is a number", edited(func(d map[string]any) { d["core_floor"] = 15 }), 0, `"core_floor"`},
		{"an empty core_floor", edited(func(d map[string]any) { d["core_floor"] = "" }), 0, `"core_floor"`},
	}
	for _, tc := range cases {
		c := r.Checker(t)
		c.Seen.Keys = tc.seen
		_, err := c.VerifyKeys(tc.raw)
		if err == nil || !strings.Contains(err.Error(), tc.want) || !strings.HasPrefix(err.Error(), "keys.json: ") {
			t.Errorf("%s: err = %v, want a keys.json refusal containing %q", tc.name, err, tc.want)
		}
	}
}

func TestManifestRefusals(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	stranger := trusttest.NewKey(t)
	good, err := r.Checker(t).VerifyKeys(r.KeysJSON())
	if err != nil {
		t.Fatal(err)
	}
	// windowed is a verified key list whose one key is valid only from `from` until `until`.
	windowed := func(from, until time.Time) trust.KeyList {
		d := r.KeysDoc()
		d["keys"] = []any{trusttest.Window(r.Signer, from, until)}
		kl, err := r.Checker(t).VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d))
		if err != nil {
			t.Fatal(err)
		}
		return kl
	}
	edited := func(f func(map[string]any)) []byte {
		d := r.ManifestDoc()
		f(d)
		return trusttest.Seal(r.Signer, trust.ManifestType, d)
	}
	// floored is the good key list stating the oldest core the site allows.
	floored := func(v string) trust.KeyList {
		d := r.KeysDoc()
		d["core_floor"] = v
		kl, err := r.Checker(t).VerifyKeys(trusttest.Seal(r.Root, trust.KeysType, d))
		if err != nil {
			t.Fatal(err)
		}
		return kl
	}
	cases := []struct {
		name string
		raw  []byte
		kl   trust.KeyList
		seen string // the manifest version this computer accepted last
		want string
	}{
		{"forged: the payload's sha256 changed after signing", trusttest.Forge(r.ManifestJSON(), func(d map[string]any) {
			d["sha256"] = strings.Repeat("0", 64)
		}), good, "", "does not verify"},
		{"forged: the expiry pushed out after signing", trusttest.Forge(r.ManifestJSON(), func(d map[string]any) {
			d["expires"] = trusttest.RFC3339(trusttest.Now.AddDate(5, 0, 0))
		}), good, "", "does not verify"},
		{"signed by a key keys.json does not list", trusttest.Seal(stranger, trust.ManifestType, r.ManifestDoc()), good, "", "unknown signer"},
		{"signed by a root directly — roots sign key lists only", trusttest.Seal(r.Root, trust.ManifestType, r.ManifestDoc()), good, "", "unknown signer"},
		{"keys.json served as the manifest", r.KeysJSON(), good, "", "payloadType"},
		{"its signing key is not valid yet", r.ManifestJSON(), windowed(trusttest.Now.Add(time.Hour), trusttest.Now.Add(2*time.Hour)), "", "valid only from"},
		{"its signing key opens past the slow clock's grace", r.ManifestJSON(), windowed(trusttest.Now.Add(trust.ClockSkew+time.Second), trusttest.Now.Add(time.Hour)), "", "valid only from"},
		{"its signing key's window is over", r.ManifestJSON(), windowed(trusttest.Now.Add(-2*time.Hour), trusttest.Now), "", "valid only from"},
		{"expired", edited(func(d map[string]any) { d["expires"] = trusttest.RFC3339(trusttest.Now) }), good, "", "expired"},
		{"replayed: older than the manifest this computer accepted", r.ManifestJSON(), good, "1.5.0", "replayed old manifest"},
		{"older than keys.json's core_floor, on a computer that remembers nothing", r.ManifestJSON(), floored("1.4.1"), "", "the oldest keys.json allows"},
		{"this stub is older than min_bootstrapper", edited(func(d map[string]any) { d["min_bootstrapper"] = "1.3.0" }), good, "", "download the current installer"},
		{"for another platform", edited(func(d map[string]any) { d["target"] = "windows/amd64" }), good, "", "it is for windows/amd64"},
		{"payload on another host", edited(func(d map[string]any) { d["payload_url"] = "https://cdn.evil.example/dgo-core" }), good, "", "is not an https:// file under"},
		{"payload over plain http", edited(func(d map[string]any) {
			d["payload_url"] = "http://digital-office.co.il/dl/linux/amd64/dgo-core"
		}), good, "", "is not an https:// file under"},
		// One host, two sites (a stable /dl, a /beta): the same release key signs both, so the site decides.
		{"a manifest of another site on the same host", edited(func(d map[string]any) {
			d["site"], d["payload_url"] = "https://digital-office.co.il/beta", "https://digital-office.co.il/beta/linux/amd64/dgo-core"
		}), good, "", "is a manifest of https://digital-office.co.il/beta"},
		{"its payload under another site of the same host", edited(func(d map[string]any) {
			d["payload_url"] = "https://digital-office.co.il/beta/linux/amd64/dgo-core"
		}), good, "", "is not an https:// file under"},
		{"a payload that climbs out of the site", edited(func(d map[string]any) {
			d["payload_url"] = "https://digital-office.co.il/dl/../beta/linux/amd64/dgo-core"
		}), good, "", "is not an https:// file under"},
		{"a payload under a look-alike of the site's path", edited(func(d map[string]any) {
			d["payload_url"] = "https://digital-office.co.il/dl2/linux/amd64/dgo-core"
		}), good, "", "is not an https:// file under"},
		{"no site", edited(func(d map[string]any) { delete(d, "site") }), good, "", `"site"`},
		{"sha256 not hex", edited(func(d map[string]any) { d["sha256"] = "zz" }), good, "", "not 64 hex"},
		{"size zero", edited(func(d map[string]any) { d["size"] = 0 }), good, "", "size is 0"},
		{"size missing", edited(func(d map[string]any) { delete(d, "size") }), good, "", `"size"`},
		{"version not a version", edited(func(d map[string]any) { d["version"] = "latest" }), good, "", "not a version"},
		// semverLess would put 1.5.0-rc.2 above 1.5.0: an old pre-release could roll a release back.
		{"a pre-release version", edited(func(d map[string]any) { d["version"] = "1.5.0-rc.2" }), good, "1.5.0", "not a version"},
		{"a min_bootstrapper that is no release", edited(func(d map[string]any) { d["min_bootstrapper"] = "1.0.0-dev" }), good, "", "not a version"},
		{"min_bootstrapper missing", edited(func(d map[string]any) { delete(d, "min_bootstrapper") }), good, "", `"min_bootstrapper"`},
		{"expires not a time", edited(func(d map[string]any) { d["expires"] = "next month" }), good, "", "RFC 3339"},
	}
	for _, tc := range cases {
		c := r.Checker(t)
		c.Seen.Manifest, c.Seen.ManifestBy = tc.seen, trust.KeyID(trusttest.PubOf(r.Signer)) // as a run remembers it: the version and its key
		_, err := c.VerifyManifest(tc.raw, tc.kl)
		if err == nil || !strings.Contains(err.Error(), tc.want) || !strings.HasPrefix(err.Error(), "manifest: ") {
			t.Errorf("%s: err = %v, want a manifest refusal containing %q", tc.name, err, tc.want)
		}
	}
}

func TestASignatureForAnotherDocumentTypeIsNeverACoreManifest(t *testing.T) {
	// The office signs key lists, core manifests and the app store's index. A second reader proved the
	// stub before this one installed a store index as dgo-core: the index's signature had the old
	// manifest's shape, under the same key. Each case hands the stub, where its manifest belongs,
	// something signed for another purpose — and the last shows it is the type, not the key, that decides.
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	store := trusttest.NewKey(t)
	d := r.KeysDoc()
	d["keys"] = []any{
		trusttest.Listed(r.Signer, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0), trust.ManifestType, trust.IndexType), // trusted for both
		trusttest.Listed(store, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0), trust.IndexType),                        // the store's own key
	}
	keysJSON := trusttest.Seal(r.Root, trust.KeysType, d)
	c := r.Checker(t)
	kl, err := c.VerifyKeys(keysJSON)
	if err != nil {
		t.Fatal(err)
	}
	index := map[string]any{"format": "bina.catalog/v1", "version": "9.0.0", "entries": []any{}}
	relabelled := trusttest.EditEnvelope(trusttest.Seal(r.Signer, trust.IndexType, r.ManifestDoc()), func(e map[string]any) { e["payloadType"] = trust.ManifestType })
	// The probe's own bytes: the old stub's format, {version, payload_url, sha256, sig} over
	// "version\npayload_url\nsha256", exactly what the store signed its index with.
	sum := sha256.Sum256([]byte(`{"entries":[]}`))
	oldURL, oldSHA := r.Site+"/v1/index.json", hex.EncodeToString(sum[:])
	oldFormat, _ := json.Marshal(map[string]any{"version": "9.0.0", "payload_url": oldURL, "sha256": oldSHA,
		"sig": trusttest.B64(ed25519.Sign(r.Signer, []byte("9.0.0\n"+oldURL+"\n"+oldSHA)))})
	cases := []struct {
		name string
		raw  []byte
		want string
	}{
		{"the store's signed index", trusttest.Seal(store, trust.IndexType, index), "payloadType"},
		{"a manifest-shaped document signed as an index, by a key trusted for both", trusttest.Seal(r.Signer, trust.IndexType, r.ManifestDoc()), "payloadType"},
		{"that index envelope relabelled as a core manifest", relabelled, "does not verify"},
		{"a core manifest signed by the store's key", trusttest.Seal(store, trust.ManifestType, r.ManifestDoc()), "does not trust that key to sign dgo-core-manifest"},
		{"keys.json", keysJSON, "payloadType"},
		{"the old format the store's index signature shared", oldFormat, "payloadType"},
	}
	for _, tc := range cases {
		if _, err := c.VerifyManifest(tc.raw, kl); err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s at the manifest's URL: err = %v, want a refusal containing %q", tc.name, err, tc.want)
		}
	}
	if _, err := c.VerifyManifest(trusttest.Seal(r.Signer, trust.ManifestType, r.ManifestDoc()), kl); err != nil {
		t.Fatalf("the same key, signing a core manifest as one, must be accepted: %v", err)
	}
	if _, err := c.VerifyKeys(trusttest.Seal(r.Signer, trust.KeysType, d)); err == nil || !strings.Contains(err.Error(), "unknown signer") {
		t.Fatalf("a listed key signing keys.json is no root: %v", err)
	}
}

func TestAnOldManifestIsRefusedOnceANewerOneWasAccepted(t *testing.T) {
	// The replay rule in one picture: the SAME correctly signed 1.3.0 manifest is fine on a computer
	// that never saw anything newer, and a refusal on one that accepted 1.4.0.
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	old := r.ManifestDoc()
	old["version"] = "1.3.0"
	raw := trusttest.Seal(r.Signer, trust.ManifestType, old)
	c := r.Checker(t)
	kl, err := c.VerifyKeys(r.KeysJSON())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.VerifyManifest(raw, kl); err != nil {
		t.Fatalf("a fresh computer has nothing to compare with: %v", err)
	}
	c.Seen.Manifest, c.Seen.ManifestBy = "1.4.0", trust.KeyID(trusttest.PubOf(r.Signer))
	if _, err := c.VerifyManifest(raw, kl); err == nil || !strings.Contains(err.Error(), "replayed old manifest") {
		t.Fatalf("after 1.4.0 was accepted, 1.3.0 must be refused as a replay: %v", err)
	}
	c.Seen.Manifest = "1.3.0"
	if _, err := c.VerifyManifest(raw, kl); err != nil {
		t.Fatalf("the same version again is not a replay (a re-run must work): %v", err)
	}
}

func TestSeenStateIsPerSiteAndRootsAndRisesOnlyWhileTrusted(t *testing.T) {
	path := filepath.Join(t.TempDir(), "dgo", "install-state")
	const header = "# the owner's words on what this file is\n"
	all := func(string) bool { return true }
	sumA, sumB := strings.Repeat("a", 64), strings.Repeat("b", 64)
	save := func(site, roots string, s trust.Seen, trusted func(string) bool) {
		t.Helper()
		if err := trust.SaveSeen(path, header, site, roots, s, trusted); err != nil {
			t.Fatal(err)
		}
	}
	load := func(site, roots string) trust.Seen {
		t.Helper()
		s, err := trust.LoadSeen(path, site, roots)
		if err != nil {
			t.Fatal(err)
		}
		return s
	}
	if s := load("https://a/dl", "r1"); s != (trust.Seen{}) {
		t.Fatalf("no file is a computer that accepted nothing: %+v", s)
	}
	save("https://a/dl", "r1", trust.Seen{Keys: 3, KeysSum: sumA, Manifest: "1.4.0", ManifestBy: "k1"}, all)
	save("https://b/dl", "r1", trust.Seen{Keys: 1, KeysSum: sumA, Manifest: "0.9.0", ManifestBy: "k1"}, all)
	save("https://a/dl", "r2", trust.Seen{Keys: 9, KeysSum: sumB}, all) // another generation of roots: a line of its own
	save("https://a/dl", "r1", trust.Seen{Keys: 4, KeysSum: sumB, Manifest: "1.5.0", ManifestBy: "k1", Beside: "k2,k3"}, all)
	// A run that overlapped a newer one saves last: the memory only ever rises…
	save("https://a/dl", "r1", trust.Seen{Keys: 3, KeysSum: sumA, Manifest: "1.4.0", ManifestBy: "k1"}, all)
	if a := load("https://a/dl", "r1"); a != (trust.Seen{Keys: 4, KeysSum: sumB, Manifest: "1.5.0", ManifestBy: "k1", Beside: "k2,k3"}) {
		t.Fatalf("a/r1 = %+v (the keys beside the floor's key are kept with it)", a)
	}
	if a2, b := load("https://a/dl", "r2"), load("https://b/dl", "r1"); a2.Keys != 9 || a2.Manifest != "" || b.Manifest != "0.9.0" {
		t.Fatalf("a/r2 = %+v, b/r1 = %+v", a2, b)
	}
	// …except a manifest floor whose key is no longer trusted: once dropped, it is not raised back.
	save("https://a/dl", "r1", trust.Seen{Keys: 4, KeysSum: sumB}, func(id string) bool { return id != "k1" })
	if a := load("https://a/dl", "r1"); a != (trust.Seen{Keys: 4, KeysSum: sumB}) {
		t.Fatalf("a floor set by a revoked key must stay dropped: %+v", a)
	}
	raw, _ := os.ReadFile(path)
	if !strings.HasPrefix(string(raw), header) || strings.Count(string(raw), "https://a/dl r1 ") != 1 {
		t.Fatalf("the file must say what it is and hold one line per site and roots:\n%s", raw)
	}
	if left, _ := filepath.Glob(path + ".*.tmp"); len(left) != 0 {
		t.Errorf("the temporary files of the renames must not be left behind: %v", left)
	}
	if err := os.WriteFile(path, []byte("https://a/dl r1 three - - -\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := trust.LoadSeen(path, "https://a/dl", "r1"); err == nil {
		t.Fatal("a malformed state file must be refused, not read as \"nothing accepted\"")
	}
}

func TestKeyListFloorsRiseStrictly(t *testing.T) {
	// The key list may not fall below the one this computer accepted, nor below the one this stub was
	// built with (so a key revoked before the build cannot install even on a fresh computer) — and at
	// an equal version it must be that very list: a revocation re-signed without "+ 1" would otherwise
	// leave the old list, and its revoked key, good for anyone who replays it.
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	v3 := r.KeysJSON()
	v3sum := trusttest.SHA256Hex(trusttest.MustPayload(t, v3))
	revokedV3 := r.KeysDoc()
	revokedV3["keys"] = []any{trusttest.Window(trusttest.NewKey(t), trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0))}
	sameVersion := trusttest.Seal(r.Root, trust.KeysType, revokedV3)
	for _, tc := range []struct {
		name  string
		floor func(*trust.Checker)
		raw   []byte
		want  string // "" = accepted
	}{
		{"the very list this computer accepted", func(c *trust.Checker) { c.Seen = trust.Seen{Keys: 3, KeysSum: v3sum} }, v3, ""},
		{"the very list this stub was built with", func(c *trust.Checker) { c.Built = trust.Seen{Keys: 3, KeysSum: v3sum} }, v3, ""},
		{"older than this stub was built with", func(c *trust.Checker) { c.Built = trust.Seen{Keys: 4} }, v3, "which this installer was built with"},
		{"another list under the version this computer accepted", func(c *trust.Checker) { c.Seen = trust.Seen{Keys: 3, KeysSum: v3sum} }, sameVersion, "changed without a new version"},
		{"another list under the version this stub was built with", func(c *trust.Checker) { c.Built = trust.Seen{Keys: 3, KeysSum: v3sum} }, sameVersion, "changed without a new version"},
	} {
		c := r.Checker(t)
		tc.floor(&c)
		_, err := c.VerifyKeys(tc.raw)
		if tc.want == "" && err != nil || tc.want != "" && (err == nil || !strings.Contains(err.Error(), tc.want)) {
			t.Errorf("%s: err = %v, want %q", tc.name, err, tc.want)
		}
	}
	for _, bad := range []string{"4", "4:", "x:" + v3sum, "4:" + strings.Repeat("g", 64), "-1:" + v3sum} {
		if _, err := trust.ParseFloor(bad); err == nil {
			t.Errorf("a built-in floor %q must be refused", bad)
		}
	}
	if f, err := trust.ParseFloor("4:" + v3sum); err != nil || f != (trust.Seen{Keys: 4, KeysSum: v3sum}) {
		t.Errorf("parseFloor = %+v, %v", f, err)
	}
}

func TestASignatureMustBeExactlyOneEd25519SignatureOfStrictBase64(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	edit := func(f func(string) string) []byte {
		return trusttest.EditEnvelope(r.KeysJSON(), func(e map[string]any) {
			s := e["signatures"].([]any)[0].(map[string]any)
			s["sig"] = f(s["sig"].(string))
		})
	}
	for name, raw := range map[string][]byte{
		"garbage after the signature": edit(func(s string) string { return s + "!!!! not base64 at all" }),
		"a signature one byte short":  edit(func(s string) string { d, _ := base64.StdEncoding.DecodeString(s); return trusttest.B64(d[:63]) }),
		"a signature one byte long":   edit(func(s string) string { d, _ := base64.StdEncoding.DecodeString(s); return trusttest.B64(append(d, 0)) }),
		"base64 without its padding":  edit(func(s string) string { return strings.TrimRight(s, "=") }),
		// 64 bytes are 86 characters and "==": the 86th carries 2 bits and 4 unused ones, always 0 in
		// canonical base64. Setting one decodes to the very same signature — unless read strictly.
		"non-canonical bits in the last character": edit(func(s string) string {
			const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
			return s[:85] + string(alphabet[strings.IndexByte(alphabet, s[85])|1]) + s[86:]
		}),
	} {
		if _, err := r.Checker(t).VerifyKeys(raw); err == nil || !strings.Contains(err.Error(), "64 bytes of base64") {
			t.Errorf("%s: err = %v", name, err)
		}
	}
}

package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

// now is the signing clock of every test: relsign takes it as an argument, so a test is deterministic.
var now = time.Date(2026, 10, 15, 12, 0, 0, 0, time.UTC)

const (
	site       = "https://digital-office.co.il/dl"
	payloadURL = site + "/linux/amd64/dgo-core"
	storeSite  = "https://apps.net.digital-office.co.il/v1"
)

// mint runs keygen the way the owner's ceremony does and returns the key path.
func mint(t *testing.T, name string) string {
	t.Helper()
	key := filepath.Join(t.TempDir(), name+".pem")
	if err := run([]string{"keygen", key}, &bytes.Buffer{}, now); err != nil {
		t.Fatalf("keygen: %v", err)
	}
	st, err := os.Stat(key)
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode().Perm()&0o077 != 0 && !isWindows() {
		t.Errorf("key file mode %v is readable by others", st.Mode().Perm())
	}
	return key
}

func pubOf(t *testing.T, key string) ed25519.PublicKey {
	t.Helper()
	var out bytes.Buffer
	if err := run([]string{"pubkey", key}, &out, now); err != nil {
		t.Fatalf("pubkey: %v", err)
	}
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(out.String()))
	if err != nil || len(raw) != ed25519.PublicKeySize {
		t.Fatalf("pubkey must print the base64 of 32 raw bytes, got %q", out.String())
	}
	return raw
}

// open checks an envelope the way the DSSE spec defines it — independently of relsign's own code
// paths — and returns the payload decoded into doc.
func open(t *testing.T, raw []byte, typ string, pub ed25519.PublicKey, doc any) {
	t.Helper()
	var env trust.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		t.Fatalf("not an envelope: %v: %s", err, raw)
	}
	if env.PayloadType != typ || len(env.Signatures) != 1 {
		t.Fatalf("envelope type %q with %d signatures, want %q with 1", env.PayloadType, len(env.Signatures), typ)
	}
	body, err := base64.StdEncoding.DecodeString(env.Payload)
	if err != nil {
		t.Fatal(err)
	}
	sig, _ := base64.StdEncoding.DecodeString(env.Signatures[0].Sig)
	msg := []byte("DSSEv1 " + strconv.Itoa(len(typ)) + " " + typ + " " + strconv.Itoa(len(body)) + " " + string(body))
	if !ed25519.Verify(pub, msg, sig) {
		t.Fatal("the signature does not verify over DSSE's PAE of the whole payload")
	}
	s := sha256.Sum256(pub)
	if env.Signatures[0].KeyID != hex.EncodeToString(s[:8]) {
		t.Errorf("keyid %q is not the first 8 bytes of the key's sha256", env.Signatures[0].KeyID)
	}
	if err := json.Unmarshal(body, doc); err != nil {
		t.Fatalf("payload is not the document: %v", err)
	}
}

func TestPAEIsDSSEv1(t *testing.T) {
	// The test vector of the DSSE protocol (secure-systems-lab/dsse, protocol.md).
	got := string(trust.PAE("http://example.com/HelloWorld", []byte("hello world")))
	if want := "DSSEv1 29 http://example.com/HelloWorld 11 hello world"; got != want {
		t.Fatalf("pae = %q, want %q (the installer verifies exactly these bytes)", got, want)
	}
}

func TestKeygenPubkey(t *testing.T) {
	key := mint(t, "root")
	if len(pubOf(t, key)) != ed25519.PublicKeySize {
		t.Fatal("pubkey must be 32 bytes")
	}
}

func TestKeygenRefusesToOverwrite(t *testing.T) {
	key := mint(t, "root")
	if err := run([]string{"keygen", key}, &bytes.Buffer{}, now); err == nil {
		t.Fatal("keygen over an existing file must refuse — a release key is not something to replace by accident")
	}
}

func TestKeysIsSignedByTheRootAndListsWindowsAndTypes(t *testing.T) {
	root, signer, next := mint(t, "root"), mint(t, "signer"), mint(t, "next")
	var out bytes.Buffer
	err := run([]string{"keys", "-signer", root, "-site", "https://digital-office.co.il/dl/", "-version", "3", "-expires", "365d",
		"-key", signer, "-types", "dgo-core-manifest",
		"-key", next + ",2027-01-01T00:00:00Z,400d", "-types", "dgo-core-manifest,dgo-app-index"}, &out, now)
	if err != nil {
		t.Fatalf("keys: %v", err)
	}
	var doc trust.KeysDoc
	open(t, out.Bytes(), "dgo-keys", pubOf(t, root), &doc)
	if doc.Site != "https://digital-office.co.il/dl" || doc.Version != 3 || doc.Expires != "2027-10-15T12:00:00Z" || len(doc.Keys) != 2 {
		t.Fatalf("keys.json = %+v (the site is written without its trailing slash)", doc)
	}
	first, second := doc.Keys[0], doc.Keys[1]
	if first.PublicKey != base64.StdEncoding.EncodeToString(pubOf(t, signer)) || strings.Join(first.Types, ",") != "dgo-core-manifest" ||
		first.NotBefore != "2026-10-14T12:00:00Z" || first.NotAfter != "2027-10-15T12:00:00Z" {
		t.Errorf("a key with no window must be valid from a day before now (a slow clock re-signed under) until the list expires, for its types only: %+v", first)
	}
	if second.NotBefore != "2027-01-01T00:00:00Z" || second.NotAfter != "2027-11-19T12:00:00Z" ||
		strings.Join(second.Types, ",") != "dgo-core-manifest,dgo-app-index" {
		t.Errorf("an explicit window (RFC 3339 and a span both) and two types must be kept: %+v", second)
	}
}

func TestKeysRefusesWhatCannotVerify(t *testing.T) {
	root, signer := mint(t, "root"), mint(t, "signer")
	scoped := func(key string) []string { return []string{"-key", key, "-types", "dgo-core-manifest"} }
	with := func(parts ...[]string) []string { // a good key list's flags, then each case's one defect
		a := []string{"keys", "-signer", root, "-site", "https://digital-office.co.il/dl", "-version", "1", "-expires", "365d"}
		for _, p := range parts {
			a = append(a, p...)
		}
		return a
	}
	if err := run(with(scoped(signer)), &bytes.Buffer{}, now); err != nil {
		t.Fatalf("the base every case below changes must pass: %v", err)
	}
	cases := []struct {
		name string
		args []string
		want string
	}{
		{"version 0", with([]string{"-version", "0"}, scoped(signer)), "-version must be 1 or more"},
		{"an expired list", with([]string{"-expires", "2026-01-01T00:00:00Z"}, scoped(signer)), "not in the future"},
		{"expires not a WHEN", with([]string{"-expires", "next year"}, scoped(signer)), "neither an RFC 3339"},
		{"no key", with(), "name at least one signing key"},
		{"no signer", append([]string{"keys", "-site", "https://digital-office.co.il/dl", "-version", "1", "-expires", "365d"}, scoped(signer)...), "-signer"},
		{"no site", with([]string{"-site", ""}, scoped(signer)), "-site must be"},
		{"a site over plain http", with([]string{"-site", "http://digital-office.co.il/dl"}, scoped(signer)), "-site must be"},
		{"a signer that is no key", with([]string{"-signer", filepath.Join(t.TempDir(), "absent.pem")}, scoped(signer)), "-signer"},
		{"an inverted window", with(scoped(signer + ",30d,10d")), "empty or already over"},
		{"a window already over", with(scoped(signer + ",2026-01-01T00:00:00Z,2026-02-01T00:00:00Z")), "empty or already over"},
		{"half a window", with(scoped(signer + ",30d")), "expected KEY or KEY,FROM,UNTIL"},
		{"a window that is no WHEN", with(scoped(signer + ",soon,later")), "neither an RFC 3339"},
		{"a key listed twice", with(scoped(signer), scoped(signer)), "listed twice"},
		{"the signing root listed", with(scoped(root)), "the -signer root itself"},
		{"not a key", with(scoped("not-a-key!!")), "a public key must be"},
		{"a key without -types", with([]string{"-key", signer}), "name what it may sign"},
		{"-types before any -key", with([]string{"-types", "dgo-core-manifest"}, scoped(signer)), "-types follows the -key"},
		{"-types twice for one key", with(scoped(signer), []string{"-types", "dgo-app-index"}), "-types follows the -key"},
		{"a listed key trusted for key lists", with([]string{"-key", signer, "-types", "dgo-keys"}), "a key list is a root's alone"},
		{"an unknown type", with([]string{"-key", signer, "-types", "dgo-core-manifes"}), "not a type a listed key may sign"},
		{"a core floor that is a pre-release", with([]string{"-core-floor", "1.5.0-rc.1"}, scoped(signer)), "-core-floor"},
		{"a stray argument", with(scoped(signer), []string{"extra"}), "unexpected"},
		{"an unknown flag", with(scoped(signer), []string{"-force"}), "not defined"},
	}
	for _, tc := range cases {
		if err := run(tc.args, &bytes.Buffer{}, now); err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s: err %v, want a refusal containing %q", tc.name, err, tc.want)
		}
	}
}

func payloadFile(t *testing.T, body string) (string, string) {
	t.Helper()
	p := filepath.Join(t.TempDir(), "dgo-core")
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	s := sha256.Sum256([]byte(body))
	return p, hex.EncodeToString(s[:])
}

func TestManifestSignsTheWholeDocument(t *testing.T) {
	signer := mint(t, "signer")
	file, sum := payloadFile(t, "pretend DGO core")
	var out bytes.Buffer
	err := run([]string{"manifest", "-signer", signer, "-site", site + "/", "-version", "1.4.0", "-target", "linux/amd64",
		"-url", payloadURL, "-file", file, "-expires", "90d", "-min-bootstrapper", "1.2.0"}, &out, now)
	if err != nil {
		t.Fatalf("manifest: %v", err)
	}
	var doc trust.ManifestDoc
	open(t, out.Bytes(), "dgo-core-manifest", pubOf(t, signer), &doc)
	want := trust.ManifestDoc{Site: site, Version: "1.4.0", Expires: "2027-01-13T12:00:00Z", MinBootstrapper: "1.2.0",
		Target: "linux/amd64", PayloadURL: payloadURL, SHA256: sum, Size: int64(len("pretend DGO core"))}
	if doc != want {
		t.Fatalf("manifest = %+v, want %+v", doc, want)
	}
}

func TestManifestUnsignedIsABareDraft(t *testing.T) {
	file, _ := payloadFile(t, "pretend DGO core")
	var out bytes.Buffer
	err := run([]string{"manifest", "-unsigned", "-site", site, "-version", "0.0.0-dev+1a2b3c4", "-target", "linux/amd64",
		"-url", payloadURL, "-file", file, "-expires", "90d"}, &out, now)
	if err != nil {
		t.Fatalf("manifest -unsigned with a development version: %v", err)
	}
	var doc trust.ManifestDoc
	if err := json.Unmarshal(out.Bytes(), &doc); err != nil || doc.Version != "0.0.0-dev+1a2b3c4" || doc.MinBootstrapper != "0.0.0" {
		t.Fatalf("an unsigned draft is the bare document with min_bootstrapper 0.0.0 by default: %v %s", err, out.String())
	}
	if strings.Contains(out.String(), "signatures") {
		t.Fatal("an unsigned draft must carry no signature field at all")
	}
}

func TestManifestRefusesWhatTheInstallerWouldRefuse(t *testing.T) {
	signer := mint(t, "signer")
	file, _ := payloadFile(t, "pretend DGO core")
	empty, _ := payloadFile(t, "")
	good := func(over ...string) []string {
		a := map[string]string{"-signer": signer, "-site": site, "-version": "1.4.0", "-target": "linux/amd64",
			"-url": payloadURL, "-file": file, "-expires": "90d"}
		for i := 0; i+1 < len(over); i += 2 {
			a[over[i]] = over[i+1]
		}
		args := []string{"manifest"}
		for k, v := range a {
			if v != "" {
				args = append(args, k, v)
			}
		}
		return args
	}
	if err := run(good(), &bytes.Buffer{}, now); err != nil {
		t.Fatalf("the base every case below changes must pass: %v", err)
	}
	cases := []struct {
		name string
		args []string
		want string
	}{
		{"a leading v", good("-version", "v1.4.0"), "needs a release version"},
		{"an empty version", good("-version", ""), "needs a release version"},
		{"a space in the version", good("-version", "1.4.0 beta"), "needs a release version"},
		{"a pre-release, signed", good("-version", "1.5.0-rc.2"), "needs a release version"},
		{"a development version, signed", good("-version", "0.0.0-dev+1a2b3c4"), "needs a release version"},
		{"a min_bootstrapper that is no release", good("-min-bootstrapper", "1.2.0-rc1"), "-min-bootstrapper"},
		{"an unsigned draft without a version", append(good("-signer", "", "-version", ""), "-unsigned"), "is not a version"},
		{"plain http", good("-url", "http://digital-office.co.il/dl/linux/amd64/dgo-core"), "-url must be a file under -site"},
		{"a -url outside -site", good("-url", "https://digital-office.co.il/beta/linux/amd64/dgo-core"), "-url must be a file under -site"},
		{"no -site", good("-site", ""), "-site must be"},
		{"a -site over plain http", good("-site", "http://digital-office.co.il/dl"), "-site must be"},
		{"a target without its arch", good("-target", "linux"), "-target must be OS/ARCH"},
		{"a target with two archs", good("-target", "linux/amd64/v3"), "-target must be OS/ARCH"},
		{"no payload file", good("-file", filepath.Join(t.TempDir(), "absent")), "-file"},
		{"an empty payload", good("-file", empty), "is empty"},
		{"already expired", good("-expires", "2026-01-01T00:00:00Z"), "not in the future"},
		{"neither -signer nor -unsigned", good("-signer", ""), "exactly one of -signer"},
		{"both -signer and -unsigned", append(good(), "-unsigned"), "exactly one of -signer"},
	}
	for _, tc := range cases {
		if err := run(tc.args, &bytes.Buffer{}, now); err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s: err %v, want a refusal containing %q", tc.name, err, tc.want)
		}
	}
}

func TestKeysLiveSixtyDaysUnlessToldOtherwise(t *testing.T) {
	// A revoked key stays good, for a computer that never saw the revoking list, until the list that
	// named it expires — so a list is short-lived by default and re-signed by a root that often.
	root, signer := mint(t, "root"), mint(t, "signer")
	var out bytes.Buffer
	if err := run([]string{"keys", "-signer", root, "-site", site, "-version", "1", "-key", signer, "-types", "dgo-core-manifest"}, &out, now); err != nil {
		t.Fatal(err)
	}
	var doc trust.KeysDoc
	open(t, out.Bytes(), "dgo-keys", pubOf(t, root), &doc)
	if doc.Expires != "2026-12-14T12:00:00Z" || doc.Keys[0].NotAfter != doc.Expires {
		t.Fatalf("keys.json lives 60 days by default, its keys as long: %+v", doc)
	}
}

func TestKeysVersionRisesAboveThePreviousList(t *testing.T) {
	root, signer := mint(t, "root"), mint(t, "signer")
	v3 := filepath.Join(t.TempDir(), "keys-3.json")
	var out bytes.Buffer
	if err := run([]string{"keys", "-signer", root, "-site", site, "-version", "3", "-key", signer, "-types", "dgo-core-manifest"}, &out, now); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(v3, out.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	for v, ok := range map[string]bool{"2": false, "3": false, "4": true} {
		err := run([]string{"keys", "-signer", root, "-site", site, "-version", v, "-previous", v3,
			"-key", signer, "-types", "dgo-core-manifest"}, &bytes.Buffer{}, now)
		if ok != (err == nil) || !ok && !strings.Contains(err.Error(), "does not rise above") {
			t.Errorf("-version %s after list 3: err %v", v, err)
		}
	}
	if err := run([]string{"keys", "-signer", root, "-site", site, "-version", "4", "-previous", filepath.Join(t.TempDir(), "absent"),
		"-key", signer, "-types", "dgo-core-manifest"}, &bytes.Buffer{}, now); err == nil {
		t.Error("a -previous that cannot be read must be refused, not skipped")
	}
}

func TestKeysCoreFloorIsStatedAndCarriedForward(t *testing.T) {
	// The site's own floor: written when stated, absent when never stated, and kept by a re-sign that
	// names -previous without restating it — a routine re-sign must not drop what a fresh computer holds.
	root, signer := mint(t, "root"), mint(t, "signer")
	dir := t.TempDir()
	list := func(name string, extra ...string) (trust.KeysDoc, []byte) {
		t.Helper()
		var out bytes.Buffer
		args := append([]string{"keys", "-signer", root, "-site", site, "-key", signer, "-types", "dgo-core-manifest"}, extra...)
		if err := run(args, &out, now); err != nil {
			t.Fatalf("keys %v: %v", extra, err)
		}
		if err := os.WriteFile(filepath.Join(dir, name), out.Bytes(), 0o644); err != nil {
			t.Fatal(err)
		}
		var doc trust.KeysDoc
		open(t, out.Bytes(), "dgo-keys", pubOf(t, root), &doc)
		return doc, mustBody(t, out.Bytes())
	}
	if d, body := list("plain.json", "-version", "1"); d.CoreFloor != "" || strings.Contains(string(body), "core_floor") {
		t.Fatalf("no -core-floor: no core_floor field at all: %s", body)
	}
	if d, _ := list("floored.json", "-version", "2", "-core-floor", "1.5.0"); d.CoreFloor != "1.5.0" {
		t.Fatalf("-core-floor 1.5.0 = %+v", d)
	}
	if d, _ := list("resigned.json", "-version", "3", "-previous", filepath.Join(dir, "floored.json")); d.CoreFloor != "1.5.0" {
		t.Fatalf("a re-sign with -previous must keep its floor: %+v", d)
	}
	if d, _ := list("raised.json", "-version", "4", "-previous", filepath.Join(dir, "resigned.json"), "-core-floor", "1.6.0"); d.CoreFloor != "1.6.0" {
		t.Fatalf("a stated -core-floor wins over the previous list's: %+v", d)
	}
}

func TestKeysDroppingACoreKeyMustStateTheCoreFloor(t *testing.T) {
	// A list that drops a key the previous one trusted for core manifests must say, on its own command
	// line, which floor takes that key's place on every computer — a floor carried over from -previous
	// was stated for another day, and without one a key kept or listed again could replay its old releases.
	root, signer, next, store := mint(t, "root"), mint(t, "signer"), mint(t, "next"), mint(t, "store")
	v3 := filepath.Join(t.TempDir(), "keys-3.json")
	var out bytes.Buffer
	if err := run([]string{"keys", "-signer", root, "-site", site, "-version", "3", "-core-floor", "1.4.0",
		"-key", signer, "-types", "dgo-core-manifest", "-key", next, "-types", "dgo-core-manifest",
		"-key", store, "-types", "dgo-app-index"}, &out, now); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(v3, out.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	v4 := func(extra ...string) error {
		return run(append([]string{"keys", "-signer", root, "-site", site, "-version", "4", "-previous", v3}, extra...), &bytes.Buffer{}, now)
	}
	core := func(k string) []string { return []string{"-key", k, "-types", "dgo-core-manifest"} }
	for _, tc := range []struct {
		name string
		args []string
		ok   bool
	}{
		{"every key kept: the floor carries over", append(append(core(signer), core(next)...), "-key", store, "-types", "dgo-app-index"), true},
		{"a core key dropped, no -core-floor", core(signer), false},
		{"a core key dropped, the previous list's floor only carried", append(core(signer), "-key", store, "-types", "dgo-app-index"), false},
		{"a core key narrowed to the store's index", append(core(signer), "-key", next, "-types", "dgo-app-index"), false},
		{"a core key dropped, the floor stated empty", append(core(signer), "-core-floor", ""), false},
		{"a core key dropped, -core-floor stated", append(core(signer), "-key", store, "-types", "dgo-app-index", "-core-floor", "1.5.0"), true},
		{"only the store's key dropped: its floor is -index-floor, no -core-floor", append(append(core(signer), core(next)...), "-index-floor", "1.0.0"), true},
	} {
		err := v4(tc.args...)
		if tc.ok != (err == nil) || !tc.ok && !strings.Contains(err.Error(), "state -core-floor") {
			t.Errorf("%s: err %v, want accepted=%v", tc.name, err, tc.ok)
		}
	}
}

func TestKeysDroppingAnIndexKeyMustStateTheIndexFloor(t *testing.T) {
	// The same rule for the store's index: a list that drops a key the previous one trusted for
	// dgo-app-index states -index-floor, the newest real index, on its own command line — or an old index
	// key listed again could bring back what it once signed. The floor carries over as -core-floor does,
	// and it is no core floor.
	root, k1, k2 := mint(t, "root"), mint(t, "k1"), mint(t, "k2")
	dir := t.TempDir()
	path := func(n int) string { return filepath.Join(dir, "keys-"+strconv.Itoa(n)+".json") }
	list := func(n int, args ...string) (trust.KeysDoc, error) {
		t.Helper()
		var out bytes.Buffer
		err := run(append([]string{"keys", "-signer", root, "-site", storeSite, "-version", strconv.Itoa(n)}, args...), &out, now)
		var doc trust.KeysDoc
		if err == nil {
			if err = os.WriteFile(path(n), out.Bytes(), 0o644); err == nil {
				open(t, out.Bytes(), "dgo-keys", pubOf(t, root), &doc)
			}
		}
		return doc, err
	}
	index := func(k string) []string { return []string{"-key", k, "-types", "dgo-app-index"} }
	if _, err := list(1, index(k1)...); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name string
		args []string
		ok   bool
	}{
		{"an index key dropped, no -index-floor", index(k2), false},
		{"an index key narrowed to core manifests", []string{"-key", k1, "-types", "dgo-core-manifest", "-key", k2, "-types", "dgo-app-index"}, false},
		{"an index key dropped, the floor stated empty", append(index(k2), "-index-floor", ""), false},
		{"an index key dropped, only -core-floor stated", append(index(k2), "-core-floor", "1.5.0"), false},
		{"an index key dropped, -index-floor stated", append(index(k2), "-index-floor", "1.4.0"), true},
	} {
		_, err := list(2, append([]string{"-previous", path(1)}, tc.args...)...)
		if tc.ok != (err == nil) || !tc.ok && !strings.Contains(err.Error(), "state -index-floor") {
			t.Errorf("%s: err %v, want accepted=%v", tc.name, err, tc.ok)
		}
	}
	// keys-2.json is the last case's: a re-sign with -previous keeps its index floor, and only it.
	if d, err := list(3, append([]string{"-previous", path(2)}, index(k2)...)...); err != nil || d.IndexFloor != "1.4.0" || d.CoreFloor != "" {
		t.Fatalf("a re-sign with -previous must keep the index floor: %+v %v", d, err)
	}
	if _, err := list(4, append([]string{"-previous", path(3), "-index-floor", "1.4.0-rc.1"}, index(k2)...)...); err == nil || !strings.Contains(err.Error(), "-index-floor") {
		t.Errorf("a pre-release -index-floor must be refused: %v", err)
	}
}

// mustBody is the payload inside an envelope, as signed.
func mustBody(t *testing.T, raw []byte) []byte {
	t.Helper()
	var env trust.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		t.Fatal(err)
	}
	body, err := base64.StdEncoding.DecodeString(env.Payload)
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func TestFloorIsTheListsVersionAndPayloadSum(t *testing.T) {
	root, signer := mint(t, "root"), mint(t, "signer")
	path := filepath.Join(t.TempDir(), "keys.json")
	var out bytes.Buffer
	if err := run([]string{"keys", "-signer", root, "-site", site, "-version", "7", "-key", signer, "-types", "dgo-core-manifest"}, &out, now); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, out.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	var env trust.Envelope
	if err := json.Unmarshal(out.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	body, _ := base64.StdEncoding.DecodeString(env.Payload)
	s := sha256.Sum256(body)
	var floor bytes.Buffer
	if err := run([]string{"floor", path}, &floor, now); err != nil || floor.String() != "7:"+hex.EncodeToString(s[:])+"\n" {
		t.Fatalf("floor = %q, %v", floor.String(), err)
	}
	manifestFile, _ := payloadFile(t, "not a key list")
	if err := run([]string{"floor", manifestFile}, &bytes.Buffer{}, now); err == nil {
		t.Error("floor of a file that is no key list must be refused")
	}
}

func TestIndexSignsTheStoresIndexDocument(t *testing.T) {
	// The store's index.json, pinned by the version it names, its sha256 and its size, for the store's
	// site — and what the store's verifier would refuse is refused here, at signing.
	signer := mint(t, "signer")
	dir := t.TempDir()
	write := func(name, body string) string {
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		return p
	}
	body := "{\n  \"format\": \"bina.catalog/v1\",\n  \"version\": \"1.4.0\",\n  \"entries\": []\n}\n"
	index := write("index.json", body)
	var out bytes.Buffer
	if err := run([]string{"index", "-signer", signer, "-site", storeSite + "/", "-version", "1.4.0", "-file", index}, &out, now); err != nil {
		t.Fatalf("index: %v", err)
	}
	var doc trust.IndexDoc
	open(t, out.Bytes(), "dgo-app-index", pubOf(t, signer), &doc)
	s := sha256.Sum256([]byte(body))
	if want := (trust.IndexDoc{Site: storeSite, Version: "1.4.0", SHA256: hex.EncodeToString(s[:]), Size: int64(len(body))}); doc != want {
		t.Fatalf("index document = %+v, want %+v (the site written without its trailing slash)", doc, want)
	}
	good := func(over ...string) []string {
		a := map[string]string{"-signer": signer, "-site": storeSite, "-version": "1.4.0", "-file": index}
		for i := 0; i+1 < len(over); i += 2 {
			a[over[i]] = over[i+1]
		}
		args := []string{"index"}
		for k, v := range a {
			if v != "" {
				args = append(args, k, v)
			}
		}
		return args
	}
	for _, tc := range []struct {
		name string
		args []string
		want string
	}{
		{"a version index.json does not name", good("-version", "1.5.0"), "names version"},
		{"a pre-release, though index.json names it", good("-version", "1.5.0-rc.1", "-file", write("rc.json", `{"version":"1.5.0-rc.1"}`)), "needs a release version"},
		{"a file that is no index", good("-file", write("core", "pretend DGO core")), "names version"},
		{"no index file", good("-file", filepath.Join(dir, "absent.json")), "-file"},
		{"no -site", good("-site", ""), "-site must be"},
		{"a -site over plain http", good("-site", "http://apps.net.digital-office.co.il/v1"), "-site must be"},
		{"no -signer", good("-signer", ""), "-signer"},
		{"a stray argument", append(good(), "extra"), "unexpected"},
	} {
		if err := run(tc.args, &bytes.Buffer{}, now); err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s: err %v, want a refusal containing %q", tc.name, err, tc.want)
		}
	}
}

func TestUnknownCommandAndUsage(t *testing.T) {
	for _, args := range [][]string{nil, {"sign"}, {"verify"}, {"keygen"}, {"pubkey", "a", "b"}} {
		if err := run(args, &bytes.Buffer{}, now); err == nil {
			t.Errorf("%v must be refused with the usage", args)
		}
	}
}

func isWindows() bool { return os.PathSeparator == '\\' }

package main

// The stub as a whole: a run against a real TLS server from welcome to installed core, the refusals
// that matter most seen from outside (a replayed old manifest, a forged keys.json), the payload swap
// that never costs the user the core they had, and the release path — relsign signs, this verifies.

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"flag"
	"math"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust/trusttest"
)

// The flags of TestReleaseTree: packaging/build-binaries.sh checks every signed release tree with the
// stub's own rules — go test -run '^TestReleaseTree$' . -args -tree DIR -site URL -stub V -floor N:SHA256
// (the committed roots).
var (
	treeDir   = flag.String("tree", "", "a signed download tree (dist/dl) to verify with this stub's rules")
	treeRoots = flag.String("roots", "", "--selftest only: throwaway roots in place of the committed roots.txt (base64, comma-separated)")
	treeSite  = flag.String("site", "", "the download site the release stubs were built with")
	treeStub  = flag.String("stub", "", "the release stubs' own version")
	treeFloor = flag.String("floor", "", "the key list floor the release stubs were built with (relsign floor keys.json)")
)

func TestMain(m *testing.M) {
	// Two tests run this test binary as if it were DGO core: one that exits with a given status, one
	// that keeps running while an update replaces it (killed by the test, or gone after a minute).
	if code := os.Getenv("DGO_INSTALL_TEST_CORE_EXIT"); code != "" {
		n, _ := strconv.Atoi(code)
		os.Exit(n)
	}
	if os.Getenv("DGO_INSTALL_TEST_CORE_RUNS") != "" {
		time.Sleep(time.Minute)
		os.Exit(0)
	}
	os.Exit(m.Run())
}

// site is a TLS download site whose files a test changes between runs.
type site struct {
	mu    sync.Mutex
	files map[string][]byte
}

func (s *site) serve(p string, b []byte) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.files[p] = b
}

func newSite(t *testing.T) (*site, string, getter) {
	s := &site{files: map[string][]byte{}}
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		b, ok := s.files[r.URL.Path]
		s.mu.Unlock()
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Write(b)
	})
	return s, ts.URL + "/dl", g
}

func TestInstallEndToEnd(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	s.serve("/dl/keys.json", r.KeysJSON())
	s.serve("/dl/linux/amd64/manifest.json", r.ManifestJSON())
	s.serve("/dl/linux/amd64/dgo-core", r.Payload)
	tmp := t.TempDir()
	var out bytes.Buffer
	in := install{site: dl, roots: r.RootsB64(), stub: "1.2.0", target: trusttest.Target,
		state: filepath.Join(tmp, "config", "dgo", "install-state"), dest: filepath.Join(tmp, "core"),
		accept: true, noLaunch: true, now: trusttest.Now, out: &out, net: g}
	core := filepath.Join(in.dest, "dgo-core")
	installed := func(want string, keys int64) {
		t.Helper()
		b, err := os.ReadFile(core)
		rec := readRecord(in.dest)
		st, serr := trust.LoadSeen(in.state, dl, r.RootsID(t))
		if err != nil || !bytes.Equal(b, r.Payload) || rec.version != want || rec.sum != trusttest.SHA256Hex(r.Payload) || rec.signer == "" ||
			serr != nil || st.Keys != keys || st.Manifest != want || st.ManifestBy != rec.signer {
			t.Fatalf("installed %q (%v), record %+v, remembered %+v (%v); want %s under key list %d", b, err, rec, st, serr, want, keys)
		}
	}

	// A fresh computer: verified and installed.
	if err := in.run(); err != nil {
		t.Fatalf("a good release must install: %v\n%s", err, out.String())
	}
	installed("1.4.0", 3)
	if !strings.Contains(out.String(), "Verified DGO core 1.4.0") {
		t.Errorf("the run must say what it verified:\n%s", out.String())
	}

	// The same release again: nothing to do (forward-only).
	out.Reset()
	if err := in.run(); err != nil || !strings.Contains(out.String(), "already installed") {
		t.Fatalf("a second run must find it installed: %v\n%s", err, out.String())
	}

	// A core cut short after VERSION was written (a power cut): "installed" means the manifest's
	// bytes, not what VERSION says — so the same release is installed again.
	if err := os.WriteFile(core, r.Payload[:5], 0o755); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if err := in.run(); err != nil || !strings.Contains(out.String(), "installing 1.4.0 in its place") {
		t.Fatalf("a damaged core must be installed again: %v\n%s", err, out.String())
	}
	installed("1.4.0", 3)

	// Another build signed under the same version (the release lane re-run on a newer toolchain): the
	// core installed here is intact, so it stays — a mirror cannot swap the two builds back and forth.
	otherBuild := []byte("another build of 1.4.0")
	sum := sha256.Sum256(otherBuild)
	other := r.ManifestDoc()
	other["sha256"], other["size"] = hex.EncodeToString(sum[:]), len(otherBuild)
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, other))
	s.serve("/dl/linux/amd64/dgo-core", otherBuild)
	out.Reset()
	if err := in.run(); err != nil || !strings.Contains(out.String(), "already installed") {
		t.Fatalf("an intact core of the same version must stay: %v\n%s", err, out.String())
	}
	installed("1.4.0", 3)
	s.serve("/dl/linux/amd64/manifest.json", r.ManifestJSON())
	s.serve("/dl/linux/amd64/dgo-core", r.Payload)

	// An OLD manifest, correctly signed, replayed by the site (or a mirror stuck in time): refused —
	// even with the installed core gone, because it is this computer's memory that refuses.
	old := r.ManifestDoc()
	old["version"] = "1.3.0"
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, old))
	if err := os.RemoveAll(in.dest); err != nil {
		t.Fatal(err)
	}
	if err := in.run(); err == nil || !strings.Contains(err.Error(), "replayed old manifest") {
		t.Fatalf("a replayed old manifest must be refused: %v", err)
	}
	if _, err := os.Stat(core); err == nil {
		t.Fatal("nothing may be downloaded after a refusal")
	}

	// A FORGED keys.json: the attacker's own key added to the list, the root's signature kept, and a
	// manifest signed with that key.
	stranger := trusttest.NewKey(t)
	s.serve("/dl/keys.json", trusttest.Forge(r.KeysJSON(), func(d map[string]any) {
		d["keys"] = append(d["keys"].([]any), trusttest.Window(stranger, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(1, 0, 0)))
	}))
	evil := r.ManifestDoc()
	evil["version"] = "9.9.9"
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(stranger, trust.ManifestType, evil))
	if err := in.run(); err == nil || !strings.Contains(err.Error(), "keys.json: ") || !strings.Contains(err.Error(), "does not verify") {
		t.Fatalf("a forged keys.json must be refused: %v", err)
	}

	// The release moves on: key list 4 retires the old signing key for a new one, which signs 1.5.0.
	next := trusttest.NewKey(t)
	kd := r.KeysDoc()
	kd["version"] = 4
	kd["keys"] = []any{trusttest.Window(next, trusttest.Now.AddDate(0, 0, -1), trusttest.Now.AddDate(0, 6, 0))}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, kd))
	r.Payload = []byte("DGO core 1.5.0, a new build")
	md := r.ManifestDoc()
	md["version"] = "1.5.0"
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(next, trust.ManifestType, md))
	s.serve("/dl/linux/amd64/dgo-core", r.Payload)
	out.Reset()
	if err := in.run(); err != nil {
		t.Fatalf("a rotated key and a newer release must install: %v\n%s", err, out.String())
	}
	installed("1.5.0", 4)

	// And the retired key comes back with the old list it was valid in: refused, the list is older
	// than the one this computer accepted — which is what makes retiring a key stick.
	s.serve("/dl/keys.json", r.KeysJSON())
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, md))
	if err := in.run(); err == nil || !strings.Contains(err.Error(), "replayed or revoked key list") {
		t.Fatalf("a replayed old key list must be refused: %v", err)
	}
}

func TestARetiredKeyStaysRetiredWhenItsRunGoesNoFurther(t *testing.T) {
	// A second reader's attack on the first cut: key list 4 retires key K, but the run that saw it
	// stopped at the manifest (this stub is too old for it), so the computer still remembered list 3 —
	// and a replayed list 3 with a manifest signed by the leaked K installed the attacker's payload.
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	s.serve("/dl/keys.json", r.KeysJSON()) // list 3: K = r.Signer
	s.serve("/dl/linux/amd64/manifest.json", r.ManifestJSON())
	s.serve("/dl/linux/amd64/dgo-core", r.Payload)
	tmp := t.TempDir()
	in := install{site: dl, roots: r.RootsB64(), stub: "1.2.0", target: trusttest.Target,
		state: filepath.Join(tmp, "state"), dest: filepath.Join(tmp, "core"),
		accept: true, noLaunch: true, now: trusttest.Now, out: &bytes.Buffer{}, net: g}
	if err := in.run(); err != nil {
		t.Fatal(err)
	}
	next := trusttest.NewKey(t)
	kd := r.KeysDoc()
	kd["version"] = 4
	kd["keys"] = []any{trusttest.Window(next, trusttest.Now.AddDate(0, 0, -1), trusttest.Now.AddDate(0, 6, 0))}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, kd))
	md := r.ManifestDoc()
	md["version"], md["min_bootstrapper"] = "1.5.0", "2.0.0"
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(next, trust.ManifestType, md))
	if err := in.run(); err == nil || !strings.Contains(err.Error(), "download the current installer") {
		t.Fatalf("this stub is too old for 1.5.0: %v", err)
	}
	if st, _ := trust.LoadSeen(in.state, dl, r.RootsID(t)); st.Keys != 4 {
		t.Fatalf("key list 4 must be remembered although its run went no further: %+v", st)
	}
	s.serve("/dl/keys.json", r.KeysJSON())
	evil := r.ManifestDoc()
	evil["version"] = "9.9.9"
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, evil))
	if err := in.run(); err == nil || !strings.Contains(err.Error(), "replayed or revoked key list") {
		t.Fatalf("the retired key's list must stay refused: %v", err)
	}
}

func TestTheOwnersRecoveryRecovers(t *testing.T) {
	// The README's two remedies, carried out on a computer that already took the attacker's core —
	// and each must put the real release on it. (The security reader's tests cover the plain revocation
	// and a new generation's state; these are the orders and places theirs leave out.)
	evilCore := []byte("the holder of a leaked key's core")
	sumHex := func(b []byte) string { return trusttest.SHA256Hex(b) }

	t.Run("a leaked online key, the state file reset before the revocation", func(t *testing.T) {
		s, dl, g := newSite(t)
		r := trusttest.NewRelease(t, dl)
		s.serve("/dl/keys.json", r.KeysJSON())
		evil := r.ManifestDoc()
		evil["version"], evil["sha256"], evil["size"] = "999999999.0.0", sumHex(evilCore), len(evilCore)
		s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, evil))
		s.serve("/dl/linux/amd64/dgo-core", evilCore)
		tmp := t.TempDir()
		in := install{site: dl, roots: r.RootsB64(), stub: "1.2.0", target: trusttest.Target, state: filepath.Join(tmp, "state"),
			dest: filepath.Join(tmp, "core"), accept: true, noLaunch: true, now: trusttest.Now, out: &bytes.Buffer{}, net: g}
		if err := in.run(); err != nil {
			t.Fatal(err)
		}
		if err := os.Remove(in.state); err != nil { // "Removing this file … never blocks an install"
			t.Fatal(err)
		}
		next := trusttest.NewKey(t)
		kd := r.KeysDoc()
		kd["version"], kd["keys"] = 4, []any{trusttest.Window(next, trusttest.Now.AddDate(0, 0, -1), trusttest.Now.AddDate(0, 6, 0))}
		s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, kd))
		rel := r.ManifestDoc()
		rel["version"] = "1.5.0"
		s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(next, trust.ManifestType, rel))
		s.serve("/dl/linux/amd64/dgo-core", r.Payload)
		if err := in.run(); err != nil {
			t.Fatalf("the revocation must replace the leaked key's core: %v", err)
		}
		if got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core")); !bytes.Equal(got, r.Payload) || readRecord(in.dest).version != "1.5.0" {
			t.Fatalf("installed %q, record %+v", got, readRecord(in.dest))
		}
	})

	t.Run("a leaked root, then a new generation of stubs over the same core", func(t *testing.T) {
		s, dl, g := newSite(t)
		gen1 := trusttest.NewRelease(t, dl)
		attacker := trusttest.NewKey(t)
		kd := gen1.KeysDoc()
		kd["version"], kd["keys"] = int64(math.MaxInt64), []any{trusttest.Window(attacker, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(1, 0, 0))}
		s.serve("/dl/keys.json", trusttest.Seal(gen1.Root, trust.KeysType, kd)) // the leaked root's list
		evil := gen1.ManifestDoc()
		evil["version"], evil["sha256"], evil["size"] = "999999999.0.0", sumHex(evilCore), len(evilCore)
		s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(attacker, trust.ManifestType, evil))
		s.serve("/dl/linux/amd64/dgo-core", evilCore)
		tmp := t.TempDir()
		at := func(r *trusttest.Release) install {
			return install{site: dl, roots: r.RootsB64(), stub: "1.2.0", target: trusttest.Target, state: filepath.Join(tmp, "state"),
				dest: filepath.Join(tmp, "core"), accept: true, noLaunch: true, now: trusttest.Now, out: &bytes.Buffer{}, net: g}
		}
		if err := at(gen1).run(); err != nil {
			t.Fatal(err)
		}
		gen2 := trusttest.NewRelease(t, dl) // new roots; the old stubs are what the leak cost
		s.serve("/dl/keys.json", gen2.KeysJSON())
		s.serve("/dl/linux/amd64/manifest.json", gen2.ManifestJSON())
		s.serve("/dl/linux/amd64/dgo-core", gen2.Payload)
		if err := at(gen2).run(); err != nil {
			t.Fatalf("a new-generation stub must install the real release over the leaked root's core: %v", err)
		}
		if got, _ := os.ReadFile(filepath.Join(tmp, "core", "dgo-core")); !bytes.Equal(got, gen2.Payload) {
			t.Fatalf("the core is still the attacker's: %q", got)
		}
	})
}

func TestRevokingOneOfTwoKeysOpensNoRollback(t *testing.T) {
	// The second reader's R2-1, held twice over: this computer's memory refuses the replay of what the
	// kept key once signed, and with that memory removed ("it never blocks an install") the installed
	// core's record still names who stood beside the key that signed it, so the replay does not replace
	// it — while a newer release by the kept key still installs.
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl) // r.Signer is k1
	k2 := trusttest.NewKey(t)
	from, until := trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 1, 0)
	l3 := r.KeysDoc()
	l3["keys"] = []any{trusttest.Window(r.Signer, from, until), trusttest.Window(k2, from, until)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l3))
	core := dl + "/linux/amd64/dgo-core"
	release := func(by ed25519.PrivateKey, version string, body []byte) {
		s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(by, trust.ManifestType, payloadDoc(r, version, core, body)))
		s.serve("/dl/linux/amd64/dgo-core", body)
	}
	fix := []byte("DGO core 1.5.0, the fix")
	release(k2, "1.5.0", fix)
	tmp := t.TempDir()
	in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
	if err := in.run(); err != nil {
		t.Fatal(err)
	}
	k1, k2id := trust.KeyID(trusttest.PubOf(r.Signer)), trust.KeyID(trusttest.PubOf(k2))
	if rec := readRecord(in.dest); rec.signer != k2id || rec.beside != k1 {
		t.Fatalf("VERSION must name k2 and, beside it, k1: %+v", rec)
	}
	if st, _ := trust.LoadSeen(in.state, dl, r.RootsID(t)); st.ManifestBy != k2id || st.Beside != k1 {
		t.Fatalf("the state file must name k2 and, beside it, k1: %+v", st)
	}
	l4 := r.KeysDoc()
	l4["version"], l4["keys"] = 4, []any{trusttest.Window(r.Signer, from, until)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, l4))
	release(r.Signer, "1.4.0", []byte("DGO core 1.4.0, known-vulnerable"))
	if err := in.run(); err == nil || !strings.Contains(err.Error(), "replayed old manifest") {
		t.Fatalf("k1's 1.4.0 replayed after k2's revocation must be refused by this computer's memory: %v", err)
	}
	if err := os.Remove(in.state); err != nil {
		t.Fatal(err)
	}
	out := &bytes.Buffer{}
	in.out = out
	if err := in.run(); err != nil || !strings.Contains(out.String(), "already installed") {
		t.Fatalf("k1's replayed 1.4.0 must leave k2's 1.5.0 in place: %v\n%s", err, out.String())
	}
	if got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core")); !bytes.Equal(got, fix) {
		t.Fatalf("the core is now %q", got)
	}
	newer := []byte("DGO core 1.6.0")
	release(r.Signer, "1.6.0", newer)
	if err := in.run(); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core")); !bytes.Equal(got, newer) {
		t.Fatalf("a newer release by the kept key must install: %q", got)
	}
}

func TestAKeyListOfAnotherSiteIsNeitherBelievedNorRemembered(t *testing.T) {
	// The roots sign more than one key list. A second reader served one meant for another site (the app
	// store's, a staging site's) at this site's keys.json, numbered far ahead: before key lists named
	// their site the stub believed it — and remembered its version, so the real next list was refused.
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	s.serve("/dl/keys.json", r.KeysJSON())
	s.serve("/dl/linux/amd64/manifest.json", r.ManifestJSON())
	s.serve("/dl/linux/amd64/dgo-core", r.Payload)
	tmp := t.TempDir()
	in := install{site: dl, roots: r.RootsB64(), stub: "1.2.0", target: trusttest.Target,
		state: filepath.Join(tmp, "state"), dest: filepath.Join(tmp, "core"),
		accept: true, noLaunch: true, now: trusttest.Now, out: &bytes.Buffer{}, net: g}
	if err := in.run(); err != nil {
		t.Fatal(err)
	}
	foreign := r.KeysDoc()
	foreign["site"], foreign["version"] = "https://apps.net.digital-office.co.il", 10
	foreign["keys"] = []any{trusttest.Listed(trusttest.NewKey(t), trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0), trust.IndexType)}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, foreign))
	if err := in.run(); err == nil || !strings.Contains(err.Error(), "key list of https://apps.net") {
		t.Fatalf("another site's key list must be refused: %v", err)
	}
	if st, _ := trust.LoadSeen(in.state, dl, r.RootsID(t)); st.Keys != 3 {
		t.Fatalf("a refused key list must not be remembered: %+v", st)
	}
	next := r.KeysDoc()
	next["version"] = 4
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, next))
	if err := in.run(); err != nil {
		t.Fatalf("the real next key list must still be accepted: %v", err)
	}
}

func TestTheStubsStateLineIsSixFields(t *testing.T) {
	// The state file's optional seventh field pins a document's bytes — the store's index; a core
	// manifest pins none. So a line of the stub's site that carries one (written by hand, or by another
	// program) goes back, on the next run, to the six fields the stub has always written.
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	s.serve("/dl/keys.json", r.KeysJSON())
	s.serve("/dl/linux/amd64/manifest.json", r.ManifestJSON())
	s.serve("/dl/linux/amd64/dgo-core", r.Payload)
	tmp := t.TempDir()
	state := filepath.Join(tmp, "state")
	pinned := dl + " " + r.RootsID(t) + " 3 - 1.0.0 " + trust.KeyID(trusttest.PubOf(r.Signer)) + " " + strings.Repeat("c", 64) + "\n"
	if err := os.WriteFile(state, []byte(seenHeader+pinned), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := freshInstall(dl, r.RootsB64(), state, filepath.Join(tmp, "core"), g).run(); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(state)
	for _, l := range strings.Split(strings.TrimSpace(string(b)), "\n") {
		if strings.HasPrefix(l, dl+" ") && len(strings.Fields(l)) != 6 {
			t.Errorf("the stub's line must be its six fields: %q", l)
		}
	}
}

func TestAStoreIndexServedAsTheManifestInstallsNothing(t *testing.T) {
	// The store lane's second reader, asked of this stub: a mirror serves the app store's signed index
	// where the core manifest belongs — in the manifest's own shape, pointing at index.json on the same
	// host. The stub before this one installed index.json as dgo-core and wrote VERSION.
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	store := trusttest.NewKey(t)
	d := r.KeysDoc()
	d["keys"] = append(d["keys"].([]any), trusttest.Listed(store, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(0, 5, 0), trust.IndexType))
	index := []byte(`{"entries":[],"format":"bina.catalog/v1","version":"9.0.0"}`)
	sum := sha256.Sum256(index)
	doc := r.ManifestDoc()
	doc["version"], doc["payload_url"], doc["sha256"], doc["size"] = "9.0.0", dl+"/v1/index.json", hex.EncodeToString(sum[:]), len(index)
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, d))
	s.serve("/dl/v1/index.json", index)
	tmp := t.TempDir()
	in := install{site: dl, roots: r.RootsB64(), stub: "1.2.0", target: trusttest.Target,
		state: filepath.Join(tmp, "state"), dest: filepath.Join(tmp, "core"),
		accept: true, noLaunch: true, now: trusttest.Now, out: &bytes.Buffer{}, net: g}
	for name, served := range map[string][]byte{
		"signed as the store's index":                     trusttest.Seal(store, trust.IndexType, doc),
		"signed by the store's key as a core manifest":    trusttest.Seal(store, trust.ManifestType, doc),
		"the index's envelope relabelled a core manifest": trusttest.EditEnvelope(trusttest.Seal(store, trust.IndexType, doc), func(e map[string]any) { e["payloadType"] = trust.ManifestType }),
	} {
		s.serve("/dl/linux/amd64/manifest.json", served)
		err := in.run()
		_, coreErr := os.Stat(filepath.Join(in.dest, "dgo-core"))
		_, verErr := os.Stat(filepath.Join(in.dest, "VERSION"))
		if err == nil || !strings.HasPrefix(err.Error(), "manifest: ") || coreErr == nil || verErr == nil {
			t.Errorf("%s: err %v; installed a core: %v, wrote VERSION: %v — want a manifest refusal and nothing written",
				name, err, coreErr == nil, verErr == nil)
		}
	}
}

func TestADevelopmentBuildSaysSoFirstAndInstallsNothing(t *testing.T) {
	offline := getter{proxy: func(string, string) (*url.URL, error) {
		t.Fatal("a development build must not touch the network")
		return nil, nil
	}}
	for _, baked := range []struct{ site, roots string }{
		{"", ""}, {"https://digital-office.co.il/dl", ""}, {"", trusttest.B64(trusttest.PubOf(trusttest.NewKey(t)))},
	} {
		var out bytes.Buffer
		in := install{site: baked.site, roots: baked.roots, stub: "dev", target: trusttest.Target,
			state: filepath.Join(t.TempDir(), "state"), dest: t.TempDir(), accept: true, now: trusttest.Now, out: &out, net: offline}
		err := in.run()
		lines := strings.Split(out.String(), "\n")
		if err == nil || !strings.Contains(err.Error(), "development build installs nothing") {
			t.Errorf("site %q roots %q: err %v", baked.site, baked.roots, err)
		}
		if len(lines) < 3 || lines[0] != "Welcome to DGO — Digital Office." || !strings.HasPrefix(lines[2], "This is a DEVELOPMENT build") {
			t.Errorf("the first screen must say plainly that this is a development build:\n%s", out.String())
		}
	}
}

func TestARunRefusesBeforeTheNetwork(t *testing.T) {
	offline := getter{proxy: func(string, string) (*url.URL, error) {
		t.Fatal("no network before the terms, the roots and the state file are settled")
		return nil, nil
	}}
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	base := install{site: r.Site, roots: r.RootsB64(), stub: "1.2.0", target: trusttest.Target,
		state: filepath.Join(t.TempDir(), "state"), dest: t.TempDir(), accept: true, now: trusttest.Now, out: &bytes.Buffer{}, net: offline}
	notAccepted, badRoot, noConfig := base, base, base
	notAccepted.accept = false
	badRoot.roots = "AAAA"
	noConfig.state = ""
	for want, in := range map[string]install{"terms not accepted": notAccepted, "built-in root key": badRoot,
		"no user configuration directory": noConfig} {
		if err := in.run(); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("err %v, want %q", err, want)
		}
	}
}

func TestFetchPayloadNeverCostsTheCoreThatWasThere(t *testing.T) {
	s, dl, g := newSite(t)
	good := []byte("the verified core")
	sum := sha256.Sum256(good)
	m := trust.Manifest{Version: "1.4.0", PayloadURL: dl + "/core", SHA256: hex.EncodeToString(sum[:]), Size: int64(len(good))}
	dest := t.TempDir()
	core := filepath.Join(dest, "dgo-core")
	in := install{dest: dest, net: g}
	// Another run's download in progress, under the name a fixed-name scheme would have used: this run
	// must neither delete it nor rename it into place.
	theirs := core + ".part"
	if err := os.WriteFile(theirs, []byte("another run's unverified bytes"), 0o644); err != nil {
		t.Fatal(err)
	}
	// …and the download of a run that died long ago (killed mid-way), which nobody writes any more.
	dead := core + ".4242.part"
	long := time.Now().Add(-2 * coreTimeout)
	if err := os.WriteFile(dead, []byte("a run that died"), 0o644); err != nil || os.Chtimes(dead, long, long) != nil {
		t.Fatal(err)
	}
	for body, want := range map[string]string{
		"the forged core!!":         "sha256 mismatch",          // same size, other bytes
		"the verified core, longer": "bytes allowed",            // more than the manifest's size
		"short":                     "bytes, the manifest says", // less
	} {
		if err := os.WriteFile(core, []byte("the old core"), 0o755); err != nil {
			t.Fatal(err)
		}
		s.serve("/dl/core", []byte(body))
		err := in.fetchPayload(m, core)
		was, _ := os.ReadFile(core)
		if err == nil || !strings.Contains(err.Error(), want) || string(was) != "the old core" {
			t.Errorf("serving %q: err %v, core now %q — want %q and the old core kept", body, err, was, want)
		}
		if left, _ := filepath.Glob(core + ".*.part"); len(left) != 0 {
			t.Errorf("serving %q: the refused download must be deleted: %v", body, left)
		}
	}
	s.serve("/dl/core", good)
	if err := in.fetchPayload(m, core); err != nil {
		t.Fatalf("a good download must replace the core: %v", err)
	}
	if was, _ := os.ReadFile(core); !bytes.Equal(was, good) {
		t.Fatalf("core is %q", was)
	}
	if b, err := os.ReadFile(theirs); err != nil || string(b) != "another run's unverified bytes" {
		t.Fatalf("another run's download was touched: %q %v", b, err)
	}
	if _, err := os.Stat(dead); err == nil {
		t.Error("the download of a run that died long ago must be cleaned away")
	}
}

func TestFetchPayloadReplacesARunningCore(t *testing.T) {
	// An update while DGO core runs. Windows refuses to overwrite a running .exe but lets it be renamed,
	// so the old core steps aside; elsewhere the rename replaces it outright. The "core" here is a copy
	// of this test binary, kept running by TestMain.
	s, dl, g := newSite(t)
	dest := t.TempDir()
	core := filepath.Join(dest, payloadName(runtime.GOOS+"/"+runtime.GOARCH))
	self, err := os.ReadFile(os.Args[0])
	if err == nil {
		err = os.WriteFile(core, self, 0o755)
	}
	if err != nil {
		t.Fatal(err)
	}
	p, err := os.StartProcess(core, []string{core}, &os.ProcAttr{Env: append(os.Environ(), "DGO_INSTALL_TEST_CORE_RUNS=1"),
		Files: []*os.File{os.Stdin, os.Stdout, os.Stderr}}) // Windows wants all three
	if err != nil {
		t.Fatal(err)
	}
	defer func() { p.Kill(); p.Wait() }()
	fresh := []byte("the new core")
	sum := sha256.Sum256(fresh)
	s.serve("/dl/core", fresh)
	m := trust.Manifest{Version: "1.5.0", PayloadURL: dl + "/core", SHA256: hex.EncodeToString(sum[:]), Size: int64(len(fresh))}
	if err := (install{dest: dest, net: g}).fetchPayload(m, core); err != nil {
		t.Fatalf("an update must replace a running core: %v", err)
	}
	if b, _ := os.ReadFile(core); !bytes.Equal(b, fresh) {
		t.Fatalf("the core is still the old one (%d bytes)", len(b))
	}
}

func TestLaunchReportsTheCoresExitStatus(t *testing.T) {
	t.Setenv("DGO_INSTALL_TEST_CORE_EXIT", "3")
	if err := launch(os.Args[0]); err == nil || !strings.Contains(err.Error(), "exit status 3") {
		t.Fatalf("a core that fails must be reported with its status: %v", err)
	}
	t.Setenv("DGO_INSTALL_TEST_CORE_EXIT", "0")
	if err := launch(os.Args[0]); err != nil {
		t.Fatalf("a core that succeeds is not an error: %v", err)
	}
}

func TestSemverLessIsNumericAndForwardOnly(t *testing.T) {
	cases := []struct {
		a, b string
		less bool
	}{
		{"1.2.0", "1.10.0", true},  // numeric, not lexical: 2 < 10
		{"1.2.0", "1.2.0", false},  // equal is not "less" — no reinstall of the same version
		{"1.3.0", "1.2.9", false},  // a newer installed version blocks an older manifest (forward-only)
		{"v1.0.0", "1.0.1", true},  // a leading v is tolerated
		{"1.0.0", "1.0.0.1", true}, // a longer, higher version is newer
		{"dev", "0.0.1", true},     // an unversioned stub is older than any min_bootstrapper above 0
	}
	for _, c := range cases {
		if got := trust.SemverLess(c.a, c.b); got != c.less {
			t.Errorf("trust.SemverLess(%q, %q) = %v, want %v", c.a, c.b, got, c.less)
		}
	}
}

func TestThePayloadLivesUnderTheSite(t *testing.T) {
	const site = "https://digital-office.co.il/dl"
	for payload, ok := range map[string]bool{
		"https://digital-office.co.il/dl/linux/amd64/dgo-core":           true,
		"https://DIGITAL-OFFICE.co.il/dl/linux/amd64/dgo-core?build=1&a": true, // a host is case-blind; a query is the server's
		"https://cdn.evil.example/dl/linux/amd64/dgo-core":               false,
		"http://digital-office.co.il/dl/linux/amd64/dgo-core":            false,
		"https://digital-office.co.il/beta/linux/amd64/dgo-core":         false, // another site of the same host
		"https://digital-office.co.il/dl2/linux/amd64/dgo-core":          false, // a look-alike of the path
		"https://digital-office.co.il/dl/../beta/linux/amd64/dgo-core":   false, // climbing out
		"https://digital-office.co.il/dl/%2e%2e/beta/dgo-core":           false, // climbing out, escaped
		"https://digital-office.co.il/dl/..%5cbeta/dgo-core":             false, // climbing out on a server that reads \ as /
		`https://digital-office.co.il/dl/..\beta\dgo-core`:               false, // the same, unescaped
		"https://digital-office.co.il/dl//linux/dgo-core":                false, // not a clean path
		"https://digital-office.co.il/dl":                                false, // the site itself is no file
		"https://user:pw@digital-office.co.il/dl/linux/amd64/dgo-core":   false,
	} {
		if got := trust.UnderSite(site, payload); got != ok {
			t.Errorf("trust.UnderSite(%s) = %v, want %v", payload, got, ok)
		}
	}
	if !trust.UnderSite(site+"/", site+"/linux/amd64/dgo-core") {
		t.Error("a site written with its trailing slash is the same site")
	}
}

// TestRelsignChainVerifiesInTheStub pins the release path to this binary: packaging/relsign makes the
// two signed documents and the stub verifies them. The programs share the protocol — trust.PAE(), trust.KeyID(),
// the envelope's and the documents' field names — and this test is what keeps the two copies honest.
// Skipped where `go` is not on PATH (the tests above still cover the stub's side).
func TestRelsignChainVerifiesInTheStub(t *testing.T) {
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
	key := func(name string) string { p := filepath.Join(dir, name+".pem"); relsign("keygen", p); return p }
	root, spare, signer := key("root"), key("spare"), key("signer")
	roots, err := trust.ParseRoots(strings.TrimSpace(string(relsign("pubkey", root))) + "," + strings.TrimSpace(string(relsign("pubkey", spare))))
	if err != nil {
		t.Fatal(err)
	}
	payload := filepath.Join(dir, "dgo-core")
	if err := os.WriteFile(payload, []byte("pretend DGO core"), 0o644); err != nil {
		t.Fatal(err)
	}
	// An & in the URL: relsign's encoding/json escapes it (a backslash, then u0026), which the stub's reader must undo.
	const payloadURL = "https://digital-office.co.il/dl/linux/amd64/dgo-core?build=1&os=linux"
	const site = "https://digital-office.co.il/dl"
	manifestArgs := []string{"-site", site, "-version", "1.4.0", "-target", "linux/amd64", "-url", payloadURL, "-file", payload,
		"-expires", "90d", "-min-bootstrapper", "1.0.0"}

	keysJSON := relsign("keys", "-signer", root, "-site", site, "-version", "1", "-key", signer, "-types", "dgo-core-manifest")
	manJSON := relsign(append([]string{"manifest", "-signer", signer}, manifestArgs...)...)
	c := trust.Checker{Type: trust.ManifestType, Roots: roots, Site: site, Now: time.Now(), Stub: "1.2.0", Target: "linux/amd64"}
	kl, err := c.VerifyKeys(keysJSON)
	if err != nil {
		t.Fatalf("a relsign key list must verify in the stub: %v", err)
	}
	// The floor build-binaries.sh bakes into a stub (relsign floor) must be the stub's own reading of
	// the list — or a stub would refuse the very list it was built with.
	keysFile := filepath.Join(dir, "keys.json")
	if err := os.WriteFile(keysFile, keysJSON, 0o644); err != nil {
		t.Fatal(err)
	}
	if got, want := strings.TrimSpace(string(relsign("floor", keysFile))), strconv.FormatInt(kl.Version, 10)+":"+kl.Sum; got != want {
		t.Errorf("relsign floor = %q, the stub reads the list as %q", got, want)
	}
	m, err := c.VerifyManifest(manJSON, kl)
	if err != nil {
		t.Fatalf("a relsign manifest must verify in the stub — the signer and the stub disagree on the protocol: %v", err)
	}
	sum := sha256.Sum256([]byte("pretend DGO core"))
	if m.Version != "1.4.0" || m.PayloadURL != payloadURL || m.SHA256 != hex.EncodeToString(sum[:]) || m.Size != 16 || m.MinBootstrapper != "1.0.0" {
		t.Fatalf("the stub read relsign's manifest wrong: %+v", m)
	}

	if _, err := c.VerifyManifest(trusttest.Forge(manJSON, func(d map[string]any) { d["version"] = "9.9.9" }), kl); err == nil {
		t.Error("a tampered relsign manifest must not verify")
	}
	floored, err := c.VerifyKeys(relsign("keys", "-signer", root, "-site", site, "-version", "2", "-core-floor", "1.5.0",
		"-key", signer, "-types", "dgo-core-manifest"))
	if err != nil || floored.CoreFloor != "1.5.0" {
		t.Fatalf("the stub must read the core_floor relsign writes: %v (%q)", err, floored.CoreFloor)
	}
	if _, err := c.VerifyManifest(manJSON, floored); err == nil || !strings.Contains(err.Error(), "the oldest keys.json allows") {
		t.Errorf("relsign's 1.4.0 under its own list's core_floor 1.5.0 must be refused: %v", err)
	}
	storeOnly, err := c.VerifyKeys(relsign("keys", "-signer", root, "-site", site, "-version", "1", "-expires", "365d", "-key", signer, "-types", "dgo-app-index"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.VerifyManifest(manJSON, storeOnly); err == nil || !strings.Contains(err.Error(), "does not trust that key") {
		t.Errorf("a key relsign scoped to the store's index must not pass a core manifest: %v", err)
	}
	notRoot := relsign("keys", "-signer", signer, "-site", site, "-version", "2", "-expires", "365d", "-key", key("next"), "-types", "dgo-core-manifest")
	if _, err := c.VerifyKeys(relsign("keys", "-signer", root, "-site", "https://apps.net.digital-office.co.il", "-version", "9",
		"-expires", "365d", "-key", signer, "-types", "dgo-app-index")); err == nil || !strings.Contains(err.Error(), "key list of") {
		t.Errorf("a relsign key list for another site must be refused here: %v", err)
	}
	if _, err := c.VerifyKeys(notRoot); err == nil || !strings.Contains(err.Error(), "unknown signer") {
		t.Errorf("a key list signed by the online key, not a root, must be refused: %v", err)
	}
	draft := relsign(append([]string{"manifest", "-unsigned"}, manifestArgs...)...)
	if _, err := c.VerifyManifest(draft, kl); err == nil {
		t.Error("an unsigned draft must never pass for a manifest")
	}
}

// TestReleaseTree is how packaging/build-binaries.sh checks a signed release before it says done: the
// stub's own rules over the tree it is about to publish — keys.json against the committed roots (the
// ones every stub embeds) and against the key list floor baked into the stubs (relsign reads the list
// with encoding/json, the stub with its own reader: were they ever to disagree, every stub would refuse
// the very list it was built with), every <os>/<arch>/manifest.json against keys.json, every payload
// against its manifest. One verifier, so a release cannot pass a check the installer would fail. Only
// --selftest passes -roots, for its throwaway chain. Without -tree it is skipped.
func TestReleaseTree(t *testing.T) {
	if *treeDir == "" {
		t.Skip("no -tree: packaging/build-binaries.sh passes one after it signs a release")
	}
	from := string(rootKeys)
	if *treeRoots != "" {
		from = *treeRoots
	}
	roots, err := trust.ParseRoots(from)
	if err != nil || len(roots) == 0 {
		t.Fatalf("the roots (packaging/installer/roots.txt, or -roots): %d roots, %v", len(roots), err)
	}
	built, err := trust.ParseFloor(*treeFloor)
	if err != nil || *treeFloor == "" {
		t.Fatalf("-floor must be the key list floor the stubs were built with (relsign floor keys.json), got %q: %v", *treeFloor, err)
	}
	raw, err := os.ReadFile(filepath.Join(*treeDir, "keys.json"))
	if err != nil {
		t.Fatal(err)
	}
	c := trust.Checker{Type: trust.ManifestType, Roots: roots, Site: *treeSite, Now: time.Now(), Stub: *treeStub, Built: built}
	kl, err := c.VerifyKeys(raw)
	if err != nil {
		t.Fatal(err)
	}
	manifests, _ := filepath.Glob(filepath.Join(*treeDir, "*", "*", "manifest.json"))
	if len(manifests) == 0 {
		t.Fatalf("no <os>/<arch>/manifest.json under %s", *treeDir)
	}
	for _, mf := range manifests {
		dir := filepath.Dir(mf)
		c.Target = filepath.Base(filepath.Dir(dir)) + "/" + filepath.Base(dir)
		raw, err := os.ReadFile(mf)
		if err != nil {
			t.Fatal(err)
		}
		m, err := c.VerifyManifest(raw, kl)
		if err != nil {
			t.Errorf("%s: %v", mf, err)
			continue
		}
		u, _ := url.Parse(m.PayloadURL)
		body, err := os.ReadFile(filepath.Join(dir, path.Base(u.Path)))
		sum := sha256.Sum256(body)
		if err != nil || int64(len(body)) != m.Size || hex.EncodeToString(sum[:]) != m.SHA256 {
			t.Errorf("%s: the payload beside it is not the one it pins (%v)", mf, err)
			continue
		}
		t.Logf("verified %s: DGO core %s, %d bytes, until %s", c.Target, m.Version, m.Size, trust.Stamp(m.Expires))
	}
}

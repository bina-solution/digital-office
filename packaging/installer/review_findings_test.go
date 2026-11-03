package main

// Second reader's tests for core-stub.patch. Each test states the property the stub should hold; each
// FAILS against the patch as written (run: go test -count=1 -run '^TestReview' -v .).

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust/trusttest"
)

// payloadDoc is r.ManifestDoc() for other bytes and another version.
func payloadDoc(r *trusttest.Release, version, payloadURL string, body []byte) map[string]any {
	sum := sha256.Sum256(body)
	d := r.ManifestDoc()
	d["version"], d["payload_url"], d["sha256"], d["size"] = version, payloadURL, hex.EncodeToString(sum[:]), len(body)
	return d
}

func freshInstall(dl, roots, state, dest string, g getter) install {
	return install{site: dl, roots: roots, stub: "1.2.0", target: trusttest.Target, state: state, dest: dest,
		accept: true, noLaunch: true, now: trusttest.Now, out: &bytes.Buffer{}, net: g}
}

// FINDING 1 — the manifest is not bound to its download site. keys.json names its site (the roots sign
// a list per site); the manifest names none, and the payload check is host-only. Two of the owner's sites
// on one host (stable /dl and a pre-release site /beta — "a pre-release belongs on its own site") whose
// lists both name the release job's one online key: beta's manifest, served at — or REDIRECTED to from —
// the stable manifest's URL, is installed by a stable stub, and its version becomes the stable floor.
func TestReviewAManifestOfAnotherSiteOnTheSameHostIsRefused(t *testing.T) {
	for _, via := range []string{"copied", "redirected"} {
		t.Run(via, func(t *testing.T) {
			s := &site{files: map[string][]byte{}}
			redirect := via == "redirected"
			ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
				s.mu.Lock()
				on := redirect
				s.mu.Unlock()
				if on && r.URL.Path == "/dl/linux/amd64/manifest.json" {
					http.Redirect(w, r, "/beta/linux/amd64/manifest.json", http.StatusFound)
					return
				}
				s.mu.Lock()
				b, ok := s.files[r.URL.Path]
				s.mu.Unlock()
				if !ok {
					http.NotFound(w, r)
					return
				}
				w.Write(b)
			})
			dl, beta := ts.URL+"/dl", ts.URL+"/beta"
			r := trusttest.NewRelease(t, dl)
			betaKeys := r.KeysDoc()
			betaKeys["site"] = beta // its own list, for its own site — the same online key in it
			s.serve("/dl/keys.json", r.KeysJSON())
			s.serve("/beta/keys.json", trusttest.Seal(r.Root, trust.KeysType, betaKeys))
			betaCore := []byte("a beta build of DGO core, never meant for /dl")
			betaManifest := trusttest.Seal(r.Signer, trust.ManifestType, payloadDoc(r, "1.9.0", beta+"/linux/amd64/dgo-core", betaCore))
			s.serve("/beta/linux/amd64/manifest.json", betaManifest)
			s.serve("/beta/linux/amd64/dgo-core", betaCore)
			if via == "copied" {
				s.serve("/dl/linux/amd64/manifest.json", betaManifest)
			}
			tmp := t.TempDir()
			in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
			err := in.run()
			got, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
			st, _ := trust.LoadSeen(in.state, dl, r.RootsID(t))
			if err == nil || bytes.Equal(got, betaCore) {
				// What follows from it: /dl's real next release is now refused as a replay.
				s.mu.Lock()
				redirect = false
				s.mu.Unlock()
				s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, payloadDoc(r, "1.5.0", dl+"/linux/amd64/dgo-core", r.Payload)))
				s.serve("/dl/linux/amd64/dgo-core", r.Payload)
				next := in.run()
				t.Fatalf("a /dl stub accepted /beta's manifest: err %v, installed %q, remembered %+v; "+
					"then /dl's own 1.5.0: %v", err, got, st, next)
			}
		})
	}
}

// FINDING 2a — a fast-forward by a leaked ONLINE key survives its revocation. TUF (spec 5.3.11/5.4.6)
// forgets the fast-forwarded version when the signing role's keys rotate; here the manifest floor and
// VERSION keep the attacker's number, so after the owner revokes the key every real release is refused
// ("replayed old manifest") — and deleting install-state, the README's reset, still leaves VERSION
// saying "already installed" over the attacker's core.
func TestReviewRevokingALeakedKeyUndoesItsFastForward(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	s.serve("/dl/keys.json", r.KeysJSON()) // list 3 names r.Signer — which leaks
	evil := []byte("the holder of the leaked online key's core")
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, payloadDoc(r, "999999999.0.0", dl+"/linux/amd64/dgo-core", evil)))
	s.serve("/dl/linux/amd64/dgo-core", evil)
	tmp := t.TempDir()
	in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
	if err := in.run(); err != nil {
		t.Fatalf("precondition (the leaked key is still listed): %v", err)
	}
	// The owner's documented remedy: list 4 without the leaked key, a new key signing the real release.
	next := trusttest.NewKey(t)
	kd := r.KeysDoc()
	kd["version"] = 4
	kd["keys"] = []any{trusttest.Window(next, trusttest.Now.AddDate(0, 0, -1), trusttest.Now.AddDate(0, 6, 0))}
	s.serve("/dl/keys.json", trusttest.Seal(r.Root, trust.KeysType, kd))
	good := []byte("DGO core 1.5.0, the real one")
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(next, trust.ManifestType, payloadDoc(r, "1.5.0", dl+"/linux/amd64/dgo-core", good)))
	s.serve("/dl/linux/amd64/dgo-core", good)
	err := in.run()
	core, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
	if err != nil || !bytes.Equal(core, good) {
		os.Remove(in.state) // the README: "Removing this file ... never blocks an install"
		out := &bytes.Buffer{}
		in.out = out
		err2 := in.run()
		core2, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
		t.Fatalf("after revoking the leaked key, the real 1.5.0 must replace the attacker's core: err %v, core %q;\n"+
			"even with install-state deleted: err %v, says %q, core %q", err, core, err2, strings.TrimSpace(lastLine(out.String())), core2)
	}
}

// FINDING 2b — the same for a leaked ROOT: its key list, numbered far ahead, is remembered for the site,
// so the README's remedy — "a leaked root means new stubs (a new generation with new roots)" — fails on
// every computer that saw it: the new generation shares the state file and site and refuses every real
// key list as "replayed". (At math.MaxInt64 the owner cannot even out-number it.)
func TestReviewANewRootGenerationIsNotLockedOutByALeakedRootsList(t *testing.T) {
	s, dl, g := newSite(t)
	gen1 := trusttest.NewRelease(t, dl)
	attacker := trusttest.NewKey(t)
	kd := gen1.KeysDoc()
	kd["version"] = int64(math.MaxInt64)
	kd["keys"] = []any{trusttest.Window(attacker, trusttest.Now.AddDate(0, -1, 0), trusttest.Now.AddDate(1, 0, 0))}
	s.serve("/dl/keys.json", trusttest.Seal(gen1.Root, trust.KeysType, kd)) // signed by the leaked gen-1 root
	tmp := t.TempDir()
	state := filepath.Join(tmp, "state")
	_ = freshInstall(dl, gen1.RootsB64(), state, filepath.Join(tmp, "core"), g).run() // remembered at once
	gen2 := trusttest.NewRelease(t, dl)                                               // the new generation: new roots, the same site
	s.serve("/dl/keys.json", gen2.KeysJSON())
	s.serve("/dl/linux/amd64/manifest.json", gen2.ManifestJSON())
	s.serve("/dl/linux/amd64/dgo-core", gen2.Payload)
	if err := freshInstall(dl, gen2.RootsB64(), state, filepath.Join(tmp, "core2"), g).run(); err != nil {
		t.Fatalf("a new-generation stub (new roots) must install the real release: %v", err)
	}
}

// FINDING 3 — a revoked online key keeps installing on every computer that has not yet seen the list
// that revoked it — every fresh install included — for the rest of the old list's life (365d in the
// README's ceremony; relsign's key windows default to it). The stub carries no floor for the key list,
// though build-binaries.sh holds the current keys.json when it bakes the stub.
func TestReviewAKeyRevokedBeforeThisStubWasBuiltCannotInstall(t *testing.T) {
	s, dl, g := newSite(t)
	r := trusttest.NewRelease(t, dl)
	// List 4 revoked r.Signer before this stub was built; the attacker replays list 3 (unexpired).
	s.serve("/dl/keys.json", r.KeysJSON())
	evil := []byte("signed with the revoked key")
	s.serve("/dl/linux/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, payloadDoc(r, "1.4.1", dl+"/linux/amd64/dgo-core", evil)))
	s.serve("/dl/linux/amd64/dgo-core", evil)
	tmp := t.TempDir()
	in := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g)
	// The fix (core-stub, security round): a release stub carries the key list it was built with —
	// build-binaries.sh bakes `relsign floor keys.json` in as -X main.keysFloor. This stub was built
	// after list 4 revoked the key, so it carries list 4.
	in.built = trust.Seen{Keys: 4}
	err := in.run()
	core, _ := os.ReadFile(filepath.Join(in.dest, "dgo-core"))
	if err == nil || bytes.Equal(core, evil) {
		t.Fatalf("a fresh computer installed a manifest signed by a key list 4 had revoked: err %v, core %q", err, core)
	}
}

// FINDING 4 — the signature's base64 is not checked: DecodeString's error is dropped and its partial
// output kept, so a valid signature followed by garbage still verifies (trust.go: "not base64 ⇒ verifies
// as nothing" is not what happens). Not a forgery, but the one signed field the reader is lax about.
func TestReviewASignatureThatIsNotBase64VerifiesAsNothing(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	padded := trusttest.EditEnvelope(r.KeysJSON(), func(e map[string]any) {
		sig := e["signatures"].([]any)[0].(map[string]any)
		sig["sig"] = sig["sig"].(string) + "!!!! not base64 at all"
	})
	if _, err := r.Checker(t).VerifyKeys(padded); err == nil {
		t.Fatal("a signature field that is not base64 verified")
	}
}

func lastLine(s string) string {
	lines := strings.Split(strings.TrimSpace(s), "\n")
	return lines[len(lines)-1]
}

var _ = time.Second

// Package trusttest mints, for tests only, what the owner's ceremony and a release job make — two
// roots, the signing key keys.json lists, the documents they vouch for — so the trust layer's own tests
// and the installer's build the very same chain. Every key is minted at runtime, the way the ceremony
// makes them: no key, real or test, lives in the repository.
//
// The documents are maps, so a test can drop or break any field, and Seal writes them with
// encoding/json's own envelope (a map's sorted field order, not trust.Seal's): the verifiers are held
// to JSON, never to one writer's bytes.
package trusttest

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

// Now is every test's clock: a run fixes its clock when it begins, so a test does too.
var Now = time.Date(2026, 10, 15, 12, 0, 0, 0, time.UTC)

// Target is the platform every test's manifest is for.
const Target = "linux/amd64"

// Release is what the owner's ceremony and a release job make: two roots (the second kept in a safe),
// the signing key keys.json lists, and the payload the manifest pins.
type Release struct {
	Root, Spare, Signer ed25519.PrivateKey
	Site                string
	Payload             []byte
}

// NewRelease is a release of site, its keys fresh.
func NewRelease(t testing.TB, site string) *Release {
	return &Release{Root: NewKey(t), Spare: NewKey(t), Signer: NewKey(t), Site: site,
		Payload: []byte("pretend DGO core bytes")}
}

// NewKey is a fresh Ed25519 key.
func NewKey(t testing.TB) ed25519.PrivateKey {
	t.Helper()
	_, priv, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	return priv
}

// PubOf is a key's public half.
func PubOf(k ed25519.PrivateKey) ed25519.PublicKey { return k.Public().(ed25519.PublicKey) }

// B64 is standard base64, as the documents carry keys and signatures.
func B64(b []byte) string { return base64.StdEncoding.EncodeToString(b) }

// RFC3339 is an instant as the documents carry it.
func RFC3339(t time.Time) string { return t.UTC().Format(time.RFC3339) }

// SHA256Hex is the hex sha256 of b.
func SHA256Hex(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

// RootsB64 is this release's roots.txt: what its stubs embed.
func (r *Release) RootsB64() string { return B64(PubOf(r.Root)) + "," + B64(PubOf(r.Spare)) }

// KeysDoc is a good key list: version 3, a year to live, the signing key valid from a month ago.
func (r *Release) KeysDoc() map[string]any {
	return map[string]any{"site": r.Site, "version": 3, "expires": RFC3339(Now.AddDate(1, 0, 0)),
		"keys": []any{Window(r.Signer, Now.AddDate(0, -1, 0), Now.AddDate(0, 5, 0))}}
}

// Window is a keys.json entry for a core-manifest signing key, valid from..until.
func Window(k ed25519.PrivateKey, from, until time.Time) map[string]any {
	return Listed(k, from, until, trust.ManifestType)
}

// Listed is a keys.json entry for k, valid from..until, trusted to sign the given document types.
func Listed(k ed25519.PrivateKey, from, until time.Time, types ...string) map[string]any {
	ts := []any{}
	for _, t := range types {
		ts = append(ts, t)
	}
	return map[string]any{"public_key": B64(PubOf(k)), "types": ts, "not_before": RFC3339(from), "not_after": RFC3339(until)}
}

// ManifestDoc is a good manifest of r.Site for r.Payload: 1.4.0, a month to live, for stubs 1.2.0 and newer.
func (r *Release) ManifestDoc() map[string]any {
	sum := sha256.Sum256(r.Payload)
	return map[string]any{"site": r.Site, "version": "1.4.0", "expires": RFC3339(Now.AddDate(0, 1, 0)),
		"min_bootstrapper": "1.2.0", "target": Target, "payload_url": r.Site + "/" + Target + "/dgo-core",
		"sha256": hex.EncodeToString(sum[:]), "size": len(r.Payload)}
}

// KeysJSON is keys.json as served: KeysDoc, sealed by the first root.
func (r *Release) KeysJSON() []byte { return Seal(r.Root, trust.KeysType, r.KeysDoc()) }

// ManifestJSON is the manifest as served: ManifestDoc, sealed by the listed key.
func (r *Release) ManifestJSON() []byte { return Seal(r.Signer, trust.ManifestType, r.ManifestDoc()) }

// RootsID is the name this release's roots give their line of the state file.
func (r *Release) RootsID(t testing.TB) string {
	t.Helper()
	roots, err := trust.ParseRoots(r.RootsB64())
	if err != nil {
		t.Fatal(err)
	}
	return trust.RootsID(roots)
}

// Checker is a fresh computer's, reading this release's site: nothing accepted yet, a stub at 1.2.0,
// on Target.
func (r *Release) Checker(t testing.TB) trust.Checker {
	t.Helper()
	roots, err := trust.ParseRoots(r.RootsB64())
	if err != nil {
		t.Fatal(err)
	}
	return trust.Checker{Roots: roots, Site: r.Site, Type: trust.ManifestType, Now: Now, Stub: "1.2.0", Target: Target}
}

// Seal writes a DSSE envelope of doc, signed by by over the PAE of the whole document — with
// encoding/json, the field order of a map; TestRelsignChainVerifiesInTheStub proves relsign's agrees.
func Seal(by ed25519.PrivateKey, typ string, doc any) []byte {
	body, err := json.Marshal(doc)
	if err != nil {
		panic(err)
	}
	env, err := json.Marshal(map[string]any{"payloadType": typ, "payload": B64(body),
		"signatures": []any{map[string]any{"keyid": trust.KeyID(PubOf(by)), "sig": B64(ed25519.Sign(by, trust.PAE(typ, body)))}}})
	if err != nil {
		panic(err)
	}
	return env
}

// Forge edits the document inside an envelope and keeps its signature — all an attacker who can serve
// files, but holds no key, is able to do.
func Forge(env []byte, edit func(map[string]any)) []byte {
	var e, doc map[string]any
	if err := json.Unmarshal(env, &e); err != nil {
		panic(err)
	}
	body, _ := base64.StdEncoding.DecodeString(e["payload"].(string))
	if err := json.Unmarshal(body, &doc); err != nil {
		panic(err)
	}
	edit(doc)
	body, _ = json.Marshal(doc)
	e["payload"] = B64(body)
	out, _ := json.Marshal(e)
	return out
}

// EditEnvelope changes the envelope's own fields (not the signed document) — the malformed cases.
func EditEnvelope(env []byte, f func(map[string]any)) []byte {
	var e map[string]any
	if err := json.Unmarshal(env, &e); err != nil {
		panic(err)
	}
	f(e)
	out, _ := json.Marshal(e)
	return out
}

// MustPayload is the document inside an envelope.
func MustPayload(t testing.TB, env []byte) []byte {
	t.Helper()
	var e map[string]any
	if err := json.Unmarshal(env, &e); err != nil {
		t.Fatal(err)
	}
	body, err := base64.StdEncoding.DecodeString(e["payload"].(string))
	if err != nil {
		t.Fatal(err)
	}
	return body
}

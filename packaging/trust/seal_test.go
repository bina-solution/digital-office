package trust_test

// The producing side (seal.go): Seal writes what encoding/json writes for the Envelope, and what the
// producers write with the documents' shapes is what the verifiers read, field for field.

import (
	"crypto/ed25519"
	"encoding/json"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust/trusttest"
)

func TestSealWritesWhatEncodingJSONWrites(t *testing.T) {
	key := trusttest.NewKey(t)
	body := []byte(`{"site":"https://digital-office.co.il/dl?a=1&b=<2>","version":"1.4.0"}`)
	for _, typ := range []string{trust.KeysType, trust.ManifestType, trust.IndexType} {
		got, err := trust.Seal(key, typ, body)
		if err != nil {
			t.Fatal(err)
		}
		want, err := json.Marshal(trust.Envelope{PayloadType: typ, Payload: trusttest.B64(body), Signatures: []trust.Signature{
			{KeyID: trust.KeyID(trusttest.PubOf(key)), Sig: trusttest.B64(ed25519.Sign(key, trust.PAE(typ, body)))}}})
		if err != nil || string(got) != string(want) {
			t.Errorf("%s: Seal wrote\n%s\nencoding/json writes\n%s", typ, got, want)
		}
	}
	for _, typ := range []string{"", "dgo-other", `dgo-keys","x":"`} {
		if _, err := trust.Seal(key, typ, body); err == nil {
			t.Errorf("%q is no type of the office's documents: Seal must refuse it", typ)
		}
	}
}

// What relsign and `dgo index build` write — the documents' shapes, marshalled by encoding/json and
// sealed by Seal — is what the verifiers read, every field of every kind.
func TestWhatTheProducersWriteIsWhatTheVerifiersRead(t *testing.T) {
	r := trusttest.NewRelease(t, "https://digital-office.co.il/dl")
	seal := func(by ed25519.PrivateKey, typ string, doc any) []byte {
		t.Helper()
		body, err := json.Marshal(doc)
		if err != nil {
			t.Fatal(err)
		}
		env, err := trust.Seal(by, typ, body)
		if err != nil {
			t.Fatal(err)
		}
		return env
	}
	from, until := trusttest.Now.AddDate(0, 0, -1), trusttest.Now.AddDate(0, 2, 0)
	by := trust.KeyID(trusttest.PubOf(r.Signer))
	keys := trust.KeysDoc{Site: r.Site, Version: 3, Expires: trust.Stamp(until), CoreFloor: "1.4.0", IndexFloor: "1.3.0", Keys: []trust.KeyEntry{{
		PublicKey: trusttest.B64(trusttest.PubOf(r.Signer)), Types: []string{trust.ManifestType, trust.IndexType},
		NotBefore: trust.Stamp(from), NotAfter: trust.Stamp(until)}}}
	c := r.Checker(t)
	kl, err := c.VerifyKeys(seal(r.Root, trust.KeysType, keys))
	if err != nil || kl.Version != 3 || kl.CoreFloor != "1.4.0" || kl.IndexFloor != "1.3.0" || !kl.Lists(by, trust.ManifestType) || !kl.Lists(by, trust.IndexType) {
		t.Fatalf("the key list as written: %+v, %v", kl, err)
	}
	man := trust.ManifestDoc{Site: r.Site, Version: "1.4.0", Expires: trust.Stamp(until), MinBootstrapper: "1.2.0", Target: trusttest.Target,
		PayloadURL: r.Site + "/linux/amd64/dgo-core?build=1&os=linux", SHA256: trusttest.SHA256Hex(r.Payload), Size: int64(len(r.Payload))}
	m, err := c.VerifyManifest(seal(r.Signer, trust.ManifestType, man), kl)
	if err != nil || (trust.ManifestDoc{Site: m.Site, Version: m.Version, Expires: trust.Stamp(m.Expires), MinBootstrapper: m.MinBootstrapper,
		Target: m.Target, PayloadURL: m.PayloadURL, SHA256: m.SHA256, Size: m.Size}) != man || m.Signer != by {
		t.Fatalf("the manifest as written %+v, read %+v: %v", man, m, err)
	}
	sc := storeChecker(t, r)
	keys.Site = storeSite
	skl, err := sc.VerifyKeys(seal(r.Root, trust.KeysType, keys))
	if err != nil {
		t.Fatal(err)
	}
	ix := trust.IndexDoc{Site: storeSite, Version: "1.4.0", SHA256: trusttest.SHA256Hex([]byte("index")), Size: 5}
	if got, signer, err := sc.VerifyIndex(seal(r.Signer, trust.IndexType, ix), skl); err != nil || got != ix || signer != by {
		t.Fatalf("the index document as written %+v, read %+v by %s: %v", ix, got, signer, err)
	}
}

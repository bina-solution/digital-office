package main

// Tests for the security-critical verification path: the whole point of this stub over `curl | run`
// is that it refuses anything the baked-in release key did not sign, served from anywhere but the
// manifest's own HTTPS host, or older than what is installed. These assert exactly those refusals.

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// signedManifest mints a key and a manifest signed by it, the way a real release build would.
func signedManifest(t *testing.T) (ed25519.PublicKey, manifest) {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}
	sum := sha256.Sum256([]byte("pretend DGO core payload bytes"))
	m := manifest{
		Version:    "1.2.0",
		PayloadURL: "https://digital-office.co.il/dl/linux/amd64/dgo-core",
		SHA256:     hex.EncodeToString(sum[:]),
	}
	m.SigB64 = base64.StdEncoding.EncodeToString(ed25519.Sign(priv, m.signedMessage()))
	return pub, m
}

// verifies composes exactly what run() composes to accept a manifest.
func verifies(pub ed25519.PublicKey, m manifest) bool {
	return ed25519.Verify(pub, m.signedMessage(), mustB64(m.SigB64))
}

func TestManifestSignatureRoundTrip(t *testing.T) {
	pub, m := signedManifest(t)
	if !verifies(pub, m) {
		t.Fatal("a correctly signed manifest must verify against its release key")
	}
}

func TestTamperBreaksSignature(t *testing.T) {
	pub, base := signedManifest(t)
	// Each field the signature covers: changing any one, with the old signature, must be rejected.
	cases := []struct {
		name string
		mut  func(*manifest)
	}{
		{"version", func(m *manifest) { m.Version = "9.9.9" }},
		{"payload_url", func(m *manifest) { m.PayloadURL = "https://cdn.evil.example/dgo-core" }},
		{"sha256", func(m *manifest) { m.SHA256 = "00" + base.SHA256[2:] }},
	}
	for _, c := range cases {
		m := base
		c.mut(&m)
		if verifies(pub, m) {
			t.Errorf("tampering with %s must invalidate the manifest signature", c.name)
		}
	}
}

func TestWrongKeyRejected(t *testing.T) {
	_, m := signedManifest(t)
	otherPub, _, _ := ed25519.GenerateKey(nil)
	if verifies(otherPub, m) {
		t.Fatal("a manifest must not verify against a key other than the one that signed it")
	}
}

func TestMalformedSignatureRejected(t *testing.T) {
	pub, m := signedManifest(t)
	m.SigB64 = "!!! not base64 !!!" // mustB64 discards the decode error and returns empty
	if verifies(pub, m) {
		t.Fatal("a malformed signature must not verify (fail-closed)")
	}
}

func TestSignedMessageIsStableAndLowercasesSHA(t *testing.T) {
	m := manifest{Version: "1.2.0", PayloadURL: "https://h/p", SHA256: "ABCDEF"}
	got := string(m.signedMessage())
	want := "1.2.0\nhttps://h/p\nabcdef" // sha is compared case-insensitively, so it is signed lowercased
	if got != want {
		t.Fatalf("signedMessage() = %q, want %q", got, want)
	}
}

func TestSameHTTPSHost(t *testing.T) {
	const man = "https://digital-office.co.il/dl/linux/amd64/manifest.json"
	cases := []struct {
		name    string
		payload string
		ok      bool
	}{
		{"same host, https", "https://digital-office.co.il/dl/linux/amd64/dgo-core", true},
		{"different host", "https://cdn.evil.example/dgo-core", false},
		{"plain http, same host", "http://digital-office.co.il/dl/linux/amd64/dgo-core", false},
	}
	for _, c := range cases {
		err := sameHTTPSHost(man, c.payload)
		if (err == nil) != c.ok {
			t.Errorf("%s: sameHTTPSHost err=%v, want accepted=%v", c.name, err, c.ok)
		}
	}
}

func TestDownloadComputesPayloadSHA(t *testing.T) {
	// The payload's integrity check is the whole second half of the trust model: the manifest is
	// signature-verified, then the downloaded bytes must hash to the sha256 the manifest names
	// (run() rejects and removes a mismatch). This asserts download() reports the true sha of what it
	// wrote, so a tampered payload — whose bytes hash to something else — cannot pass that check.
	payload := []byte("pretend DGO core binary bytes, any length")
	sum := sha256.Sum256(payload)
	want := hex.EncodeToString(sum[:])

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(payload)
	}))
	defer ts.Close()

	dst := filepath.Join(t.TempDir(), "dgo-core")
	got, err := download(ts.URL, dst)
	if err != nil {
		t.Fatalf("download: %v", err)
	}
	if got != want {
		t.Errorf("download reported sha %s, want %s", got, want)
	}
	wrote, err := os.ReadFile(dst)
	if err != nil {
		t.Fatalf("reading written payload: %v", err)
	}
	if !bytes.Equal(wrote, payload) {
		t.Error("the bytes written to disk differ from the bytes served")
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
	}
	for _, c := range cases {
		if got := semverLess(c.a, c.b); got != c.less {
			t.Errorf("semverLess(%q, %q) = %v, want %v", c.a, c.b, got, c.less)
		}
	}
}

func TestFetchManifestRefusesNonHTTPS(t *testing.T) {
	// The scheme is checked before any network call, so no server is needed.
	if _, err := fetchManifest(http.DefaultClient, "http://digital-office.co.il/manifest.json"); err == nil {
		t.Fatal("a non-https manifest URL must be refused before fetching")
	}
}

func TestFetchManifestParsesGoodAndRefusesBad(t *testing.T) {
	const good = `{"version":"1.2.0","payload_url":"https://h/p","sha256":"abc","sig":"c2ln"}`
	cases := []struct {
		name   string
		status int
		body   string
		ok     bool
	}{
		{"good", 200, good, true},
		{"http error status", 404, good, false},
		{"missing required field", 200, `{"version":"1.2.0","payload_url":"https://h/p"}`, false},
		{"malformed json", 200, `{not valid json`, false},
	}
	for _, c := range cases {
		ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(c.status)
			io.WriteString(w, c.body)
		}))
		m, err := fetchManifest(ts.Client(), ts.URL+"/manifest.json")
		ts.Close()
		if (err == nil) != c.ok {
			t.Errorf("%s: err=%v, want accepted=%v", c.name, err, c.ok)
			continue
		}
		if c.ok && (m.Version != "1.2.0" || m.PayloadURL != "https://h/p") {
			t.Errorf("%s: parsed manifest is wrong: %+v", c.name, m)
		}
	}
}

// TestRelsignSignatureVerifiesInGo pins the release path to this binary: packaging/build-binaries.sh
// signs every manifest with packaging/relsign over signedMessage()'s bytes, and this stub verifies
// with its baked-in public key. The two programs each carry a copy of that one message line; this
// test is what keeps them honest — a key, a public half and a signature made by relsign must verify
// here. Skipped where `go` is not on PATH (the Go-only tests above still cover the stub's side).
func TestRelsignSignatureVerifiesInGo(t *testing.T) {
	if _, err := exec.LookPath("go"); err != nil {
		t.Skip("go not on PATH")
	}
	relsign := func(args ...string) string {
		cmd := exec.Command("go", append([]string{"run", "."}, args...)...)
		cmd.Dir = filepath.Join("..", "relsign")
		out, err := cmd.Output()
		if err != nil {
			t.Fatalf("relsign %v: %v", args, err)
		}
		return strings.TrimSpace(string(out))
	}
	key := filepath.Join(t.TempDir(), "release-key.pem")
	relsign("keygen", key)
	pubRaw, err := base64.StdEncoding.DecodeString(relsign("pubkey", key))
	if err != nil || len(pubRaw) != ed25519.PublicKeySize {
		t.Fatalf("relsign pubkey must print the base64 of 32 raw bytes")
	}
	sum := sha256.Sum256([]byte("pretend DGO core payload bytes"))
	m := manifest{Version: "1.4.0", PayloadURL: "https://digital-office.co.il/dl/linux/amd64/dgo-core", SHA256: hex.EncodeToString(sum[:])}
	m.SigB64 = relsign("sign", key, m.Version, m.PayloadURL, m.SHA256)
	if !verifies(ed25519.PublicKey(pubRaw), m) {
		t.Fatal("a relsign signature over signedMessage() must verify in the stub — the release signer and the stub disagree on the message")
	}
	m.Version = "9.9.9"
	if verifies(ed25519.PublicKey(pubRaw), m) {
		t.Fatal("a tampered manifest must not verify against relsign's signature")
	}
}

func TestFetchManifestCapsBodySize(t *testing.T) {
	// A body past the 1 MiB LimitReader is truncated mid-JSON, so it cannot parse — a hostile
	// endpoint cannot stream an unbounded manifest into the installer's memory.
	big := `{"version":"1.0.0","payload_url":"https://h/p","sha256":"` + strings.Repeat("a", 2<<20) + `","sig":"x"}`
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, big)
	}))
	defer ts.Close()
	if _, err := fetchManifest(ts.Client(), ts.URL+"/manifest.json"); err == nil {
		t.Fatal("an oversized manifest body must not parse (the LimitReader truncates it)")
	}
}

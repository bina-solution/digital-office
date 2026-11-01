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
	"strings"
	"testing"
)

func sha() string { s := sha256.Sum256([]byte("pretend DGO core")); return hex.EncodeToString(s[:]) }

const url = "https://digital-office.co.il/dl/linux/amd64/dgo-core"

// mint runs keygen the way the release script does and returns the key path.
func mint(t *testing.T) string {
	t.Helper()
	key := filepath.Join(t.TempDir(), "release-key.pem")
	if err := run([]string{"keygen", key}, &bytes.Buffer{}); err != nil {
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

func TestSignedMessageIsTheInstallersFormat(t *testing.T) {
	m := manifest{Version: "1.2.0", PayloadURL: "https://h/p", SHA256: "ABCDEF"}
	if got := string(m.signedMessage()); got != "1.2.0\nhttps://h/p\nabcdef" {
		t.Fatalf("signedMessage() = %q — must equal packaging/installer/main.go's", got)
	}
}

func TestKeygenPubkeyManifestVerify(t *testing.T) {
	key := mint(t)
	var pub bytes.Buffer
	if err := run([]string{"pubkey", key}, &pub); err != nil {
		t.Fatalf("pubkey: %v", err)
	}
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(pub.String()))
	if err != nil || len(raw) != ed25519.PublicKeySize {
		t.Fatalf("pubkey must print the base64 of 32 raw bytes, got %q", pub.String())
	}
	var out bytes.Buffer
	if err := run([]string{"manifest", key, "1.4.0", url, sha()}, &out); err != nil {
		t.Fatalf("manifest: %v", err)
	}
	var m manifest
	if err := json.Unmarshal(out.Bytes(), &m); err != nil {
		t.Fatalf("manifest output is not JSON: %v: %s", err, out.String())
	}
	if m.Version != "1.4.0" || m.PayloadURL != url || m.SHA256 != sha() || m.SigB64 == "" {
		t.Fatalf("manifest fields wrong: %+v", m)
	}
	mf := filepath.Join(t.TempDir(), "manifest.json")
	if err := os.WriteFile(mf, out.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	// verify with the private key (derived public), with the base64 the stub bakes in, and in Go directly
	for _, who := range []string{key, strings.TrimSpace(pub.String())} {
		if err := run([]string{"verify", who, mf}, &bytes.Buffer{}); err != nil {
			t.Errorf("verify with %q: %v", who, err)
		}
	}
	sig, _ := base64.StdEncoding.DecodeString(m.SigB64)
	if !ed25519.Verify(ed25519.PublicKey(raw), m.signedMessage(), sig) {
		t.Fatal("crypto/ed25519 must verify what relsign signed — the installer uses exactly this call")
	}
}

func TestTamperedManifestFailsVerify(t *testing.T) {
	key := mint(t)
	var out bytes.Buffer
	if err := run([]string{"manifest", key, "1.4.0", url, sha()}, &out); err != nil {
		t.Fatal(err)
	}
	for _, mut := range []struct{ name, from, to string }{
		{"version", `"version":"1.4.0"`, `"version":"9.9.9"`},
		{"payload_url", "digital-office.co.il", "cdn.evil.example"},
		{"sha256", sha()[:4], "0000"},
	} {
		mf := filepath.Join(t.TempDir(), "manifest.json")
		tampered := strings.Replace(out.String(), mut.from, mut.to, 1)
		if tampered == out.String() {
			t.Fatalf("%s: the mutation did not apply", mut.name)
		}
		if err := os.WriteFile(mf, []byte(tampered), 0o644); err != nil {
			t.Fatal(err)
		}
		if err := run([]string{"verify", key, mf}, &bytes.Buffer{}); err == nil {
			t.Errorf("a manifest with a tampered %s must not verify", mut.name)
		}
	}
}

func TestKeygenRefusesToOverwrite(t *testing.T) {
	key := mint(t)
	if err := run([]string{"keygen", key}, &bytes.Buffer{}); err == nil {
		t.Fatal("keygen over an existing file must refuse — a release key is not something to replace by accident")
	}
}

func TestManifestRefusesWhatTheInstallerWouldRefuse(t *testing.T) {
	key := mint(t)
	bad := [][]string{
		{"manifest", key, "v1.4.0", url, sha()},                  // leading v
		{"manifest", key, "", url, sha()},                        // empty version
		{"manifest", key, "1.4.0", "http://h/p", sha()},          // plain http
		{"manifest", key, "1.4.0", url, "abc"},                   // not a sha256
		{"manifest", key, "1.4.0", url, strings.Repeat("g", 64)}, // not hex
	}
	for _, args := range bad {
		if err := run(args, &bytes.Buffer{}); err == nil {
			t.Errorf("%v must be refused", args[2:])
		}
	}
}

func TestWrongKeyAndGarbageArePublicKeyErrors(t *testing.T) {
	key := mint(t)
	other := mint(t)
	var out bytes.Buffer
	if err := run([]string{"manifest", key, "1.4.0", url, sha()}, &out); err != nil {
		t.Fatal(err)
	}
	mf := filepath.Join(t.TempDir(), "manifest.json")
	if err := os.WriteFile(mf, out.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := run([]string{"verify", other, mf}, &bytes.Buffer{}); err == nil {
		t.Error("a manifest must not verify against a key other than the one that signed it")
	}
	if err := run([]string{"verify", "not-a-key-not-base64!!", mf}, &bytes.Buffer{}); err == nil {
		t.Error("garbage in place of a public key must be an error, not a pass")
	}
}

func isWindows() bool { return os.PathSeparator == '\\' }

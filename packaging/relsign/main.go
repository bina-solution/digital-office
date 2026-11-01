// Command relsign is the release signer for DGO's download manifests — the private half of what
// packaging/installer verifies. The installer bakes in an Ed25519 PUBLIC key and refuses any manifest
// that key did not sign; this is the tool that signs them, and the only place the private key is
// ever read. It is stdlib-only (crypto/ed25519, crypto/x509 for the PEM) so the release build needs
// nothing but Go: the first attempt signed with openssl and died on Git for Windows' OpenSSL 1.1.1,
// whose pkeyutl has no -rawin — a version trap this tool exists to remove.
//
// The signed bytes are EXACTLY what the installer's manifest.signedMessage() builds:
// "version\npayload_url\nsha256" with the sha lower-cased and no trailing newline — a stable byte
// string, not JSON, so re-encoding or re-ordering the manifest cannot change what was signed. The two
// copies of that one line (here and in packaging/installer/main.go) are kept honest by the installer's
// TestRelsignSignatureVerifiesInGo, which signs with this program and verifies with the installer.
//
// Keys are PKCS#8 PEM ("PRIVATE KEY"), the format `openssl genpkey -algorithm ed25519` writes, so a
// key made either way works here.
//
//	relsign keygen   <key.pem>                             a new Ed25519 private key (0600; never overwrites)
//	relsign pubkey   <key.pem>                             the 32 raw public bytes, base64 — what the stub bakes in
//	relsign sign     <key.pem> <version> <payload_url> <sha256>   base64 signature over signedMessage()
//	relsign manifest <key.pem> <version> <payload_url> <sha256>   the signed manifest as one JSON line
//	relsign verify   <key.pem|pub.pem|pub-base64> <manifest.json> exit 0 if it verifies, 1 if not
package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
)

const usage = `usage:
  relsign keygen   <key.pem>
  relsign pubkey   <key.pem>
  relsign sign     <key.pem> <version> <payload_url> <sha256>
  relsign manifest <key.pem> <version> <payload_url> <sha256>
  relsign verify   <key.pem|pub.pem|pub-base64> <manifest.json>`

// manifest mirrors packaging/installer/main.go — the JSON the website serves per OS/arch.
type manifest struct {
	Version    string `json:"version"`
	PayloadURL string `json:"payload_url"`
	SHA256     string `json:"sha256"`
	SigB64     string `json:"sig"`
}

// signedMessage must stay byte-identical to the installer's.
func (m manifest) signedMessage() []byte {
	return []byte(m.Version + "\n" + m.PayloadURL + "\n" + strings.ToLower(m.SHA256))
}

func main() {
	if err := run(os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "relsign: "+err.Error())
		os.Exit(1)
	}
}

func run(args []string, out io.Writer) error {
	if len(args) == 0 {
		return errors.New(usage)
	}
	switch args[0] {
	case "keygen":
		if len(args) != 2 {
			return errors.New(usage)
		}
		return keygen(args[1])
	case "pubkey":
		if len(args) != 2 {
			return errors.New(usage)
		}
		priv, err := loadPrivate(args[1])
		if err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, base64.StdEncoding.EncodeToString(priv.Public().(ed25519.PublicKey)))
		return err
	case "sign", "manifest":
		if len(args) != 5 {
			return errors.New(usage)
		}
		priv, err := loadPrivate(args[1])
		if err != nil {
			return err
		}
		m, err := newManifest(args[2], args[3], args[4])
		if err != nil {
			return err
		}
		m.SigB64 = base64.StdEncoding.EncodeToString(ed25519.Sign(priv, m.signedMessage()))
		if args[0] == "sign" {
			_, err = fmt.Fprintln(out, m.SigB64)
			return err
		}
		enc, err := json.Marshal(m)
		if err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, string(enc))
		return err
	case "verify":
		if len(args) != 3 {
			return errors.New(usage)
		}
		pub, err := loadPublic(args[1])
		if err != nil {
			return err
		}
		raw, err := os.ReadFile(args[2])
		if err != nil {
			return err
		}
		var m manifest
		if err := json.Unmarshal(raw, &m); err != nil {
			return fmt.Errorf("%s: not a manifest: %w", args[2], err)
		}
		if m.Version == "" || m.PayloadURL == "" || m.SHA256 == "" || m.SigB64 == "" {
			return fmt.Errorf("%s: a required field is empty (version/payload_url/sha256/sig)", args[2])
		}
		sig, err := base64.StdEncoding.DecodeString(strings.TrimSpace(m.SigB64))
		if err != nil || !ed25519.Verify(pub, m.signedMessage(), sig) {
			return fmt.Errorf("%s: signature does NOT verify", args[2])
		}
		_, err = fmt.Fprintf(out, "%s: verified (version %s)\n", args[2], m.Version)
		return err
	default:
		return fmt.Errorf("unknown command %q\n%s", args[0], usage)
	}
}

// newManifest refuses the inputs the installer would refuse, so a bad release fails here, not there.
func newManifest(version, payloadURL, sha string) (manifest, error) {
	sha = strings.ToLower(strings.TrimSpace(sha))
	if len(sha) != 64 || strings.Trim(sha, "0123456789abcdef") != "" {
		return manifest{}, fmt.Errorf("sha256 must be 64 hex characters, got %q", sha)
	}
	if !strings.HasPrefix(payloadURL, "https://") {
		return manifest{}, fmt.Errorf("payload_url must be https, got %q", payloadURL)
	}
	if version == "" || strings.HasPrefix(version, "v") {
		return manifest{}, fmt.Errorf("version must be non-empty and without a leading v, got %q", version)
	}
	return manifest{Version: version, PayloadURL: payloadURL, SHA256: sha}, nil
}

func keygen(path string) error {
	if _, err := os.Stat(path); err == nil {
		return fmt.Errorf("%s exists — refusing to overwrite a release key", path)
	}
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return err
	}
	der, err := x509.MarshalPKCS8PrivateKey(priv)
	if err != nil {
		return err
	}
	return os.WriteFile(path, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), 0o600)
}

func loadPrivate(path string) (ed25519.PrivateKey, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	block, _ := pem.Decode(raw)
	if block == nil || block.Type != "PRIVATE KEY" {
		return nil, fmt.Errorf("%s: not a PKCS#8 PEM private key", path)
	}
	k, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	priv, ok := k.(ed25519.PrivateKey)
	if !ok {
		return nil, fmt.Errorf("%s: not an Ed25519 key", path)
	}
	return priv, nil
}

// loadPublic accepts the private key (its public half is derived), a PEM public key, or the base64
// the stub bakes in — so a manifest can be checked with exactly what the installer holds.
func loadPublic(arg string) (ed25519.PublicKey, error) {
	if raw, err := os.ReadFile(arg); err == nil {
		block, _ := pem.Decode(raw)
		if block == nil {
			return nil, fmt.Errorf("%s: not a PEM file", arg)
		}
		switch block.Type {
		case "PRIVATE KEY":
			priv, err := loadPrivate(arg)
			if err != nil {
				return nil, err
			}
			return priv.Public().(ed25519.PublicKey), nil
		case "PUBLIC KEY":
			k, err := x509.ParsePKIXPublicKey(block.Bytes)
			if err != nil {
				return nil, fmt.Errorf("%s: %w", arg, err)
			}
			pub, ok := k.(ed25519.PublicKey)
			if !ok {
				return nil, fmt.Errorf("%s: not an Ed25519 public key", arg)
			}
			return pub, nil
		}
		return nil, fmt.Errorf("%s: PEM type %q is neither PRIVATE KEY nor PUBLIC KEY", arg, block.Type)
	}
	b, err := base64.StdEncoding.DecodeString(strings.TrimSpace(arg))
	if err != nil || len(b) != ed25519.PublicKeySize {
		return nil, errors.New("public key must be a key file or the base64 of 32 raw Ed25519 bytes")
	}
	return ed25519.PublicKey(b), nil
}

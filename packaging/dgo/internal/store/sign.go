package store

// The store's trust is the office's one chain (packaging/trust): a root signs keys.json for this
// store's site, a key that list names for dgo-app-index signs index.sig.json — the index document,
// which pins index.json by version, sha256 and size — and index.json pins every artifact by its sha256.
// The envelope, the signed bytes, keys.json's rules, the site and this machine's floor are that
// package's, the same code the installer stub verifies its core with; this file only finds the files.

import (
	"bytes"
	"cmp"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

// The two DER shapes an Ed25519 key has (RFC 8410), as fixed prefixes: what `relsign keygen` and
// `openssl genpkey -algorithm ed25519` write, and their public halves. Parsed by prefix because
// crypto/x509 would pull the whole certificate stack (net included) into a binary that needs 48
// bytes of it; anything else — another algorithm, a v2 key with its public half — is refused.
var (
	pkcs8Ed25519 = []byte{0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20}
	spkiEd25519  = []byte{0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00}
)

// loadPrivateKey reads the signing key: PKCS#8 PEM, as relsign keeps it.
func loadPrivateKey(path string) (ed25519.PrivateKey, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	k, err := parsePrivateKey(raw)
	if err != nil {
		return nil, fmt.Errorf("%s: %v", path, err)
	}
	return k, nil
}

func parsePrivateKey(raw []byte) (ed25519.PrivateKey, error) {
	b, _ := pem.Decode(raw)
	if b == nil || b.Type != "PRIVATE KEY" || len(b.Bytes) != len(pkcs8Ed25519)+ed25519.SeedSize || !bytes.HasPrefix(b.Bytes, pkcs8Ed25519) {
		return nil, errors.New("not an Ed25519 PKCS#8 PEM private key (what `relsign keygen` writes)")
	}
	return ed25519.NewKeyFromSeed(b.Bytes[len(pkcs8Ed25519):]), nil
}

// readRoots reads --root: roots in the form of roots.txt — the base64 `relsign pubkey` prints, one key
// or several, '#' comments — read by the stub's own reader, or one PEM PUBLIC KEY. A private key is
// refused: a root is the half you hand out.
func readRoots(path string) ([]trust.Signer, error) {
	if path == "" {
		return nil, errors.New("a verified index needs its root: --root <public-key-file> (what `relsign pubkey` prints)")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	text := string(raw)
	if b, _ := pem.Decode(raw); b != nil {
		switch {
		case b.Type == "PUBLIC KEY" && len(b.Bytes) == len(spkiEd25519)+ed25519.PublicKeySize && bytes.HasPrefix(b.Bytes, spkiEd25519):
			text = base64.StdEncoding.EncodeToString(b.Bytes[len(spkiEd25519):])
		case strings.Contains(b.Type, "PRIVATE"):
			return nil, fmt.Errorf("%s: the root is a PRIVATE key — pass its public half (`relsign pubkey <key.pem>`)", path)
		default:
			return nil, fmt.Errorf("%s: PEM %q is not an Ed25519 PUBLIC KEY", path, b.Type)
		}
	}
	roots, err := trust.ParseRoots(text)
	if err == nil && len(roots) == 0 {
		err = errors.New("it names no root key")
	}
	if err != nil {
		return nil, fmt.Errorf("%s: %v", path, err)
	}
	return roots, nil
}

// Read limits: what a mirror serves is untrusted until verified, so no file is read past what a real
// one could be (the index is ~70 KB for 28 apps; this is room for thousands; the stub caps its
// documents at the same 64 KiB).
const (
	maxSig   = 64 << 10 // index.sig.json, keys.json
	maxIndex = 32 << 20
)

// verified is an index whose key list, signature, site, floor, hash, format and version all checked out.
type verified struct {
	dir   string
	doc   trust.IndexDoc // what the signature vouches for — index.json's sha256 among it
	by    string         // the keyid of the key that signed it
	keys  int64          // the version of the key list that names that key
	index indexDoc
}

// url is the index's address, as a lock records it: index.json under the signed site.
func (v *verified) url() string { return strings.TrimSuffix(v.doc.Site, "/") + "/" + indexName }

// loadVerified is the only way this package reads an index: nothing in index.json is parsed before
// the chain has held — a root signed keys.json for this store's site (baseURL: the channel, so a
// staging index is not a release one, whoever signed both), a key it names for the index signed
// index.sig.json for the same site inside its window, and index.json is the bytes that document pins.
// The index is then held to this machine's floor for the site: never an older one, never another
// one under a version it accepted.
func loadVerified(dir, rootFile, baseURL string) (*verified, error) {
	roots, err := readRoots(rootFile)
	if err != nil {
		return nil, err
	}
	site := strings.TrimRight(cmp.Or(baseURL, defaultBaseURL), "/")
	if !strings.HasPrefix(site, "https://") {
		return nil, fmt.Errorf("--base-url %q must be https", baseURL)
	}
	sraw, err := readCapped(filepath.Join(dir, sigName), maxSig)
	if errors.Is(err, fs.ErrNotExist) {
		if _, derr := os.Stat(filepath.Join(dir, draftName)); derr == nil {
			return nil, fmt.Errorf("%s holds only the UNSIGNED draft %s — sign it with a key keys.json lists for %s first", dir, draftName, trust.IndexType)
		}
		return nil, fmt.Errorf("no signature at %s — an unsigned index is refused", filepath.Join(dir, sigName))
	}
	if err != nil {
		return nil, err
	}
	kraw, err := readCapped(filepath.Join(dir, keysName), maxSig)
	if err != nil {
		return nil, fmt.Errorf("no key list for the signature: %w", err)
	}
	id := trust.RootsID(roots)
	state, err := statePath(site, id)
	if err != nil {
		return nil, err
	}
	seen, err := trust.LoadSeen(state, site, id)
	if err != nil {
		return nil, err
	}
	c := trust.Checker{Roots: roots, Site: site, Type: trust.IndexType, Now: time.Now(), Seen: seen}
	kl, err := c.VerifyKeys(kraw)
	if err != nil {
		return nil, err
	}
	// Remembered at once, as the stub remembers it: a key list that retired a key sticks on this
	// machine even when this index goes no further.
	c.Seen = kl.Settle(c.Seen)
	c.Seen.Keys, c.Seen.KeysSum = kl.Version, kl.Sum
	if err := trust.SaveSeen(state, stateHeader, site, id, c.Seen, kl.Stands); err != nil {
		return nil, fmt.Errorf("remembering the accepted key list: %w", err)
	}
	doc, by, err := c.VerifyIndex(sraw, kl)
	if err != nil {
		return nil, err
	}
	body, err := readCapped(filepath.Join(dir, indexName), maxIndex)
	if err != nil {
		return nil, err
	}
	digest := sha256.Sum256(body)
	if sum := hex.EncodeToString(digest[:]); sum != doc.SHA256 || int64(len(body)) != doc.Size {
		return nil, fmt.Errorf("%s sha256 %s… (%d bytes) != the signed %s… (%d bytes) — the index was altered", indexName, sum[:16], len(body),
			short(doc.SHA256), doc.Size)
	}
	var ix indexDoc
	if err := json.Unmarshal(body, &ix); err != nil {
		return nil, fmt.Errorf("%s: %v", indexName, err)
	}
	switch {
	case ix.Format != indexFormat:
		return nil, fmt.Errorf("%s: unsupported format %q (expected %s)", indexName, ix.Format, indexFormat)
	case ix.Version != doc.Version:
		return nil, fmt.Errorf("%s says version %q, its signature %q — refused", indexName, ix.Version, doc.Version)
	}
	c.Seen.Manifest, c.Seen.ManifestBy, c.Seen.Beside, c.Seen.ManifestSum = doc.Version, by, kl.Besides(by), doc.SHA256
	if err := trust.SaveSeen(state, stateHeader, site, id, c.Seen, kl.Stands); err != nil {
		return nil, fmt.Errorf("remembering the accepted index: %w", err)
	}
	return &verified{dir: dir, doc: doc, by: by, keys: kl.Version, index: ix}, nil
}

// readCapped reads a file of at most limit bytes, and refuses a larger one without reading it.
func readCapped(path string, limit int64) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err == nil && int64(len(b)) > limit {
		err = fmt.Errorf("%s is larger than %d bytes — no real one is; refused", path, limit)
	}
	return b, err
}

// ── the trust memory: no going back ────────────────────────────────────────────────────────────

// stateHeader opens each of the store's state files; trust.SaveSeen writes the line under it.
const stateHeader = "# dgo index: for one store site and set of roots, the newest keys.json (version, sha256) and index\n" +
	"# (version, the key that signed it and the keys listed beside it, its sha256) this machine accepted;\n" +
	"# - is none. Removing this file forgets them — it weakens rollback protection, it never blocks an install.\n"

// statePath is the file that keeps this machine's floor for one store site under one set of roots —
// trust.Seen, the stub's own record — a file of its own under DGO_HOME, so two channels never share one.
func statePath(site, rootsID string) (string, error) {
	h, err := home()
	if err != nil {
		return "", err
	}
	k := sha256.Sum256([]byte(site + "\n" + rootsID))
	return filepath.Join(h, "index-trust", hex.EncodeToString(k[:8])), nil
}

// home is where dgo keeps what it remembers between runs: $DGO_HOME, else ~/.dgo — the installer's
// directory.
func home() (string, error) {
	if h := os.Getenv("DGO_HOME"); h != "" {
		return h, nil
	}
	u, err := os.UserHomeDir()
	if err != nil {
		return "", errors.New("no DGO_HOME and no home directory: nowhere to remember the newest index this root has signed")
	}
	return filepath.Join(u, ".dgo"), nil
}

// short is the first 16 characters of a hash, as catalog.py prints one.
func short(s string) string {
	if len(s) > 16 {
		return s[:16]
	}
	return s
}

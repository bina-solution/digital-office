// Command relsign is the release signer for DGO's downloads — the private half of what
// packaging/installer verifies, and the only program that ever reads a private key. It is stdlib-only
// (crypto/ed25519, crypto/x509 for the PEM) so a release needs nothing but Go: the first attempt signed
// with openssl and died on Git for Windows' OpenSSL 1.1.1, whose pkeyutl has no -rawin.
//
// It makes the signed documents of the office's trust chain in the one encoding packaging/trust
// defines — the envelope, the documents' shapes, the signed bytes (PAE) and the key ids are that
// package's, so what relsign signs is what every verifier reads:
//
//	keys.json      type dgo-keys: for one site, the online signing keys, each with a validity window
//	               and the document types it may sign, and the site's core_floor if it states one —
//	               signed by an offline ROOT
//	manifest.json  type dgo-core-manifest: version, expires, min_bootstrapper, target, payload
//	               url+sha256+size — signed by a key keys.json lists for that type (the "delegated" key
//	               a release job holds as DGO_RELEASE_KEY)
//	index.sig.json type dgo-app-index: the app store's index.json, pinned by its version, sha256 and size
//	               for the store's site — signed by a key listed for that type; `dgo index build --key`
//	               signs the same document into the same bytes
//
// Each is a DSSE envelope {payloadType, payload, signatures:[{keyid, sig}]} whose signature covers the
// WHOLE document and its type (DSSE's PAE), so a field added later is signed the day it is added and a
// signature over one kind of document never passes for another. relsign only produces; the verifiers
// are packaging/trust's — the stub's, which build-binaries.sh runs over every release tree before it
// says done (TestReleaseTree), and `dgo index verify` — so the rules live in one place.
// TestRelsignChainVerifiesInTheStub signs with this program and verifies with the stub.
//
// Keys are PKCS#8 PEM ("PRIVATE KEY"), the format `openssl genpkey -algorithm ed25519` writes, so a
// key made either way works here.
//
//	relsign keygen   <key.pem>        a new Ed25519 private key (0600; never overwrites)
//	relsign pubkey   <key.pem>        the 32 raw public bytes, base64 — a line of roots.txt, for a root
//	relsign keys     -signer ROOT.pem -site URL -version N [-previous OLD.json] [-expires 60d]
//	                 [-core-floor V] [-index-floor V] -key KEY[,FROM,UNTIL] -types TYPE[,TYPE] [-key … -types …]
//	relsign manifest -signer KEY.pem -site URL -version V -target OS/ARCH -url URL -file PAYLOAD -expires WHEN
//	                 [-min-bootstrapper V]        (-unsigned in place of -signer: a draft no stub accepts)
//	relsign index    -signer KEY.pem -site URL -version V -file index.json
//	relsign floor    <keys.json>      "version:sha256" of the list — what a release stub is built with
package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

const usage = `usage:
  relsign keygen   <key.pem>
  relsign pubkey   <key.pem>
  relsign keys     -signer ROOT.pem -site URL -version N [-previous OLD.json] [-expires 60d]
                   [-core-floor V] [-index-floor V] -key KEY[,FROM,UNTIL] -types TYPE[,TYPE] [-key ... -types ...]
  relsign manifest -signer KEY.pem | -unsigned  -site URL -version V -target OS/ARCH -url URL
                   -file PAYLOAD -expires WHEN [-min-bootstrapper V]
  relsign index    -signer KEY.pem -site URL -version V -file index.json
  relsign floor    <keys.json>
WHEN is an RFC 3339 time or a span from now (90d, 36h). KEY is a key file (private or public PEM)
or the base64 of a public key; its window defaults to a day before now until the key list expires.
TYPE is what the key before it may sign: dgo-core-manifest, dgo-app-index. -previous is the list this
one replaces: the version must rise above it — a list changed under the same version is refused by
every stub — and its -core-floor (the oldest DGO core any computer installs) carries over unless given;
a list that drops a key -previous trusted for dgo-core-manifest must give it (the newest real release).
-index-floor is the same for the store's index: carried over, and given by a list that drops a key
-previous trusted for dgo-app-index (the newest real index).`

// signable are the types a listed key may be trusted for: the installer's manifest and the app store's
// index. Never dgo-keys — a key list is signed by a root.
var signable = []string{trust.ManifestType, trust.IndexType}

func main() {
	if err := run(os.Args[1:], os.Stdout, time.Now()); err != nil {
		fmt.Fprintln(os.Stderr, "relsign: "+err.Error())
		os.Exit(1)
	}
}

func run(args []string, out io.Writer, now time.Time) error {
	if len(args) == 0 {
		return errors.New(usage)
	}
	switch args[0] {
	case "keygen", "pubkey":
		if len(args) != 2 {
			return errors.New(usage)
		}
		if args[0] == "keygen" {
			return keygen(args[1])
		}
		priv, err := loadPrivate(args[1])
		if err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, base64.StdEncoding.EncodeToString(priv.Public().(ed25519.PublicKey)))
		return err
	case "keys":
		return keys(args[1:], out, now)
	case "manifest":
		return manifest(args[1:], out, now)
	case "index":
		return index(args[1:], out)
	case "floor":
		if len(args) != 2 {
			return errors.New(usage)
		}
		doc, sum, err := readKeys(args[1])
		if err == nil {
			_, err = fmt.Fprintf(out, "%d:%s\n", doc.Version, sum)
		}
		return err
	default:
		return fmt.Errorf("unknown command %q\n%s", args[0], usage)
	}
}

// keys writes keys.json: the signing keys a root vouches for, each inside a window and only for the
// document types its -types names. It lives 60 days by default: a revoked key stays good, for a
// computer that never saw the revoking list, until the list that named it expires — so the list is
// re-signed (offline, by a root) at least that often. -core-floor and -index-floor are the root's own
// floors for the site — DGO core releases, the store's index — which a computer that remembers nothing
// holds too; a re-sign keeps the previous list's. A list that drops a key -previous trusted for one of
// those kinds must state that kind's floor, on its command line: on every computer it then takes the
// place of what that key vouched for (packaging/trust's Settle) — without it, a key kept or listed again
// could replay what it once signed.
func keys(args []string, out io.Writer, now time.Time) error {
	fs := flags("keys")
	signerPath := fs.String("signer", "", "")
	site := fs.String("site", "", "")
	version := fs.Int64("version", 0, "")
	previous := fs.String("previous", "", "")
	expiresAt := fs.String("expires", "60d", "")
	coreFloor := fs.String("core-floor", "", "")
	indexFloor := fs.String("index-floor", "", "")
	var specs []keyArg
	fs.Func("key", "", func(s string) error { specs = append(specs, keyArg{spec: s}); return nil })
	fs.Func("types", "", func(s string) error { // the flag package calls these in command-line order
		if len(specs) == 0 || specs[len(specs)-1].types != nil {
			return errors.New("-types follows the -key it scopes, once per key")
		}
		for _, t := range strings.Split(s, ",") {
			if !contains(signable, t) {
				return fmt.Errorf("%q is not a type a listed key may sign (%s; a key list is a root's alone)", t, strings.Join(signable, ", "))
			}
			specs[len(specs)-1].types = append(specs[len(specs)-1].types, t)
		}
		return nil
	})
	if err := parse(fs, args); err != nil {
		return err
	}
	if !strings.HasPrefix(*site, "https://") {
		return fmt.Errorf("-site must be the https:// download site the list is for (what stubs bake in), got %q", *site)
	}
	if *version < 1 {
		return errors.New("-version must be 1 or more, and higher than the last keys.json: a stub refuses a key list older than one it has seen")
	}
	stated := map[string]bool{} // the floors given on this command line, not carried over from -previous
	fs.Visit(func(f *flag.Flag) { stated[f.Name] = true })
	var was trust.KeysDoc
	if *previous != "" {
		var err error
		if was, _, err = readKeys(*previous); err != nil {
			return fmt.Errorf("-previous: %w", err)
		}
		if *version <= was.Version {
			return fmt.Errorf("-version %d does not rise above -previous's %d: a list changed under the same version is refused by every stub that saw the other, and the old list would stand beside it", *version, was.Version)
		}
		// a routine re-sign must not drop a floor a fresh computer relies on
		if !stated["core-floor"] {
			*coreFloor = was.CoreFloor
		}
		if !stated["index-floor"] {
			*indexFloor = was.IndexFloor
		}
	}
	// The root's floors, one per kind of document a listed key signs: the newest real one is what a list
	// that drops such a key states, and only a release version can be ordered by its reader.
	floors := []struct{ flag, typ, newest, reader, v string }{
		{"core-floor", trust.ManifestType, "the newest real release", "the installer", *coreFloor},
		{"index-floor", trust.IndexType, "the newest real index", "dgo index", *indexFloor},
	}
	for _, f := range floors {
		if f.v != "" && !trust.ValidVersion(f.v) {
			return fmt.Errorf("-%s %q is not a release version (dotted numbers, 1.4.0): %s could not order it", f.flag, f.v, f.reader)
		}
	}
	expires, err := future(*expiresAt, now, "-expires")
	if err != nil {
		return err
	}
	if len(specs) == 0 {
		return errors.New("-key: name at least one signing key")
	}
	root, err := loadPrivate(*signerPath)
	if err != nil {
		return fmt.Errorf("-signer: %w", err)
	}
	doc := trust.KeysDoc{Site: strings.TrimSuffix(*site, "/"), Version: *version, Expires: stamp(expires), CoreFloor: *coreFloor,
		IndexFloor: *indexFloor}
	// The root that signs the list is never one of its online keys: that would make it an online key.
	listed := map[string]bool{trust.KeyID(root.Public().(ed25519.PublicKey)): true}
	for _, k := range specs {
		if len(k.types) == 0 {
			return fmt.Errorf("-key %s: name what it may sign after it: -types %s", k.spec, strings.Join(signable, "|"))
		}
		pub, from, until, err := keySpec(k.spec, now, expires)
		if err != nil {
			return err
		}
		if listed[trust.KeyID(pub)] {
			return fmt.Errorf("-key %s: listed twice, or it is the -signer root itself (roots stay offline)", k.spec)
		}
		listed[trust.KeyID(pub)] = true
		doc.Keys = append(doc.Keys, trust.KeyEntry{PublicKey: base64.StdEncoding.EncodeToString(pub), Types: k.types,
			NotBefore: stamp(from), NotAfter: stamp(until)})
	}
	for _, f := range floors {
		if gone := dropped(was.Keys, doc.Keys, f.typ); gone != "" && (!stated[f.flag] || f.v == "") {
			return fmt.Errorf("this list drops key %s, which -previous trusted for %s: state -%s, %s — every computer then holds it in place of what that key vouched for (a leaked key's push included), and no key kept or listed again can bring back anything older", gone, f.typ, f.flag, f.newest)
		}
	}
	return seal(out, root, trust.KeysType, doc)
}

// dropped is a key the previous list trusted for documents of type typ and the new one does not ("" =
// none), as its base64 public key.
func dropped(was, now []trust.KeyEntry, typ string) string {
	kept := map[string]bool{}
	for _, k := range now {
		if contains(k.Types, typ) {
			kept[k.PublicKey] = true
		}
	}
	for _, k := range was {
		if contains(k.Types, typ) && !kept[k.PublicKey] {
			return k.PublicKey
		}
	}
	return ""
}

// keyArg is one -key and the -types that scope it.
type keyArg struct {
	spec  string
	types []string
}

func contains(list []string, s string) bool {
	for _, e := range list {
		if e == s {
			return true
		}
	}
	return false
}

// backdate is how long before the signing instant a key's window opens when -key names none. A list is
// re-signed at least every 60 days, and a window that opened at that instant would be refused, until it
// came, by every computer whose clock runs behind (a dual-boot clock hours off) — though the key was
// valid all along.
const backdate = 24 * time.Hour

// keySpec reads KEY[,FROM,UNTIL]; the window defaults to a day before now until the list's own expiry.
func keySpec(spec string, now, expires time.Time) (ed25519.PublicKey, time.Time, time.Time, error) {
	parts := strings.Split(spec, ",")
	if len(parts) != 1 && len(parts) != 3 {
		return nil, time.Time{}, time.Time{}, fmt.Errorf("-key %s: expected KEY or KEY,FROM,UNTIL", spec)
	}
	pub, err := loadPublic(parts[0])
	if err != nil {
		return nil, time.Time{}, time.Time{}, err
	}
	from, until := now.Add(-backdate), expires
	if len(parts) == 3 {
		if from, err = when(parts[1], now); err == nil {
			until, err = when(parts[2], now)
		}
		if err != nil {
			return nil, time.Time{}, time.Time{}, fmt.Errorf("-key %s: %w", spec, err)
		}
	}
	if !from.Before(until) || !until.After(now) {
		return nil, time.Time{}, time.Time{}, fmt.Errorf("-key %s: the window %s..%s is empty or already over", spec, stamp(from), stamp(until))
	}
	return pub, from, until, nil
}

// manifest writes one target's manifest, the payload's sha256 and size read from the file itself.
func manifest(args []string, out io.Writer, now time.Time) error {
	fs := flags("manifest")
	signerPath := fs.String("signer", "", "")
	unsigned := fs.Bool("unsigned", false, "")
	site := fs.String("site", "", "")
	version := fs.String("version", "", "")
	target := fs.String("target", "", "")
	payloadURL := fs.String("url", "", "")
	file := fs.String("file", "", "")
	expiresAt := fs.String("expires", "", "")
	minBoot := fs.String("min-bootstrapper", "0.0.0", "")
	if err := parse(fs, args); err != nil {
		return err
	}
	if (*signerPath == "") != *unsigned {
		return errors.New("name exactly one of -signer KEY.pem and -unsigned")
	}
	switch {
	case !trust.ValidVersion(*minBoot):
		return fmt.Errorf("-min-bootstrapper %q is not a release version (dotted numbers, 1.4.0)", *minBoot)
	case *unsigned && !draftVersion(*version):
		return fmt.Errorf("-version %q is not a version", *version)
	case !*unsigned && !trust.ValidVersion(*version):
		return fmt.Errorf("-version %q: a signed manifest needs a release version — dotted numbers, 1.4.0 — which the installer can order; a pre-release would sort above its release", *version)
	}
	goos, goarch, ok := strings.Cut(*target, "/")
	if !ok || goos == "" || goarch == "" || strings.Contains(goarch, "/") {
		return fmt.Errorf("-target must be OS/ARCH, got %q", *target)
	}
	siteURL := strings.TrimSuffix(*site, "/")
	if !strings.HasPrefix(siteURL, "https://") {
		return fmt.Errorf("-site must be the https:// download site the manifest is for, got %q", *site)
	}
	if !strings.HasPrefix(*payloadURL, siteURL+"/") {
		return fmt.Errorf("-url must be a file under -site %s, got %q", siteURL, *payloadURL)
	}
	expires, err := future(*expiresAt, now, "-expires")
	if err != nil {
		return err
	}
	sum, size, err := digest(*file)
	if err != nil {
		return err
	}
	doc := trust.ManifestDoc{Site: siteURL, Version: *version, Expires: stamp(expires), MinBootstrapper: *minBoot,
		Target: *target, PayloadURL: *payloadURL, SHA256: sum, Size: size}
	if *unsigned {
		body, err := json.Marshal(doc)
		if err == nil {
			_, err = fmt.Fprintln(out, string(body))
		}
		return err
	}
	priv, err := loadPrivate(*signerPath)
	if err != nil {
		return fmt.Errorf("-signer: %w", err)
	}
	return seal(out, priv, trust.ManifestType, doc)
}

// readKeys reads a keys.json relsign wrote: the list, and the sha256 of its payload — the list itself,
// as a stub hashes it. It reads; it does not verify (that is the installer's code alone).
func readKeys(path string) (trust.KeysDoc, string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return trust.KeysDoc{}, "", err
	}
	var env trust.Envelope
	if err := json.Unmarshal(raw, &env); err != nil || env.PayloadType != trust.KeysType {
		return trust.KeysDoc{}, "", fmt.Errorf("%s is not a %s envelope", path, trust.KeysType)
	}
	body, err := base64.StdEncoding.DecodeString(env.Payload)
	var doc trust.KeysDoc
	if err == nil {
		err = json.Unmarshal(body, &doc)
	}
	if err != nil || doc.Version < 1 {
		return trust.KeysDoc{}, "", fmt.Errorf("%s: its payload is not a key list", path)
	}
	s := sha256.Sum256(body)
	return doc, hex.EncodeToString(s[:]), nil
}

// index writes the app store's index document: index.json pinned by its version, sha256 and size, for
// the store's site — what `dgo index build --key` signs, into the same bytes. The version must be the
// one index.json names and a release version, which every computer's floor can order: one the store's
// verifier would refuse fails here, at signing, not on a user's computer.
func index(args []string, out io.Writer) error {
	fs := flags("index")
	signerPath := fs.String("signer", "", "")
	site := fs.String("site", "", "")
	version := fs.String("version", "", "")
	file := fs.String("file", "", "")
	if err := parse(fs, args); err != nil {
		return err
	}
	siteURL := strings.TrimSuffix(*site, "/")
	if !strings.HasPrefix(siteURL, "https://") {
		return fmt.Errorf("-site must be the https:// base URL the store's index is served from, got %q", *site)
	}
	if !trust.ValidVersion(*version) {
		return fmt.Errorf("-version %q: a signed index needs a release version — dotted numbers, 1.4.0 — which every computer's floor can order", *version)
	}
	raw, err := os.ReadFile(*file)
	if err != nil {
		return fmt.Errorf("-file: %w", err)
	}
	var named struct {
		Version string `json:"version"`
	}
	if err := json.Unmarshal(raw, &named); err != nil || named.Version != *version {
		return fmt.Errorf("-file %s names version %q, not -version %s: an index and its signature name one version", *file, named.Version, *version)
	}
	priv, err := loadPrivate(*signerPath)
	if err != nil {
		return fmt.Errorf("-signer: %w", err)
	}
	sum := sha256.Sum256(raw)
	return seal(out, priv, trust.IndexType, trust.IndexDoc{Site: siteURL, Version: *version, SHA256: hex.EncodeToString(sum[:]),
		Size: int64(len(raw))})
}

// seal signs the whole of doc, with its type, and writes the DSSE envelope as one JSON line.
func seal(out io.Writer, priv ed25519.PrivateKey, typ string, doc any) error {
	body, err := json.Marshal(doc)
	if err != nil {
		return err
	}
	env, err := trust.Seal(priv, typ, body)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, string(env))
	return err
}

// draftVersion is what an unsigned draft may carry: a release version or a development one such as
// 0.0.0-dev+1a2b3c4 (a digit, then letters, digits, '.', '-', '+') — a draft is never installed.
func draftVersion(v string) bool {
	if v == "" || len(v) > 64 || v[0] < '0' || v[0] > '9' {
		return false
	}
	return strings.Trim(v, "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-+") == ""
}

// when reads an instant: RFC 3339, or a span from now — "90d", "36h".
func when(s string, now time.Time) (time.Time, error) {
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t, nil
	}
	if days, ok := strings.CutSuffix(s, "d"); ok {
		if n, err := strconv.Atoi(days); err == nil && n >= 0 {
			return now.Add(time.Duration(n) * 24 * time.Hour), nil
		}
	}
	if d, err := time.ParseDuration(s); err == nil {
		return now.Add(d), nil
	}
	return time.Time{}, fmt.Errorf("%q is neither an RFC 3339 time nor a span like 90d or 36h", s)
}

func future(s string, now time.Time, name string) (time.Time, error) {
	t, err := when(s, now)
	if err == nil && !t.After(now) {
		err = fmt.Errorf("%s is not in the future", stamp(t))
	}
	if err != nil {
		return time.Time{}, fmt.Errorf("%s: %w", name, err)
	}
	return t, nil
}

// stamp writes an instant the way both documents carry it: RFC 3339, UTC, whole seconds.
func stamp(t time.Time) string { return t.UTC().Format(time.RFC3339) }

func digest(path string) (string, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", 0, fmt.Errorf("-file: %w", err)
	}
	defer f.Close()
	h := sha256.New()
	n, err := io.Copy(h, f)
	if err == nil && n == 0 {
		err = fmt.Errorf("-file %s is empty", path)
	}
	return hex.EncodeToString(h.Sum(nil)), n, err
}

func flags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	return fs
}

func parse(fs *flag.FlagSet, args []string) error {
	if err := fs.Parse(args); err != nil {
		return fmt.Errorf("%s: %v\n%s", fs.Name(), err, usage)
	}
	if fs.NArg() != 0 {
		return fmt.Errorf("%s: unexpected %q\n%s", fs.Name(), fs.Arg(0), usage)
	}
	return nil
}

// keygen writes a new key; the file is created exclusively, so an existing key is never overwritten —
// not even by one that appeared between a check and the write.
func keygen(path string) error {
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return err
	}
	der, err := x509.MarshalPKCS8PrivateKey(priv)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if errors.Is(err, os.ErrExist) {
		return fmt.Errorf("%s exists — refusing to overwrite a release key", path)
	}
	if err != nil {
		return err
	}
	_, err = f.Write(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	return err
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

// loadPublic accepts a private key (its public half is derived), a PEM public key, or the base64 a
// stub bakes in — so keys.json can list a key from whichever form the owner holds.
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
		return nil, errors.New("a public key must be a key file or the base64 of 32 raw Ed25519 bytes")
	}
	return ed25519.PublicKey(b), nil
}

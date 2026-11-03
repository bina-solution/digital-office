// Package trust is the office's one signed-document layer: why a DGO program may believe what it
// downloads — the installer stub (packaging/installer) its core, `dgo index` (packaging/dgo) the app
// store's index — and the one encoding packaging/relsign and `dgo index build` sign with (seal.go).
// Stdlib only, and no encoding/json (jsonread.go reads the documents): the stub carries this package
// inside its 4 MiB budget. TUF's rules, a DSSE envelope, Ed25519:
//
//	root keys — offline; only their PUBLIC halves are in a verifier (the stub embeds the committed roots.txt)
//	  └─ sign keys.json: for ONE site, the online signing keys, each valid inside a window and only for
//	     the document types it names; the list has a version and an expiry
//	       ├─ a key listed for "dgo-core-manifest" signs the manifest: for the same site, version,
//	       │  expires, min_bootstrapper, target, and the payload's url (under the site), sha256 and size
//	       │    └─ the payload's bytes must be exactly that size and hash to that sha256
//	       └─ a key listed for "dgo-app-index" signs the store's index document (index.go): for the
//	          same site, version, and index.json's sha256 and size
//
// Why two tiers: the key a release job holds (DGO_RELEASE_KEY) is an ONLINE key, so it must be
// replaceable without a new stub — a new keys.json drops it. The roots never leave the owner's safe,
// and there are several so that one can retire while the stubs in the world still trust another.
// Why the whole document is signed: a field added later is covered the day it is added. Why every
// signed document names its type, and the type is inside what is signed (DSSE's PAE): the office signs
// key lists, core manifests and the app store's index, and a signature over one kind must never pass
// for another (a store index once passed for a core manifest). Why both documents name their site:
// the same roots and the same release key serve more than one site (a stable /dl, a /beta, the store),
// and a mirror or a redirect must not carry one site's documents into another.
//
// The refusals TUF names, each its own rule below: an expired document (a frozen mirror), a version
// older than one this computer accepted, than the list this stub was built with, or than the oldest core
// the site's key list allows (a replay), a key list changed without a new version (a revocation that
// would not stick), a stub older than the release allows, an unknown signer, a manifest for another
// platform. And TUF's recovery (§5.3.11), without a door for a replay: once keys.json stops listing a
// key, the root's core_floor (index_floor, for the store's index) takes the place of what that key
// vouched for (Settle) — a leaked key's 999999999.0.0 gives way to the real release, whoever signs it —
// and a list that states no such floor (relsign never writes one that drops a key) leaves it binding the
// keys that were listed beside it (Binds): revoking one of two keys never reopens a rollback to what the
// other once signed.
package trust

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// The document types (an envelope's payloadType) — the office's whole vocabulary of signed documents.
// A verifier accepts each only where it expects it: the stub keys.json and core manifests, the store
// keys.json and its index.
const (
	KeysType     = "dgo-keys"          // keys.json: signed by a root, never by a listed key
	ManifestType = "dgo-core-manifest" // <os>/<arch>/manifest.json: signed by a key listed for it
	IndexType    = "dgo-app-index"     // the app store's index.sig.json: signed by a key listed for it
)

// strict64 is the one base64 the documents use, read strictly: a byte that is not canonical base64 is a
// refusal, not something to skip.
var strict64 = base64.StdEncoding.Strict()

// PAE is DSSE's pre-authentication encoding (github.com/secure-systems-lab/dsse, protocol.md): the
// exact bytes a signature covers — the payload type and the whole payload, each length-prefixed.
func PAE(typ string, body []byte) []byte {
	return []byte("DSSEv1 " + strconv.Itoa(len(typ)) + " " + typ + " " + strconv.Itoa(len(body)) + " " + string(body))
}

// KeyID names a public key in an envelope: the first 8 bytes of its SHA-256, in hex (minisign's size).
func KeyID(pub ed25519.PublicKey) string {
	s := sha256.Sum256(pub)
	return hex.EncodeToString(s[:8])
}

func sha256hex(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

// Signer is a key trusted to sign the document types it names: a root (key lists, no window), or a
// signing key from keys.json, valid from `from` until `until`.
type Signer struct {
	pub         ed25519.PublicKey
	types       []string  // the payload types it may sign
	from, until time.Time // zero = unbounded
}

func (s Signer) may(typ string) bool {
	for _, t := range s.types {
		if t == typ {
			return true
		}
	}
	return false
}

// ParseRoots reads roots in the form of roots.txt, which the stub is built with: base64 Ed25519 public
// keys, one per line or separated by commas or spaces; '#' starts a comment. A refusal says what is
// wrong; the caller says where the roots came from (the stub's are "the built-in" ones).
func ParseRoots(s string) ([]Signer, error) {
	var roots []Signer
	for _, line := range strings.Split(s, "\n") {
		line, _, _ = strings.Cut(line, "#")
		for _, f := range strings.FieldsFunc(line, func(r rune) bool { return r == ',' || r == ' ' || r == '\t' || r == '\r' }) {
			b, err := strict64.DecodeString(f)
			if err != nil || len(b) != ed25519.PublicKeySize {
				return nil, fmt.Errorf("root key %q is not a base64 Ed25519 public key", f)
			}
			roots = append(roots, Signer{pub: b, types: []string{KeysType}})
		}
	}
	return roots, nil
}

// RootsID names a set of roots: the first 8 bytes of the SHA-256 of their sorted keys. This computer's
// memory is kept per site AND per RootsID, so stubs of a new generation (new roots, after one leaked)
// never inherit a version the leaked root pushed the old memory to.
func RootsID(roots []Signer) string {
	keys := make([]string, len(roots))
	for i, r := range roots {
		keys[i] = string(r.pub)
	}
	sort.Strings(keys)
	return KeyID([]byte(strings.Join(keys, "")))
}

// ClockSkew is how far behind this computer's clock may run and still accept a key from the start of
// its window: a key list re-signed this morning must not be refused by a clock a few minutes slow. Only
// a window's start gets it — an end or an expiry gets no grace, or a frozen mirror would gain it too.
// (relsign also opens a key's window a day before the list is signed.)
const ClockSkew = 10 * time.Minute

// Open verifies a DSSE envelope and returns its payload — the only part of it that is trusted —
// and the keyid of the signer that vouched for it. Its payloadType must be typ, and one of its
// signatures must be by one of signers, over PAE(typ, payload), by a signer trusted for typ, at a time
// inside that signer's window.
func Open(raw []byte, typ string, signers []Signer, now time.Time) ([]byte, string, error) {
	v, err := parseJSON(raw)
	if err != nil {
		return nil, "", err
	}
	env, err := asObj(v, "the envelope")
	if err != nil {
		return nil, "", err
	}
	if t, _ := env.text("payloadType"); t != typ {
		return nil, "", fmt.Errorf("its payloadType is %q, not %q", t, typ)
	}
	p64, err := env.text("payload")
	if err != nil {
		return nil, "", err
	}
	payload, err := strict64.DecodeString(p64)
	if err != nil {
		return nil, "", errors.New("its payload is not base64")
	}
	sigs, err := env.list("signatures")
	if err != nil {
		return nil, "", err
	}
	msg := PAE(typ, payload)
	why := "it is signed by no key this installer trusts for it (unknown signer)"
	for _, s := range sigs {
		so, err := asObj(s, "a signature")
		if err != nil {
			return nil, "", err
		}
		id, _ := so.text("keyid")
		s64, _ := so.text("sig")
		sig, err := strict64.DecodeString(s64)
		if err != nil || len(sig) != ed25519.SignatureSize {
			why = "the signature of key " + id + " is not " + strconv.Itoa(ed25519.SignatureSize) + " bytes of base64"
			continue
		}
		for _, k := range signers {
			switch {
			case KeyID(k.pub) != id:
				continue
			case !ed25519.Verify(k.pub, msg, sig):
				why = "the signature of key " + id + " does not verify — forged or corrupted"
			case !k.may(typ):
				why = "key " + id + " signed it, but keys.json does not trust that key to sign " + typ + " documents"
			case !k.from.IsZero() && now.Add(ClockSkew).Before(k.from) || !k.until.IsZero() && !now.Before(k.until):
				why = fmt.Sprintf("key %s signed it, but that key is valid only from %s until %s (this computer's clock says %s)",
					id, Stamp(k.from), Stamp(k.until), Stamp(now))
			default:
				return payload, id, nil
			}
		}
	}
	return nil, "", errors.New(why)
}

// Checker is what a verifier knows before it reads a byte from the network.
type Checker struct {
	Roots  []Signer
	Site   string    // the site built in — every document names the site it was signed for
	Type   string    // what the site serves, its floor kept here: ManifestType (the stub), IndexType (the store)
	Now    time.Time // fixed when the run began: one clock for every expiry (TUF §5.1)
	Stub   string    // the stub's version, held against a core manifest's min_bootstrapper
	Target string    // GOOS/GOARCH — a core manifest for another platform is refused
	Seen   Seen      // what this computer accepted from this site under these roots
	Built  Seen      // the key list the stub was built with (its Keys and KeysSum only)
}

// KeyList is a verified keys.json.
type KeyList struct {
	Version    int64
	Sum        string // sha256 of the list's payload — the list itself, whatever envelope carried it
	CoreFloor  string // the oldest DGO core the list allows on any computer ("" = it states none)
	IndexFloor string // the oldest store index the list allows on any computer ("" = it states none)
	Signers    []Signer
	typ        string // the documents whose floor it settles and binds: the Checker's Type
}

// Lists reports whether keys.json still lists key id for documents of type typ — its window aside: a key
// whose window ended was not revoked, but one the list no longer names was.
func (kl KeyList) Lists(id, typ string) bool {
	for _, s := range kl.Signers {
		if KeyID(s.pub) == id && s.may(typ) {
			return true
		}
	}
	return false
}

// ViaKeysJSON stands, in this computer's memory, where a key's id would: the floor is the root's own —
// core_floor, or index_floor on the store's site (Settle) — which no key list revokes.
const ViaKeysJSON = "core_floor"

// Stands reports whether what keyid vouched for still holds every key: keys.json lists it for the
// site's documents, or it is the root's floor.
func (kl KeyList) Stands(keyid string) bool {
	return keyid == ViaKeysJSON || kl.Lists(keyid, kl.typ)
}

// floor is the root's own floor for the site's documents, one per kind: core_floor names DGO core
// releases, index_floor the store's index versions, and neither is a floor of the other's documents.
func (kl KeyList) floor() string {
	switch kl.typ {
	case ManifestType:
		return kl.CoreFloor
	case IndexType:
		return kl.IndexFloor
	}
	return ""
}

// Settle is this computer's memory under the key list it just accepted. A list that states the root's
// floor for the site's documents (core_floor; index_floor on the store's site) puts the root's word in
// place of a floor whose key it no longer lists — a leaked key's 999999999.0.0 included, so the next real
// release installs, whichever listed key signs it — and raises a lower floor to it; either way the floor
// is then the root's, which pins no bytes, kept by a later list that states none. A list that states no
// floor changes nothing: a revoked key's floor stands, binding the keys beside it.
func (kl KeyList) Settle(s Seen) Seen {
	if f := kl.floor(); f != "" && (!kl.Stands(s.ManifestBy) || SemverLess(s.Manifest, f)) {
		s.Manifest, s.ManifestBy, s.Beside, s.ManifestSum = f, ViaKeysJSON, "", ""
	}
	return s
}

// Binds reports whether what key by vouched for — the newest manifest this computer accepted, the core
// it installed — holds a manifest signed by signer: no older release may pass it. While it stands, it
// holds every key. Once by is revoked: if the list states the root's floor, it has taken its
// place (Settle) and it holds nothing; if not — a list relsign refuses to write — it holds the keys that
// were listed beside by when this computer took its word, which may have signed older releases a replay
// would bring back. Any other key is free of it: one never listed before, as the owner's release after
// a leak is signed with, but also an old key listed again, which only the rule in relsign keeps out.
func (kl KeyList) Binds(by, beside, signer string) bool {
	switch {
	case kl.Stands(by):
		return true
	case kl.floor() != "":
		return false
	}
	for _, k := range strings.Split(beside, ",") {
		if k == signer {
			return true
		}
	}
	return false
}

// Besides is the other keys keys.json lists for the site's documents, comma-separated: what a floor
// that signer sets still binds if signer is revoked (Binds).
func (kl KeyList) Besides(signer string) string {
	var ids []string
	for _, s := range kl.Signers {
		if id := KeyID(s.pub); id != signer && s.may(kl.typ) {
			ids = append(ids, id)
		}
	}
	return strings.Join(ids, ",")
}

// VerifyKeys accepts keys.json only when a root signed it for THIS download site, it has not expired,
// and it is neither older than the key list this computer accepted nor than the one this stub was built
// with — and, at an equal version, it is that same list: a list changed under an unchanged version (a
// revocation that forgot its "+ 1") would let the old list stand beside it, so it is refused. The site
// is inside the signature because the roots sign more than one list, and any of them served here would
// otherwise be believed: its keys trusted, its version remembered.
func (c Checker) VerifyKeys(raw []byte) (kl KeyList, err error) {
	defer func() {
		if err != nil {
			err = fmt.Errorf("keys.json: %w — refusing", err)
		}
	}()
	// The floors this list settles and binds are those of the documents the site serves; a reader that
	// names none would keep a floor that binds no key, so it reads nothing.
	if c.Type != ManifestType && c.Type != IndexType {
		return KeyList{}, fmt.Errorf("the reader names no document its site serves (type %q)", c.Type)
	}
	kl.typ = c.Type
	body, _, err := Open(raw, KeysType, c.Roots, c.Now)
	if err != nil {
		return KeyList{}, err
	}
	v, err := parseJSON(body)
	if err != nil {
		return KeyList{}, err
	}
	doc, err := asObj(v, "the key list")
	if err != nil {
		return KeyList{}, err
	}
	site, err := doc.text("site")
	if err != nil {
		return KeyList{}, err
	}
	if strings.TrimSuffix(site, "/") != strings.TrimSuffix(c.Site, "/") {
		return KeyList{}, fmt.Errorf("it is the key list of %s, and this installer's site is %s", site, c.Site)
	}
	if kl.Version, err = doc.natural("version"); err != nil {
		return KeyList{}, err
	}
	kl.Sum = sha256hex(body)
	// core_floor and index_floor are the root's own floors for the site — DGO core releases, the store's
	// index: no computer accepts an older one — a fresh one included, which remembers nothing. The owner
	// raises one when a release must not come back, and states it whenever the list drops a key.
	for _, f := range []struct {
		name string
		dst  *string
	}{{"core_floor", &kl.CoreFloor}, {"index_floor", &kl.IndexFloor}} {
		if _, stated := doc[f.name]; stated {
			if *f.dst, err = doc.text(f.name); err == nil && !ValidVersion(*f.dst) {
				err = fmt.Errorf("its %s %q is not a release version", f.name, *f.dst)
			}
			if err != nil {
				return KeyList{}, err
			}
		}
	}
	expires, err := doc.instant("expires")
	if err != nil {
		return KeyList{}, err
	}
	entries, err := doc.list("keys")
	if err != nil {
		return KeyList{}, err
	}
	if !c.Now.Before(expires) {
		return KeyList{}, fmt.Errorf("it expired at %s (this computer's clock says %s)", Stamp(expires), Stamp(c.Now))
	}
	for _, floor := range []struct {
		Seen
		who string
	}{{c.Seen, "this computer already accepted"}, {c.Built, "this installer was built with"}} {
		switch {
		case kl.Version < floor.Keys:
			return KeyList{}, fmt.Errorf("it is version %d, older than version %d which %s — a replayed or revoked key list", kl.Version, floor.Keys, floor.who)
		case kl.Version == floor.Keys && floor.KeysSum != "" && kl.Sum != floor.KeysSum:
			return KeyList{}, fmt.Errorf("it is version %d, but not the version %d which %s — a key list changed without a new version", kl.Version, floor.Keys, floor.who)
		}
	}
	for _, e := range entries {
		k, err := asObj(e, "a key")
		if err != nil {
			return KeyList{}, err
		}
		p64, err := k.text("public_key")
		if err != nil {
			return KeyList{}, err
		}
		pub, err := strict64.DecodeString(p64)
		if err != nil || len(pub) != ed25519.PublicKeySize {
			return KeyList{}, fmt.Errorf("%q is not a base64 Ed25519 public key", p64)
		}
		s := Signer{pub: pub}
		types, err := k.list("types")
		if err != nil {
			return KeyList{}, err
		}
		for _, t := range types {
			if name, ok := t.(string); ok && name != "" {
				s.types = append(s.types, name) // a type this stub does not know is kept and never asked for
				continue
			}
			return KeyList{}, fmt.Errorf("key %s: its types must be names of documents", KeyID(pub))
		}
		if s.from, err = k.instant("not_before"); err != nil {
			return KeyList{}, err
		}
		if s.until, err = k.instant("not_after"); err != nil {
			return KeyList{}, err
		}
		if !s.from.Before(s.until) { // empty by its own terms: no clock's grace may make it a window
			return KeyList{}, fmt.Errorf("key %s: its window %s..%s ends before it starts", KeyID(pub), Stamp(s.from), Stamp(s.until))
		}
		kl.Signers = append(kl.Signers, s)
	}
	return kl, nil
}

// Manifest is a verified manifest — every field of it was under the signature.
type Manifest struct {
	Site, Version, MinBootstrapper, Target, PayloadURL, SHA256 string
	Expires                                                    time.Time
	Size                                                       int64
	Signer                                                     string // keyid of the key that vouched for it
}

// VerifyManifest accepts a manifest only when a key of the verified list signed it inside its window
// and every rule below holds. Two floors stand under it: the one this computer remembers (Settle), for
// every key it binds (Binds), and keys.json's core_floor, on every computer and every release tree.
func (c Checker) VerifyManifest(raw []byte, kl KeyList) (m Manifest, err error) {
	defer func() {
		if err != nil {
			err = fmt.Errorf("manifest: %w — refusing", err)
		}
	}()
	if kl.typ != ManifestType {
		return Manifest{}, fmt.Errorf("its key list was read for %q documents", kl.typ)
	}
	body, signer, err := Open(raw, ManifestType, kl.Signers, c.Now)
	if err != nil {
		return Manifest{}, err
	}
	v, err := parseJSON(body)
	if err != nil {
		return Manifest{}, err
	}
	doc, err := asObj(v, "the manifest")
	if err != nil {
		return Manifest{}, err
	}
	for _, f := range []struct {
		dst  *string
		name string
	}{{&m.Site, "site"}, {&m.Version, "version"}, {&m.MinBootstrapper, "min_bootstrapper"}, {&m.Target, "target"},
		{&m.PayloadURL, "payload_url"}, {&m.SHA256, "sha256"}} {
		if *f.dst, err = doc.text(f.name); err != nil {
			return Manifest{}, err
		}
	}
	if m.Expires, err = doc.instant("expires"); err != nil {
		return Manifest{}, err
	}
	if m.Size, err = doc.natural("size"); err != nil {
		return Manifest{}, err
	}
	m.SHA256, m.Signer = strings.ToLower(m.SHA256), signer
	switch {
	case strings.TrimSuffix(m.Site, "/") != strings.TrimSuffix(c.Site, "/"):
		return Manifest{}, fmt.Errorf("it is a manifest of %s, and this installer's site is %s", m.Site, c.Site)
	case !UnderSite(c.Site, m.PayloadURL):
		return Manifest{}, fmt.Errorf("its payload %s is not an https:// file under %s", m.PayloadURL, c.Site)
	case !c.Now.Before(m.Expires):
		return Manifest{}, fmt.Errorf("it expired at %s (this computer's clock says %s)", Stamp(m.Expires), Stamp(c.Now))
	case m.Target != c.Target:
		return Manifest{}, fmt.Errorf("it is for %s, and this computer is %s", m.Target, c.Target)
	case !ValidVersion(m.Version) || !ValidVersion(m.MinBootstrapper):
		return Manifest{}, fmt.Errorf("version %q or min_bootstrapper %q is not a version", m.Version, m.MinBootstrapper)
	case c.Seen.Manifest != "" && SemverLess(m.Version, c.Seen.Manifest) && kl.Binds(c.Seen.ManifestBy, c.Seen.Beside, signer):
		return Manifest{}, fmt.Errorf("it offers DGO core %s, older than %s, the floor this computer already accepted — a replayed old manifest", m.Version, c.Seen.Manifest)
	case kl.CoreFloor != "" && SemverLess(m.Version, kl.CoreFloor):
		return Manifest{}, fmt.Errorf("it offers DGO core %s, older than %s, the oldest keys.json allows — a replayed old manifest", m.Version, kl.CoreFloor)
	case SemverLess(c.Stub, m.MinBootstrapper):
		return Manifest{}, fmt.Errorf("this installer (%s) is older than DGO core %s accepts (%s or newer) — download the current installer from https://digital-office.co.il", c.Stub, m.Version, m.MinBootstrapper)
	case len(m.SHA256) != 64 || strings.Trim(m.SHA256, "0123456789abcdef") != "":
		return Manifest{}, fmt.Errorf("sha256 %q is not 64 hex characters", m.SHA256)
	case m.Size == 0:
		return Manifest{}, errors.New("its payload size is 0")
	}
	return m, nil
}

// UnderSite reports whether payload is an https:// file inside site: the same host and a clean path
// under the site's own — /dl/linux/amd64/dgo-core is under /dl, while /beta/…, /dl2/… and /dl/../beta/…
// are not, nor is a path with a backslash (sent as %5C), which some servers (IIS) read as a "/":
// /dl/..\beta would climb out of the site.
func UnderSite(site, payload string) bool {
	s, err := url.Parse(site)
	if err != nil {
		return false
	}
	p, err := url.Parse(payload)
	if err != nil || p.Scheme != "https" || p.User != nil || !strings.EqualFold(p.Host, s.Host) {
		return false
	}
	return path.Clean(p.Path) == p.Path && !strings.Contains(p.Path, `\`) && strings.HasPrefix(p.Path, strings.TrimSuffix(s.Path, "/")+"/")
}

// ValidVersion is a release version — dotted numbers, 1.4.0 — and nothing else, because SemverLess
// orders exactly these: with a pre-release suffix 1.5.0-rc.2 would sort above 1.5.0, and an old signed
// pre-release could roll a release back. Each part is at most 9 digits, so it never overflows an int.
// relsign refuses to sign anything else.
func ValidVersion(v string) bool {
	if v == "" || len(v) > 64 {
		return false
	}
	for _, part := range strings.Split(v, ".") {
		if part == "" || len(part) > 9 || strings.Trim(part, "0123456789") != "" {
			return false
		}
	}
	return true
}

// SemverLess reports whether a < b for dotted-numeric versions (1.2.0 < 1.10.0). A non-numeric field
// compares as 0, which is conservative: an unparseable installed version never blocks a real update.
func SemverLess(a, b string) bool {
	as, bs := strings.Split(a, "."), strings.Split(b, ".")
	for i := 0; i < len(as) || i < len(bs); i++ {
		var ai, bi int
		if i < len(as) {
			ai, _ = strconv.Atoi(strings.TrimLeft(as[i], "v"))
		}
		if i < len(bs) {
			bi, _ = strconv.Atoi(strings.TrimLeft(bs[i], "v"))
		}
		if ai != bi {
			return ai < bi
		}
	}
	return false
}

// Stamp prints an instant for a person; an unbounded end of a window prints as such.
func Stamp(t time.Time) string {
	if t.IsZero() {
		return "(unbounded)"
	}
	return t.UTC().Format(time.RFC3339)
}

// Seen is what this computer accepted from one site under one set of roots: the memory that turns a
// replayed, correctly signed OLD keys.json or document into a refusal instead of a downgrade. Its
// "manifest" is the newest document of the site's type — a core manifest for the stub's site, the index
// for the store's.
type Seen struct {
	Keys        int64  // keys.json's version
	KeysSum     string // that list's sha256: another list under the same version is refused
	Manifest    string // the newest document version accepted ("" = none)
	ManifestBy  string // keyid of the key that signed it (or ViaKeysJSON: the root's floor), and
	Beside      string // the keys listed beside it then: what the floor binds once it is revoked (Binds)
	ManifestSum string // its sha256 where a document's bytes are pinned per version: the index, which never
	// expires and so is never re-signed under one version; "" for a core manifest, re-signed as it expires
}

// VouchedBy is how the state file and VERSION write who vouched for a version: the key that signed it,
// then the keys listed beside it — "k2,k1"; strings.Cut at the first "," reads it back.
func VouchedBy(by, beside string) string {
	if beside == "" {
		return by
	}
	return by + "," + beside
}

// ParseFloor reads the key list a release stub is built with — "version:sha256", baked in by
// packaging/build-binaries.sh; empty in a development build.
func ParseFloor(s string) (Seen, error) {
	if s == "" {
		return Seen{}, nil
	}
	n, h, ok := strings.Cut(s, ":")
	v, err := strconv.ParseInt(n, 10, 64)
	if !ok || err != nil || v < 0 || len(h) != 64 || strings.Trim(h, "0123456789abcdef") != "" {
		return Seen{}, fmt.Errorf("the built-in key list floor %q is not version:sha256", s)
	}
	return Seen{Keys: v, KeysSum: h}, nil
}

// LoadSeen reads the state file's line for site under roots; no file or no line is a computer that has
// accepted nothing there yet. A malformed file is refused rather than read as "nothing accepted". A line
// is the site, the roots, the key list's version and sha256 (- is none), the newest document's version
// and who vouched for it (VouchedBy) — and, where its bytes are pinned, their sha256.
func LoadSeen(path, site, roots string) (Seen, error) {
	b, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return Seen{}, nil
	}
	if err != nil {
		return Seen{}, err
	}
	for _, line := range strings.Split(string(b), "\n") {
		f := strings.Fields(line)
		if len(f) == 0 || strings.HasPrefix(f[0], "#") {
			continue
		}
		if len(f) != 6 && len(f) != 7 {
			return Seen{}, fmt.Errorf("%s: malformed line %q", path, line)
		}
		n, err := strconv.ParseInt(f[2], 10, 64)
		if err != nil || n < 0 {
			return Seen{}, fmt.Errorf("%s: malformed line %q", path, line)
		}
		if f[0] == site && f[1] == roots {
			s := Seen{Keys: n, KeysSum: f[3], Manifest: f[4]}
			s.ManifestBy, s.Beside, _ = strings.Cut(f[5], ",")
			if len(f) == 7 {
				s.ManifestSum = f[6]
			}
			for _, v := range []*string{&s.KeysSum, &s.Manifest, &s.ManifestBy} {
				if *v == "-" {
					*v = ""
				}
			}
			return s, nil
		}
	}
	return Seen{}, nil
}

// SaveSeen records s for site under roots, keeping every other line. It only ever raises what a run
// that overlapped this one wrote — a higher key list, or a higher manifest floor while its signer is
// still trusted (trusted reports that) — and replaces the file through a temporary of its own, synced
// before the rename, so a crash or a power cut leaves the old memory or the new one, never half of either.
// header is the file's first lines, its owner's: what the file is, and that removing it only forgets.
func SaveSeen(path, header, site, roots string, s Seen, trusted func(keyid string) bool) error {
	cur, err := LoadSeen(path, site, roots)
	if err != nil {
		return err
	}
	if cur.Keys > s.Keys {
		s.Keys, s.KeysSum = cur.Keys, cur.KeysSum
	}
	if cur.Manifest != "" && (s.Manifest == "" || SemverLess(s.Manifest, cur.Manifest)) && trusted(cur.ManifestBy) {
		s.Manifest, s.ManifestBy, s.Beside, s.ManifestSum = cur.Manifest, cur.ManifestBy, cur.Beside, cur.ManifestSum
	}
	old, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	out := header
	for _, line := range strings.Split(string(old), "\n") {
		if f := strings.Fields(line); (len(f) == 6 || len(f) == 7) && !strings.HasPrefix(f[0], "#") && !(f[0] == site && f[1] == roots) {
			out += line + "\n"
		}
	}
	field := func(v string) string {
		if v == "" {
			return "-"
		}
		return v
	}
	rec := []string{site, roots, strconv.FormatInt(s.Keys, 10), field(s.KeysSum), field(s.Manifest),
		field(VouchedBy(s.ManifestBy, s.Beside))}
	if s.ManifestSum != "" { // only where bytes are pinned: the stub's lines stay six fields
		rec = append(rec, s.ManifestSum)
	}
	out += strings.Join(rec, " ") + "\n"
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	_, err = f.WriteString(out)
	if err == nil {
		err = f.Sync()
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err == nil {
		err = os.Rename(f.Name(), path)
	}
	if err != nil {
		_ = os.Remove(f.Name())
	}
	return err
}

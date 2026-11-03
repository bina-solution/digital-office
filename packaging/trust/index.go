package trust

// The app store's index document (IndexType) — what `dgo index build` and `relsign index` sign and what
// `dgo index verify|install` believes. It pins one file, <site>/index.json (every installable app, and
// each artifact's sha256), the way a core manifest pins a core:
//
//	{"site":"https://apps.net.digital-office.co.il/v1","version":"1.4.0","sha256":"<hex>","size":71234}
//
// It shares the chain's rules: its site binds it to one channel, its signer must be listed for its type
// inside its window, and this computer's floor (Seen) refuses an older one. Its root floor is keys.json's
// index_floor, as core_floor is a core's: a list that drops an index key states it (relsign refuses one
// that does not), and on every computer it then takes the place of what that key vouched for (Settle) —
// so neither a leaked key's push nor an old key listed again can roll the index back. One thing differs
// from a core manifest, on purpose: it never expires — an index is installed from a mirror or a USB stick
// as long as its key list lives, and keys.json's expiry is the freshness the chain asks of it — and so
// it is never re-signed under one version: its bytes are pinned per version (Seen.ManifestSum), and
// another index under a version this computer accepted is refused, as another key list under one
// version is.

import (
	"errors"
	"fmt"
	"strings"
)

// VerifyIndex accepts the store's index document only when a key the verified list trusts for it
// signed it inside its window, it names this site, its version is a release version no older than the
// floor this computer keeps (and, at that version, the very index it accepted), and it pins index.json
// by a sha256 and a size. It returns the document and the keyid of the key that vouched for it.
func (c Checker) VerifyIndex(raw []byte, kl KeyList) (ix IndexDoc, signer string, err error) {
	defer func() {
		if err != nil {
			err = fmt.Errorf("index.sig.json: %w — refusing", err)
		}
	}()
	if kl.typ != IndexType {
		return IndexDoc{}, "", fmt.Errorf("its key list was read for %q documents", kl.typ)
	}
	body, signer, err := Open(raw, IndexType, kl.Signers, c.Now)
	if err != nil {
		return IndexDoc{}, "", err
	}
	v, err := parseJSON(body)
	if err != nil {
		return IndexDoc{}, "", err
	}
	doc, err := asObj(v, "the index document")
	if err != nil {
		return IndexDoc{}, "", err
	}
	for _, f := range []struct {
		dst  *string
		name string
	}{{&ix.Site, "site"}, {&ix.Version, "version"}, {&ix.SHA256, "sha256"}} {
		if *f.dst, err = doc.text(f.name); err != nil {
			return IndexDoc{}, "", err
		}
	}
	if ix.Size, err = doc.natural("size"); err != nil {
		return IndexDoc{}, "", err
	}
	ix.SHA256 = strings.ToLower(ix.SHA256)
	floor := c.Seen
	binds := floor.Manifest != "" && kl.Binds(floor.ManifestBy, floor.Beside, signer)
	switch {
	case strings.TrimSuffix(ix.Site, "/") != strings.TrimSuffix(c.Site, "/"):
		return IndexDoc{}, "", fmt.Errorf("it is the index of %s, and this store's site is %s", ix.Site, c.Site)
	case !ValidVersion(ix.Version):
		return IndexDoc{}, "", fmt.Errorf("version %q is not a release version", ix.Version)
	case binds && SemverLess(ix.Version, floor.Manifest):
		return IndexDoc{}, "", fmt.Errorf("it offers index %s, older than %s, the floor this computer already accepted — a replayed old index", ix.Version, floor.Manifest)
	case binds && !SemverLess(floor.Manifest, ix.Version) && floor.ManifestSum != "" && ix.SHA256 != floor.ManifestSum:
		return IndexDoc{}, "", fmt.Errorf("it is index %s, but not the index %s this computer already accepted — one version, one index", ix.Version, floor.Manifest)
	case kl.IndexFloor != "" && SemverLess(ix.Version, kl.IndexFloor):
		return IndexDoc{}, "", fmt.Errorf("it offers index %s, older than %s, the oldest keys.json allows — a replayed old index", ix.Version, kl.IndexFloor)
	case len(ix.SHA256) != 64 || strings.Trim(ix.SHA256, "0123456789abcdef") != "":
		return IndexDoc{}, "", fmt.Errorf("sha256 %q is not 64 hex characters", ix.SHA256)
	case ix.Size == 0:
		return IndexDoc{}, "", errors.New("its index size is 0")
	}
	return ix, signer, nil
}

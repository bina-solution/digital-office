package store

// Second reader's probes (core-trust): the store's dgo-app-index verifier held to the installer's rules.
// Every case that a stub would refuse must be refused here too; a case is a failure only when an index
// the installer's rules refuse is ACCEPTED (or the reverse, a good one refused). In the suite as the
// reader wrote them, but for the two probes of finding F1, adapted to its fix (index_floor, and relsign's
// guard for index keys) where the reader's copy asserted the rollback against lists that state no floor.

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

// rvBuild is a signed index of one app at version, by key, with keys (keys.json) beside it.
func rvBuild(t *testing.T, version string, key ed25519.PrivateKey, keys []byte) string {
	t.Helper()
	out := filepath.Join(t.TempDir(), "index")
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/a/notes.txt": "v" + version + time.Now().String()})
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: out, Key: key, Keys: keys, Version: version}); err != nil {
		t.Fatal(err)
	}
	return out
}

func rvVerify(dir, root, baseURL string) (int, string) {
	var out, errb bytes.Buffer
	code := verify(dir, root, baseURL, &out, &errb)
	return code, errb.String() + out.String()
}

func rvPut(t *testing.T, dir, name string, body []byte) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), body, 0o644); err != nil {
		t.Fatal(err)
	}
}

// rvSealRaw seals body (already JSON bytes) as typ by key into dir/name.
func rvSealRaw(t *testing.T, dir, name string, key ed25519.PrivateKey, typ string, body []byte) {
	t.Helper()
	env, err := trust.Seal(key, typ, body)
	if err != nil {
		t.Fatal(err)
	}
	rvPut(t, dir, name, append(env, '\n'))
}

// rvKeys seals a key list doc (any JSON shape) by root, the way a hand-made keys.json would be.
func rvKeys(t *testing.T, root ed25519.PrivateKey, doc any) []byte {
	t.Helper()
	body, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	env, err := trust.Seal(root, trust.KeysType, body)
	if err != nil {
		t.Fatal(err)
	}
	return env
}

func rvEntry(key ed25519.PrivateKey, from, until time.Time, types ...string) trust.KeyEntry {
	return trust.KeyEntry{PublicKey: base64.StdEncoding.EncodeToString(key.Public().(ed25519.PublicKey)), Types: types,
		NotBefore: from.UTC().Format(time.RFC3339), NotAfter: until.UTC().Format(time.RFC3339)}
}

// rvEnvelope edits index.sig.json's envelope fields.
func rvEnvelope(t *testing.T, dir string, edit func(e *trust.Envelope)) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir, sigName))
	if err != nil {
		t.Fatal(err)
	}
	var e trust.Envelope
	if err := json.Unmarshal(raw, &e); err != nil {
		t.Fatal(err)
	}
	edit(&e)
	out, _ := json.Marshal(e)
	rvPut(t, dir, sigName, out)
}

func rvIndexDoc(t *testing.T, dir string) trust.IndexDoc {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir, indexName))
	if err != nil {
		t.Fatal(err)
	}
	s := sha256.Sum256(raw)
	return trust.IndexDoc{Site: defaultBaseURL, Version: signedVersion, SHA256: hex.EncodeToString(s[:]), Size: int64(len(raw))}
}

// noncanonical flips the unused low bits of the last data character of a padded base64 string: the
// same bytes to a lenient decoder, refused by a strict one.
func noncanonical(s string) string {
	const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	i := len(strings.TrimRight(s, "=")) - 1
	v := strings.IndexByte(alphabet, s[i])
	return s[:i] + string(alphabet[v|1]) + s[i+1:]
}

// TestRVIndexRefusalsMatrix: question 2 — wrong type, other site, windows, unknown/unlisted keys, a key
// not allowed the type, non-canonical signatures, keys.json not signed by the root. All must refuse.
func TestRVIndexRefusalsMatrix(t *testing.T) {
	t.Parallel()
	now := time.Now()
	cases := []struct {
		name   string
		tamper func(t *testing.T, dir string, c *chain) (root, baseURL string)
		want   string
	}{
		{"index sealed as a core manifest by the listed key", func(t *testing.T, dir string, c *chain) (string, string) {
			body, _ := json.Marshal(rvIndexDoc(t, dir))
			rvSealRaw(t, dir, sigName, c.key, trust.ManifestType, body)
			return c.rootFile, ""
		}, "payloadType"},
		{"index envelope relabelled dgo-core-manifest", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) { e.PayloadType = trust.ManifestType })
			return c.rootFile, ""
		}, "payloadType"},
		{"index envelope relabelled dgo-keys", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) { e.PayloadType = trust.KeysType })
			return c.rootFile, ""
		}, "payloadType"},
		{"index document sealed as dgo-keys by the ROOT", func(t *testing.T, dir string, c *chain) (string, string) {
			body, _ := json.Marshal(rvIndexDoc(t, dir))
			rvSealRaw(t, dir, sigName, c.root, trust.KeysType, body)
			return c.rootFile, ""
		}, "payloadType"},
		{"index document sealed as dgo-app-index by the ROOT (not listed)", func(t *testing.T, dir string, c *chain) (string, string) {
			body, _ := json.Marshal(rvIndexDoc(t, dir))
			rvSealRaw(t, dir, sigName, c.root, trust.IndexType, body)
			return c.rootFile, ""
		}, "unknown signer"},
		{"keys.json sealed as dgo-app-index by the root", func(t *testing.T, dir string, c *chain) (string, string) {
			body, _ := json.Marshal(trust.KeysDoc{Site: defaultBaseURL, Version: 2, Expires: now.AddDate(0, 1, 0).UTC().Format(time.RFC3339),
				Keys: []trust.KeyEntry{listed(c.key, trust.IndexType)}})
			rvSealRaw(t, dir, keysName, c.root, trust.IndexType, body)
			return c.rootFile, ""
		}, "payloadType"},
		{"keys.json of the core download site", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, "https://digital-office.co.il/dl", 2, listed(c.key, trust.IndexType)))
			return c.rootFile, ""
		}, "key list of https://digital-office.co.il/dl"},
		{"keys.json of the site with another case", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, strings.ToUpper(defaultBaseURL), 2, listed(c.key, trust.IndexType)))
			return c.rootFile, ""
		}, "key list of"},
		{"index document of the site in another case", func(t *testing.T, dir string, c *chain) (string, string) {
			resign(t, dir, c.key, signedVersion, "https://APPS.net.digital-office.co.il/v1")
			return c.rootFile, ""
		}, "it is the index of"},
		{"index document of a path under the site", func(t *testing.T, dir string, c *chain) (string, string) {
			resign(t, dir, c.key, signedVersion, defaultBaseURL+"/beta")
			return c.rootFile, ""
		}, "it is the index of"},
		{"index document of a prefix of the site", func(t *testing.T, dir string, c *chain) (string, string) {
			resign(t, dir, c.key, signedVersion, strings.TrimSuffix(defaultBaseURL, "1"))
			return c.rootFile, ""
		}, "it is the index of"},
		{"index document of the site with two trailing slashes", func(t *testing.T, dir string, c *chain) (string, string) {
			resign(t, dir, c.key, signedVersion, defaultBaseURL+"//")
			return c.rootFile, ""
		}, "it is the index of"},
		{"--base-url over plain http", func(t *testing.T, dir string, c *chain) (string, string) {
			return c.rootFile, "http://apps.net.digital-office.co.il/v1"
		}, "must be https"},
		{"the signing key's window ended an hour ago", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, defaultBaseURL, 2, rvEntry(c.key, now.AddDate(0, 0, -3), now.Add(-time.Hour), trust.IndexType)))
			return c.rootFile, ""
		}, "valid only from"},
		{"the signing key's window opens in an hour", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, defaultBaseURL, 2, rvEntry(c.key, now.Add(time.Hour), now.AddDate(1, 0, 0), trust.IndexType)))
			return c.rootFile, ""
		}, "valid only from"},
		{"an inverted window", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, defaultBaseURL, 2, rvEntry(c.key, now.AddDate(1, 0, 0), now.AddDate(0, 0, -1), trust.IndexType)))
			return c.rootFile, ""
		}, "ends before it starts"},
		{"an empty window (from == until)", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, defaultBaseURL, 2, rvEntry(c.key, now.Add(time.Minute), now.Add(time.Minute), trust.IndexType)))
			return c.rootFile, ""
		}, "ends before it starts"},
		{"keys.json expired a minute ago", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, rvKeys(t, c.root, trust.KeysDoc{Site: defaultBaseURL, Version: 2, Expires: now.Add(-time.Minute).UTC().Format(time.RFC3339),
				Keys: []trust.KeyEntry{listed(c.key, trust.IndexType)}}))
			return c.rootFile, ""
		}, "expired"},
		{"index by a key the list does not name", func(t *testing.T, dir string, c *chain) (string, string) {
			resign(t, dir, newKey(t), signedVersion, defaultBaseURL)
			return c.rootFile, ""
		}, "unknown signer"},
		{"index by a key listed for core manifests only", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, defaultBaseURL, 2, listed(c.key, trust.ManifestType)))
			return c.rootFile, ""
		}, "does not trust that key to sign " + trust.IndexType},
		{"index by a key listed for a near-miss type", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, defaultBaseURL, 2, listed(c.key, "DGO-APP-INDEX", "dgo-app-index ", "dgo-keys")))
			return c.rootFile, ""
		}, "does not trust that key"},
		{"index by a key listed twice: index type expired, core type open", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.root, defaultBaseURL, 2,
				rvEntry(c.key, now.AddDate(0, 0, -3), now.Add(-time.Hour), trust.IndexType), listed(c.key, trust.ManifestType)))
			return c.rootFile, ""
		}, "refusing"},
		{"keys.json signed by the online key itself", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, c.key, defaultBaseURL, 2, listed(c.key, trust.IndexType)))
			return c.rootFile, ""
		}, "unknown signer"},
		{"keys.json signed by another root", func(t *testing.T, dir string, c *chain) (string, string) {
			rvPut(t, dir, keysName, keyList(t, newKey(t), defaultBaseURL, 2, listed(c.key, trust.IndexType)))
			return c.rootFile, ""
		}, "unknown signer"},
		{"the root file names another root", func(t *testing.T, dir string, c *chain) (string, string) {
			return rootFile(t, newKey(t)), ""
		}, "unknown signer"},
		{"a signature with non-canonical base64 bits", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) { e.Signatures[0].Sig = noncanonical(e.Signatures[0].Sig) })
			return c.rootFile, ""
		}, "bytes of base64"},
		{"a signature without its padding", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) { e.Signatures[0].Sig = strings.TrimRight(e.Signatures[0].Sig, "=") })
			return c.rootFile, ""
		}, "bytes of base64"},
		{"a signature of 65 bytes", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) {
				b, _ := base64.StdEncoding.DecodeString(e.Signatures[0].Sig)
				e.Signatures[0].Sig = base64.StdEncoding.EncodeToString(append(b, 0))
			})
			return c.rootFile, ""
		}, "bytes of base64"},
		{"a signature of 63 bytes", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) {
				b, _ := base64.StdEncoding.DecodeString(e.Signatures[0].Sig)
				e.Signatures[0].Sig = base64.StdEncoding.EncodeToString(b[:63])
			})
			return c.rootFile, ""
		}, "bytes of base64"},
		{"a signature in URL-safe characters", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) { e.Signatures[0].Sig = "-_" + e.Signatures[0].Sig[2:] })
			return c.rootFile, ""
		}, "bytes of base64"},
		{"a payload with non-canonical base64 bits", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) {
				if !strings.HasSuffix(e.Payload, "=") {
					e.Payload += "=" // no padding to play with: an extra '=' is refused too
					return
				}
				e.Payload = noncanonical(e.Payload)
			})
			return c.rootFile, ""
		}, "not base64"},
		{"a zeroed signature under the listed key's id", func(t *testing.T, dir string, c *chain) (string, string) {
			rvEnvelope(t, dir, func(e *trust.Envelope) {
				forged := trust.Signature{KeyID: e.Signatures[0].KeyID, Sig: base64.StdEncoding.EncodeToString(make([]byte, 64))}
				e.Signatures = []trust.Signature{forged}
			})
			return c.rootFile, ""
		}, "does not verify"},
		{"an index document with a duplicate version", func(t *testing.T, dir string, c *chain) (string, string) {
			d := rvIndexDoc(t, dir)
			body := []byte(`{"site":"` + d.Site + `","version":"` + d.Version + `","sha256":"` + d.SHA256 + `","size":` +
				strings.TrimSpace(string(mustJSON(t, d.Size))) + `,"version":"` + d.Version + `"}`)
			rvSealRaw(t, dir, sigName, c.key, trust.IndexType, body)
			return c.rootFile, ""
		}, "duplicate"},
		{"an index document at a pre-release", func(t *testing.T, dir string, c *chain) (string, string) {
			rewrite(t, filepath.Join(dir, indexName), `"version": "`+signedVersion+`"`, `"version": "1.0.0-rc.1"`)
			resign(t, dir, c.key, "1.0.0-rc.1", defaultBaseURL)
			return c.rootFile, ""
		}, "not a release version"},
		{"an index document with a v-prefixed version", func(t *testing.T, dir string, c *chain) (string, string) {
			rewrite(t, filepath.Join(dir, indexName), `"version": "`+signedVersion+`"`, `"version": "v1.0.0"`)
			resign(t, dir, c.key, "v1.0.0", defaultBaseURL)
			return c.rootFile, ""
		}, "not a release version"},
		{"an index document a byte too long", func(t *testing.T, dir string, c *chain) (string, string) {
			d := rvIndexDoc(t, dir)
			d.Size++
			body, _ := json.Marshal(d)
			rvSealRaw(t, dir, sigName, c.key, trust.IndexType, body)
			return c.rootFile, ""
		}, "the index was altered"},
		{"an index document of size 0 and the empty file's hash", func(t *testing.T, dir string, c *chain) (string, string) {
			d := rvIndexDoc(t, dir)
			s := sha256.Sum256(nil)
			d.Size, d.SHA256 = 0, hex.EncodeToString(s[:])
			body, _ := json.Marshal(d)
			rvSealRaw(t, dir, sigName, c.key, trust.IndexType, body)
			return c.rootFile, ""
		}, "size is 0"},
		{"an index document without a site", func(t *testing.T, dir string, c *chain) (string, string) {
			d := rvIndexDoc(t, dir)
			body := []byte(`{"version":"` + d.Version + `","sha256":"` + d.SHA256 + `","size":` + strings.TrimSpace(string(mustJSON(t, d.Size))) + `}`)
			rvSealRaw(t, dir, sigName, c.key, trust.IndexType, body)
			return c.rootFile, ""
		}, "site"},
	}
	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			dir, ch := signedTree(t)
			root, base := tc.tamper(t, dir, ch)
			code, out := rvVerify(dir, root, base)
			if code == 0 || !strings.Contains(out, tc.want) {
				t.Errorf("ACCEPTED or refused for another reason: exit %d, want a refusal containing %q\n%s", code, tc.want, out)
			} else {
				t.Logf("refused: %s", firstLine(out))
			}
		})
	}
}

func mustJSON(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func firstLine(s string) string {
	l, _, _ := strings.Cut(s, "\n")
	return l
}

// TestRVIndexWindowGraceMatchesTheStub: a key whose window opens 5 minutes from now is inside the
// stub's 10-minute grace — the store must agree with the stub (accept), not be stricter or looser.
func TestRVIndexWindowGraceMatchesTheStub(t *testing.T) {
	t.Parallel()
	dir, c := signedTree(t)
	now := time.Now()
	rvPut(t, dir, keysName, keyList(t, c.root, defaultBaseURL, 2, rvEntry(c.key, now.Add(5*time.Minute), now.AddDate(1, 0, 0), trust.IndexType)))
	if code, out := rvVerify(dir, c.rootFile, ""); code != 0 {
		t.Errorf("a window opening inside the grace must verify, as in the stub: exit %d\n%s", code, out)
	}
}

// TestRVIndexFloors: question 2 — replays the installer's rules refuse.
func TestRVIndexFloors(t *testing.T) {
	t.Parallel()
	t.Run("same key, lower version", func(t *testing.T) {
		t.Parallel()
		c := newChain(t)
		hi, lo := rvBuild(t, "2.0.0", c.key, c.keys), rvBuild(t, "1.0.0", c.key, c.keys)
		if code, out := rvVerify(hi, c.rootFile, ""); code != 0 {
			t.Fatal(out)
		}
		if code, out := rvVerify(lo, c.rootFile, ""); code == 0 || !strings.Contains(out, "replayed old index") {
			t.Errorf("ACCEPTED a lower index by the same key: %s", out)
		}
	})
	t.Run("another listed key, lower version", func(t *testing.T) {
		t.Parallel()
		c := newChain(t)
		k2 := newKey(t)
		both := keyList(t, c.root, defaultBaseURL, 1, listed(c.key, trust.IndexType), listed(k2, trust.IndexType))
		hi, lo := rvBuild(t, "2.0.0", c.key, both), rvBuild(t, "1.0.0", k2, both)
		if code, out := rvVerify(hi, c.rootFile, ""); code != 0 {
			t.Fatal(out)
		}
		if code, out := rvVerify(lo, c.rootFile, ""); code == 0 || !strings.Contains(out, "replayed old index") {
			t.Errorf("ACCEPTED a lower index by another listed key: %s", out)
		}
	})
	t.Run("R2-1 shape: the newer of two overlapping keys revoked, the older replays", func(t *testing.T) {
		t.Parallel()
		c := newChain(t)
		k2 := newKey(t)
		both := keyList(t, c.root, defaultBaseURL, 1, listed(c.key, trust.IndexType), listed(k2, trust.IndexType))
		k1old := rvBuild(t, "1.0.0", c.key, both) // K1's old index, published
		k2new := rvBuild(t, "2.0.0", k2, both)
		if code, out := rvVerify(k2new, c.rootFile, ""); code != 0 {
			t.Fatal(out)
		}
		rvPut(t, k1old, keysName, keyList(t, c.root, defaultBaseURL, 2, listed(c.key, trust.IndexType))) // K2 revoked
		if code, out := rvVerify(k1old, c.rootFile, ""); code == 0 || !strings.Contains(out, "replayed old index") {
			t.Errorf("ACCEPTED K1's older index after K2 (listed beside it) was revoked: %s", out)
		}
	})
	t.Run("same version, other bytes, by the key listed beside", func(t *testing.T) {
		t.Parallel()
		c := newChain(t)
		k2 := newKey(t)
		both := keyList(t, c.root, defaultBaseURL, 1, listed(c.key, trust.IndexType), listed(k2, trust.IndexType))
		a, b := rvBuild(t, "2.0.0", c.key, both), rvBuild(t, "2.0.0", k2, both)
		if code, out := rvVerify(a, c.rootFile, ""); code != 0 {
			t.Fatal(out)
		}
		if code, out := rvVerify(b, c.rootFile, ""); code == 0 || !strings.Contains(out, "one version, one index") {
			t.Errorf("ACCEPTED another index under an accepted version: %s", out)
		}
	})
	t.Run("a lower keys.json version, and another list under the same version", func(t *testing.T) {
		t.Parallel()
		c := newChain(t)
		v2 := keyList(t, c.root, defaultBaseURL, 2, listed(c.key, trust.IndexType))
		d := rvBuild(t, "1.0.0", c.key, v2)
		if code, out := rvVerify(d, c.rootFile, ""); code != 0 {
			t.Fatal(out)
		}
		rvPut(t, d, keysName, c.keys) // version 1
		if code, out := rvVerify(d, c.rootFile, ""); code == 0 || !strings.Contains(out, "replayed or revoked key list") {
			t.Errorf("ACCEPTED an older key list: %s", out)
		}
		rvPut(t, d, keysName, keyList(t, c.root, defaultBaseURL, 2, listed(c.key, trust.IndexType), listed(newKey(t), trust.IndexType)))
		if code, out := rvVerify(d, c.rootFile, ""); code == 0 || !strings.Contains(out, "changed without a new version") {
			t.Errorf("ACCEPTED another key list under an accepted version: %s", out)
		}
	})
}

// rvFloored seals a key list that states the root's floors (either may be ""), as relsign writes one.
func rvFloored(t *testing.T, root ed25519.PrivateKey, version int64, coreFloor, indexFloor string, keys ...trust.KeyEntry) []byte {
	t.Helper()
	return rvKeys(t, root, trust.KeysDoc{Site: defaultBaseURL, Version: version, CoreFloor: coreFloor, IndexFloor: indexFloor,
		Expires: time.Now().AddDate(0, 2, 0).UTC().Format(time.RFC3339), Keys: keys})
}

// TestRVIndexRelistedKeyReplaysAnOlderIndex: the R3-1 shape on the store (F1). K1 signs indexes; the
// owner rotates to K2, then lists K1 again. A mirror with NO key serves K1's old, authentic index beside
// the current keys.json. Expected: refused. Adapted to the fix: a list that drops an index key states
// index_floor, as relsign now requires (TestRVRelsignMadeListsReachTheIndexRollback); and a later list
// that omits it does not reopen the replay — the root's floor is this machine's own by then.
func TestRVIndexRelistedKeyReplaysAnOlderIndex(t *testing.T) {
	t.Parallel()
	for _, tc := range []struct {
		name string
		v3   func(root, k1, k2 ed25519.PrivateKey) []byte
	}{
		{"K2 dropped, K1 listed again", func(root, k1, k2 ed25519.PrivateKey) []byte {
			return rvFloored(t, root, 3, "", "1.5.0", listed(k1, trust.IndexType))
		}},
		{"K2 kept but narrowed to core manifests, K1 listed again", func(root, k1, k2 ed25519.PrivateKey) []byte {
			return rvFloored(t, root, 3, "", "1.5.0", listed(k1, trust.IndexType), listed(k2, trust.ManifestType))
		}},
		{"K1 listed again, the list stating a core_floor beside its index_floor", func(root, k1, k2 ed25519.PrivateKey) []byte {
			return rvFloored(t, root, 3, "1.5.0", "1.5.0", listed(k1, trust.IndexType))
		}},
	} {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			root := newKey(t)
			rf := rootFile(t, root)
			k1, k2 := newKey(t), newKey(t)
			v1 := keyList(t, root, defaultBaseURL, 1, listed(k1, trust.IndexType))
			v2 := rvFloored(t, root, 2, "", "1.4.0", listed(k2, trust.IndexType)) // K1 dropped: the newest real index stated
			k1v100 := rvBuild(t, "1.0.0", k1, v1)                                 // K1's oldest index, long published
			k1v140 := rvBuild(t, "1.4.0", k1, v1)
			k2v150 := rvBuild(t, "1.5.0", k2, v2)
			for _, d := range []string{k1v140, k2v150} {
				if code, out := rvVerify(d, rf, ""); code != 0 {
					t.Fatalf("setup: %s", out)
				}
			}
			site := strings.TrimRight(defaultBaseURL, "/")
			roots, _ := readRoots(rf)
			sp, _ := statePath(site, trust.RootsID(roots))
			for i, keys := range [][]byte{tc.v3(root, k1, k2), rvFloored(t, root, 4, "", "", listed(k1, trust.IndexType))} {
				rvPut(t, k1v100, keysName, keys) // the mirror: today's keys.json beside K1's old index
				code, out := rvVerify(k1v100, rf, "")
				st, _ := trust.LoadSeen(sp, site, trust.RootsID(roots))
				if code == 0 {
					t.Errorf("list %d: ACCEPTED K1's index 1.0.0 after this machine accepted 1.4.0 (by K1 itself) and 1.5.0 (by K2): the floor is now %q by %q — %s",
						3+i, st.Manifest, st.ManifestBy, firstLine(out))
				} else {
					t.Logf("list %d: refused: %s", 3+i, firstLine(out))
				}
			}
		})
	}
}

// TestRVRelsignMadeListsReachTheIndexRollback: the same rotation, every keys.json made by relsign itself
// with -previous (the owner's documented path). Adapted to the fix: relsign refuses a list that drops an
// index key unless -index-floor is given (its R3-1 guard now covers dgo-app-index); with the floor
// stated, dgo refuses K1's old index.
func TestRVRelsignMadeListsReachTheIndexRollback(t *testing.T) {
	t.Parallel()
	if _, err := exec.LookPath("go"); err != nil {
		t.Skip("go not on PATH")
	}
	dir := t.TempDir()
	bin := filepath.Join(dir, "relsign")
	if runtime.GOOS == "windows" {
		bin += ".exe"
	}
	build := exec.Command("go", "build", "-o", bin, ".")
	build.Dir = filepath.Join(repoRoot(t), "packaging", "relsign")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("building packaging/relsign: %v — %s", err, out)
	}
	relsign := func(args ...string) ([]byte, error) {
		var stderr bytes.Buffer
		cmd := exec.Command(bin, args...)
		cmd.Stderr = &stderr
		out, err := cmd.Output()
		if err != nil {
			return nil, fmt.Errorf("%v: %s", err, stderr.String())
		}
		return out, nil
	}
	must := func(b []byte, err error) []byte {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return b
	}
	pem := func(name string) string { p := filepath.Join(dir, name+".pem"); must(relsign("keygen", p)); return p }
	rootPEM, k1PEM, k2PEM := pem("root"), pem("k1"), pem("k2")
	rf := filepath.Join(dir, "root.pub")
	rvPutFile(t, rf, must(relsign("pubkey", rootPEM)))
	file := func(name string, b []byte) string { p := filepath.Join(dir, name); rvPutFile(t, p, b); return p }
	v1 := file("keys-1.json", must(relsign("keys", "-signer", rootPEM, "-site", defaultBaseURL, "-version", "1", "-key", k1PEM, "-types", trust.IndexType)))
	if _, err := relsign("keys", "-signer", rootPEM, "-site", defaultBaseURL, "-version", "2", "-previous", v1, "-key", k2PEM, "-types", trust.IndexType); err == nil ||
		!strings.Contains(err.Error(), "state -index-floor") {
		t.Fatalf("relsign must refuse to drop K1 (an index key) without -index-floor: %v", err)
	}
	v2b := must(relsign("keys", "-signer", rootPEM, "-site", defaultBaseURL, "-version", "2", "-previous", v1, "-index-floor", "1.4.0",
		"-key", k2PEM, "-types", trust.IndexType))
	v2 := file("keys-2.json", v2b)
	if _, err := relsign("keys", "-signer", rootPEM, "-site", defaultBaseURL, "-version", "3", "-previous", v2, "-key", k1PEM, "-types", trust.IndexType); err == nil ||
		!strings.Contains(err.Error(), "state -index-floor") {
		t.Fatalf("relsign must refuse to list K1 again in place of K2 without -index-floor: %v", err)
	}
	v3b := must(relsign("keys", "-signer", rootPEM, "-site", defaultBaseURL, "-version", "3", "-previous", v2, "-index-floor", "1.5.0",
		"-key", k1PEM, "-types", trust.IndexType))
	k1, err := loadPrivateKey(k1PEM)
	if err != nil {
		t.Fatal(err)
	}
	k2, err := loadPrivateKey(k2PEM)
	if err != nil {
		t.Fatal(err)
	}
	k1v100, k1v140 := rvBuild(t, "1.0.0", k1, must(os.ReadFile(v1))), rvBuild(t, "1.4.0", k1, must(os.ReadFile(v1)))
	k2v150 := rvBuild(t, "1.5.0", k2, v2b)
	for _, d := range []string{k1v140, k2v150} {
		if code, out := rvVerify(d, rf, ""); code != 0 {
			t.Fatalf("setup: %s", out)
		}
	}
	rvPut(t, k1v100, keysName, v3b)
	if code, out := rvVerify(k1v100, rf, ""); code == 0 {
		t.Errorf("ACCEPTED, on relsign-made lists: K1's index 1.0.0 after this machine accepted K1's 1.4.0 and K2's 1.5.0 — %s", firstLine(out))
	} else {
		t.Logf("refused: %s", firstLine(out))
	}
}

func rvPutFile(t *testing.T, p string, b []byte) {
	t.Helper()
	if err := os.WriteFile(p, b, 0o644); err != nil {
		t.Fatal(err)
	}
}

package trust

// The producing side — what packaging/relsign and `dgo index build` write. Both marshal the documents
// below with encoding/json (this package never imports it: the stub carries this package) and seal the
// bytes with Seal, so a document signed by either program is the same file, byte for byte. The writer's
// shapes live here, beside the rules that read them, so the two cannot drift apart unseen.

import (
	"crypto/ed25519"
	"encoding/base64"
	"fmt"
)

// Envelope is DSSE's JSON envelope as encoding/json reads and writes it — the bytes Seal writes, for a
// program that reads one back (relsign reads the key list it wrote before). Open, never this, is how an
// envelope is believed.
type Envelope struct {
	PayloadType string      `json:"payloadType"`
	Payload     string      `json:"payload"`
	Signatures  []Signature `json:"signatures"`
}

// Signature is one signature of an Envelope.
type Signature struct {
	KeyID string `json:"keyid"`
	Sig   string `json:"sig"`
}

// KeysDoc is keys.json (KeysType), signed by a root: the online keys it vouches for, for one site.
type KeysDoc struct {
	Site       string     `json:"site"` // the site the list is for: a reader of another site refuses it
	Version    int64      `json:"version"`
	Expires    string     `json:"expires"`
	CoreFloor  string     `json:"core_floor,omitempty"`  // the oldest DGO core any computer installs, a fresh one too
	IndexFloor string     `json:"index_floor,omitempty"` // the oldest store index any computer accepts, a fresh one too
	Keys       []KeyEntry `json:"keys"`
}

// KeyEntry is one key of keys.json: the document types it may sign, and when.
type KeyEntry struct {
	PublicKey string   `json:"public_key"`
	Types     []string `json:"types"`
	NotBefore string   `json:"not_before"`
	NotAfter  string   `json:"not_after"`
}

// ManifestDoc is one target's core manifest (ManifestType), as VerifyManifest reads it.
type ManifestDoc struct {
	Site            string `json:"site"` // the download site it is for, like keys.json's: not another site's
	Version         string `json:"version"`
	Expires         string `json:"expires"`
	MinBootstrapper string `json:"min_bootstrapper"`
	Target          string `json:"target"`
	PayloadURL      string `json:"payload_url"`
	SHA256          string `json:"sha256"`
	Size            int64  `json:"size"`
}

// IndexDoc is the store's index document (IndexType), as VerifyIndex reads it: it pins <site>/index.json.
type IndexDoc struct {
	Site    string `json:"site"`    // the store's base URL: another channel is another site
	Version string `json:"version"` // the index's own release version, which this computer's floor orders
	SHA256  string `json:"sha256"`  // of index.json's bytes
	Size    int64  `json:"size"`    // of index.json, in bytes
}

// Seal signs the whole of body with its type (PAE) and returns the envelope as one JSON line without
// its newline: exactly what encoding/json writes for the Envelope (TestSealWritesWhatEncodingJSONWrites),
// because the type is one of this package's and base64 and hex need no escaping.
func Seal(priv ed25519.PrivateKey, typ string, body []byte) ([]byte, error) {
	switch typ {
	case KeysType, ManifestType, IndexType:
	default:
		return nil, fmt.Errorf("%q is not a type of the office's signed documents", typ)
	}
	b64 := base64.StdEncoding.EncodeToString
	return []byte(`{"payloadType":"` + typ + `","payload":"` + b64(body) + `","signatures":[{"keyid":"` +
		KeyID(priv.Public().(ed25519.PublicKey)) + `","sig":"` + b64(ed25519.Sign(priv, PAE(typ, body))) + `"}]}`), nil
}

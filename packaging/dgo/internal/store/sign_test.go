package store

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

// TestRelsignSignsItDgoVerifiesItAndTheReverse holds the store to packaging/relsign's own code, on a
// chain relsign made — its root, its signing key and the key list that root signed. An index dgo
// signs verifies here, and `relsign index` signs the same index.json into the very same bytes; an
// index dgo built as an unsigned draft, signed by relsign, verifies here too; and what relsign signs
// for anything else — a core manifest, a key list of another site, a key scoped to core manifests —
// is refused where the index's signature belongs. relsign is built once (a `go run` per call would
// relink it each time: half a minute on Windows). Skipped where `go` is not on PATH.
func TestRelsignSignsItDgoVerifiesItAndTheReverse(t *testing.T) {
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
		t.Fatalf("building packaging/relsign: %v\n%s", err, out)
	}
	relsign := func(args ...string) []byte {
		t.Helper()
		var stderr bytes.Buffer
		cmd := exec.Command(bin, args...)
		cmd.Stderr = &stderr
		out, err := cmd.Output()
		if err != nil {
			t.Fatalf("relsign %v: %v\n%s", args[0], err, stderr.String())
		}
		return out
	}
	keygen := func(name string) string { // throwaway keys, gone with the test
		p := filepath.Join(dir, name+".pem")
		relsign("keygen", p)
		return p
	}
	rootPEM, signerPEM := keygen("root"), keygen("signer")
	root := filepath.Join(dir, "root.pub")
	if err := os.WriteFile(root, relsign("pubkey", rootPEM), 0o644); err != nil {
		t.Fatal(err)
	}
	keysJSON := relsign("keys", "-signer", rootPEM, "-site", defaultBaseURL, "-version", "1", "-key", signerPEM, "-types", trust.IndexType)
	key, err := loadPrivateKey(signerPEM)
	if err != nil {
		t.Fatalf("relsign's key does not load here: %v", err)
	}
	src := tree(t, map[string]string{"apps/a/app.json": manifest("a", "")})
	check := func(dir, want string) {
		t.Helper()
		var out, errb bytes.Buffer
		code := verify(dir, root, "", &out, &errb)
		if want == "" && code != 0 || want != "" && (code != 1 || !strings.Contains(errb.String(), want)) {
			t.Fatalf("verify %s: exit %d, want %q\n%s%s", filepath.Base(dir), code, want, out.String(), errb.String())
		}
	}

	// dgo signs, under relsign's root and key list — and relsign signs the same index into the same bytes.
	signed := filepath.Join(dir, "signed")
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: signed, Key: key, Keys: keysJSON, Version: "1.4.0"}); err != nil {
		t.Fatal(err)
	}
	check(signed, "")
	ours, err := os.ReadFile(filepath.Join(signed, sigName))
	if err != nil {
		t.Fatal(err)
	}
	if theirs := relsign("index", "-signer", signerPEM, "-site", defaultBaseURL, "-version", "1.4.0", "-file", filepath.Join(signed, indexName)); string(theirs) != string(ours) {
		t.Fatalf("relsign signs the same index differently\n dgo     %s relsign %s", ours, theirs)
	}

	// The reverse: dgo builds the unsigned draft, relsign signs it, dgo verifies it.
	draft := filepath.Join(dir, "draft")
	if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: draft, Version: "1.5.0"}); err != nil {
		t.Fatal(err)
	}
	put := func(name string, body []byte) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(draft, name), body, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	relsigned := relsign("index", "-signer", signerPEM, "-site", defaultBaseURL, "-version", "1.5.0", "-file", filepath.Join(draft, indexName))
	put(keysName, keysJSON)
	put(sigName, relsigned)
	check(draft, "")

	// Whatever relsign signs for something else is refused where the index's signature belongs.
	payload := filepath.Join(dir, "dgo-core")
	if err := os.WriteFile(payload, []byte("pretend DGO core"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name      string
		keys, sig []byte
		want      string
	}{
		{"a core manifest relsign signed", keysJSON, relsign("manifest", "-signer", signerPEM, "-site", defaultBaseURL, "-version", "1.6.0",
			"-target", "linux/amd64", "-url", defaultBaseURL+"/dgo-core", "-file", payload, "-expires", "30d"), "payloadType"},
		{"relsign's key list for the download site", relsign("keys", "-signer", rootPEM, "-site", "https://digital-office.co.il/dl",
			"-version", "3", "-key", signerPEM, "-types", trust.IndexType), relsigned, "key list of https://digital-office.co.il/dl"},
		{"a key list relsign scoped to core manifests", relsign("keys", "-signer", rootPEM, "-site", defaultBaseURL, "-version", "2",
			"-key", signerPEM, "-types", trust.ManifestType), relsigned, "does not trust that key to sign " + trust.IndexType},
	} {
		put(keysName, tc.keys)
		put(sigName, tc.sig)
		check(draft, tc.want)
	}
}

// The fixed prefixes are exactly what crypto/x509 writes for an Ed25519 key — PKCS#8 for the private
// half (relsign keygen's MarshalPKCS8PrivateKey), PKIX for the public one; and a roots file is read as
// the stub reads roots.txt.
func TestKeysAreTheShapesX509Writes(t *testing.T) {
	t.Parallel()
	key, other := newKey(t), newKey(t)
	der, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	got, err := parsePrivateKey(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))
	if err != nil || !bytes.Equal(got, key) {
		t.Fatalf("PKCS#8 from x509: %v", err)
	}
	pder, err := x509.MarshalPKIXPublicKey(key.Public())
	if err != nil {
		t.Fatal(err)
	}
	b64 := func(k ed25519.PrivateKey) string {
		return base64.StdEncoding.EncodeToString(k.Public().(ed25519.PublicKey))
	}
	rootsOf := func(text string) string {
		t.Helper()
		roots, err := trust.ParseRoots(text)
		if err != nil {
			t.Fatal(err)
		}
		return trust.RootsID(roots)
	}
	dir := t.TempDir()
	file := func(name string, body []byte) string {
		t.Helper()
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, body, 0o644); err != nil {
			t.Fatal(err)
		}
		return p
	}
	for name, tc := range map[string]struct {
		raw   []byte
		roots string
	}{
		"pem-public-key":        {pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: pder}), rootsOf(b64(key))},
		"relsign-pubkey-base64": {[]byte(b64(key) + "\n"), rootsOf(b64(key))},
		"roots-txt-two-roots":   {[]byte("# the office's roots\n" + b64(key) + "\n" + b64(other) + " # the spare\n"), rootsOf(b64(key) + "," + b64(other))},
	} {
		if roots, err := readRoots(file(name, tc.raw)); err != nil || trust.RootsID(roots) != tc.roots {
			t.Errorf("%s: %v", name, err)
		}
	}
	for name, tc := range map[string]struct {
		raw  []byte
		want string
	}{
		"private-key":   {pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), "PRIVATE"},
		"no-root":       {[]byte("# no root yet\n"), "names no root"},
		"not-base64":    {[]byte("not a key!\n"), "not a base64 Ed25519 public key"},
		"another-pem":   {pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: []byte{1}}), "not an Ed25519 PUBLIC KEY"},
		"half-of-a-key": {[]byte(b64(key)[:20] + "\n"), "not a base64 Ed25519 public key"},
	} {
		if _, err := readRoots(file(name, tc.raw)); err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s: a root file must be refused with %q, got %v", name, tc.want, err)
		}
	}
	if _, err := parsePrivateKey([]byte("-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n")); err == nil {
		t.Error("a PEM that is not an Ed25519 PKCS#8 key must be refused")
	}
}

// signedTree is a built, signed index of one app, and the chain that signed it.
func signedTree(t *testing.T) (string, *chain) {
	t.Helper()
	c := newChain(t)
	out := filepath.Join(t.TempDir(), "index")
	if _, err := Build(Options{Root: repoRoot(t), Source: tree(t, map[string]string{"apps/a/app.json": manifest("a", "")}), Out: out,
		Key: c.key, Keys: c.keys, Version: signedVersion}); err != nil {
		t.Fatal(err)
	}
	return out, c
}

// seal writes doc as the envelope of typ, signed by key, into path — as relsign and Build write one.
func seal(t *testing.T, path string, key ed25519.PrivateKey, typ string, doc any) {
	t.Helper()
	body, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	env, err := trust.Seal(key, typ, body)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, append(env, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}
}

// resign writes a signature over the index as it now is: its document for version and site, by key.
func resign(t *testing.T, dir string, key ed25519.PrivateKey, version, site string) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir, indexName))
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(raw)
	seal(t, filepath.Join(dir, sigName), key, trust.IndexType,
		trust.IndexDoc{Site: site, Version: version, SHA256: hex.EncodeToString(sum[:]), Size: int64(len(raw))})
}

// forge edits the document inside the signature and keeps the signature — all a mirror without a key can do.
func forge(t *testing.T, dir string, edit func(map[string]any)) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir, sigName))
	if err != nil {
		t.Fatal(err)
	}
	var env trust.Envelope
	var doc map[string]any
	if err := json.Unmarshal(raw, &env); err != nil {
		t.Fatal(err)
	}
	body, _ := base64.StdEncoding.DecodeString(env.Payload)
	if err := json.Unmarshal(body, &doc); err != nil {
		t.Fatal(err)
	}
	edit(doc)
	body, _ = json.Marshal(doc)
	env.Payload = base64.StdEncoding.EncodeToString(body)
	raw, _ = json.Marshal(env)
	if err := os.WriteFile(filepath.Join(dir, sigName), raw, 0o644); err != nil {
		t.Fatal(err)
	}
}

func rewrite(t *testing.T, path, from, to string) {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(raw, []byte(from)) {
		t.Fatalf("%s holds no %q", path, from)
	}
	if err := os.WriteFile(path, bytes.Replace(raw, []byte(from), []byte(to), 1), 0o644); err != nil {
		t.Fatal(err)
	}
}

// Every refusal is the point: a good index verifying proves little, a bad one not verifying is the
// guarantee.
func TestVerifyRefuses(t *testing.T) {
	t.Parallel()
	const staging = "https://staging.example.org/v1"
	cases := []struct {
		name    string
		tamper  func(t *testing.T, dir string, c *chain) string // returns the roots file to use
		baseURL string
		want    string
	}{
		{"no root", func(t *testing.T, dir string, c *chain) string { return "" }, "", "needs its root"},
		{"another root", func(t *testing.T, dir string, c *chain) string { return rootFile(t, newKey(t)) }, "", "unknown signer"},
		{"no signature", func(t *testing.T, dir string, c *chain) string {
			os.Remove(filepath.Join(dir, sigName))
			return c.rootFile
		}, "", "no signature"},
		{"only the draft", func(t *testing.T, dir string, c *chain) string {
			os.Rename(filepath.Join(dir, sigName), filepath.Join(dir, draftName))
			return c.rootFile
		}, "", "UNSIGNED draft"},
		{"no key list", func(t *testing.T, dir string, c *chain) string {
			os.Remove(filepath.Join(dir, keysName))
			return c.rootFile
		}, "", "no key list"},
		{"a key list another root signed", func(t *testing.T, dir string, c *chain) string {
			os.WriteFile(filepath.Join(dir, keysName), keyList(t, newKey(t), defaultBaseURL, 1, listed(c.key, trust.IndexType)), 0o644)
			return c.rootFile
		}, "", "unknown signer"},
		{"a key list that names the key for core manifests only", func(t *testing.T, dir string, c *chain) string {
			os.WriteFile(filepath.Join(dir, keysName), keyList(t, c.root, defaultBaseURL, 2, listed(c.key, trust.ManifestType)), 0o644)
			return c.rootFile
		}, "", "does not trust that key to sign " + trust.IndexType},
		{"an altered index", func(t *testing.T, dir string, c *chain) string {
			rewrite(t, filepath.Join(dir, indexName), `"kind": "service"`, `"kind": "tool"`)
			return c.rootFile
		}, "", "the index was altered"},
		{"an altered signed version", func(t *testing.T, dir string, c *chain) string {
			forge(t, dir, func(d map[string]any) { d["version"] = "9.9.9" })
			return c.rootFile
		}, "", "does not verify"},
		{"a core manifest where the index's signature belongs", func(t *testing.T, dir string, c *chain) string {
			raw, _ := os.ReadFile(filepath.Join(dir, indexName))
			sum := sha256.Sum256(raw)
			seal(t, filepath.Join(dir, sigName), c.key, trust.ManifestType, trust.ManifestDoc{Site: defaultBaseURL, Version: signedVersion,
				Expires: "2099-01-01T00:00:00Z", MinBootstrapper: "0.0.0", Target: "linux/amd64", PayloadURL: defaultBaseURL + "/" + indexName,
				SHA256: hex.EncodeToString(sum[:]), Size: int64(len(raw))})
			return c.rootFile
		}, "", "payloadType"},
		{"a signature for plain http", func(t *testing.T, dir string, c *chain) string {
			resign(t, dir, c.key, signedVersion, "http://apps.net.digital-office.co.il/v1")
			return c.rootFile
		}, "", "it is the index of http://"},
		{"another channel's index", func(t *testing.T, dir string, c *chain) string {
			resign(t, dir, c.key, signedVersion, staging)
			return c.rootFile
		}, "", "it is the index of " + staging},
		{"this channel's index read as another's", func(t *testing.T, dir string, c *chain) string { return c.rootFile }, staging, "key list of " + defaultBaseURL},
		{"versions that disagree", func(t *testing.T, dir string, c *chain) string {
			resign(t, dir, c.key, "2.0.0", defaultBaseURL)
			return c.rootFile
		}, "", "its signature"},
		{"another format", func(t *testing.T, dir string, c *chain) string {
			rewrite(t, filepath.Join(dir, indexName), indexFormat, "bina.catalog/v2")
			resign(t, dir, c.key, signedVersion, defaultBaseURL)
			return c.rootFile
		}, "", "unsupported format"},
		{"an index larger than any", func(t *testing.T, dir string, c *chain) string {
			f, _ := os.OpenFile(filepath.Join(dir, indexName), os.O_APPEND|os.O_WRONLY, 0)
			f.Write(make([]byte, maxIndex))
			f.Close()
			resign(t, dir, c.key, signedVersion, defaultBaseURL)
			return c.rootFile
		}, "", "larger than"},
	}
	for _, c := range cases {
		dir, ch := signedTree(t)
		root := c.tamper(t, dir, ch)
		var out, errb bytes.Buffer
		if code := verify(dir, root, c.baseURL, &out, &errb); code != 1 || !strings.Contains(errb.String(), c.want) {
			t.Errorf("%s: exit %d, stderr %q — want 1 and %q", c.name, code, errb.String(), c.want)
		}
	}

	// the index is intact but an artifact is not: the chain's last link, reported per entry — a
	// changed size before a byte is read, changed bytes by their hash
	for _, c := range []struct{ name, want string }{{"grown", "is not the "}, {"altered", "  TAMPERED a: sha256 "}} {
		dir, ch := signedTree(t)
		zipPath := filepath.Join(dir, artifactsDir, "a-0.0.0.zip")
		raw, _ := os.ReadFile(zipPath)
		if c.name == "grown" {
			raw = append(raw, 0)
		} else {
			raw[len(raw)-1] ^= 1
		}
		os.WriteFile(zipPath, raw, 0o644)
		var out, errb bytes.Buffer
		if code := verify(dir, ch.rootFile, "", &out, &errb); code != 1 || !strings.Contains(out.String(), c.want) || !strings.Contains(out.String(), "VERIFY FAILED — 1 entry(ies)") {
			t.Errorf("a %s artifact: exit %d\n%s%s", c.name, code, out.String(), errb.String())
		}
	}
}

// The trust memory: an index older than the newest this machine accepted from the site under its
// roots is refused, and so is another index under a version already seen; a newer one moves it on.
func TestTheTrustMemoryNeverGoesBack(t *testing.T) {
	t.Parallel()
	c := newChain(t)
	build := func(version, notes string) string {
		out := filepath.Join(t.TempDir(), "index")
		src := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/a/notes.txt": notes})
		if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: out, Key: c.key, Keys: c.keys, Version: version}); err != nil {
			t.Fatal(err)
		}
		return out
	}
	v2, v1, v2b, v3 := build("2.0.0", "two"), build("1.0.0", "one"), build("2.0.0", "two, again"), build("3.0.0", "three")
	for _, step := range []struct {
		dir  string
		code int
		want string
	}{
		{v2, 0, ""},
		{v1, 1, "older than 2.0.0"},
		{v2b, 1, "one version, one index"},
		{v2, 0, ""},
		{v3, 0, ""},
		{v2, 1, "older than 3.0.0"},
	} {
		var out, errb bytes.Buffer
		if code := verify(step.dir, c.rootFile, "", &out, &errb); code != step.code || !strings.Contains(errb.String(), step.want) {
			t.Fatalf("verify %s: exit %d (want %d), stderr %q", step.dir, code, step.code, errb.String())
		}
	}
}

// The chain's recovery, end to end: a leaked key's index 9.0.0 holds this machine until the root's next
// key list drops that key — then the release signed by a key never listed before verifies. The new list
// is remembered as soon as it is read, even when the index beside it is refused, so the old list,
// replayed with the leaked key's index, is refused as a list this machine has passed.
func TestARevokedKeysIndexGivesWayToTheNextKeys(t *testing.T) {
	t.Parallel()
	c := newChain(t) // c.key leaks
	build := func(version string, key ed25519.PrivateKey, keys []byte) string {
		out := filepath.Join(t.TempDir(), "index")
		src := tree(t, map[string]string{"apps/a/app.json": manifest("a", ""), "apps/a/notes.txt": version})
		if _, err := Build(Options{Root: repoRoot(t), Source: src, Out: out, Key: key, Keys: keys, Version: version}); err != nil {
			t.Fatal(err)
		}
		return out
	}
	next := newKey(t)
	revoked := keyList(t, c.root, defaultBaseURL, 2, listed(next, trust.IndexType))
	for _, step := range []struct {
		dir  string
		code int
		want string
	}{
		{build("9.0.0", c.key, c.keys), 0, ""},                    // the leaked key's push, while it is listed
		{build("1.5.0", next, c.keys), 1, "unknown signer"},       // the next key, before the root lists it
		{build("9.0.1", c.key, revoked), 1, "unknown signer"},     // list 2 drops the leaked key: its index refused
		{build("9.1.0", c.key, c.keys), 1, "replayed or revoked"}, // list 1 replayed with the leaked key
		{build("1.5.0", next, revoked), 0, ""},                    // the release, by the key list 2 names
	} {
		var out, errb bytes.Buffer
		if code := verify(step.dir, c.rootFile, "", &out, &errb); code != step.code || !strings.Contains(errb.String(), step.want) {
			t.Fatalf("verify %s: exit %d (want %d), stderr %q", step.dir, code, step.code, errb.String())
		}
	}
}

func TestVerifyReadsOnlyInsideTheTree(t *testing.T) {
	t.Parallel()
	for _, u := range []string{"../outside.zip", "/etc/passwd", `C:\x.zip`, `artifacts\..\..\x.zip`, "https://evil.example/a.zip"} {
		dir, c := signedTree(t)
		rewrite(t, filepath.Join(dir, indexName), `"url": "artifacts/a-0.0.0.zip"`, `"url": "`+strings.ReplaceAll(u, `\`, `\\`)+`"`)
		resign(t, dir, c.key, signedVersion, defaultBaseURL)
		var out, errb bytes.Buffer
		if code := verify(dir, c.rootFile, "", &out, &errb); code != 1 || !strings.Contains(out.String(), "is not a file of this tree") {
			t.Errorf("artifact url %q: exit %d\n%s%s", u, code, out.String(), errb.String())
		}
	}
}

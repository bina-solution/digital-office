// Command dgo-install is the tiny, signed bootstrapper the DGO website hands you — one small EXE
// (Windows), one small binary inside a DMG (macOS), or one small file / one-line download (Linux).
// It is deliberately minimal: a welcome, terms acceptance, then it downloads and VERIFIES "DGO core"
// and launches it. DGO core is what then provisions the container engine and runs the install wizard
// (a separate, larger binary — not this stub).
//
// SECURITY MODEL — why this is not just `curl | run`. The stub's OWN signature (Authenticode on
// Windows, notarization on macOS) proves who shipped THE STUB; it says nothing about the bytes the
// stub later downloads. So the payload is verified here against a MANIFEST that is Ed25519-signed by
// a release key whose PUBLIC half is baked into this binary at build time. No key or no manifest URL
// baked in ⇒ the stub refuses to do anything (fail-closed): this template never silently trusts.
// Forward-only: it will not install a version older than the one already present.
//
// Build (release): go build -trimpath -ldflags "-s -w \
//     -X main.pubKeyB64=<ed25519 public key, std base64> \
//     -X main.manifestURL=https://digital-office.co.il/dl/<os>/<arch>/manifest.json \
//     -X main.version=<stub version>"
// Cross-compile for every OS from one host: GOOS=windows|darwin|linux GOARCH=amd64|arm64 go build .
package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// Baked in at build time (see the build line above). Empty ⇒ this is the unconfigured template.
var (
	pubKeyB64   string
	manifestURL string
	version     = "dev"
)

const terms = `DGO — Digital Office. By continuing you accept the terms at https://digital-office.co.il/terms.
This installer will download DGO core (verified against a signed manifest) and run it on this computer.`

// manifest is what the website serves per OS/arch. `sig` is Ed25519 over the exact bytes
// signedMessage() returns, so re-ordering or re-encoding the JSON cannot change what was signed.
type manifest struct {
	Version    string `json:"version"`     // forward-only: must be newer than what is installed
	PayloadURL string `json:"payload_url"` // HTTPS, and the SAME host as the manifest
	SHA256     string `json:"sha256"`      // hex, of the payload bytes
	SigB64     string `json:"sig"`         // base64 Ed25519 signature over signedMessage()
}

func (m manifest) signedMessage() []byte {
	return []byte(m.Version + "\n" + m.PayloadURL + "\n" + strings.ToLower(m.SHA256))
}

func main() {
	accept := flag.Bool("accept-terms", false, "accept the terms and proceed without prompting")
	printTerms := flag.Bool("terms", false, "print the terms and exit")
	dest := flag.String("dest", defaultDest(), "directory to install DGO core into")
	noLaunch := flag.Bool("no-launch", false, "download and verify only; do not launch DGO core")
	showVer := flag.Bool("version", false, "print the stub version and exit")
	flag.Parse()

	if *showVer {
		fmt.Println("dgo-install", version, runtime.GOOS+"/"+runtime.GOARCH)
		return
	}
	if *printTerms {
		fmt.Println(terms)
		return
	}
	if err := run(*accept, *dest, *noLaunch); err != nil {
		fmt.Fprintln(os.Stderr, "dgo-install: "+err.Error())
		os.Exit(1)
	}
}

func run(accept bool, dest string, noLaunch bool) error {
	fmt.Println("Welcome to DGO — Digital Office.")
	fmt.Println()
	fmt.Println(terms)
	fmt.Println()
	if !accept {
		return fmt.Errorf("terms not accepted — re-run with --accept-terms (or --terms to read them)")
	}

	// fail-closed: an unconfigured template verifies nothing, so it must do nothing.
	if strings.TrimSpace(pubKeyB64) == "" || strings.TrimSpace(manifestURL) == "" {
		return fmt.Errorf("this is an unconfigured template build (no release key / manifest URL baked in); " +
			"a real release injects -X main.pubKeyB64=… and -X main.manifestURL=…")
	}
	pub, err := base64.StdEncoding.DecodeString(strings.TrimSpace(pubKeyB64))
	if err != nil || len(pub) != ed25519.PublicKeySize {
		return fmt.Errorf("baked-in public key is not a valid Ed25519 key")
	}

	man, err := fetchManifest(&http.Client{Timeout: 30 * time.Second}, manifestURL)
	if err != nil {
		return err
	}
	if !ed25519.Verify(ed25519.PublicKey(pub), man.signedMessage(), mustB64(man.SigB64)) {
		return fmt.Errorf("manifest signature does not verify against the baked-in release key — refusing")
	}
	// payload must come from the SAME host as the manifest, over HTTPS.
	if err := sameHTTPSHost(manifestURL, man.PayloadURL); err != nil {
		return err
	}
	if cur := installedVersion(dest); cur != "" && !semverLess(cur, man.Version) {
		fmt.Printf("DGO core %s is already installed (manifest offers %s) — nothing to do.\n", cur, man.Version)
		return nil
	}

	if err := os.MkdirAll(dest, 0o755); err != nil {
		return err
	}
	payload := filepath.Join(dest, payloadName())
	fmt.Printf("Downloading DGO core %s …\n", man.Version)
	sum, err := download(man.PayloadURL, payload)
	if err != nil {
		return err
	}
	if !strings.EqualFold(sum, man.SHA256) {
		_ = os.Remove(payload)
		return fmt.Errorf("payload sha256 mismatch (got %s, manifest %s) — refusing and removing", sum, man.SHA256)
	}
	if runtime.GOOS != "windows" {
		_ = os.Chmod(payload, 0o755)
	}
	_ = os.WriteFile(filepath.Join(dest, "VERSION"), []byte(man.Version+"\n"), 0o644)
	fmt.Printf("Verified DGO core %s (sha256 %s).\n", man.Version, man.SHA256)

	if noLaunch {
		fmt.Println("Done (--no-launch): run", payload, "to start DGO core.")
		return nil
	}
	fmt.Println("Launching DGO core …")
	cmd := exec.Command(payload)
	cmd.Stdout, cmd.Stderr, cmd.Stdin = os.Stdout, os.Stderr, os.Stdin
	return cmd.Run()
}

func fetchManifest(client *http.Client, u string) (manifest, error) {
	var m manifest
	if pu, err := url.Parse(u); err != nil || pu.Scheme != "https" {
		return m, fmt.Errorf("manifest URL must be https")
	}
	resp, err := client.Get(u)
	if err != nil {
		return m, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return m, fmt.Errorf("manifest fetch: HTTP %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return m, err
	}
	if err := json.Unmarshal(body, &m); err != nil {
		return m, fmt.Errorf("manifest is not valid JSON: %w", err)
	}
	if m.Version == "" || m.PayloadURL == "" || m.SHA256 == "" || m.SigB64 == "" {
		return m, fmt.Errorf("manifest is missing a required field (version/payload_url/sha256/sig)")
	}
	return m, nil
}

func download(u, dst string) (string, error) {
	client := &http.Client{Timeout: 30 * time.Minute}
	resp, err := client.Get(u)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("payload fetch: HTTP %d", resp.StatusCode)
	}
	f, err := os.Create(dst)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(io.MultiWriter(f, h), resp.Body); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// sameHTTPSHost refuses a payload served over plain HTTP or from a different host than the manifest.
func sameHTTPSHost(manURL, payURL string) error {
	mu, err := url.Parse(manURL)
	if err != nil {
		return err
	}
	pu, err := url.Parse(payURL)
	if err != nil {
		return fmt.Errorf("payload URL is not a URL")
	}
	if pu.Scheme != "https" {
		return fmt.Errorf("payload URL must be https")
	}
	if !strings.EqualFold(pu.Host, mu.Host) {
		return fmt.Errorf("payload host %q differs from manifest host %q — refusing", pu.Host, mu.Host)
	}
	return nil
}

func installedVersion(dest string) string {
	b, err := os.ReadFile(filepath.Join(dest, "VERSION"))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

// semverLess reports whether a < b for dotted-numeric versions (1.2.0 < 1.10.0). A non-numeric field
// compares as 0, which is conservative: an unparseable installed version never blocks a real update.
func semverLess(a, b string) bool {
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

func payloadName() string {
	if runtime.GOOS == "windows" {
		return "dgo-core.exe"
	}
	return "dgo-core"
}

func defaultDest() string {
	if d, err := os.UserHomeDir(); err == nil {
		return filepath.Join(d, ".dgo", "core")
	}
	return filepath.Join(".", "dgo-core-install")
}

func mustB64(s string) []byte {
	b, _ := base64.StdEncoding.DecodeString(strings.TrimSpace(s))
	return b
}

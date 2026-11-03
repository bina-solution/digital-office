// Command dgo-install is the tiny, signed bootstrapper the DGO website hands you — one small EXE
// (Windows), one small binary inside a DMG (macOS), or one small file / one-line download (Linux).
// It is deliberately minimal: a welcome, terms acceptance, then it downloads and VERIFIES "DGO core"
// and launches it. DGO core is what then provisions the container engine and runs the install wizard
// (a separate, larger binary — not this stub).
//
// SECURITY MODEL — why this is not just `curl | run`. The stub's OWN signature (Authenticode on
// Windows, notarization on macOS) proves who shipped THE STUB; it says nothing about the bytes the
// stub later downloads. So those bytes are trusted only through a chain that starts at root keys whose
// PUBLIC halves are in this binary (packaging/trust, the office's one signed-document layer): the
// committed roots.txt, embedded — no build flag can put other roots in a stub. A root signs keys.json, a
// key it lists signs the manifest, the manifest pins the payload's size and sha256. No roots or no
// download site ⇒ a development build, which says so on its first screen and installs nothing.
// Forward-only: it never installs a version older than the one present, nor accepts a manifest older
// than one this computer accepted or than keys.json's core_floor — and once a key is revoked, the root's
// core_floor takes the place of what it vouched for (trust.KeyList's Settle and Binds), so the real
// release undoes a leaked key's push.
//
// SIZE is part of the contract — at most 4 MiB per target, which packaging/build-binaries.sh enforces.
// So no net/http (https.go is the client), no encoding/json (packaging/trust reads the documents with
// its own reader) and no os/exec (os.StartProcess launches the core): on windows/amd64 that took this
// binary from 5,327,872 to 4,093,440 bytes, the key layer included.
//
// Build (release) — packaging/build-binaries.sh passes exactly these; the roots come from roots.txt:
//
//	go build -trimpath -ldflags "-s -w \
//	    -X main.siteURL=https://digital-office.co.il/dl \
//	    -X main.keysFloor=<version>:<sha256 of the payload of the keys.json current at build time> \
//	    -X main.version=<stub version>"
//
// Cross-compile for every OS from one host: GOOS=windows|darwin|linux GOARCH=amd64|arm64 go build .
package main

import (
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

// rootKeys is the committed roots.txt: the release roots' PUBLIC keys, the whole of what a stub trusts.
// A []byte because the linker's -X sets only string variables: -X main.rootKeys=… is a build error,
// never a silent stand-in for the reviewed file.
//
//go:embed roots.txt
var rootKeys []byte

// Baked in at build time (see the build line above). No site ⇒ a development build.
var (
	siteURL   string // keys.json and <os>/<arch>/manifest.json live under it
	keysFloor string // "version:sha256" of the keys.json current when this stub was built ("" = none)
	version   = "dev"
)

const terms = `DGO — Digital Office. By continuing you accept the terms at https://digital-office.co.il/terms.
This installer will download DGO core (verified against a signed manifest) and run it on this computer.`

const devNotice = `This is a DEVELOPMENT build of the DGO installer: no release keys are built into it, so it
will not download or install anything. Release builds come from packaging/build-binaries.sh --sign-key.`

const (
	maxDocBytes = 64 << 10 // keys.json or a manifest, envelope included
	docTimeout  = 30 * time.Second
	coreTimeout = 30 * time.Minute
)

func main() {
	accept := flag.Bool("accept-terms", false, "accept the terms and proceed without prompting")
	printTerms := flag.Bool("terms", false, "print the terms and exit")
	dest := flag.String("dest", defaultDest(), "directory to install DGO core into")
	noLaunch := flag.Bool("no-launch", false, "download and verify only; do not launch DGO core")
	showVer := flag.Bool("version", false, "print the stub version and exit")
	flag.Parse()

	target := runtime.GOOS + "/" + runtime.GOARCH
	if *showVer {
		dev := ""
		if isDevBuild(siteURL, string(rootKeys)) {
			dev = " (development build: no release keys)"
		}
		fmt.Println("dgo-install", version, target+dev)
		return
	}
	if *printTerms {
		fmt.Println(terms)
		return
	}
	built, err := trust.ParseFloor(keysFloor)
	if err != nil {
		fmt.Fprintln(os.Stderr, "dgo-install: "+err.Error())
		os.Exit(1)
	}
	in := install{site: siteURL, roots: string(rootKeys), built: built, stub: version, target: target, state: statePath(),
		dest: *dest, accept: *accept, noLaunch: *noLaunch, now: time.Now(), out: os.Stdout,
		net: getter{agent: "dgo-install/" + version}}
	if err := in.run(); err != nil {
		fmt.Fprintln(os.Stderr, "dgo-install: "+err.Error())
		os.Exit(1)
	}
}

// install is one run of the stub with everything it depends on, so a test can run it whole against
// its own TLS server, keys, clock and directories.
type install struct {
	site, roots, stub string     // built in: the download site, the roots (roots.txt), this stub's version
	built             trust.Seen // the key list this stub was built with: no older list, no other one at its version
	target            string     // GOOS/GOARCH
	state             string     // the file that remembers accepted versions ("" = no config dir to keep it in)
	dest              string     // where DGO core goes
	accept, noLaunch  bool
	now               time.Time // fixed when the run begins
	out               io.Writer
	net               getter
}

func (in install) run() error {
	dev := isDevBuild(in.site, in.roots)
	fmt.Fprintln(in.out, "Welcome to DGO — Digital Office.")
	if dev {
		fmt.Fprintln(in.out)
		fmt.Fprintln(in.out, devNotice)
	}
	fmt.Fprintln(in.out)
	fmt.Fprintln(in.out, terms)
	fmt.Fprintln(in.out)
	if dev {
		return errors.New("a development build installs nothing: no release keys or download site are built in (fail-closed)")
	}
	if !in.accept {
		return fmt.Errorf("terms not accepted — re-run with --accept-terms (or --terms to read them)")
	}
	roots, err := trust.ParseRoots(in.roots)
	if err != nil {
		return fmt.Errorf("the built-in %w", err)
	}
	if in.state == "" {
		return errors.New("no user configuration directory to remember accepted versions in — refusing")
	}
	id := trust.RootsID(roots)
	last, err := trust.LoadSeen(in.state, in.site, id)
	if err != nil {
		return err
	}
	last.ManifestSum = "" // a core manifest pins no bytes: the stub's line is the six fields it always was
	c := trust.Checker{Roots: roots, Site: in.site, Type: trust.ManifestType, Now: in.now, Stub: in.stub, Target: in.target,
		Seen: last, Built: in.built}

	var doc bytes.Buffer
	if _, err := in.net.get(in.site+"/keys.json", maxDocBytes, docTimeout, &doc); err != nil {
		return fmt.Errorf("fetching keys.json: %w", err)
	}
	kl, err := c.VerifyKeys(doc.Bytes())
	if err != nil {
		return err
	}
	// Remembered at once, before the manifest is even fetched — the list, and the floor it settles: a key
	// list that retired a key or stated a core_floor must stick on this computer even when this run goes
	// no further (an expired manifest, a stub too old, a 404).
	c.Seen = kl.Settle(c.Seen)
	c.Seen.Keys, c.Seen.KeysSum = kl.Version, kl.Sum
	if err := trust.SaveSeen(in.state, seenHeader, in.site, id, c.Seen, kl.Stands); err != nil {
		return fmt.Errorf("remembering the accepted key list: %w", err)
	}
	doc.Reset()
	if _, err := in.net.get(in.site+"/"+in.target+"/manifest.json", maxDocBytes, docTimeout, &doc); err != nil {
		return fmt.Errorf("fetching the manifest: %w", err)
	}
	man, err := c.VerifyManifest(doc.Bytes(), kl)
	if err != nil {
		return err
	}
	beside := kl.Besides(man.Signer)
	c.Seen.Manifest, c.Seen.ManifestBy, c.Seen.Beside = man.Version, man.Signer, beside
	if err := trust.SaveSeen(in.state, seenHeader, in.site, id, c.Seen, kl.Stands); err != nil {
		return fmt.Errorf("remembering the accepted versions: %w", err)
	}
	fmt.Fprintf(in.out, "Verified the manifest for %s: DGO core %s, signed under key list %d, valid until %s.\n",
		man.Target, man.Version, kl.Version, trust.Stamp(man.Expires))

	payload := filepath.Join(in.dest, payloadName(in.target))
	switch rec := readRecord(in.dest); {
	case rec.version == "":
	case intact(payload, rec.sum) && kl.Binds(rec.signer, rec.beside, man.Signer):
		// Forward-only, over a core this stub can still vouch for: its bytes are the ones recorded at
		// install (so another build signed under the same version cannot swap it back and forth) and
		// the key that signed them is still listed — or, revoked with no core_floor in its place, was
		// listed beside this release's key (Binds).
		if !trust.SemverLess(rec.version, man.Version) {
			fmt.Fprintf(in.out, "DGO core %s is already installed (manifest offers %s) — nothing to do.\n", rec.version, man.Version)
			return nil
		}
	default:
		// Damaged (a power cut), unrecorded, or vouched for by a revoked key that no longer binds this
		// release's key — what a leaked key installed is replaced by the real release, whatever their
		// numbers: the manifest has already met the floor the root put in the leaked key's place.
		fmt.Fprintf(in.out, "The installed DGO core %s is damaged, unrecorded, or signed by a key keys.json no longer lists — installing %s in its place.\n",
			rec.version, man.Version)
	}
	fmt.Fprintf(in.out, "Downloading DGO core %s (%d bytes) …\n", man.Version, man.Size)
	if err := in.fetchPayload(man, payload); err != nil {
		return err
	}
	if err := writeRecord(in.dest, record{version: man.Version, sum: man.SHA256, signer: man.Signer, beside: beside}); err != nil {
		return err
	}
	fmt.Fprintf(in.out, "Verified DGO core %s (sha256 %s).\n", man.Version, man.SHA256)

	if in.noLaunch {
		fmt.Fprintln(in.out, "Done (--no-launch): run", payload, "to start DGO core.")
		return nil
	}
	fmt.Fprintln(in.out, "Launching DGO core …")
	return launch(payload)
}

// record is VERSION beside the core: its first line the installed version (as it always was), then the
// sha256 of the bytes installed and who vouched for them — the key that signed their manifest and the
// keys listed beside it ("signer k2,k1") — what makes "already installed" a fact this stub can check
// rather than a claim it must take.
type record struct{ version, sum, signer, beside string }

func readRecord(dest string) record {
	b, err := os.ReadFile(filepath.Join(dest, "VERSION"))
	if err != nil {
		return record{}
	}
	lines := strings.Split(strings.TrimSpace(string(b)), "\n")
	r := record{version: strings.TrimSpace(lines[0])}
	for _, l := range lines[1:] {
		switch k, v, _ := strings.Cut(strings.TrimSpace(l), " "); k {
		case "sha256":
			r.sum = v
		case "signer":
			r.signer, r.beside, _ = strings.Cut(v, ",")
		}
	}
	return r
}

func writeRecord(dest string, r record) error {
	return os.WriteFile(filepath.Join(dest, "VERSION"), []byte(r.version+"\nsha256 "+r.sum+"\nsigner "+trust.VouchedBy(r.signer, r.beside)+"\n"), 0o644)
}

// intact reports whether the core on disk still hashes to the sha256 recorded at install.
func intact(path, want string) bool {
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()
	h := sha256.New()
	_, err = io.Copy(h, f)
	return err == nil && len(want) == 64 && hex.EncodeToString(h.Sum(nil)) == want
}

// fetchPayload downloads DGO core into a file of its own beside the core and moves it into place only
// when its size and sha256 are the manifest's: an interrupted, forged or concurrent download never costs
// the user the core they had, and a refused one is deleted. The name is unique per run, so two runs at
// once never rename each other's unverified bytes into place.
func (in install) fetchPayload(man trust.Manifest, dst string) error {
	if err := os.MkdirAll(in.dest, 0o755); err != nil {
		return err
	}
	// The downloads of runs that died: older than any run's deadline, so nobody writes them any more
	// (on Windows one still open simply refuses to go).
	if entries, err := os.ReadDir(in.dest); err == nil {
		for _, e := range entries {
			name := e.Name()
			if info, err := e.Info(); err == nil && strings.HasPrefix(name, filepath.Base(dst)+".") &&
				strings.HasSuffix(name, ".part") && time.Since(info.ModTime()) > coreTimeout {
				_ = os.Remove(filepath.Join(in.dest, name))
			}
		}
	}
	f, err := os.CreateTemp(in.dest, filepath.Base(dst)+".*.part")
	if err != nil {
		return err
	}
	part := f.Name()
	h := sha256.New()
	n, err := in.net.get(man.PayloadURL, man.Size, coreTimeout, io.MultiWriter(f, h))
	if err == nil {
		err = f.Chmod(0o755) // CreateTemp makes it 0600; the core must be executable
	}
	if err == nil {
		err = f.Sync() // on disk before the rename: a power cut leaves the old core or the new one
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	switch got := hex.EncodeToString(h.Sum(nil)); {
	case err != nil:
		err = fmt.Errorf("downloading DGO core: %w", err)
	case n != man.Size:
		err = fmt.Errorf("DGO core is %d bytes, the manifest says %d — refusing and removing it", n, man.Size)
	case got != man.SHA256:
		err = fmt.Errorf("payload sha256 mismatch (got %s, manifest %s) — refusing and removing it", got, man.SHA256)
	default:
		err = replaceFile(part, dst)
	}
	if err != nil {
		_ = os.Remove(part)
	}
	return err
}

// replaceFile moves the verified download over the core. Windows refuses to overwrite a running .exe
// but lets it be renamed, so there the old core steps aside first — and comes back if the move fails.
func replaceFile(part, dst string) error {
	err := os.Rename(part, dst) // elsewhere a rename replaces even a running binary
	if err == nil || runtime.GOOS != "windows" {
		return err
	}
	old := dst + ".old"
	_ = os.Remove(old) // the last update's, unless it is still running
	aside := false
	if _, err := os.Stat(dst); err == nil {
		if err := retried(func() error { return os.Rename(dst, old) }); err != nil {
			return fmt.Errorf("moving the installed DGO core aside: %w", err)
		}
		aside = true
	}
	if err = retried(func() error { return os.Rename(part, dst) }); err != nil && aside {
		_ = retried(func() error { return os.Rename(old, dst) })
	}
	return err
}

// retried runs a file operation until it succeeds or about two seconds pass. On Windows a virus scanner
// holds a freshly written .exe open for a moment, and a rename fails until it lets go — cmd/go's
// robustio waits out the same thing.
func retried(op func() error) error {
	err := op()
	for wait := 10 * time.Millisecond; err != nil && wait <= time.Second; wait *= 2 {
		time.Sleep(wait)
		err = op()
	}
	return err
}

// launch runs DGO core on this terminal and returns when it ends. os.StartProcess rather than os/exec:
// the path is known, so os/exec's PATH lookup and plumbing would only add 143 KB.
func launch(path string) error {
	p, err := os.StartProcess(path, []string{path}, &os.ProcAttr{Files: []*os.File{os.Stdin, os.Stdout, os.Stderr}})
	if err != nil {
		return err
	}
	st, err := p.Wait()
	if err == nil && !st.Success() {
		err = errors.New("DGO core ended with " + st.String())
	}
	return err
}

// isDevBuild: no download site, or a roots file that names no root (as roots.txt does until the
// owner's key ceremony) — such a stub installs nothing.
func isDevBuild(site, roots string) bool {
	rs, err := trust.ParseRoots(roots)
	return strings.TrimSpace(site) == "" || err == nil && len(rs) == 0
}

// statePath is where accepted versions are remembered: the user's configuration directory (%AppData%
// on Windows, ~/Library/Application Support on macOS, $XDG_CONFIG_HOME or ~/.config on Linux).
func statePath() string {
	d, err := os.UserConfigDir()
	if err != nil {
		return ""
	}
	return filepath.Join(d, "dgo", "install-state")
}

// seenHeader opens the state file (trust.SaveSeen writes the lines under it).
const seenHeader = "# dgo-install: per download site and set of built-in roots, the newest keys.json (version, sha256) and\n" +
	"# manifest (version, the key that signed it and the keys listed beside it) this computer accepted; - is\n" +
	"# none. Removing this file forgets them — it weakens rollback protection, it never blocks an install.\n"

func payloadName(target string) string {
	if strings.HasPrefix(target, "windows/") {
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

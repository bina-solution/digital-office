// Package store is the app store's signed static index — step 9 of ai/context/dgo-architecture-2026.md
// (Plane DGO-599): `dgo index build`, `dgo index verify` and `dgo index install --dry-run`.
//
// ONE TOP-LEVEL WORD. Everything here hangs under `index`, which no app id, cli.alias or bbox verb
// uses. Not `install`: `bbox install debian|windows|macos` provisions a host and `dgo install …`
// reaches it today through the hand-off to bbox — a store verb by that name would take it away.
//
// WHAT AN INDEX IS. Static files, served by any CDN, any mirror or a USB stick — no compute on the
// install path, the one firm conclusion of ai/context/research/package-registry.md:
//
//	https://apps.net.digital-office.co.il/v1/index.json         every installable app, and what the platform provides
//	https://apps.net.digital-office.co.il/v1/index.sig.json     its signature: the dgo-app-index document {site, version, sha256, size}
//	https://apps.net.digital-office.co.il/v1/keys.json          the root-signed key list that names the key that signed it
//	https://apps.net.digital-office.co.il/v1/artifacts/<id>-<version>.zip   each app's directory, packed
//
// One chain covers the tree — a root → keys.json → the signature → the index's sha256 → each
// artifact's sha256 — so a mirror is a copy of the tree that cannot change a byte unseen (catalog.py's
// F-Droid model, kept); artifact URLs are relative so the tree works wherever it is copied. What a
// mirror CAN do is serve an older index, which a signature never stops verifying, or another channel's:
// so the signature names this store's site (--base-url picks another channel), and every verification
// is held to the newest index this machine accepted from the site under its roots (the trust memory
// under DGO_HOME, ~/.dgo), to the root's index_floor in keys.json, and to the index a dgo.lock was
// resolved against.
//
// THE ENTRIES ARE catalog.py's. Every field platform/manager/catalog.py's entry_from_manifest()
// publishes, with the same values, and the same files in each artifact — names, bytes, dates, modes:
// TestIndexMatchesCatalogPy runs catalog.py's build on the same tree and compares the two field by
// field and member by member. The artifact's size and sha256 are this build's own — zlib and
// compress/flate are different deflaters.
//
// THE TRUST IS THE OFFICE'S ONE CHAIN (packaging/trust), the installer stub's own: a DSSE envelope of
// type dgo-app-index, signed by a key a root's keys.json lists for that type, for this store's site,
// under this machine's floor. One key format (PKCS#8 PEM), one signer (`relsign index` signs the same
// document into the same file, byte for byte), one verifier. catalog.py's envelope and keyring stay
// what `bbox catalog` uses.
//
// ON PURPOSE UNLIKE catalog.py: no `generated` clock — the same tree, flags and key give the same
// bytes, signature included, whatever the builder's git config; the index names its own `version`
// (the signed one) and its `platform` (the capabilities layers 1–2 provide, so a plan can tell "the
// office already has it" from "nothing provides it"); and it refuses what catalog.py would publish —
// a manifest the compiler refuses, a junction outside git (catalog.py's walk descends into one, out
// of the app), two names that differ only in case, a git that fails (catalog.py then packs whatever
// is on disk, untracked secrets included), a compose file yamlish cannot read, a port it would have
// to spell as Python syntax, a path that leaves the app.
package store

import (
	"flag"
	"fmt"
	"io"
	"strings"
)

// Verbs are the store's top-level words. Every OS answers them in-process (nothing here needs the
// engine, so on Windows they stay on the host like the compiler's verbs), and they have no Python
// twin to roll back to: `bbox catalog` and `bbox app install` stay the Python store, untouched.
var Verbs = map[string]func(root string, args []string, stdout, stderr io.Writer) int{
	"index": indexVerb,
}

const usage = `usage:
  dgo index build <out-dir> [--key <key.pem> --keys <keys.json> --version <x.y.z>] [--base-url <https-url>] [--source <dir>] [--name <text>]
  dgo index verify <dir> --root <roots-file> [--base-url <https-url>]
  dgo index install --dry-run --index <dir> --root <roots-file> [--base-url <https-url>] [--lock <file>] <app>[@<version>]
`

func indexVerb(root string, args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprint(stderr, usage)
		return 2
	}
	fs := flags(stderr)
	switch args[0] {
	case "build":
		o := Options{Root: root}
		key := fs.String("key", "", "")
		keys := fs.String("keys", "", "")
		fs.StringVar(&o.Version, "version", "", "")
		fs.StringVar(&o.BaseURL, "base-url", "", "")
		fs.StringVar(&o.Source, "source", "", "")
		fs.StringVar(&o.Name, "name", "", "")
		pos, ok := parse(fs, args[1:], 1)
		if !ok {
			return 2
		}
		o.Out = pos[0]
		if *key != "" {
			k, err := loadPrivateKey(*key)
			if err != nil {
				fmt.Fprintln(stderr, "dgo index build: "+err.Error())
				return 1
			}
			o.Key = k
		}
		if *keys != "" {
			k, err := readCapped(*keys, maxSig)
			if err != nil {
				fmt.Fprintln(stderr, "dgo index build: --keys: "+err.Error())
				return 1
			}
			o.Keys = k
		}
		b, err := Build(o)
		if err != nil {
			fmt.Fprintln(stderr, "dgo index build: "+err.Error())
			return 1
		}
		b.report(stdout)
		return 0
	case "verify":
		rootKey := fs.String("root", "", "")
		baseURL := fs.String("base-url", "", "")
		pos, ok := parse(fs, args[1:], 1)
		if !ok {
			return 2
		}
		return verify(pos[0], *rootKey, *baseURL, stdout, stderr)
	case "install":
		dry := fs.Bool("dry-run", false, "")
		dir := fs.String("index", "", "")
		rootKey := fs.String("root", "", "")
		baseURL := fs.String("base-url", "", "")
		lock := fs.String("lock", "", "")
		pos, ok := parse(fs, args[1:], 1)
		if !ok {
			return 2
		}
		if !*dry {
			// Placing an app is still platform/manager/appinstall.py's (`bbox app install`): it validates
			// the unpacked manifest against the office's own catalog and enables it through the
			// lifecycle. This verb plans; it does not pretend to install.
			fmt.Fprintln(stderr, "dgo index install: only --dry-run is native so far — installing is `bbox app install`")
			return 2
		}
		if *dir == "" {
			fmt.Fprint(stderr, "dgo index install: --index <dir> is required\n"+usage)
			return 2
		}
		app, want, _ := strings.Cut(pos[0], "@")
		return install(*dir, *rootKey, *baseURL, app, want, *lock, stdout, stderr)
	}
	fmt.Fprint(stderr, usage)
	return 2
}

// flags is a FlagSet that reports to the verb's stderr and prints the store's usage.
func flags(stderr io.Writer) *flag.FlagSet {
	fs := flag.NewFlagSet("dgo", flag.ContinueOnError)
	fs.SetOutput(stderr)
	fs.Usage = func() { fmt.Fprint(stderr, usage) }
	return fs
}

// parse lets flags come after the positionals too (`dgo index build out --key k.pem`), which the
// stdlib's FlagSet alone does not, and requires exactly n positionals.
func parse(fs *flag.FlagSet, args []string, n int) ([]string, bool) {
	var pos []string
	for {
		if fs.Parse(args) != nil {
			return nil, false
		}
		if fs.NArg() == 0 {
			break
		}
		pos = append(pos, fs.Arg(0))
		args = fs.Args()[1:]
	}
	if len(pos) != n {
		fs.Usage()
		return nil, false
	}
	return pos, true
}

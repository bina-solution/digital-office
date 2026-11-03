package store

import (
	"cmp"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

// indexDoc is the part of index.json the reading side uses.
type indexDoc struct {
	Format   string              `json:"format"`
	Version  string              `json:"version"`
	Platform map[string][]string `json:"platform"`
	Entries  []indexEntry        `json:"entries"`
}

type indexEntry struct {
	ID       string `json:"id"`
	Version  string `json:"version"`
	Provides []struct {
		Name string `json:"name"`
	} `json:"provides"`
	Uses []struct {
		Capability string `json:"capability"`
		Strength   string `json:"strength"`
	} `json:"uses"`
	Artifact struct {
		URL    string `json:"url"`
		SHA256 string `json:"sha256"`
		Size   int64  `json:"size"`
	} `json:"artifact"`
	sv semver
}

func (e *indexEntry) provides(capability string) bool {
	for _, p := range e.Provides {
		if p.Name == capability {
			return true
		}
	}
	return false
}

// header is what both readers say first: which index, and what proved it.
func header(w io.Writer, v *verified) {
	fmt.Fprintf(w, "index: %s\n", filepath.Join(v.dir, indexName))
	fmt.Fprintf(w, "  signature OK (ed25519, key %s of key list %d) — version %s, %s\n", v.by, v.keys, v.doc.Version, v.url())
	fmt.Fprintf(w, "  %d entry(ies)\n", len(v.index.Entries))
}

// verify is `dgo index verify`: the signature, then every artifact against the hash the signed index
// names — catalog.py's `bbox catalog verify`, its per-entry lines word for word.
func verify(dir, rootFile, baseURL string, stdout, stderr io.Writer) int {
	v, err := loadVerified(dir, rootFile, baseURL)
	if err != nil {
		fmt.Fprintln(stderr, "index REFUSED: "+err.Error())
		return 1
	}
	header(stdout, v)
	bad := 0
	for _, e := range v.index.Entries {
		if line := check(dir, e); line != "" {
			fmt.Fprintln(stdout, line)
			bad++
			continue
		}
		fmt.Fprintf(stdout, "  ok       %-24s v%-8s sha256:%s…\n", e.ID, e.Version, short(e.Artifact.SHA256))
	}
	if bad > 0 {
		fmt.Fprintf(stdout, "VERIFY FAILED — %d entry(ies) do not match the signed index\n", bad)
		return 1
	}
	fmt.Fprintln(stdout, "VERIFY OK — signature and every per-entry hash match")
	return 0
}

// check is one artifact against its entry: "" when it matches, else the line that says why. The
// signed size is checked before a byte is read, and the hash streams — a mirror cannot make verify
// read more than the index promised.
func check(dir string, e indexEntry) string {
	// only a path inside this tree is read: a signed index still never sends a read elsewhere
	u := e.Artifact.URL
	if c := path.Clean(u); u == "" || strings.ContainsAny(u, `:\`) || path.IsAbs(c) || c == ".." || strings.HasPrefix(c, "../") {
		return fmt.Sprintf("  MISSING  %s: %q is not a file of this tree", e.ID, u)
	}
	p := filepath.Join(dir, filepath.FromSlash(u))
	f, err := os.Open(p)
	if err != nil {
		return fmt.Sprintf("  MISSING  %s: %s (%s)", e.ID, p, pyError(err))
	}
	defer f.Close()
	if st, err := f.Stat(); err != nil || st.Size() != e.Artifact.Size {
		return fmt.Sprintf("  TAMPERED %s: %s is not the %d bytes the index signs", e.ID, u, e.Artifact.Size)
	}
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return fmt.Sprintf("  MISSING  %s: %s (%s)", e.ID, p, pyError(err))
	}
	if got := hex.EncodeToString(h.Sum(nil)); got != e.Artifact.SHA256 {
		return fmt.Sprintf("  TAMPERED %s: sha256 %s… != %s…", e.ID, got[:16], short(e.Artifact.SHA256))
	}
	return ""
}

// pyError names an error as catalog.py's MISSING line does: by the Python exception it would be.
func pyError(err error) string {
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return "FileNotFoundError"
	case errors.Is(err, fs.ErrPermission):
		return "PermissionError"
	}
	return "OSError"
}

// install is `dgo index install --dry-run`: resolve from a verified index, print the plan, write
// nothing but the lock when one is asked for — and never move a lock back to an older index.
func install(dir, rootFile, baseURL, app, want, lockPath string, stdout, stderr io.Writer) int {
	refused := func(err error) int {
		fmt.Fprintln(stderr, "dgo index install: index REFUSED: "+err.Error())
		return 1
	}
	v, err := loadVerified(dir, rootFile, baseURL)
	if err != nil {
		return refused(err)
	}
	if lockPath != "" {
		if err := fresher(v, lockPath); err != nil {
			return refused(err)
		}
	}
	header(stdout, v)
	p, errs := resolve(&v.index, app, want)
	if len(errs) > 0 {
		for _, e := range errs {
			fmt.Fprintln(stderr, "  ERROR "+e)
		}
		return 1
	}
	p.print(stdout)
	if lockPath == "" {
		fmt.Fprintln(stdout, "dry run — nothing was written")
		return 0
	}
	if err := os.WriteFile(lockPath, p.lock(v), 0o644); err != nil {
		fmt.Fprintln(stderr, "dgo index install: "+err.Error())
		return 1
	}
	fmt.Fprintf(stdout, "dry run — nothing was written but the lock: %s\n", lockPath)
	return 0
}

// fresher refuses an index older than the one an existing lock was resolved against, another index
// under the same version, or one from another channel: a lock never goes back. Index versions are the
// release versions the signature names, ordered as this machine's floor orders them (trust.SemverLess).
func fresher(v *verified, lockPath string) error {
	raw, err := os.ReadFile(lockPath)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	var old struct {
		Format string `json:"format"`
		Index  struct {
			Version string `json:"version"`
			URL     string `json:"url"`
			SHA256  string `json:"sha256"`
		} `json:"index"`
	}
	ok := json.Unmarshal(raw, &old) == nil && old.Format == lockFormat && trust.ValidVersion(old.Index.Version)
	nv, ov := v.doc.Version, old.Index.Version
	switch {
	case !ok:
		return fmt.Errorf("%s is not a %s — refusing to overwrite it", lockPath, lockFormat)
	case old.Index.URL != v.url():
		return fmt.Errorf("%s was resolved against %s, and this index is %s", lockPath, old.Index.URL, v.url())
	case trust.SemverLess(nv, ov):
		return fmt.Errorf("index %s is older than %s, which %s was resolved against — a lock never goes back", nv, ov, lockPath)
	case !trust.SemverLess(ov, nv) && old.Index.SHA256 != v.doc.SHA256:
		return fmt.Errorf("index %s is not the %s %s was resolved against — one version, one index", nv, ov, lockPath)
	}
	return nil
}

// ── resolution: minimal version selection over the index ────────────────────────────────────────

// A plan is a resolved request: the build list, who needs each app and for what, and what the
// platform is relied on for.
type plan struct {
	request  string
	root     *indexEntry
	apps     []*indexEntry                  // the build list, by id
	needs    map[string]map[string][]string // provider id → capability → the apps that require it
	platform map[string][]string            // capability → the layer 1–2 apps the index says provide it
}

// resolve picks the request's version — the one asked for, else the highest release — and then the
// build list by minimal version selection (Cox, "Minimal Version Selection", algorithm 1): walk every
// app version the requirement graph reaches from the root; each app's selected version is the
// highest one reached.
//
// A manifest's use[] names a capability, not a version, so the minimum MVS needs is the minimal
// version that SATISFIES it: the lowest RELEASE of the provider that provides that capability — not
// merely the oldest version that exists, and never a pre-release, which is installed only when asked
// for by name (`app@1.2.0-rc.1`), as the request. Higher versions come in only when something in the
// graph needs them, so a new release in the index changes no plan by itself; a lock pins the rest.
// What gets installed is what the SELECTED versions need: a version MVS passed over may raise
// another app's version, but brings no app of its own.
//
// A capability's provider is chosen by the compiler's rules as far as an index carries them: the
// HARD strengths pull one in (compiler.Hard), the sole candidate is chosen, and more than one is a
// refusal naming them all — an index has no office state to bind one with, and catalog.py's entries
// never published default_provider or a provider's ops, so neither is decided here. Several that are
// all layers 1–2 are no refusal: the plan installs none of them either way, and relies on the platform.
// The compiler decides both again on the unpacked manifests when the app is placed (appinstall.py's
// step 5).
func resolve(ix *indexDoc, app, want string) (*plan, []string) {
	byID := map[string][]*indexEntry{}
	var errs []string
	for i := range ix.Entries {
		e := &ix.Entries[i]
		sv, ok := parseSemver(e.Version)
		if !ok {
			errs = append(errs, fmt.Sprintf("%s: version %q in the index is not SemVer", e.ID, e.Version))
			continue
		}
		e.sv = sv
		byID[e.ID] = append(byID[e.ID], e)
	}
	ids := make([]string, 0, len(byID))
	for id, vs := range byID {
		ids = append(ids, id)
		sort.SliceStable(vs, func(i, j int) bool { return less(vs[i], vs[j]) })
		for i := 1; i < len(vs); i++ {
			if vs[i].Version == vs[i-1].Version {
				errs = append(errs, fmt.Sprintf("%s@%s is in the index twice", id, vs[i].Version))
			}
		}
	}
	sort.Strings(ids)
	if len(errs) > 0 {
		return nil, errs
	}
	vs := byID[app]
	if len(vs) == 0 {
		return nil, []string{fmt.Sprintf("no app '%s' in the index (have: %s)", app, strings.Join(ids, ", "))}
	}
	var root *indexEntry
	var have []string
	for _, e := range vs {
		have = append(have, e.Version)
		if (want == "" && len(e.sv.pre) == 0) || e.Version == want {
			root = e // ascending: the last release, or the one asked for
		}
	}
	switch {
	case root == nil && want == "":
		return nil, []string{fmt.Sprintf("%s has only pre-releases (%s) — ask for one by version", app, strings.Join(have, ", "))}
	case root == nil:
		return nil, []string{fmt.Sprintf("%s@%s is not in the index (versions: %s)", app, want, strings.Join(have, ", "))}
	}

	// capability → the index apps that provide it in some version, and each one's minimal satisfying
	// version: its lowest release that provides it (the requested root counts, pre-release or not)
	capIDs := map[string][]string{}
	minimal := map[[2]string]*indexEntry{}
	for _, id := range ids {
		for _, e := range byID[id] {
			for _, p := range e.Provides {
				k := [2]string{id, p.Name}
				if !contains(capIDs[p.Name], id) {
					capIDs[p.Name] = append(capIDs[p.Name], id)
				}
				if minimal[k] == nil && (len(e.sv.pre) == 0 || e == root) {
					minimal[k] = e
				}
			}
		}
	}
	// sole is the one index app that answers a hard use, or "" when the platform does, nothing
	// does or several would (the build list's pass below names those).
	sole := func(capability string) string {
		if c := capIDs[capability]; len(c) == 1 && len(ix.Platform[capability]) == 0 {
			return c[0]
		}
		return ""
	}

	sel := map[string]*indexEntry{}
	seen := map[*indexEntry]bool{}
	for queue := []*indexEntry{root}; len(queue) > 0; queue = queue[1:] {
		e := queue[0]
		if seen[e] {
			continue
		}
		seen[e] = true
		if cur := sel[e.ID]; cur == nil || less(cur, e) {
			sel[e.ID] = e
		}
		for _, u := range e.Uses {
			if p := sole(u.Capability); compiler.Hard(u.Strength) && p != "" && p != e.ID && minimal[[2]string{p, u.Capability}] != nil {
				queue = append(queue, minimal[[2]string{p, u.Capability}])
			}
		}
	}
	if sel[root.ID] != root {
		return nil, []string{fmt.Sprintf("%s@%s was asked for, but what it requires needs %s@%s", root.ID, root.Version, root.ID, sel[root.ID].Version)}
	}
	need := map[string]bool{}
	for queue := []*indexEntry{root}; len(queue) > 0; queue = queue[1:] {
		e := queue[0]
		if need[e.ID] {
			continue
		}
		need[e.ID] = true
		for _, u := range e.Uses {
			if p := sole(u.Capability); compiler.Hard(u.Strength) && p != "" && p != e.ID && sel[p] != nil {
				queue = append(queue, sel[p])
			}
		}
	}

	// the build list's own requirements: who needs what, what the platform answers, what nothing does
	p := &plan{request: app, root: root, needs: map[string]map[string][]string{}, platform: map[string][]string{}}
	if want != "" {
		p.request += "@" + want
	}
	for _, id := range ids {
		e := sel[id]
		if !need[id] {
			continue
		}
		p.apps = append(p.apps, e)
		for _, u := range e.Uses {
			if !compiler.Hard(u.Strength) {
				continue
			}
			c, plat := capIDs[u.Capability], ix.Platform[u.Capability]
			switch {
			case len(c)+len(plat) == 0:
				errs = append(errs, fmt.Sprintf("%s: requires capability '%s' — no app in the index provides it, and the platform does not", id, u.Capability))
			case len(c) == 0:
				// only layers 1–2 answer it, and they ship with the platform: relied on, never
				// installed, whichever of several the office runs — the compiler picks that one when
				// the app is placed (identity: authentik and forward-auth)
				p.platform[u.Capability] = plat
			case len(c)+len(plat) > 1:
				all := append(append([]string{}, c...), plat...)
				sort.Strings(all)
				errs = append(errs, fmt.Sprintf("%s: capability '%s' has %d providers (%s) and an index has no rule to choose — the office's bindings decide it at install", id, u.Capability, len(all), strings.Join(all, ", ")))
			case c[0] == id && e.provides(u.Capability):
				// it provides what it uses
			case sel[c[0]] == nil:
				errs = append(errs, fmt.Sprintf("%s: requires capability '%s', which only pre-releases of %s provide — a plan never picks a pre-release it was not asked for", id, u.Capability, c[0]))
			case !sel[c[0]].provides(u.Capability):
				errs = append(errs, fmt.Sprintf("%s: requires capability '%s', which %s@%s — the version selected — does not provide", id, u.Capability, c[0], sel[c[0]].Version))
			default:
				if p.needs[c[0]] == nil {
					p.needs[c[0]] = map[string][]string{}
				}
				if r := p.needs[c[0]][u.Capability]; len(r) == 0 || r[len(r)-1] != id {
					p.needs[c[0]][u.Capability] = append(r, id)
				}
			}
		}
	}
	sort.Strings(errs)
	return p, dedupe(errs)
}

func less(a, b *indexEntry) bool {
	if c := a.sv.compare(b.sv); c != 0 {
		return c < 0
	}
	return a.Version < b.Version // equal precedence (build metadata only): any fixed order
}

func contains(xs []string, x string) bool {
	for _, v := range xs {
		if v == x {
			return true
		}
	}
	return false
}

func dedupe(xs []string) []string {
	out := xs[:0]
	for i, x := range xs {
		if i == 0 || x != xs[i-1] {
			out = append(out, x)
		}
	}
	return out
}

// print is the plan, one app per line, each with the capabilities it is installed for.
func (p *plan) print(w io.Writer) {
	fmt.Fprintf(w, "plan: %s — %d app(s), %d capability(ies) from the platform\n", p.request, len(p.apps), len(p.platform))
	for _, e := range p.apps {
		var why []string
		if e == p.root {
			why = append(why, "requested")
		}
		for _, c := range sortedKeys(p.needs[e.ID]) {
			why = append(why, c+" ("+strings.Join(p.needs[e.ID][c], ", ")+")")
		}
		fmt.Fprintf(w, "  %-24s v%-8s %s\n", e.ID, e.Version, strings.Join(why, ", "))
	}
	if len(p.platform) > 0 {
		var parts []string
		for _, c := range sortedKeys(p.platform) {
			parts = append(parts, c+" ("+strings.Join(p.platform[c], ", ")+")")
		}
		fmt.Fprintf(w, "  platform: %s\n", strings.Join(parts, ", "))
	}
}

const lockFormat = "dgo.lock/v1"

// lock is dgo.lock: the build list pinned by version and artifact sha256, the index it came from,
// the platform capabilities it assumes. Fixed field order and sorted lists: the same plan is the
// same bytes, so a lock diffs as cleanly as it reads.
func (p *plan) lock(v *verified) []byte {
	type app struct {
		ID      string `json:"id"`
		Version string `json:"version"`
		SHA256  string `json:"sha256"`
	}
	l := struct {
		Format  string `json:"format"`
		Request string `json:"request"`
		Index   struct {
			Version string `json:"version"`
			URL     string `json:"url"`
			SHA256  string `json:"sha256"`
		} `json:"index"`
		Apps     []app    `json:"apps"`
		Platform []string `json:"platform"`
	}{Format: lockFormat, Request: p.request, Apps: []app{}, Platform: sortedKeys(p.platform)}
	l.Index.Version, l.Index.URL, l.Index.SHA256 = v.doc.Version, v.url(), v.doc.SHA256
	for _, e := range p.apps {
		l.Apps = append(l.Apps, app{e.ID, e.Version, e.Artifact.SHA256})
	}
	b, _ := json.MarshalIndent(l, "", "  ") // strings and lists of them cannot fail to encode
	return append(b, '\n')
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// ── SemVer 2.0.0 precedence ────────────────────────────────────────────────────────────────────

// semver is a version as precedence needs it: the three numbers as digit strings (compared by
// length, then bytes — no number is too big) and the pre-release identifiers. Build metadata never
// orders (§10), so it is checked and dropped.
type semver struct {
	num [3]string
	pre []string
}

func parseSemver(v string) (semver, bool) {
	var s semver
	rest, build, hasBuild := strings.Cut(v, "+")
	if hasBuild && !idents(build, false) {
		return s, false
	}
	core, pre, hasPre := strings.Cut(rest, "-")
	if hasPre {
		if !idents(pre, true) {
			return s, false
		}
		s.pre = strings.Split(pre, ".")
	}
	nums := strings.Split(core, ".")
	if len(nums) != 3 {
		return s, false
	}
	for i, n := range nums {
		if !number(n) {
			return s, false
		}
		s.num[i] = n
	}
	return s, true
}

// idents checks dot-separated [0-9A-Za-z-]+ identifiers; a pre-release's numeric ones have no
// leading zero.
func idents(s string, pre bool) bool {
	for _, id := range strings.Split(s, ".") {
		if id == "" || strings.Trim(id, "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-") != "" {
			return false
		}
		if pre && digits(id) && !number(id) {
			return false
		}
	}
	return true
}

func digits(s string) bool { return s != "" && strings.Trim(s, "0123456789") == "" }
func number(s string) bool { return digits(s) && (s == "0" || s[0] != '0') }

func (a semver) compare(b semver) int {
	for i := range a.num {
		if c := cmpNum(a.num[i], b.num[i]); c != 0 {
			return c
		}
	}
	if len(a.pre) == 0 || len(b.pre) == 0 {
		return cmp.Compare(len(b.pre), len(a.pre)) // a release outranks its pre-releases
	}
	for i := 0; i < len(a.pre) && i < len(b.pre); i++ {
		x, y := a.pre[i], b.pre[i]
		var c int
		switch dx, dy := digits(x), digits(y); {
		case dx && dy:
			c = cmpNum(x, y)
		case dx:
			c = -1 // numeric identifiers rank below alphanumeric ones
		case dy:
			c = 1
		default:
			c = strings.Compare(x, y)
		}
		if c != 0 {
			return c
		}
	}
	return cmp.Compare(len(a.pre), len(b.pre))
}

func cmpNum(x, y string) int {
	if c := cmp.Compare(len(x), len(y)); c != 0 {
		return c
	}
	return strings.Compare(x, y)
}

package store

import (
	"archive/zip"
	"bytes"
	"cmp"
	"compress/flate"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
)

const (
	indexName      = "index.json"
	sigName        = "index.sig.json"          // the index document (trust.IndexType), signed
	draftName      = "index.sig.unsigned.json" // build-binaries.sh's rule: an unsigned draft has a name no release has
	keysName       = "keys.json"               // the root-signed key list that names the signing key
	artifactsDir   = "artifacts"
	indexFormat    = "bina.catalog/v1" // catalog.py's INDEX_FORMAT, so `bbox catalog list|verify --insecure` read this index too
	defaultBaseURL = "https://apps.net.digital-office.co.il/v1"
	defaultName    = "bina-platform app catalog" // catalog.py's name with DEPLOYMENT_NAME unset: a flag, not the environment, changes it
	defaultVersion = "0.0.0-dev"
)

// appID is the schema's character class for an id, which names files, zip members and hosts: lower
// case only, so two ids never collide on a case-folding file system (a FAT mirror, the office's
// /mnt/c checkout), and nothing an unpacker reads as a separator. (The schema's length bound stays
// the compiler's to enforce, as all of `pattern` does.)
var appID = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*$`)

// Options is one build of the index. Empty strings take the defaults.
type Options struct {
	Root    string             // the checkout: its schema is what a manifest must pass to be published
	Source  string             // the tree published — the directory that holds apps/ and platform-base/ (Root)
	Out     string             // the directory the static files are written to, replaced whole on success
	Version string             // the index's own version, the one signed: SemVer, no leading v (0.0.0-dev, unsigned only)
	BaseURL string             // where Out will be served: the signed site (apps.net…/v1), whose index.json it is
	Name    string             // the catalog's display name, repo.name (catalog.py's default)
	Key     ed25519.PrivateKey // nil: an unsigned draft that verify refuses
	Keys    []byte             // keys.json, published beside the signature: a root's list naming Key for the index
}

// Built is what one build wrote.
type Built struct {
	Out      string
	Entries  []map[string]any
	Platform map[string][]string
	Doc      trust.IndexDoc // the index document: signed, or the unsigned draft
	Signed   bool
	Links    []string // "<id>/<path>" of every link left out of an artifact, never followed
}

// Build compiles Source's catalog into Out: index.json, its signature (or an unsigned draft) and one
// artifact per installable app. Layer 3 only, as catalog.py: layers 1–2 are the chassis, installed
// with the platform and refused by the installer, so they appear only as `platform` — the
// capabilities a plan may rely on the office already having.
//
// Everything is written into a fresh directory beside Out and swapped in when the last byte is
// written: a build that fails — or is still running — never touches the index Out serves.
func Build(o Options) (*Built, error) {
	switch {
	case o.Key != nil && o.Version == "":
		return nil, errors.New("a signed index needs --version: clients refuse to go back to a lower one, so each signed index names its own")
	case o.Key != nil && !trust.ValidVersion(o.Version):
		return nil, fmt.Errorf("--version %q: a signed index needs a release version — dotted numbers, 1.4.0 — which every machine's floor can order", o.Version)
	case o.Key != nil && len(o.Keys) == 0:
		return nil, fmt.Errorf("a signed index needs --keys: the root-signed key list naming --key for %s, published beside the signature", trust.IndexType)
	case o.Key == nil && len(o.Keys) > 0:
		return nil, errors.New("--keys goes with --key: an unsigned draft publishes no key list")
	}
	o.Source, o.Version = cmp.Or(o.Source, o.Root), cmp.Or(o.Version, defaultVersion)
	o.BaseURL, o.Name = cmp.Or(o.BaseURL, defaultBaseURL), cmp.Or(o.Name, defaultName)
	if _, ok := parseSemver(o.Version); !ok {
		return nil, fmt.Errorf("--version %q is not SemVer (a release passes its tag without the v: 1.4.0)", o.Version)
	}
	base := strings.TrimRight(o.BaseURL, "/")
	if !strings.HasPrefix(base, "https://") {
		return nil, fmt.Errorf("--base-url %q must be https — the signed site is, as relsign and the installer require", o.BaseURL)
	}
	// --source is the tree that HOLDS apps/ — not catalog.py's directory of app folders. Given that,
	// or a typo, the catalog loader finds nothing, and an empty index would be signed and served.
	if st, err := os.Stat(filepath.Join(o.Source, "apps")); err != nil || !st.IsDir() {
		return nil, fmt.Errorf("--source %s holds no apps/ — it names the tree that holds apps/ and platform-base/, not catalog.py's directory of app folders", o.Source)
	}
	cat, err := compiler.LoadCatalog(o.Source)
	if err != nil {
		return nil, err
	}
	// A store must not publish what the platform refuses to install: the compiler's own validator,
	// which catalog.py never ran (appinstall.py runs it only after the download).
	errs, _, err := compiler.Validate(o.Root, cat)
	if err != nil {
		return nil, err
	}
	if len(errs) > 0 {
		return nil, errors.New("MANIFEST VALIDATION FAILED:\n  - " + strings.Join(errs, "\n  - "))
	}
	b := &Built{Out: o.Out, Platform: map[string][]string{}}
	var apps []*compiler.App
	for _, id := range cat.Order {
		app := cat.Apps[id]
		if app.Root != "apps" {
			caps, err := app.List("capabilities")
			if err != nil {
				return nil, err
			}
			for _, c := range caps {
				if name, ok := c["name"].(string); ok {
					b.Platform[name] = append(b.Platform[name], id)
				}
			}
			continue
		}
		if !appID.MatchString(id) {
			return nil, fmt.Errorf("%q: an id is lower-case letters, digits and hyphens (%s)", id, appID)
		}
		apps = append(apps, app)
	}
	if len(apps) == 0 {
		return nil, fmt.Errorf("%s holds no app — an empty index is never built", filepath.Join(o.Source, "apps"))
	}
	if err := replaceable(o.Out); err != nil {
		return nil, err
	}
	parent := filepath.Dir(filepath.Clean(o.Out))
	if err := os.MkdirAll(parent, 0o755); err != nil {
		return nil, err
	}
	tmp, err := os.MkdirTemp(parent, "."+filepath.Base(o.Out)+".build-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(tmp) // nothing left behind on failure; gone already after the swap
	if err := os.Mkdir(filepath.Join(tmp, artifactsDir), 0o755); err != nil {
		return nil, err
	}

	// Packing is the whole cost of a build (best-level deflate over every file) and each artifact is
	// its own file, so the apps are packed side by side, one per CPU — the bytes do not depend on it.
	// The failure reported is the first in catalog order, whichever finished first.
	b.Entries = make([]map[string]any, len(apps))
	failed := make([]error, len(apps))
	links := make([][]string, len(apps))
	var wg sync.WaitGroup
	cpu := make(chan struct{}, runtime.GOMAXPROCS(0))
	for i, app := range apps {
		wg.Add(1)
		go func() {
			defer wg.Done()
			cpu <- struct{}{}
			defer func() { <-cpu }()
			b.Entries[i], links[i], failed[i] = entry(app, tmp)
		}()
	}
	wg.Wait()
	for i, err := range failed {
		if err != nil {
			return nil, err
		}
		for _, l := range links[i] {
			b.Links = append(b.Links, apps[i].ID+"/"+l)
		}
	}
	// catalog.py sorts by id; the catalog's path order differs where one id is another's prefix (a, a-b)
	sort.Slice(b.Entries, func(i, j int) bool { return b.Entries[i]["id"].(string) < b.Entries[j]["id"].(string) })

	raw, err := encode(map[string]any{
		"format":   indexFormat,
		"version":  o.Version,
		"repo":     map[string]any{"name": o.Name, "artifact_base": artifactsDir + "/", "mirrors": []any{}},
		"platform": b.Platform,
		"entries":  b.Entries,
	})
	if err != nil {
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(tmp, indexName), raw, 0o644); err != nil {
		return nil, err
	}
	// The signature is the index document — what the index IS is its type (trust.IndexType), not a
	// field of the index — sealed as relsign seals it: `relsign index` writes these very bytes.
	sum := sha256.Sum256(raw)
	b.Doc = trust.IndexDoc{Site: base, Version: o.Version, SHA256: hex.EncodeToString(sum[:]), Size: int64(len(raw))}
	doc, err := json.Marshal(b.Doc)
	if err != nil {
		return nil, err
	}
	name := draftName
	if o.Key != nil {
		if doc, err = trust.Seal(o.Key, trust.IndexType, doc); err != nil {
			return nil, err
		}
		if err := os.WriteFile(filepath.Join(tmp, keysName), o.Keys, 0o644); err != nil {
			return nil, err
		}
		name, b.Signed = sigName, true
	}
	if err := os.WriteFile(filepath.Join(tmp, name), append(doc, '\n'), 0o644); err != nil {
		return nil, err
	}
	return b, swap(tmp, o.Out)
}

// replaceable refuses an Out that is not an index: a build replaces the whole directory, so
// `dgo index build .` must never take anything else with it.
func replaceable(out string) error {
	ents, err := os.ReadDir(out)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	foreign := func(name string) error {
		return fmt.Errorf("%s holds %s, which no index build wrote — build into an empty directory or a previous index's", out, name)
	}
	for _, e := range ents {
		switch n := e.Name(); {
		case (n == indexName || n == sigName || n == draftName || n == keysName) && e.Type().IsRegular():
		case n == artifactsDir && e.IsDir():
			zips, err := os.ReadDir(filepath.Join(out, n))
			if err != nil {
				return err
			}
			for _, z := range zips {
				if !z.Type().IsRegular() || !strings.HasSuffix(z.Name(), ".zip") {
					return foreign(n + "/" + z.Name())
				}
			}
		default:
			return foreign(n)
		}
	}
	return nil
}

// swap puts the finished tree in Out's place by renames: a reader finds the old index or the new
// one, never half of each, and stale artifacts leave with the old tree.
func swap(tmp, out string) error {
	if _, err := os.Lstat(out); errors.Is(err, fs.ErrNotExist) {
		return os.Rename(tmp, out)
	}
	old := tmp + ".old"
	if err := os.Rename(out, old); err != nil {
		return err
	}
	if err := os.Rename(tmp, out); err != nil {
		if rerr := os.Rename(old, out); rerr != nil {
			return fmt.Errorf("%v — and the previous index could not be put back: it is at %s", err, old)
		}
		return err
	}
	return os.RemoveAll(old)
}

// report prints what was built, in catalog.py's `bbox catalog build` words.
func (b *Built) report(w io.Writer) {
	ids := make([]string, len(b.Entries))
	for i, e := range b.Entries {
		ids[i] = e["id"].(string)
	}
	fmt.Fprintf(w, "index built: %s\n", b.Out)
	fmt.Fprintf(w, "  %d entry(ies): %s\n", len(b.Entries), strings.Join(ids, ", "))
	for _, e := range b.Entries {
		a := e["artifact"].(map[string]any)
		fmt.Fprintf(w, "    %-24s v%-8s %8d B  sha256:%s…  (%d files)\n", e["id"], e["version"], a["size"], a["sha256"].(string)[:16], a["files"])
	}
	fmt.Fprintf(w, "  platform: %d capability(ies) provided by layers 1–2\n", len(b.Platform))
	if len(b.Links) > 0 {
		fmt.Fprintf(w, "  left out, links are never followed: %s\n", strings.Join(b.Links, ", "))
	}
	d := b.Doc
	if b.Signed {
		fmt.Fprintf(w, "  signed: ed25519, %s %s for %s — %s, beside %s\n", trust.IndexType, d.Version, d.Site, sigName, keysName)
		return
	}
	fmt.Fprintf(w, "  UNSIGNED draft %s — verify refuses it until a key keys.json lists for %s signs it:\n", draftName, trust.IndexType)
	fmt.Fprintf(w, "    relsign index -signer <key.pem> -site %s -version %s -file %s > %s   (and %s beside it)\n",
		d.Site, d.Version, filepath.Join(b.Out, indexName), filepath.Join(b.Out, sigName), keysName)
}

// encode is the index's JSON: two-space indent and sorted keys like catalog.py's (encoding/json
// sorts map keys), characters as themselves, one trailing newline. LF only — the signature covers
// these bytes, so they must not depend on the OS that wrote them.
func encode(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	err := enc.Encode(v)
	return buf.Bytes(), err
}

// ── one entry: catalog.py's entry_from_manifest(), field for field ──────────────────────────────

// entry is one app's catalog entry and its artifact, written under out/artifacts/, and the links its
// directory holds, which the artifact leaves out.
func entry(app *compiler.App, out string) (map[string]any, []string, error) {
	m := app.Raw
	version, _ := or(m["version"], "0.0.0").(string)
	// The version names a file below, so one with `../` would write outside the artifacts directory.
	// SemVer cannot — refused by name, as catalog.py refuses it.
	if _, ok := parseSemver(version); !ok {
		return nil, nil, fmt.Errorf("%s: version %q is not SemVer — the index orders versions and names files by it", app.ID, version)
	}
	manifest, err := os.ReadFile(filepath.Join(app.Dir, "app.json"))
	if err != nil {
		return nil, nil, err
	}
	facts, err := composeFacts(app)
	if err != nil {
		return nil, nil, err
	}
	lists := map[string][]map[string]any{}
	for _, key := range []string{"routing", "capabilities", "use", "connections"} {
		if lists[key], err = app.List(key); err != nil {
			return nil, nil, err
		}
	}
	routing := []any{}
	for _, r := range lists["routing"] {
		module, _ := r["module"].(map[string]any)
		routing = append(routing, map[string]any{
			"host": r["host"], "port": r["port"], "auth": get(r, "auth", "sso"),
			"sso": compiler.Truthy(r["sso"]), "tile": compiler.Truthy(module["id"]),
		})
	}
	provides := []any{}
	for _, c := range lists["capabilities"] {
		provides = append(provides, map[string]any{"name": c["name"], "type": c["type"], "interface": c["interface"]})
	}
	uses := []any{}
	for _, u := range lists["use"] {
		uses = append(uses, map[string]any{"capability": u["capability"], "strength": get(u, "strength", "requires"), "ops": or(u["ops"], []any{})})
	}
	connections := []any{}
	for _, c := range lists["connections"] {
		connections = append(connections, map[string]any{"id": c["id"], "required": compiler.Truthy(get(c, "required", true))})
	}
	data, bp := object(m["data"]), object(m["blueprints"])
	n8n, _ := bp["n8n"].(string)
	n8n = strings.TrimSpace(n8n)
	workflows := 0
	if n8n != "" {
		// catalog.py joins the path as given — an absolute or `..` one counts files outside the app.
		// Inside the app, or refused.
		if leaves(n8n) {
			return nil, nil, fmt.Errorf("%s: blueprints.n8n %q leaves the app's directory", app.ID, n8n)
		}
		// A workflow is its id, the file's stem: n8n-as-code's <id>.workflow.ts, or a legacy <id>.json
		// beside them — one workflow when it is there in both forms (the identity apps/n8n/hooks/present
		// counts by). Exact suffixes, as catalog.py matches them: the count is the same on every OS.
		ids := map[string]bool{}
		ents, _ := os.ReadDir(filepath.Join(app.Dir, filepath.FromSlash(n8n)))
		for _, e := range ents {
			for _, suffix := range []string{".workflow.ts", ".json"} {
				if id, ok := strings.CutSuffix(e.Name(), suffix); ok {
					ids[id] = true
				}
			}
		}
		workflows = len(ids)
	}
	name := app.ID + "-" + version + ".zip"
	files, links, err := sources(app.Dir)
	if err != nil {
		return nil, nil, fmt.Errorf("%s: %v", app.ID, err)
	}
	size, sum, err := pack(app.Dir, app.ID, files, filepath.Join(out, artifactsDir, name))
	if err != nil {
		return nil, nil, fmt.Errorf("%s: packing %s: %v", app.ID, name, err)
	}
	digest := sha256.Sum256(manifest)
	return map[string]any{
		"id":              m["id"],
		"version":         version,
		"title":           or(m["title"], map[string]any{}),
		"summary":         or(m["summary"], map[string]any{}),
		"layer":           m["layer"],
		"kind":            m["kind"],
		"provides":        provides,
		"uses":            uses,
		"connections":     connections,
		"routing":         routing,
		"volumes":         or(data["volumes"], []any{}),
		"on_uninstall":    get(data, "on_uninstall", "prompt"),
		"resources":       or(m["resources"], map[string]any{}),
		"automations":     map[string]any{"n8n": n8n != "", "workflows": workflows, "requires_stdlib": bp["requires_stdlib"]},
		"runtime":         facts,
		"manifest_sha256": hex.EncodeToString(digest[:]),
		"artifact": map[string]any{"name": name, "format": "zip", "files": len(files), "size": size, "sha256": sum,
			"url": artifactsDir + "/" + name},
	}, links, nil
}

// or is Python's `v or def`.
func or(v, def any) any {
	if compiler.Truthy(v) {
		return v
	}
	return def
}

// get is Python's dict.get(key, def): the default only for an absent key — a present null stays null.
func get(m map[string]any, key string, def any) any {
	if v, ok := m[key]; ok {
		return v
	}
	return def
}

// object is `m.get(key) or {}` for a JSON object field.
func object(v any) map[string]any {
	if o, ok := v.(map[string]any); ok {
		return o
	}
	return map[string]any{}
}

// leaves is true for a manifest path that does not stay inside the app it is joined to.
func leaves(rel string) bool {
	if filepath.IsAbs(rel) || filepath.VolumeName(rel) != "" || strings.HasPrefix(rel, "/") || strings.HasPrefix(rel, `\`) {
		return true
	}
	for _, p := range strings.FieldsFunc(rel, func(r rune) bool { return r == '/' || r == '\\' }) {
		if p == ".." {
			return true
		}
	}
	return false
}

// composeFacts is catalog.py's _compose_facts(): what an app's compose file will do to the host —
// images, published ports, host mounts, the docker socket, privileged mode — read from the file that
// is executed, because the manifest does not say any of it.
func composeFacts(app *compiler.App) (map[string]any, error) {
	var images, ports, hostPaths []string
	var services []any
	socket, privileged := false, false
	facts := func() (map[string]any, error) {
		svc, ok := pyServices(services)
		if !ok {
			return nil, fmt.Errorf("%s: compose service names mix what YAML reads as strings, booleans and numbers — catalog.py cannot sort them", app.ID)
		}
		return map[string]any{"images": uniq(images), "ports": uniq(ports), "host_paths": uniq(hostPaths),
			"services": svc, "docker_socket": socket, "privileged": privileged}, nil
	}
	comp, _ := app.Raw["compose"].(string)
	if comp == "" {
		return facts()
	}
	if leaves(comp) {
		return nil, fmt.Errorf("%s: compose %q leaves the app's directory", app.ID, comp)
	}
	raw, err := os.ReadFile(filepath.Join(app.Dir, filepath.FromSlash(comp)))
	if err != nil {
		return facts() // catalog.py: no such file, or not readable — no facts
	}
	refuse := func(what string) error {
		return fmt.Errorf("%s: %s: %s — catalog.py would publish Python's spelling of it; this build refuses rather than imitate", app.ID, comp, what)
	}
	doc, err := yamlish.Unmarshal(raw)
	if err != nil {
		// PyYAML reads more YAML than yamlish does; publishing empty facts for a file that has real
		// ones would hide exactly what this disclosure exists to show, so the build stops instead.
		return nil, fmt.Errorf("%s: %s: %v", app.ID, comp, err)
	}
	if !compiler.Truthy(doc) {
		return facts()
	}
	dm, ok := doc.(*yamlish.Map)
	if !ok {
		return nil, refuse("the document is not a mapping")
	}
	sv, _ := dm.Get("services")
	if !compiler.Truthy(sv) {
		return facts()
	}
	sm, ok := sv.(*yamlish.Map)
	if !ok {
		return nil, refuse("services is not a mapping")
	}
	for _, name := range sm.Keys() {
		v, _ := sm.Get(name)
		spec, ok := v.(*yamlish.Map)
		if !ok {
			continue
		}
		key := sm.TypedKey(name) // `yes:` is True to PyYAML and `8080:` is 8080, and catalog.py publishes them so
		services = append(services, key)
		if img, _ := spec.Get("image"); compiler.Truthy(img) {
			s, ok := pyStr(img)
			if !ok {
				return nil, refuse("services." + name + ".image is not a scalar")
			}
			images = append(images, s)
		} else if build, _ := spec.Get("build"); compiler.Truthy(build) {
			s, ok := pyStr(key)
			if !ok {
				return nil, refuse("service " + name + " has a name YAML reads as a number with a fraction or as null")
			}
			images = append(images, "(built from source: "+s+")")
		}
		if p, _ := spec.Get("privileged"); compiler.Truthy(p) {
			privileged = true
		}
		pv, _ := spec.Get("ports")
		pl, ok := seq(pv)
		if !ok {
			return nil, refuse("services." + name + ".ports is not a list")
		}
		for _, prt := range pl {
			s, ok := pyStr(prt)
			if !ok {
				return nil, refuse("services." + name + ".ports has a long-syntax entry")
			}
			ports = append(ports, s)
		}
		vv, _ := spec.Get("volumes")
		vl, ok := seq(vv)
		if !ok {
			return nil, refuse("services." + name + ".volumes is not a list")
		}
		for _, x := range vl {
			s, isStr := x.(string)
			if !isStr {
				continue // long syntax: catalog.py looks only at the short form
			}
			if strings.Contains(s, "docker.sock") {
				socket = true
			}
			if src, _, _ := strings.Cut(s, ":"); strings.HasPrefix(src, "/") || strings.HasPrefix(src, ".") ||
				strings.HasPrefix(src, "~") || strings.HasPrefix(src, "$") {
				hostPaths = append(hostPaths, s)
			}
		}
	}
	return facts()
}

// pyServices is sorted(set(names)) over the service names as YAML typed them: strings by code point,
// booleans False before True, integers by value. A mix — or a float or a null — is what catalog.py
// cannot sort (TypeError) or no service is called, and is refused.
func pyServices(keys []any) ([]any, bool) {
	var strs []string
	var bools, ints []any
	for _, k := range keys {
		switch t := k.(type) {
		case string:
			strs = append(strs, t)
		case bool:
			bools = append(bools, t)
		case int64:
			ints = append(ints, t)
		default:
			return nil, false
		}
	}
	switch {
	case len(bools) == 0 && len(ints) == 0:
		out := []any{}
		for _, s := range uniq(strs) {
			out = append(out, s)
		}
		return out, true
	case len(strs) == 0 && len(ints) == 0:
		sort.Slice(bools, func(i, j int) bool { return !bools[i].(bool) && bools[j].(bool) })
		return bools, true // a mapping holds each key once: no duplicates to drop
	case len(strs) == 0 && len(bools) == 0:
		sort.Slice(ints, func(i, j int) bool { return ints[i].(int64) < ints[j].(int64) })
		return ints, true
	}
	return nil, false
}

// seq is `v or []` for a YAML list; false for a truthy value that is not one (Python would iterate
// a string's characters or a mapping's keys).
func seq(v any) ([]any, bool) {
	if !compiler.Truthy(v) {
		return nil, true
	}
	l, ok := v.([]any)
	return l, ok
}

// pyStr is str() of a YAML scalar — spelled by internal/pyval, the one copy of Python's spellings;
// false for what str() would spell as Python syntax, which this build refuses rather than publish.
func pyStr(v any) (string, bool) {
	switch v.(type) {
	case string, int64, bool, nil:
		return pyval.Str(v), true
	}
	return "", false
}

// uniq is sorted(set(xs)) — never nil, so it encodes as [] as catalog.py's does.
func uniq(xs []string) []string {
	sort.Strings(xs)
	out := []string{}
	for i, x := range xs {
		if i == 0 || x != xs[i-1] {
			out = append(out, x)
		}
	}
	return out
}

// ── the artifact: catalog.py's _sources() and pack() ───────────────────────────────────────────

// Never packaged: build detritus, local secrets, what a fresh clone would not have (catalog.py's
// SKIP_PARTS, SKIP_NAMES, SKIP_SUFFIX).
var (
	skipParts  = map[string]bool{"__pycache__": true, ".git": true, "node_modules": true, ".venv": true, ".pytest_cache": true}
	skipNames  = map[string]bool{"portainer_password.txt": true, ".DS_Store": true, "Thumbs.db": true}
	skipSuffix = []string{".pyc", ".pyo"}
)

// zipEpoch is catalog.py's fixed member date: the artifact is a function of the files, not the clock.
var zipEpoch = time.Date(1980, 1, 1, 0, 0, 0, 0, time.UTC)

// source is one file of an artifact, app-relative with forward slashes.
type source struct {
	rel  string
	exec bool
}

// sources is _sources(): the files a fresh clone holds under dir, sorted, the skips applied, only
// what is a file, and the links left out. As catalog.py (DGO-609): git lists with -z, so every name
// is exact whatever the builder's core.quotepath says, and a name no unpacker reads the same is
// refused; the execute bit is the one git records (`ls-files -s`), the same answer on every OS,
// where the disk calls every file executable on Windows; and a link — one git tracks (mode 120000,
// known by name without touching the disk), or one on disk — is never followed nor packed, and is
// returned for the build to say so. On three points deliberately not catalog.py's, which publishes
// what it should not:
//
//   - Inside a repository the files are git's, or the build stops. catalog.py turns any git failure
//     (a refused "dubious ownership", a broken index, no git) into a walk of the directory, which
//     packs the untracked .env and key.pem beside the app. A walk is for a tree outside any repository.
//   - A link to a directory is named too: catalog.py's walk descends into a Windows junction, out of
//     the app, and passes over a symlink to a directory without a word.
//   - Two names that differ only in case are refused: they would collide on a case-folding file
//     system. catalog.py packs both.
func sources(dir string) ([]source, []string, error) {
	var rels, links []string
	gitMode := map[string]string{}
	diskExec := map[string]bool{}
	cmd := exec.Command("git", "-C", dir, "ls-files", "-s", "-z")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	listed, err := cmd.Output()
	switch {
	case err != nil && inRepo(dir):
		return nil, nil, fmt.Errorf("git ls-files in %s failed — inside a repository an artifact is what git tracks, or nothing: %v %s", dir, err, strings.TrimSpace(stderr.String()))
	case err == nil:
		for _, rec := range strings.Split(string(listed), "\x00") {
			meta, rel, ok := strings.Cut(rec, "\t")
			if !ok || strings.TrimSpace(rel) == "" {
				continue
			}
			rels = append(rels, rel)
			gitMode[rel], _, _ = strings.Cut(meta, " ")
		}
		if len(rels) == 0 {
			return nil, nil, fmt.Errorf("git tracks no file in %s — an artifact is what a fresh clone holds, so add the app to git first", dir)
		}
	default:
		err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
			switch {
			case err != nil:
				return nil // os.walk skips what it cannot read
			case d.IsDir():
				if p != dir && skipParts[d.Name()] {
					return filepath.SkipDir
				}
				return nil
			case skipNames[d.Name()] || skipped(d.Name()):
				return nil
			}
			rel, err := filepath.Rel(dir, p)
			if err != nil {
				return err
			}
			rel = filepath.ToSlash(rel)
			rels = append(rels, rel)
			if info, err := d.Info(); err == nil {
				diskExec[rel] = info.Mode()&0o111 != 0
			}
			return nil
		})
		if err != nil {
			return nil, nil, err
		}
	}
	sort.Strings(rels)
	var out []source
	folded := map[string]string{}
	for i, rel := range rels {
		if i > 0 && rel == rels[i-1] {
			continue
		}
		parts := strings.Split(rel, "/")
		skip := skipNames[parts[len(parts)-1]] || skipped(rel)
		for _, p := range parts {
			skip = skip || skipParts[p]
		}
		if skip {
			continue
		}
		if gitMode[rel] == "120000" {
			links = append(links, rel)
			continue
		}
		st, err := os.Lstat(filepath.Join(dir, filepath.FromSlash(rel)))
		switch {
		case err != nil || st.IsDir():
			continue // catalog.py's is_file(): tracked but gone, or a directory (a submodule) — not a file
		case !st.Mode().IsRegular():
			links = append(links, rel)
			continue
		case !portable(rel):
			return nil, nil, fmt.Errorf("%q cannot be named in an artifact: not UTF-8, or a control character or a backslash", rel)
		}
		if other, dup := folded[strings.ToLower(rel)]; dup {
			return nil, nil, fmt.Errorf("%s and %s differ only in case — they would collide on a case-folding file system", other, rel)
		}
		folded[strings.ToLower(rel)] = rel
		// a hook that loses its x-bit stops being runnable, so hooks/ is executable whatever the file says
		out = append(out, source{rel, gitMode[rel] == "100755" || diskExec[rel] || strings.HasPrefix(rel, "hooks/")})
	}
	return out, links, nil
}

// inRepo is git's own question — is dir inside a work tree? — answered without git: a .git
// directory with a HEAD, or the .git file a worktree or submodule has, here or above; or GIT_DIR.
func inRepo(dir string) bool {
	if os.Getenv("GIT_DIR") != "" {
		return true
	}
	d, err := filepath.Abs(dir)
	if err != nil {
		return true // when in doubt, git's answer or nothing
	}
	for {
		if st, err := os.Stat(filepath.Join(d, ".git")); err == nil {
			if !st.IsDir() {
				return true
			}
			if _, err := os.Stat(filepath.Join(d, ".git", "HEAD")); err == nil {
				return true
			}
		}
		parent := filepath.Dir(d)
		if parent == d {
			return false
		}
		d = parent
	}
}

// portable is a member name every unpacker reads the same: UTF-8, no control character, no
// backslash (which an unpacker on Windows takes for a separator).
func portable(rel string) bool {
	if !utf8.ValidString(rel) {
		return false
	}
	for _, r := range rel {
		if r < 0x20 || r == 0x7f || r == '\\' {
			return false
		}
	}
	return true
}

func skipped(name string) bool {
	for _, s := range skipSuffix {
		if strings.HasSuffix(name, s) {
			return true
		}
	}
	return false
}

// pack is pack(): a deterministic zip of the files, each under "<id>/", deflated at the best level,
// dated 1980-01-01, mode 0755 or 0644 made by Unix (SetMode; catalog.py's create_system 3) and nothing
// else about the machine — the same tree is the same bytes, so anybody can rebuild an artifact and
// check the hash the signed index names. It returns the zip's size and sha256.
func pack(dir, id string, files []source, dest string) (int64, string, error) {
	f, err := os.Create(dest)
	if err != nil {
		return 0, "", err
	}
	h := sha256.New()
	zw := zip.NewWriter(io.MultiWriter(f, h))
	zw.RegisterCompressor(zip.Deflate, func(w io.Writer) (io.WriteCloser, error) {
		return flate.NewWriter(w, flate.BestCompression)
	})
	err = func() error {
		for _, s := range files {
			hdr := &zip.FileHeader{Name: id + "/" + s.rel, Method: zip.Deflate, Modified: zipEpoch}
			hdr.SetMode(0o644)
			if s.exec {
				hdr.SetMode(0o755)
			}
			w, err := zw.CreateHeader(hdr)
			if err != nil {
				return err
			}
			src, err := os.Open(filepath.Join(dir, filepath.FromSlash(s.rel)))
			if err != nil {
				return err
			}
			_, err = io.Copy(w, src)
			src.Close()
			if err != nil {
				return err
			}
		}
		return zw.Close()
	}()
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	var st fs.FileInfo
	if err == nil {
		st, err = os.Stat(dest)
	}
	if err != nil {
		return 0, "", err
	}
	return st.Size(), hex.EncodeToString(h.Sum(nil)), nil
}

package compiler

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── compose-files: the one answer to "which -f files are the stack?" ───────────────────────────────
//
// compose_files(): the compiled compose.yml, then each overlay that exists — the routing labels, the
// reverse plane's aliases, the credential-broker cutovers (LAST of the three: it blanks what the apps'
// own files set), the sign-in bootstrap's input digest (written here, so compose recreates that
// container exactly when what it applies changed), and the CPU plan cut to the services that still
// exist. It validates nothing and resolves nothing — it must answer while a manifest is broken — and
// it fails open as reconcile.py does: an overlay it cannot compute is the last one written.

var bootstrapInputs = []string{"bootstrap.sh", "outpost-ready.py"} // + the committed blueprints/*.yaml

// ComposeFilesCmd is `compose-files`: the -f list, one path a line, repo-relative with forward
// slashes — or, before any render, the one line that says to render.
func ComposeFilesCmd(repo string, args []string, stdout, stderr io.Writer) int {
	if _, code, done := parseArgs("compose-files", args, stdout, stderr); done {
		return code
	}
	if _, err := os.Stat(filepath.Join(repo, genDir, "compose.yml")); err != nil {
		fmt.Fprintln(stderr, "not rendered — run: python3 platform/manager/reconcile.py render")
		return 1
	}
	files, err := composeFiles(repo)
	if err != nil {
		return failed(err, stderr)
	}
	for _, f := range files {
		fmt.Fprintln(stdout, f)
	}
	return 0
}

// composeFiles is compose_files(): the canonical -f order; the overlays last.
func composeFiles(repo string) ([]string, error) {
	gen := filepath.Join(repo, genDir)
	files := []string{genDir + "/compose.yml"}
	for _, f := range []string{"routing.override.yml", "remote.override.yml", "connections.override.yml"} {
		if exists(filepath.Join(gen, f)) {
			files = append(files, genDir+"/"+f)
		}
	}
	compiled, cerr := compiledServices(repo)
	if isGap(cerr) {
		return nil, cerr
	}
	if f := bootstrapOverlay(repo, compiled, cerr); f != "" {
		files = append(files, f)
	}
	if exists(filepath.Join(gen, "cpu-budget.yml")) {
		f, err := effectiveCPUBudget(repo, compiled, cerr)
		if err != nil {
			return nil, err
		}
		files = append(files, f)
	}
	return files, nil
}

// exists is Path.exists(): there — a directory too.
func exists(p string) bool { _, err := os.Stat(p); return err == nil }

// gapError is a document the YAML reader refuses by its design where PyYAML reads it — an anchor, a
// merge key, a tag, an integer past 64 bits. dgo cannot know what reconcile.py would answer from it,
// so it stops and says so, rather than fail open into an answer of its own (a different -f list).
type gapError struct {
	file string
	err  error
}

func (g *gapError) Error() string {
	return "FATAL " + g.file + ": " + g.err.Error() + " — dgo cannot read what reconcile.py reads here; DGO_COMPILER=python answers"
}

func isGap(err error) bool { var g *gapError; return errors.As(err, &g) }

// readYAML is yaml.safe_load(text) of the named file: the document, or why not — PyYAML's refusal too,
// or a gapError where only the reader refuses (yamlish.OutsideSubset: the reader's own verdict, held to
// PyYAML's corner by corner).
func readYAML(file, text string) (any, error) {
	v, err := yamlish.Unmarshal([]byte(text))
	if yamlish.OutsideSubset(err) {
		return nil, &gapError{file, err}
	}
	return v, err
}

// loadYAML is yaml.safe_load(path.read_text()).
func loadYAML(path string) (any, error) {
	text, err := readText(path)
	if err != nil {
		return nil, err
	}
	return readYAML(path, text)
}

// compiledServices is _compiled_services(): every service the compiled set declares — the services of
// .generated/compose.yml, of each file it includes, and of the routing and connections overlays. An
// error is where Python raises (its callers fail open).
func compiledServices(repo string) (map[string]bool, error) {
	gen := filepath.Join(repo, genDir)
	have := map[string]bool{}
	addServices := func(v any, where string) error {
		doc, err := dict(v, where)
		if err != nil {
			return err
		}
		svcs, err := dict(get(doc, "services"), where+": services")
		if err != nil {
			return err
		}
		for _, k := range svcs.Keys() {
			have[k] = true
		}
		return nil
	}
	v, err := loadYAML(filepath.Join(gen, "compose.yml"))
	if err != nil {
		return nil, err
	}
	if err := addServices(v, "compose.yml"); err != nil {
		return nil, err
	}
	compiled, _ := dict(v, "compose.yml")
	includes, err := list(get(compiled, "include"), "compose.yml: include")
	if err != nil {
		return nil, err
	}
	for _, inc := range includes {
		rel := inc // `inc if isinstance(inc, str) else inc.get("path", "")`, joined to the checkout
		if _, isText := inc.(string); !isText {
			m, err := asDict(inc, "compose.yml: include")
			if err != nil {
				return nil, err
			}
			rel = getOr(m, "path", "")
		}
		name, isText := rel.(string)
		if !isText {
			return nil, died("compose.yml: include path %s: TypeError: not a path", pyval.Repr(rel))
		}
		p := joinPath(repo, name)
		if !isRegular(p) {
			continue
		}
		doc, err := loadYAML(p)
		if err != nil {
			return nil, err
		}
		if err := addServices(doc, name); err != nil {
			return nil, err
		}
	}
	for _, extra := range []string{"routing.override.yml", "connections.override.yml"} {
		p := filepath.Join(gen, extra)
		if !exists(p) {
			continue
		}
		doc, err := loadYAML(p)
		if err != nil {
			return nil, err
		}
		if err := addServices(doc, extra); err != nil {
			return nil, err
		}
	}
	return have, nil
}

// bootstrapOverlay is _bootstrap_inputs_overlay(): a label on authentik-bootstrap carrying the digest of
// everything it runs and applies (bootstrap.sh, outpost-ready.py, the committed blueprints but the
// compiled one), written only on change; removed — and no overlay — when the compiled set has no
// bootstrap (an overlay naming a missing service breaks the whole project). Where any of it cannot be
// done, the overlay last written, if there is one.
func bootstrapOverlay(repo string, compiled map[string]bool, cerr error) string {
	out := filepath.Join(repo, genDir, "authentik-bootstrap.override.yml")
	const rel = genDir + "/authentik-bootstrap.override.yml"
	lastGood := func() string {
		if exists(out) {
			return rel
		}
		return ""
	}
	if cerr != nil {
		return lastGood()
	}
	if !compiled["authentik-bootstrap"] {
		if err := unlink(out); err != nil {
			return lastGood()
		}
		return ""
	}
	adir := filepath.Join(repo, filepath.FromSlash(authentikDir))
	var files []string
	for _, f := range bootstrapInputs {
		files = append(files, filepath.Join(adir, f))
	}
	files = append(files, yamlFiles(filepath.Join(adir, "blueprints"))...)
	h := sha256.New()
	for _, f := range files {
		if !isRegular(f) {
			continue
		}
		data, err := os.ReadFile(f)
		if err != nil {
			return lastGood()
		}
		r, _ := filepath.Rel(repo, f)
		h.Write([]byte(filepath.ToSlash(r) + "\x00"))
		h.Write(append(bytes.ReplaceAll(data, []byte("\r\n"), []byte("\n")), 0)) // CRLF checkouts hash alike
	}
	body := "# GENERATED by reconcile.compose_files() — do not edit.\n" +
		"# The digest of what authentik-bootstrap runs and of the committed blueprints it applies\n" +
		"# (bootstrap.sh, outpost-ready.py, blueprints/*.yaml but the compiled one). It only exists\n" +
		"# so compose recreates the container when they change.\n" +
		"services:\n" +
		"  authentik-bootstrap:\n" +
		"    labels:\n" +
		"      bbox.bootstrap-inputs: " + hex.EncodeToString(h.Sum(nil))[:16] + "\n"
	if old, err := readText(out); err == nil && old == body {
		return rel
	} else if exists(out) && err != nil {
		return lastGood() // unreadable: read_text raised, the last overlay stands
	}
	if err := os.WriteFile(out, []byte(body), 0o666); err != nil {
		return lastGood()
	}
	return rel
}

// yamlFiles is sorted(dir.glob("*.yaml")) but the compiled blueprint: matched and ordered as pathlib
// does on this OS (case-insensitively on Windows) — and, as pathlib's glob swallows every OSError of
// the directory it reads, nothing at all where the directory cannot be read.
func yamlFiles(dir string) []string {
	entries, _ := dirEntries(dir)
	key := func(s string) string {
		if pathlibIgnoresCase {
			return strings.ToLower(s)
		}
		return s
	}
	var out []string
	for _, e := range entries {
		if n := e.Name(); strings.HasSuffix(key(n), ".yaml") && n != generatedBlueprint {
			out = append(out, n)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return key(out[i]) < key(out[j]) })
	for i, n := range out {
		out[i] = filepath.Join(dir, n)
	}
	return out
}

// effectiveCPUBudget is _effective_cpu_budget(): the CPU overlay as compose is given it — itself, or,
// where it budgets services the compiled set no longer declares, cpu-budget.effective.yml without them
// (written only on change). Unreadable inputs are the overlay as rendered.
func effectiveCPUBudget(repo string, compiled map[string]bool, cerr error) (string, error) {
	gen := filepath.Join(repo, genDir)
	const src, out = genDir + "/cpu-budget.yml", genDir + "/cpu-budget.effective.yml"
	v, err := loadYAML(filepath.Join(gen, "cpu-budget.yml"))
	if err != nil {
		if isGap(err) {
			return "", err
		}
		return src, nil
	}
	if cerr != nil {
		return src, nil
	}
	overlay, err := dict(v, "cpu-budget.yml")
	if err != nil {
		return src, nil
	}
	services, err := dict(get(overlay, "services"), "cpu-budget.yml: services")
	if err != nil {
		return src, nil
	}
	kept := yamlish.NewMap()
	var dropped []string
	for _, k := range services.Keys() {
		if compiled[k] {
			kept.Set(k, get(services, k))
		} else {
			dropped = append(dropped, k)
		}
	}
	if len(dropped) == 0 {
		return src, nil
	}
	sort.Strings(dropped)
	doc, err := yamlish.Marshal(ordered("services", kept), yamlish.Options{SortKeys: true})
	if err != nil {
		return "", err
	}
	body := "# GENERATED by reconcile.compose_files() from cpu-budget.yml — do not edit.\n" +
		"# Dropped — no such service in the compiled set any more: " + strings.Join(dropped, ", ") + "\n" + string(doc)
	path := filepath.Join(gen, "cpu-budget.effective.yml")
	if old, err := readText(path); err != nil || old != body {
		var d *dies
		if errors.As(err, &d) {
			return "", d // read_text raised a UnicodeDecodeError: no OSError, so nothing catches it
		}
		if err := os.WriteFile(path, []byte(body), 0o666); err != nil {
			return src, nil
		}
	}
	return out, nil
}

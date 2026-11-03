package compiler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"math"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── the oracle for the generating verbs: reconcile.py and dgo on two copies of one tree ────────────
//
// render, compose-files and serve-plan write and print what reconcile.py writes and prints. Each case
// builds a tree from this checkout — reconcile.py and serve.py, every manifest and every file one
// names, the sign-in bootstrap's inputs, dgo-extend's identity.py, the state file — reshapes it
// (another state, a .env, .dgo/, a fixture app, an earlier render made by reconcile.py itself), copies
// it, runs `python3 reconcile.py <verb>` in one copy and dgo's verb in the other, and then holds the
// two to each other: the exit status, stdout and stderr, and the WHOLE resulting tree — every file and
// directory under it, its bytes and its permission bits — wherever either wrote, .generated/ and the
// two files render writes into apps' own config directories (traefik's, authentik's) included.

// genCmds are the generating verbs as dgo routes them.
var genCmds = map[string]func(string, []string, io.Writer, io.Writer) int{
	"render": RenderCmd, "compose-files": ComposeFilesCmd, "serve-plan": ServePlanCmd,
}

const removed = "\x00removed" // a files value: the file is taken out of the tree

// renderCase is one command line, the tree it runs on, and how reconcile.py answers it: dies marks a
// traceback, where dgo prints one FATAL line instead (the read verbs' rule).
type renderCase struct {
	name  string
	argv  []string
	state string            // "" is this checkout's platform.state.yaml; noState removes it
	files map[string]string // repo-relative path → content (removed takes the file out)
	setup func(t *testing.T, py []string, dir string)
	// hold is a condition of each tree only while its verb runs (a file no one may read), let go of
	// before the trees are compared
	hold func(t *testing.T, dir string) (release func())
	dies bool
	seed string // PYTHONHASHSEED for reconcile.py ("" is 0)
}

// generatorTree is the tree a case starts from.
func generatorTree(t *testing.T, c renderCase, realState string) string {
	t.Helper()
	src, dir := repoRoot(t), t.TempDir()
	copyIn := func(rel string) {
		raw, err := os.ReadFile(filepath.Join(src, filepath.FromSlash(rel)))
		if err != nil {
			return // a file the checkout does not have is one the tree does not have
		}
		put(t, dir, rel, string(raw))
	}
	for _, f := range []string{"platform/manager/reconcile.py", "platform/manager/serve.py", "platform/schema/app.schema.json",
		"platform/legacy-capabilities.yaml", "compose.yml", "platform.state.default.yaml", "apps/dgo-extend/identity.py",
		"platform-base/authentik/bootstrap.sh", "platform-base/authentik/outpost-ready.py"} {
		copyIn(f)
	}
	blueprints, _ := filepath.Glob(filepath.Join(src, "platform-base", "authentik", "blueprints", "*.yaml"))
	for _, b := range blueprints {
		if filepath.Base(b) != generatedBlueprint {
			copyIn("platform-base/authentik/blueprints/" + filepath.Base(b))
		}
	}
	for _, root := range []string{"apps", "platform-base"} {
		ms, _ := filepath.Glob(filepath.Join(src, root, "*", "app.json"))
		for _, m := range ms {
			app := root + "/" + filepath.Base(filepath.Dir(m))
			copyIn(app + "/app.json")
			var man struct {
				Compose any `json:"compose"`
				Agent   struct {
					Context string `json:"context"`
				} `json:"agent"`
			}
			raw, _ := os.ReadFile(m)
			json.Unmarshal(raw, &man)
			if comp, ok := man.Compose.(string); ok && comp != "" {
				copyIn(app + "/" + comp)
			}
			if man.Agent.Context != "" {
				copyIn(app + "/" + man.Agent.Context)
			}
		}
	}
	if err := os.MkdirAll(filepath.Join(dir, "platform-base", "traefik", "config"), 0o755); err != nil {
		t.Fatal(err)
	}
	switch c.state {
	case noState:
	case "":
		put(t, dir, stateName, realState)
	default:
		put(t, dir, stateName, c.state)
	}
	for rel, body := range c.files {
		if body == removed {
			os.Remove(filepath.Join(dir, filepath.FromSlash(rel)))
			continue
		}
		put(t, dir, rel, body)
	}
	return dir
}

// copyTreeForTest copies a tree file for file, modes kept exactly (setgid and the rest; the umask does
// not get a say), and each directory listing as the original's does — so a render that stops half way
// through a listing stops at the same entry in both trees. Where a filesystem lists in creation order
// (XFS, tmpfs since Linux 6.6) the entries are made in the order they are listed; where it lists the
// newest first (tmpfs before 6.6 — the Dell's runner, where the two "no one may read" cases archived
// different files in every go-test run until 2026-11-02), in the reverse; one that orders by name or by
// hash lists both trees alike either way. A copy that still lists otherwise is refused here, never
// reported as a difference between the twins.
func copyTreeForTest(t *testing.T, from, to string) {
	t.Helper()
	newestFirst := listsNewestFirst(t)
	var copyDir func(from, to string) error
	copyDir = func(from, to string) error {
		entries, err := dirEntries(from)
		if err != nil {
			return err
		}
		made := entries
		if newestFirst {
			made = make([]os.DirEntry, len(entries))
			for i, e := range entries {
				made[len(entries)-1-i] = e
			}
		}
		for _, e := range made {
			src, dst := filepath.Join(from, e.Name()), filepath.Join(to, e.Name())
			info, err := e.Info()
			if err != nil {
				return err
			}
			switch {
			case e.Type()&fs.ModeSymlink != 0: // a link stays a link
				target, err := os.Readlink(src)
				if err == nil {
					err = os.Symlink(target, dst)
				}
				if err != nil {
					return err
				}
				continue
			case e.IsDir():
				if err := os.Mkdir(dst, 0o700); err != nil { // writable while it is filled
					return err
				}
				if err := copyDir(src, dst); err != nil {
					return err
				}
			default:
				raw, err := os.ReadFile(src)
				if err == nil {
					err = os.WriteFile(dst, raw, 0o600)
				}
				if err != nil {
					return err
				}
			}
			if err := os.Chmod(dst, imode(info)); err != nil {
				return err
			}
		}
		// to is still this user's to read: its own mode is set by the caller, after this returns
		copied, err := dirEntries(to)
		if err != nil {
			return err
		}
		if want, got := entryNames(entries), entryNames(copied); want != got {
			return fmt.Errorf("the copy %s lists [%s], the original %s lists [%s]: this filesystem's order cannot be made again", to, got, from, want)
		}
		return nil
	}
	if err := copyDir(from, to); err != nil {
		t.Fatal(err)
	}
}

// listsNewestFirst reports whether the filesystem of this test's temporary directories lists a
// directory's entries newest first: three files made a, b, c and listed c, b, a.
func listsNewestFirst(t *testing.T) bool {
	t.Helper()
	dir := t.TempDir()
	for _, name := range []string{"a", "b", "c"} {
		if err := os.WriteFile(filepath.Join(dir, name), nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	entries, err := dirEntries(dir)
	if err != nil {
		t.Fatal(err)
	}
	return entryNames(entries) == "c b a"
}

// entryNames is a listing's names, space-separated, in its order.
func entryNames(entries []os.DirEntry) string {
	names := make([]string, len(entries))
	for i, e := range entries {
		names[i] = e.Name()
	}
	return strings.Join(names, " ")
}

// pyVerb runs reconcile.py's verb in dir under a hash seed: stdout, stderr (LF, as the contract is) and
// the exit status.
func pyVerb(t *testing.T, py []string, dir, seed string, argv ...string) (string, string, int) {
	t.Helper()
	cmd := exec.Command(py[0], append(append(append([]string{}, py[1:]...), filepath.Join(dir, "platform", "manager", "reconcile.py")), argv...)...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1", "PYTHONHASHSEED="+seed)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	code := 0
	if err := cmd.Run(); err != nil {
		ee, ok := err.(*exec.ExitError)
		if !ok {
			t.Fatalf("running reconcile.py: %v", err)
		}
		code = ee.ExitCode()
	}
	return strings.ReplaceAll(out.String(), "\r\n", "\n"), strings.ReplaceAll(errb.String(), "\r\n", "\n"), code
}

// pyRender is a setup step: reconcile.py renders the tree (an earlier render), and must succeed.
func pyRender(t *testing.T, py []string, dir string) {
	t.Helper()
	if out, errs, code := pyVerb(t, py, dir, "0", "render"); code != 0 {
		t.Fatalf("the setup render failed (%d):\n%s%s", code, out, errs)
	}
}

// lockedOutHolds reports whether lockedOut keeps this user out — root reads a file of mode 0 — and
// so whether a case built on it is one where reconcile.py raises.
func lockedOutHolds(t *testing.T) bool {
	t.Helper()
	probe := filepath.Join(t.TempDir(), "probe")
	if err := os.WriteFile(probe, []byte("x"), 0o666); err != nil {
		t.Fatal(err)
	}
	defer lockedOut(t, probe)()
	_, err := os.ReadFile(probe)
	return err != nil
}

// treeOf is every file, directory and link under root but Python's bytecode caches: its kind, its mode
// — the permission bits and setuid, setgid and sticky, S_IMODE's twelve, which copystat carries — and,
// for a file, its bytes; for a link, where it points.
func treeOf(t *testing.T, root string) map[string]string {
	t.Helper()
	out := map[string]string{}
	filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			t.Fatal(err)
		}
		if d.IsDir() && d.Name() == "__pycache__" {
			return filepath.SkipDir
		}
		rel, _ := filepath.Rel(root, p)
		info, _ := d.Info()
		switch {
		case d.Type()&fs.ModeSymlink != 0:
			target, _ := os.Readlink(p)
			out[filepath.ToSlash(rel)] = "link " + target
		case d.IsDir():
			out[filepath.ToSlash(rel)] = fmt.Sprintf("dir %v", imode(info))
		default:
			raw, _ := os.ReadFile(p)
			out[filepath.ToSlash(rel)] = fmt.Sprintf("file %v\n%s", imode(info), raw)
		}
		return nil
	})
	return out
}

// imode is S_IMODE: a file's permission bits with setuid, setgid and sticky.
func imode(info fs.FileInfo) fs.FileMode {
	return info.Mode() & (fs.ModePerm | fs.ModeSetuid | fs.ModeSetgid | fs.ModeSticky)
}

// diagnostic is a resolver diagnostic as main() prints it.
var diagnostic = regexp.MustCompile(`^  (info  |ERROR )`)

// sameOutput holds two outputs to each other: their lines in order, but the resolver's diagnostics as
// a set, each "X: pulled in as provider …" cut after X — which consumer and capability Python names
// depends on the order its set iteration meets them in (the hash seed), dgo's on sorted order.
func sameOutput(a, b string) bool {
	split := func(s string) (string, string) {
		var diags, rest []string
		for _, l := range strings.SplitAfter(s, "\n") {
			if diagnostic.MatchString(l) {
				diags = append(diags, pulledFor.ReplaceAllString(strings.TrimSuffix(l, "\n"), "$1"))
			} else {
				rest = append(rest, l)
			}
		}
		sort.Strings(diags)
		return strings.Join(diags, "\n"), strings.Join(rest, "")
	}
	ad, ar := split(a)
	bd, br := split(b)
	return ad == bd && ar == br
}

// runRenderCases builds each case's tree, copies it, and holds dgo to reconcile.py on the two copies.
func runRenderCases(t *testing.T, cases []renderCase) {
	t.Helper()
	py := python(t)
	realState, err := os.ReadFile(filepath.Join(officeRoot(t), stateName))
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		pyDir := generatorTree(t, c, string(realState))
		if c.setup != nil {
			c.setup(t, py, pyDir)
		}
		goDir := t.TempDir()
		copyTreeForTest(t, pyDir, goDir)
		before := treeOf(t, pyDir)
		held := func(dir string, run func()) {
			if c.hold != nil {
				defer c.hold(t, dir)()
			}
			run()
		}
		var pyOut, pyErr string
		var pyCode int
		held(pyDir, func() { pyOut, pyErr, pyCode = pyVerb(t, py, pyDir, either(c.seed, "0").(string), c.argv...) })
		var goOut, goErr bytes.Buffer
		var goCode int
		held(goDir, func() { goCode = genCmds[c.argv[0]](goDir, c.argv[1:], &goOut, &goErr) })
		name := c.name + " (" + strings.Join(c.argv, " ") + ")"
		if goCode != pyCode || !sameOutput(goOut.String(), pyOut) && !sameFailures(goOut.String(), pyOut) {
			t.Errorf("%s:\n--- dgo (exit %d):\n%s--- reconcile.py (exit %d):\n%s--- dgo stderr:\n%s--- reconcile.py stderr:\n%s",
				name, goCode, goOut.String(), pyCode, pyOut, goErr.String(), pyErr)
			continue
		}
		traceback := strings.HasPrefix(pyErr, "Traceback")
		switch {
		case c.dies != traceback:
			t.Errorf("%s: reconcile.py %s, the case says it %s:\n%s", name, map[bool]string{true: "raised", false: "did not raise"}[traceback],
				map[bool]string{true: "dies", false: "answers"}[c.dies], pyErr)
		case c.dies:
			if !strings.HasPrefix(goErr.String(), "FATAL ") || strings.Count(goErr.String(), "\n") != 1 {
				t.Errorf("%s: reconcile.py raised; dgo must stop with one FATAL line, it said:\n%s", name, goErr.String())
			}
		case !sameOutput(goErr.String(), pyErr):
			t.Errorf("%s: stderr differs\n--- dgo:\n%s--- reconcile.py:\n%s", name, goErr.String(), pyErr)
		}
		pyTree, goTree := treeOf(t, pyDir), treeOf(t, goDir)
		var diffs []string
		for p, v := range pyTree {
			if goTree[p] != v {
				diffs = append(diffs, p)
			}
		}
		for p := range goTree {
			if _, ok := pyTree[p]; !ok {
				diffs = append(diffs, p)
			}
		}
		sort.Strings(diffs)
		for i, p := range diffs {
			if i == 5 {
				t.Errorf("%s: … %d more", name, len(diffs)-5)
				break
			}
			at := firstDiffAt(goTree[p], pyTree[p])
			t.Errorf("%s: %s differs at byte %d\n--- dgo:\n%s\n--- reconcile.py:\n%s", name, p, at, window(goTree[p], at), window(pyTree[p], at))
		}
		changed := 0 // written, added or removed
		for p, v := range pyTree {
			if before[p] != v {
				changed++
			}
		}
		for p := range before {
			if _, ok := pyTree[p]; !ok {
				changed++
			}
		}
		t.Logf("%s: exit %d, %d path(s) changed, the same in both trees", name, pyCode, changed)
	}
}

func firstDiffAt(a, b string) int {
	n := min(len(a), len(b))
	for i := 0; i < n; i++ {
		if a[i] != b[i] {
			return i
		}
	}
	return n
}

func window(s string, at int) string {
	lo, hi := max(0, at-200), min(len(s), at+200)
	return s[lo:hi]
}

// ── the states that matter ─────────────────────────────────────────────────────────────────────────

// withApps is the checkout's state with each app's line made `{ state: <dispo> }` (added when it
// has none).
func withApps(t *testing.T, state, dispo string, ids ...string) string {
	t.Helper()
	for _, id := range ids {
		next, _, err := setDisposition(state, id, dispo, "test", true)
		if err != nil {
			t.Fatal(err)
		}
		state = next
	}
	return state
}

// everyApp is every app id of this checkout's catalog.
func everyApp(t *testing.T) []string {
	t.Helper()
	cat, err := LoadCatalog(repoRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	return cat.Order
}

// withoutRemote is a state cut before its `remote:` block.
func withoutRemote(state string) string {
	if i := strings.Index(state, "\nremote:\n"); i >= 0 {
		return state[:i+1]
	}
	return state
}

// manifestJSON is a valid layer-3 manifest with more fields.
func manifestJSON(id, extra string) string {
	if extra != "" {
		extra = "," + extra
	}
	return fmt.Sprintf(`{"id":%q,"layer":3,"title":{"he":"בדיקה","en":"Test"},"kind":"service"%s}`, id, extra)
}

// zzProviders is two providers of one capability, a consumer of it, and this checkout's product
// default binding that capability to zz-p2 — the cases that reach the product's binding and the rule
// before it.
func zzProviders(t *testing.T) map[string]string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(repoRoot(t), defaultName))
	if err != nil {
		t.Fatal(err)
	}
	def := string(raw)
	if strings.Contains(def, "\nproduct_bindings:\n") {
		def = strings.Replace(def, "\nproduct_bindings:\n", "\nproduct_bindings:\n  zz-cap: zz-p2\n", 1)
	} else {
		def += "product_bindings:\n  zz-cap: zz-p2\n"
	}
	files := map[string]string{defaultName: def, "apps/zz-c/app.json": manifestJSON("zz-c", `"use":[{"capability":"zz-cap"}]`)}
	for _, p := range []string{"zz-p1", "zz-p2"} {
		files["apps/"+p+"/app.json"] = manifestJSON(p, `"capabilities":[{"name":"zz-cap","type":"service","endpoint":"http://`+p+`:1"}],"compose":"docker-compose.yml"`)
		files["apps/"+p+"/docker-compose.yml"] = "services:\n  " + p + ":\n    image: x\n"
	}
	return files
}

const (
	envDomain = "BUSINESS_NAME=\"Bina Solutions Ltd.\"\r\n#@derived slug\r\nCOMPANY_SLUG=old\r\n" +
		"DEPLOYMENT_DOMAIN=${COMPANY_SLUG}.example.co.il\r\nCONSOLE_BASE_URL=console.${DEPLOYMENT_DOMAIN}\r\n" +
		"AUTH_PROTOCOL=https\r\nGIT_BASE_URL=git.${DEPLOYMENT_DOMAIN}\r\nBAD=\xff\xfe${MISSING:-fallback}\r\n"
	envLocalPort = "# a laptop office: the edge on :8080\nBUSINESS_NAME=Hacohen\nexport X=1\nDEPLOYMENT_DOMAIN=localhost\n" +
		"CONSOLE_BASE_URL=http://console.localhost:8080\nAPP_MANAGEMENT_BASE_URL=apps.localhost:8080\n" +
		"GIT_BASE_URL='git.localhost:8080'\nPROJECT_PLN_BASE_URL=plane.console.localhost\nGIT_PROTOCOL=ftp\nSELF=${SELF}x\n"
	// a remote block of every shape plan() accepts: two offices, one behind a door (link_port) with an
	// identity mapped both ways, one without; apps embedded and of their own host, with and without
	// the authority they answer under, an agent's second door, labels as text and as an object, a mark
	// the vocabularies know and one they do not
	remoteShapes = `remote:
- office: macbook
  label: {he: המקבוק, en: MacBook}
  link: macbook
  address: 10.79.3.2
  commit: abc123
  link_port: 9002
  mark: {color: Muted, animal: OWL}
  apps:
  - app: bina-ds
    alias: bina
    port: 3080
    agent_api_port: 3081
    name: בינה
    icon: bot
    group: ראשי
    order: 1
    module: {kind: external, path: /, id: bina}
    host: bina.localhost
    identity: {to: owner, from: [alice, bob]}
  - app: drive
    port: "8975"
    name_en: Drive
    title: {he: דרייב}
    order: 2.5
    module: {kind: embedded}
    identity: {to: owner, from: carol}
- office: vps9
  label: Staging
  address: " 10.79.9.2 "
  mark: {color: red, animal: deer}
  apps:
  - app: sites
    alias: Site
    port: 8979
    host: sites.localhost
    health: /ready
    desc: האתרים
`
	// remoteDoors: doors with no tile (DGO-945) — one beside a tile, and an office that gives a door
	// and no app at all; remoteBadDoors: every refusal a door can earn.
	remoteDoors = `remote:
- office: dell
  address: 10.79.5.2
  link_port: 9005
  apps:
  - app: ollama
    port: 11434
  services:
  - app: apitools
    alias: speech
    port: 8987
  - {app: Zz-Door, alias: " Hooks ", port: "5678"}
- office: vps1
  address: 10.79.4.2
  link_port: 9004
  apps: []
  services:
  - app: meet
    alias: recordings
    port: 8001
`
	remoteBadDoors = `remote:
- office: dell
  address: 10.79.5.2
  apps: [{app: ollama, port: 1}]
  services: speech
- office: vps1
  address: 10.79.4.2
  apps: [{app: project-pln, alias: plane, port: 80}]
  services:
  - nope
  - {app: Bad_, alias: x, port: 1}
  - {app: meet, alias: plane, port: 1}
  - {app: meet, alias: recordings, port: 70000}
  - {app: meet, alias: rec2, port: abc}
  - {app: meet, alias: rec3}
- office: mac
  address: 10.79.6.2
  apps: []
  services: []
`
	// zzDoor: an app whose capabilities include two offered to links — one of them on the port its
	// agent door would otherwise be read from — and one that is its agent door.
	zzDoor = `"routing":[{"host":"zd","port":8080,"service":"zd-web","module":{"alias":"zd","name":"דלת","icon":"x","group":"עסק","url":"http://zd-web:8080"}}],
		"capabilities":[{"name":"hooks","type":"protocol","endpoint":"http://zd-hooks:5678","link":true},
		{"name":" Speech ","type":"protocol","endpoint":"HTTP://ZD-ASR/","link":true},
		{"name":"bad","type":"protocol","endpoint":"http://zd-x:99999","link":true},
		{"name":"api","type":"service","endpoint":"http://zd-web:9090"}]`
)

func TestRenderMatchesPython(t *testing.T) {
	real, err := os.ReadFile(filepath.Join(officeRoot(t), stateName))
	if err != nil {
		t.Fatal(err)
	}
	state := string(real)
	all := withApps(t, state, "enabled", everyApp(t)...)
	render := []string{"render"}
	cases := []renderCase{
		{name: "this checkout as committed: a remote: block with a linked office", argv: render},
		{name: "every app enabled, a real domain, a CRLF .env with a stale slug and bytes that are not UTF-8", argv: render, state: all,
			files: map[string]string{".env": envDomain}},
		{name: "every app enabled on a .localhost edge with a port: framed hosts and their port twins", argv: render, state: all,
			files: map[string]string{".env": envLocalPort}},
		{name: "the console on the LAN under its name: every shared app's lan form (DGO-1126)", argv: render,
			state: withApps(t, withoutRemote(state), "enabled", "lan-console") + remoteShapes,
			files: map[string]string{".env": envLocalPort + "LAN_ADDRESS=192.168.16.100\nLAN_PORT= 8081 \n"}},
		{name: "the console on the LAN under a name the office chose", argv: render,
			state: withApps(t, withoutRemote(state), "enabled", "lan-console") + remoteShapes,
			files: map[string]string{".env": envLocalPort + "LAN_ADDRESS=192.168.16.100\nLAN_DOMAIN=lan.office.example\n"}},
		{name: "--json: the diagnostics on stderr", argv: []string{"render", "--json", "--app", "ignored"}, state: withApps(t, withoutRemote(state), "enabled", "drive", "indox")},
		{name: "an app pulled in as a provider, a disabled app, bridged legacy capabilities", argv: render,
			state: withApps(t, withApps(t, state, "enabled", "drive", "mail", "indox", "project-pln"), "disabled", "git", "bina-ds")},
		{name: "a provider binding between two providers of one capability", argv: render,
			state: withApps(t, state, "enabled", "zz-users") + "bindings:\n  sql: { provider: zz-alt-db }\n",
			files: map[string]string{
				"apps/zz-alt-db/app.json":           manifestJSON("zz-alt-db", `"capabilities":[{"name":"sql","type":"service","endpoint":"http://zz-alt-db:5432"}],"compose":"docker-compose.yml"`),
				"apps/zz-alt-db/docker-compose.yml": "services:\n  zz-alt-db:\n    image: x\n",
				"apps/zz-users/app.json":            manifestJSON("zz-users", `"use":[{"capability":"sql"}]`),
			}},
		{name: "the product's binding decides between two providers the office runs neither of", argv: render,
			state: withApps(t, state, "enabled", "zz-c"), files: zzProviders(t)},
		{name: "the one provider the office runs decides before the product's binding", argv: render,
			state: withApps(t, state, "enabled", "zz-c", "zz-p1"), files: zzProviders(t)},
		{name: "a refused plan: the product's binding never starts a provider the office switched off", argv: render,
			state: withApps(t, withApps(t, state, "enabled", "zz-c"), "disabled", "zz-p2"), files: zzProviders(t)},
		{name: "nothing enabled: every list empty, every overlay absent", argv: render, state: "schema_version: 1\napps: {}\ninstances:\n"},
		{name: "an office: block, instances and the legacy serve: block", argv: render,
			state: strings.Replace(state, "\nremote:\n", "\noffice:\n  name: הלשכה\n  animal: elephant\n  hue: muted\nserve:\n", 1)},
		{name: "a remote block of every shape", argv: render, state: withoutRemote(state) + remoteShapes},
		{name: "the same without dgo-extend's identity.py: tiles without a mark", argv: render, state: withoutRemote(state) + remoteShapes,
			files: map[string]string{"apps/dgo-extend/identity.py": removed}},
		{name: "doors with no tile: an app's link capabilities, a door beside a tile, an office that gives only a door", argv: render,
			state: withApps(t, withoutRemote(state), "enabled", "zz-door") + remoteDoors,
			files: map[string]string{"apps/zz-door/app.json": manifestJSON("zz-door", zzDoor)}},
		{name: "SERVE PLAN REFUSED: doors that are not doors", argv: render, state: withoutRemote(state) + remoteBadDoors},
		{name: "on-demand apps (DGO-1270): their routers again on the waker, one wake service, a route with no sign-in", argv: render,
			state: withApps(t, state, "enabled", "cad", "app-management", "zz-od"),
			files: map[string]string{"apps/zz-od/app.json": manifestJSON("zz-od", `"routing":[{"host":"zod","port":80,"auth":"none","on_demand":{"idle":"45m"}}]`)}},
		{name: "ON DEMAND REFUSED: an idle window that is no duration", argv: render,
			state: withApps(t, state, "enabled", "app-management", "zz-od"),
			files: map[string]string{"apps/zz-od/app.json": manifestJSON("zz-od", `"routing":[{"host":"zod","port":80,"on_demand":{"idle":"2h\n"}}]`)}},
		{name: "on demand with no waker: nothing sleeps", argv: render,
			state: withApps(t, withApps(t, state, "enabled", "cad"), "disabled", "app-management")},
		{name: "a broker cutover: url_env, a routing service, blank_env out of order", argv: render,
			state: withApps(t, state, "enabled", "drive", "zz-broker"),
			files: map[string]string{"apps/zz-broker/app.json": manifestJSON("zz-broker", `"routing":[{"host":"zz","service":"zz-web","port":80,"auth":"none"}],
				"broker":{"url_env":"BROKER","blank_env":["Z_KEY","A_KEY","M KEY"],"entrypoint":["python","-m","app: run","--flag=#x"]},
				"observability":{"sentry_platform":"go","sentry_project":"zz-broker-project-with-a-long-name"}`)}},
		{name: "contributions, probes, owned providers and a connection read by two services", argv: render,
			state: withApps(t, state, "enabled", "zz-contrib", "n8n", "glitchtip"),
			files: map[string]string{"apps/zz-contrib/app.json": manifestJSON("zz-contrib", `"routing":[{"host":"zc","port":8080,"service":"zc-web",
				"module":{"alias":"zc","name":"צי","icon":"x","group":"עסק","url":"http://zc-web:8080","url_env":"ZC_URL","order":3}}],
				"connections":[{"id":"zc-token","required":true,"service":["zc-web","zc-runner"]},{"id":"zc-opt"}],
				"contributes":{"env":{"console":{"B":"2","A":"1"},"any-concurrency":{"X":"y"}},"volumes":{"n8n:n8n-worker":["./x:/x:ro"],"nope":["./y:/y"]},
				"connection_probes":{"zc-token":{"type":"tcp","port":1}},
				"connection_providers":[{"id":"zc-pass","_app":"first","kind":"password","fields":[{"name":"p","secret":true}]}]},
				"engine":{"id":"zc","profiles":[{"id":"main","display_name":"ראשי"}]},
				"capabilities":[{"name":"zc","type":"service","endpoint":"http://zc-web:8081/api","contract":"platform-service.v1","required_ops":["read"],"optional_ops":["write"]}],
				"agent":{"context":"AGENT.md","order":5}`),
				"apps/zz-contrib/AGENT.md": "# zc\n\nthe brief, with a trailing space \n\n"}},
		{name: "SERVE PLAN REFUSED: what is written before the refusal stays", argv: render,
			state: withoutRemote(state) + "remote:\n- office: macbook\n  address: 10.80.0.2\n  apps: [{app: x, port: 1}]\n- office: macbook\n  address: 10.79.1.2\n  apps: []\n- office: Q\n"},
		{name: "SERVE PLAN REFUSED: the address is this office's own (.dgo)", argv: render,
			state: withoutRemote(state) + "remote:\n- office: macbook\n  address: 10.79.3.2\n  apps: [{app: x, port: 1}]\n",
			files: map[string]string{".dgo/addressing.json": `{"self": "10.79.3.1", "pairs": [{"self": "10.79.3.2"}]}`}},
		{name: "SERVE PLAN REFUSED: remote: is not a list", argv: render, state: withoutRemote(state) + "remote: macbook\n"},
		{name: "a manifest with more after its object: json.loads' Extra data", argv: render,
			files: map[string]string{"apps/zz-extra/app.json": manifestJSON("zz-extra", "") + "\n{}"}},
		{name: "a manifest that is not JSON, in json.loads' words", argv: render,
			files: map[string]string{"apps/zz-broken/app.json": "{not json"}},
		{name: "a CRLF manifest that is not JSON: json.loads places the error in the text read_text gives it", argv: render,
			files: map[string]string{"apps/zz-crlf/app.json": "{\r\n  \"id\": \"zz-crlf\",\r\n  bad\r\n}\r\n"}},
		{name: "a manifest that is not UTF-8, of an app not even enabled: read_text raises before a byte is written", argv: render, dies: true,
			files: map[string]string{"apps/zz-latin/app.json": strings.Replace(manifestJSON("zz-latin", ""), "בדיקה", "caf\xe9", 1)}},
		{name: "a manifest that is a list: load_catalog's a[\"_dir\"] raises", argv: render, dies: true,
			files: map[string]string{"apps/zz-list/app.json": "[]"}},
		{name: "a manifest whose id is a mapping: str() of it, in its own key order", argv: render,
			files: map[string]string{"apps/zz-dictid/app.json": `{"id":{"b":1,"a":2.50},"layer":3}`}},
		{name: "a manifest whose layer is a mapping: str() of it, in its own key order", argv: render,
			files: map[string]string{"apps/zz-dictlayer/app.json": `{"id":"zz-dictlayer","layer":{"z":1,"y":[1.0, 1e16]}}`}},
		{name: "a manifest nested past the recursion limit: json.loads raises", argv: render, dies: true,
			files: map[string]string{"apps/zz-deep/app.json": strings.Repeat("[", 5000) + strings.Repeat("]", 5000)}},
		{name: "a manifest holding an integer of 5000 digits: json.loads raises ValueError", argv: render, dies: true,
			files: map[string]string{"apps/zz-long/app.json": manifestJSON("zz-long", `"version":`+strings.Repeat("7", 5000))}},
		{name: "NaN and the infinities, which json.loads reads: validated, and written as Python writes them", argv: render,
			state: withApps(t, state, "enabled", "zz-nan"),
			files: map[string]string{
				"apps/zz-nan/app.json": manifestJSON("zz-nan", `"resources":{"cpus":NaN},"agent":{"context":"AGENT.md"},
					"capabilities":[{"name":"zn","type":"service","endpoint":"http://zn:1","limits":[Infinity,-Infinity,NaN,1e400,-0.0,1E5]}]`),
				"apps/zz-nan/AGENT.md": "# zn\n"}},
		{name: "NaN where the schema says integer: MANIFEST VALIDATION FAILED", argv: render,
			files: map[string]string{"apps/zz-nan/app.json": manifestJSON("zz-nan",
				`"routing":[{"host":"zn","port":80,"module":{"alias":"zn","name":"n","icon":"x","group":"עסק","order":NaN}}]`)}},
		{name: "MANIFEST VALIDATION FAILED", argv: render,
			files: map[string]string{"apps/zz-bad/app.json": manifestJSON("zz-bad", `"bogus":1,"routing":[{"host":"x","port":"80","auth":"SSO"}]`)}},
		{name: "RESOLVE FAILED: a capability no app provides", argv: render,
			state: withApps(t, state, "enabled", "zz-needy"),
			files: map[string]string{"apps/zz-needy/app.json": manifestJSON("zz-needy", `"use":[{"capability":"nothing-provides-this"}]`)}},
		{name: "a passthrough without its alias", argv: render, state: withApps(t, state, "enabled", "zz-pass"),
			files: map[string]string{"apps/zz-pass/app.json": manifestJSON("zz-pass", `"routing":[{"host":"zp","port":80,"module":{"name":"p","icon":"x","group":"עסק","passthrough":[{"path":"/ws","transport":"websocket"}]}}]`)}},
		{name: "a passthrough of an app that is not embedded", argv: render, state: withApps(t, state, "enabled", "zz-pass"),
			files: map[string]string{"apps/zz-pass/app.json": manifestJSON("zz-pass", `"routing":[{"host":"zp","port":80,"module":{"alias":"zp","embed":false,"passthrough":[{"path":"/ws","transport":"websocket"}]}}]`)}},
		{name: "a passthrough on a route outside the sign-in", argv: render, state: withApps(t, state, "enabled", "zz-pass"),
			files: map[string]string{"apps/zz-pass/app.json": manifestJSON("zz-pass", `"routing":[{"host":"zp","port":80,"auth":"none","module":{"alias":"zp","name":"p","icon":"x","group":"עסק","passthrough":[{"path":"/ws","transport":"websocket"}]}}]`)}},
		{name: "no console app: a passthrough has nowhere to go", argv: render,
			files: map[string]string{"platform-base/console/app.json": removed}},
		{name: "a passthrough at the console's root, carved out of its reserved paths", argv: render, state: withApps(t, state, "enabled", "zz-pass"),
			files: map[string]string{"apps/zz-pass/app.json": manifestJSON("zz-pass", `"routing":[{"host":"zp","port":80,"module":{"alias":"zp","name":"p","icon":"x","group":"עסק",
				"passthrough":[{"path":"/api","transport":"http","mount":"root","match":"prefix"},{"path":"/ws","transport":"websocket","strip_mount_prefix":false}]}}]`)}},
		{name: "two providers of one name: the blueprint is refused before it is written", argv: render,
			state: withApps(t, state, "enabled", "zz-one", "zz-two"),
			files: map[string]string{
				"apps/zz-one/app.json": manifestJSON("zz-one", `"routing":[{"host":"one","port":80,"auth":"sso","sso":{"slug":"one","default_host":"one.localhost","display_name":"Same","base_url_env":"ONE_URL"}}]`),
				"apps/zz-two/app.json": manifestJSON("zz-two", `"routing":[{"host":"two","port":80,"auth":"sso","sso":{"slug":"two","default_host":"two.localhost","display_name":"Same","base_url_env":"TWO_URL","local_twin":true}}]`),
			}},
		{name: "a routing entry without its host: reconcile.py raises", argv: render, state: withApps(t, state, "enabled", "zz-hostless"), dies: true,
			files: map[string]string{"apps/zz-hostless/app.json": manifestJSON("zz-hostless", `"routing":[{"port":80}]`)}},
		{name: "a remote app's order that is text beside numbers: reconcile.py cannot sort the tiles", argv: render, dies: true,
			state: withoutRemote(state) + "remote:\n- office: macbook\n  address: 10.79.3.2\n  apps: [{app: x, port: 1, order: first}]\n"},
		{name: "a contribution whose volumes are null: .extend(None) raises", argv: render, dies: true,
			state: withApps(t, state, "enabled", "zz-vols", "n8n"),
			files: map[string]string{"apps/zz-vols/app.json": manifestJSON("zz-vols", `"contributes":{"volumes":{"n8n":null}}`)}},
		{name: "a remote office's orders with a NaN among them: the tiles in sorted()'s order", argv: render,
			state: withoutRemote(state) + "remote:\n- office: macbook\n  address: 10.79.3.2\n  apps:\n  - {app: a, port: 1, order: 1}\n" +
				"  - {app: b, port: 2, order: .nan}\n  - {app: c, port: 3, order: 2}\n  - {app: d, port: 4, order: 0.5}\n"},
		{name: "one tile only, its order a mapping with typed keys: written as safe_dump writes them", argv: render,
			state: "schema_version: 1\napps: {}\nremote:\n- office: macbook\n  address: 10.79.3.2\n  apps:\n  - {app: a, port: 1, order: {1: x, 2.5: y, null: z, '3': w}}\n"},
		{name: "orders that are lists headed by NaN: sorted() compares past it (PyYAML's one NaN object)", argv: render,
			state: "schema_version: 1\napps: {}\nremote:\n- office: macbook\n  address: 10.79.3.2\n  apps:\n" +
				"  - {app: a, port: 1, order: [.nan, 2]}\n  - {app: b, port: 2, order: [.nan, 1]}\n  - {app: c, port: 3, order: [.nan, 1, 0]}\n"},
		{name: "orders headed by equal mappings, a description with typed keys: compared and spelled as Python does", argv: render,
			state: "schema_version: 1\napps: {}\nremote:\n- office: macbook\n  address: 10.79.3.2\n  apps:\n" +
				"  - {app: a, port: 1, order: [{k: 1}, 2], desc: {1: x, 2.5: y, null: z}}\n  - {app: b, port: 2, order: [{k: 1.0}, 1]}\n"},
		{name: "traefik's config directory is a file, nothing served or framed: unlink raises where the OS calls it no directory", argv: render,
			state: "schema_version: 1\napps: {}\ninstances:\n", dies: runtime.GOOS != "windows", // Windows answers "path not found", which missing_ok takes
			setup: func(t *testing.T, py []string, dir string) {
				os.RemoveAll(filepath.Join(dir, "platform-base", "traefik", "config"))
				put(t, dir, "platform-base/traefik/config", "a file\n")
			}},
		{name: "an archived file no one may read: copytree copies every other one, then raises", argv: render, dies: lockedOutHolds(t),
			setup: func(t *testing.T, py []string, dir string) { pyRender(t, py, dir) },
			hold: func(t *testing.T, dir string) func() {
				return lockedOut(t, filepath.Join(dir, ".generated", "registry", "agent-context.json"))
			}},
		{name: "a top-level file no one may read: the archive stops there, in the directory's own order", argv: render, dies: lockedOutHolds(t),
			setup: func(t *testing.T, py []string, dir string) { pyRender(t, py, dir) },
			hold: func(t *testing.T, dir string) func() {
				return lockedOut(t, filepath.Join(dir, ".generated", "glitchtip.projects.yml"))
			}},
		{name: "a generation numbered past 64 bits: the next one after it", argv: render,
			setup: func(t *testing.T, py []string, dir string) {
				put(t, dir, ".generated/generations/99999999999999999999/compose.yml", "old\n")
				put(t, dir, ".generated/compose.yml", "old\n")
			}},
		{name: "the state file is missing on a checkout that has compiled before", argv: render, state: noState,
			files: map[string]string{".generated/resolved.json": "{}"}},
		{name: "a first run: the state created from the product default", argv: render, state: noState},
		{name: "render again: the last render archived, nothing rewritten", argv: render,
			setup: func(t *testing.T, py []string, dir string) { pyRender(t, py, dir) }},
		{name: "a setgid directory and a read-only file in .generated/: archived with their modes (copystat's S_IMODE)", argv: render,
			setup: func(t *testing.T, py []string, dir string) {
				pyRender(t, py, dir)
				reg := filepath.Join(dir, ".generated", "registry")
				if err := os.Chmod(reg, 0o775|fs.ModeSetgid); err != nil { // the bits Windows has none of are ignored there
					t.Fatal(err)
				}
				if err := os.Chmod(filepath.Join(reg, "console.app_bases.json"), 0o444); err != nil {
					t.Fatal(err)
				}
			}},
		// The Dell, 2026-11-01 (DGO-1080): a compiled file another user left — root's, from a control plane
		// compiling in its container — whose bytes must change, is replaced. Windows refuses to remove a
		// read-only file, so both compilers stop there, as they did before.
		{name: "a compiled file this user may not write, whose bytes change: replaced", argv: render,
			dies: runtime.GOOS == "windows",
			setup: func(t *testing.T, py []string, dir string) {
				pyRender(t, py, dir)
				reg := filepath.Join(dir, ".generated", "registry", "console.app_bases.json")
				put(t, dir, ".generated/registry/console.app_bases.json", "stale\n")
				if err := os.Chmod(reg, 0o444); err != nil {
					t.Fatal(err)
				}
			}},
		{name: "an office no longer linked, overlays no longer needed: removed", argv: render,
			state: state,
			setup: func(t *testing.T, py []string, dir string) {
				pyRender(t, py, dir)
				put(t, dir, ".generated/connections.override.yml", "stale\n")
				put(t, dir, ".generated/registry/remote.gone.x.json", "{}\n")
				put(t, dir, ".generated/registry/remote..json", "{}\n")
				put(t, dir, ".generated/registry/remote.json", "{}\n")
				put(t, dir, stateName, withApps(t, withoutRemote(state), "disabled", "console", "app-management", "traefik", "authentik",
					"connections", "bina-ds", "computers", "git", "dgo-extend", "digital-assets"))
			}},
		{name: "authentik switched off for forward-auth: no sign-in blueprint, the last one removed (release 0.3.0)", argv: render,
			state: state,
			setup: func(t *testing.T, py []string, dir string) {
				pyRender(t, py, dir)
				put(t, dir, stateName, withApps(t, withApps(t, state, "disabled", "authentik"), "enabled", "forward-auth"))
			}},
		{name: "twenty-two generations: the oldest pruned, the next numbered after the highest", argv: render,
			setup: func(t *testing.T, py []string, dir string) {
				for i := 1; i <= 22; i++ {
					put(t, dir, fmt.Sprintf(".generated/generations/%04d/compose.yml", i*3), "old\n")
				}
				put(t, dir, ".generated/generations/notes/x", "kept\n")
				put(t, dir, ".generated/plans/0001.yaml", "plan: '0001'\n")
			}},
		{name: "a CPU plan naming a service the compiled set no longer has", argv: render,
			setup: func(t *testing.T, py []string, dir string) {
				put(t, dir, ".generated/cpu-budget.yml", "services:\n  traefik-deployment:\n    deploy: {resources: {limits: {cpus: '0.5'}}}\n  plane-mq:\n    deploy: {resources: {limits: {cpus: '1'}}}\n")
			}},
		{name: "authentik switched off: no bootstrap overlay, the last one removed", argv: render,
			state: withApps(t, state, "disabled", "authentik"),
			setup: func(t *testing.T, py []string, dir string) {
				put(t, dir, ".generated/authentik-bootstrap.override.yml", "services: {}\n")
			}},
	}
	runRenderCases(t, cases)
}

// TestRenderLeavesLinksAsPythonDoes: a dangling link where an overlay no longer needed was
// (`exists()` follows it, so Python leaves it), and a generation that is a link among the oldest
// (`rmtree(ignore_errors=True)` refuses a link, so it stays). A host where this user may not make links
// (Windows without the privilege) cannot prove it: it skips there, and fails under DGO_ORACLE_REQUIRED=1
// rather than let a green run omit it. Linux and macOS always run it.
func TestRenderLeavesLinksAsPythonDoes(t *testing.T) {
	if err := os.Symlink("nowhere", filepath.Join(t.TempDir(), "probe")); err != nil {
		unprovable(t, fmt.Sprintf("this user may not make links here: %v", err))
	}
	link := func(t *testing.T, target, at string) {
		if err := os.MkdirAll(filepath.Dir(at), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(target, at); err != nil {
			t.Fatal(err)
		}
	}
	nothingServed := "schema_version: 1\napps: {}\ninstances:\n"
	runRenderCases(t, []renderCase{
		{name: "a dangling link in .generated/: archiving it raises, as copy2 follows the link", argv: []string{"render"},
			state: "schema_version: 1\napps: {}\n", dies: true,
			setup: func(t *testing.T, py []string, dir string) {
				link(t, "gone.yml", filepath.Join(dir, ".generated", "routing.override.yml"))
			}},
		{name: "a dangling link where traefik's zz-serve.yaml goes, nothing served: unlink takes the link", argv: []string{"render"},
			state: nothingServed,
			setup: func(t *testing.T, py []string, dir string) {
				link(t, "gone.yaml", filepath.Join(dir, "platform-base", "traefik", "config", "zz-serve.yaml"))
			}},
		{name: "a dangling link where traefik's zz-serve.yaml goes, a linked office served: written through the link", argv: []string{"render"},
			setup: func(t *testing.T, py []string, dir string) {
				link(t, "gone.yaml", filepath.Join(dir, "platform-base", "traefik", "config", "zz-serve.yaml"))
			}},
		{name: "the oldest generation is a link: rmtree leaves it", argv: []string{"render"},
			setup: func(t *testing.T, py []string, dir string) {
				put(t, dir, "elsewhere/compose.yml", "kept\n")
				link(t, filepath.Join("..", "..", "elsewhere"), filepath.Join(dir, ".generated", "generations", "0001"))
				for i := 2; i <= 21; i++ {
					put(t, dir, fmt.Sprintf(".generated/generations/%04d/compose.yml", i), "old\n")
				}
				put(t, dir, ".generated/compose.yml", "old\n")
			}},
	})
}

// TestRenderUnderOtherHashSeeds: which consumer and which capability a "pulled in as provider" line
// names depends on the order Python's set iteration meets the enabled apps in — so the oracle runs
// reconcile.py under other seeds too, and every file and every other line must still be dgo's.
func TestRenderUnderOtherHashSeeds(t *testing.T) {
	real, err := os.ReadFile(filepath.Join(officeRoot(t), stateName))
	if err != nil {
		t.Fatal(err)
	}
	state := withApps(t, withoutRemote(string(real)), "enabled", "drive", "mail", "indox", "project-pln", "my-docs", "apitools", "chat")
	var cases []renderCase
	for _, seed := range []string{"1", "7", "42"} {
		cases = append(cases, renderCase{name: "apps pulled in by three consumers, seed " + seed, argv: []string{"render"}, state: state, seed: seed},
			renderCase{name: "--json, seed " + seed, argv: []string{"render", "--json"}, state: state, seed: seed})
	}
	runRenderCases(t, cases)
}

func TestComposeFilesMatchesPython(t *testing.T) {
	cf := []string{"compose-files"}
	rendered := func(more func(dir string)) func(*testing.T, []string, string) {
		return func(t *testing.T, py []string, dir string) {
			pyRender(t, py, dir)
			if more != nil {
				more(dir)
			}
		}
	}
	cases := []renderCase{
		{name: "not rendered", argv: cf},
		{name: "after a render", argv: []string{"compose-files", "--json"}, setup: rendered(nil)},
		{name: "a CPU plan with a stale service: the effective one written", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/cpu-budget.yml", "services:\n  traefik-deployment:\n    deploy: {resources: {limits: {cpus: '0.5'}}}\n  gone:\n    cpus: 1\n")
		})},
		{name: "a CPU plan whose every service exists: itself", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/cpu-budget.yml", "services:\n  traefik-deployment: {cpus: 1}\n  authentik-server: {cpus: 2}\n")
		})},
		{name: "an effective CPU plan that is not UTF-8: reconcile.py raises (only OSError is caught there)", argv: cf, dies: true,
			setup: rendered(func(dir string) {
				put(t, dir, ".generated/cpu-budget.yml", "services:\n  traefik: {cpus: 1}\n  gone: {cpus: 1}\n")
				put(t, dir, ".generated/cpu-budget.effective.yml", "old \xff\n")
			})},
		{name: "a CPU plan that is not YAML: the overlay as rendered", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/cpu-budget.yml", "services: [\n")
		})},
		{name: "a compiled set that cannot be read: the last bootstrap overlay stands", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/routing.override.yml", "services: [\n")
		})},
		// YAML that PyYAML refuses as well as this reader: failing open where reconcile.py does — the CPU
		// plan as rendered, as its stale service shows — and never stopping as if PyYAML had read it
		{name: "an overlay of two documents: PyYAML refuses it too, the CPU plan as rendered", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/cpu-budget.yml", "services:\n  gone: {cpus: 1}\n")
			put(t, dir, ".generated/routing.override.yml", "services: {}\n---\nservices: {}\n")
		})},
		{name: "an overlay with a block scalar header PyYAML refuses (|12), the CPU plan as rendered", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/cpu-budget.yml", "services:\n  gone: {cpus: 1}\n")
			put(t, dir, ".generated/routing.override.yml", "services:\n  zz:\n    command: |12\n      run\n")
		})},
		{name: "an overlay naming an alias it never anchored, the CPU plan as rendered", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/cpu-budget.yml", "services:\n  gone: {cpus: 1}\n")
			put(t, dir, ".generated/routing.override.yml", "services:\n  zz: *nope\n")
		})},
		{name: "an overlay with a directive mid-document, the CPU plan as rendered", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/cpu-budget.yml", "services:\n  gone: {cpus: 1}\n")
			put(t, dir, ".generated/routing.override.yml", "services: {}\n%x\n")
		})},
		{name: "an overlay that ends twice (... ...): PyYAML reads it, and so does dgo", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/cpu-budget.yml", "services:\n  gone: {cpus: 1}\n")
			put(t, dir, ".generated/routing.override.yml", "services: {}\n...\n# done\n...\n")
		})},
		{name: "an overlay with compose's own !reset tag: safe_load has no constructor for it, the CPU plan as rendered", argv: cf,
			setup: rendered(func(dir string) {
				put(t, dir, ".generated/cpu-budget.yml", "services:\n  gone: {cpus: 1}\n")
				put(t, dir, ".generated/routing.override.yml", "services:\n  zz:\n    ports: !reset []\n")
			})},
		{name: "an overlay whose value goes on in a line that starts with a dash: text, as PyYAML reads it", argv: cf,
			setup: rendered(func(dir string) {
				put(t, dir, ".generated/cpu-budget.yml", "services:\n  gone: {cpus: 1}\n")
				put(t, dir, ".generated/routing.override.yml", "services:\n  zz:\n    command: run\n      - fast\n")
			})},
		{name: "an overlay whose value goes on past a comment: PyYAML refuses it, the CPU plan as rendered", argv: cf,
			setup: rendered(func(dir string) {
				put(t, dir, ".generated/cpu-budget.yml", "services:\n  gone: {cpus: 1}\n")
				put(t, dir, ".generated/routing.override.yml", "services:\n  zz:\n    command: run # c\n      fast\n")
			})},
		{name: "includes as mappings, one that is not there", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/compose.yml", "include:\n- path: platform-base/authentik/docker-compose.yml\n- {path: nope.yml}\n- compose.yml\n")
		})},
		{name: "an include whose path is a list that says 'unsupported': a TypeError, failing open", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/compose.yml", "include:\n- {path: [unsupported]}\n")
		})},
		{name: "blueprints/ is a file: the glob finds nothing, the digest of the two inputs", argv: cf, setup: rendered(func(dir string) {
			os.RemoveAll(filepath.Join(dir, "platform-base", "authentik", "blueprints"))
			put(t, dir, "platform-base/authentik/blueprints", "not a directory\n")
		})},
		{name: "no bootstrap in the compiled set: the overlay removed", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, ".generated/compose.yml", "include:\n- compose.yml\n")
		})},
		{name: "a bootstrap input that changed: the overlay rewritten", argv: cf, setup: rendered(func(dir string) {
			put(t, dir, "platform-base/authentik/bootstrap.sh", "#!/bin/sh\r\necho changed\r\n")
			put(t, dir, "platform-base/authentik/blueprints/aa-extra.yaml", "version: 1\n")
		})},
	}
	runRenderCases(t, cases)
}

func TestServePlanMatchesPython(t *testing.T) {
	real, err := os.ReadFile(filepath.Join(officeRoot(t), stateName))
	if err != nil {
		t.Fatal(err)
	}
	state := string(real)
	sp := []string{"serve-plan"}
	cases := []renderCase{
		{name: "this checkout as committed", argv: sp},
		{name: "no remote block", argv: sp, state: withoutRemote(state)},
		{name: "a remote block of every shape", argv: sp, state: withoutRemote(state) + remoteShapes},
		{name: "the legacy serve: block", argv: sp, state: strings.Replace(state, "\nremote:\n", "\nremote: []\nserve:\n", 1)},
		{name: "without dgo-extend's identity.py", argv: sp, state: withoutRemote(state) + remoteShapes,
			files: map[string]string{"apps/dgo-extend/identity.py": removed}},
		{name: "refused, a sentence per reason", argv: sp,
			state: withoutRemote(state) + "remote:\n- office: macbook\n  address: 10.79.3.0\n  apps: [{app: x, port: 1}]\n- 5\n- office: vps\n  address: 10.79.4.2\n  label: 7\n  apps: [{app: y, port: 70000}, {app: z, port: 2, identity: {to: 'a b'}}, {app: w, port: 3, agent_api_port: 3}]\n"},
		{name: "remote: is a mapping", argv: sp, state: withoutRemote(state) + "remote: {office: x}\n"},
		{name: "an office named by a mapping with typed keys: refused, spelled as repr() spells it", argv: sp,
			state: withoutRemote(state) + "remote:\n- office: {true: x, 1.5: y}\n  address: 10.79.3.2\n  apps: []\n"},
		{name: "a manifest that fails validation comes first", argv: sp,
			files: map[string]string{"apps/zz-bad/app.json": manifestJSON("zz-bad", `"bogus":1`)}},
	}
	runRenderCases(t, cases)
}

// TestServePlanOnRandomRemoteBlocks: the `remote:` block is another office's catalog, copied in — so
// serve-plan (the plan's refusals, every tile and row it builds) is asked of 240 seeded random blocks:
// offices, addresses, ports, identities, hosts, modules, orders, labels and marks drawn from pools of
// valid values — and, in every other block, invalid ones too — through reconcile.py's own main() in one
// process, and through dgo. Where Python raises, dgo must stop with one FATAL line (the oracle's rule).
func TestServePlanOnRandomRemoteBlocks(t *testing.T) {
	real, err := os.ReadFile(filepath.Join(officeRoot(t), stateName))
	if err != nil {
		t.Fatal(err)
	}
	dir := generatorTree(t, renderCase{files: map[string]string{".dgo/addressing.json": `{"self": "10.79.3.1"}`}}, string(real))
	base := withoutRemote(string(real))
	r := rand.New(rand.NewSource(20261015))
	hostile := false // this block may draw invalid values too
	// field is `"k": v, ` with v one of the valid values ("" leaves the key out) — or, in a hostile
	// block, now and then one of the invalid ones
	field := func(k string, valid, invalid []string) string {
		pool := valid
		if hostile && len(invalid) > 0 && r.Intn(6) == 0 {
			pool = invalid
		}
		if v := pool[r.Intn(len(pool))]; v != "" {
			return `"` + k + `": ` + v + `, `
		}
		return ""
	}
	vs := func(v ...string) []string { return v }
	app := func() string {
		return "{" + field("app", vs(`"indox"`, `"drive"`, `"sites"`, `"Mail "`, `"bina-ds"`), vs(`""`, `"x y"`, `5`)) +
			field("alias", vs("", `"bina"`, `"Docs "`, `"a-b"`, `null`), vs(`"-bad"`, `"a.b"`)) +
			field("port", vs(`8080`, `"8080"`, `3080`, `true`, `3.7`), vs(`"x"`, `0`, `70000`, `null`)) +
			field("agent_api_port", vs("", `""`, `3081`, `null`), vs(`8080`, `"z"`, `0`)) +
			field("identity", vs("", `{}`, `{"to": "owner"}`, `{"from": ["x", "y"]}`, `{"to": "owner", "from": "z"}`, `{"to": "owner", "from": ["", null]}`), vs(`{"to": "a b"}`, `"str"`, `{"to": "other"}`, `{"from": ["a:b"]}`)) +
			field("host", vs("", `"x.localhost"`, `"H.LOCALHOST"`, `"h.localhost:80"`), vs(`"Bad Host"`, `"h:x"`)) +
			field("module", vs("", `{}`, `{"kind": "external"}`, `{"path": "/x/", "id": "m"}`, `{"kind": "embedded", "path": ""}`), vs(`"str"`)) +
			field("order", vs("", `1`, `2.5`, `"first"`, `true`, `null`), nil) +
			field("name", vs("", `"שם"`, `""`, `7`), nil) + field("name_en", vs("", `"En"`), nil) +
			field("title", vs("", `{"he": "כותרת", "en": "Title"}`, `"x"`, `{"en": "T"}`), nil) +
			field("icon", vs("", `"bot"`), nil) + field("group", vs("", `"עסק"`), nil) +
			field("desc", vs("", `"תיאור"`), nil) + field("health", vs("", `"/ready"`), nil) + `"zz": 0}`
	}
	var calls []call
	var states []string
	for i := 0; i < 240; i++ {
		hostile = i%2 == 1
		var entries []string
		for _, office := range []string{`"macbook"`, `"vps1"`, `" Hp-Laptop "`}[:r.Intn(3)+1] {
			apps := "[" + app()
			for n := r.Intn(3); n > 0; n-- {
				apps += ", " + app()
			}
			apps += "]"
			if hostile && r.Intn(8) == 0 {
				apps = []string{`[]`, `"none"`, `null`}[r.Intn(3)]
			}
			entries = append(entries, "{"+field("office", vs(office), vs(`"Q"`, `""`, `"macbook"`))+
				field("address", vs(`"10.79.3.2"`, `" 10.79.4.2 "`, `"10.79.200.9"`), vs(`"10.79.3.1"`, `"10.79.0.0"`, `"10.79.3.255"`, `"10.80.1.2"`, `"fe80::1"`, `"10.079.3.2"`, `"garbage"`))+
				field("label", vs("", `""`, `"Label"`, `{"he": "ה"}`, `{"en": "E"}`), vs(`7`))+
				field("mark", vs("", `{"color": "lime", "animal": "deer"}`, `{"color": "Muted", "animal": "OWL"}`, `{"color": "red", "animal": "x"}`), nil)+
				field("link_port", vs("", `""`, `9002`, `"9002"`), vs(`0`, `"abc"`))+field("link", vs("", `"l"`), nil)+
				field("commit", vs("", `"c1"`), nil)+`"apps": `+apps+"}")
		}
		state := base + "remote: [" + strings.Join(entries, ", ") + "]\n"
		if i%40 == 0 {
			state = base + "remote: " + []string{`"x"`, `5`, `{}`, `[]`}[r.Intn(4)] + "\nserve: [" + strings.Join(entries, ", ") + "]\n"
		}
		states = append(states, state)
		calls = append(calls, call{argv: []string{"serve-plan"}, write: map[string]*string{stateName: &states[len(states)-1]}})
	}
	want := pythonAnswers(t, dir, calls)
	bad, refused, raised := 0, 0, 0
	for i := range calls {
		put(t, dir, stateName, states[i])
		var out, errb bytes.Buffer
		code := ServePlanCmd(dir, nil, &out, &errb)
		w := want[i]
		same := code == w.Code && out.String() == w.Stdout && errb.String() == w.Stderr
		if strings.HasPrefix(w.Stderr, "Traceback") {
			raised++
			same = code == w.Code && out.String() == w.Stdout && strings.HasPrefix(errb.String(), "FATAL ") && strings.Count(errb.String(), "\n") == 1
		}
		if !same {
			if bad++; bad <= 5 {
				t.Errorf("block %d:\n%s\n--- dgo (exit %d):\n%s%s--- reconcile.py (exit %d):\n%s%s", i, states[i][len(base):], code, out.String(), errb.String(), w.Code, w.Stdout, w.Stderr)
			}
		}
		if w.Code != 0 {
			refused++
		}
	}
	t.Logf("%d of %d random remote blocks answered as reconcile.py answers them: %d planned, %d refused (%d where Python raises)",
		len(calls)-bad, len(calls), len(calls)-refused, refused, raised)
}

// TestMarksAreDgoExtends holds the compiler's copy of the office-mark vocabulary to
// apps/dgo-extend/identity.py itself: the mark each name gets and each published mark's cleaning.
// TestCatalogStopsAtHalfASurrogatePair: json.loads keeps a lone \ud800 escape as half a character, which
// a Go string cannot hold — so every verb that loads the catalog stops and says so (the reader-gap
// rule), rather than answer from a text Python does not have.
func TestCatalogStopsAtHalfASurrogatePair(t *testing.T) {
	dir := t.TempDir()
	put(t, dir, "apps/zz-half/app.json", strings.Replace(manifestJSON("zz-half", ""), "בדיקה", `x\ud800`, 1))
	_, err := LoadCatalog(dir)
	if err == nil || !strings.HasPrefix(err.Error(), "FATAL "+filepath.Join("apps", "zz-half", "app.json")+": Unpaired surrogate escape") ||
		!strings.HasSuffix(err.Error(), "DGO_COMPILER=python answers") {
		t.Fatalf("LoadCatalog: %v", err)
	}
}

func TestMarksAreDgoExtends(t *testing.T) {
	py := python(t)
	root := repoRoot(t)
	names := []string{"hp", "HP ", "hp-laptop", "macbook", "vps", "vps1", "vps2", "staging", "office-7", "שלום", "", "a"}
	marks := []string{`{"color":"lime","animal":"deer"}`, `{"color":" Muted ","animal":"OWL"}`, `{"color":"red","animal":"deer"}`,
		`{"color":"sky"}`, `"lime"`, `{"color":5,"animal":"fox"}`, `null`, `{}`}
	const oracle = `import json, sys
sys.path.insert(0, sys.argv[1])
import identity
names, marks = json.load(sys.stdin)
print(json.dumps([[identity.clean_mark(json.loads(m)) or identity.mark_for(n) for m in marks] for n in names]))`
	cmd := exec.Command(py[0], append(py[1:], "-c", oracle, filepath.Join(root, "apps", "dgo-extend"))...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	in, _ := json.Marshal([]any{names, marks})
	cmd.Stdin = bytes.NewReader(in)
	raw, err := cmd.Output()
	if err != nil {
		t.Fatalf("identity.py: %v", err)
	}
	var want [][]map[string]string
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatal(err)
	}
	for i, n := range names {
		for j, m := range marks {
			v, err := yamlish.LoadJSON(m)
			if err != nil {
				t.Fatal(err)
			}
			got := officeMark(root, v, n)
			color, _ := got.Get("color")
			animal, _ := got.Get("animal")
			if color != want[i][j]["color"] || animal != want[i][j]["animal"] {
				t.Errorf("mark of %q with %s: dgo %v/%v, identity.py %v", n, m, color, animal, want[i][j])
			}
		}
	}
	t.Logf("%d names × %d published marks: the marks identity.py gives", len(names), len(marks))
}

// holdsNaN reports whether a value holds a NaN anywhere — the one value sorted() has no order for.
func holdsNaN(v any) bool {
	switch t := v.(type) {
	case float64:
		return math.IsNaN(t)
	case []any:
		for _, e := range t {
			if holdsNaN(e) {
				return true
			}
		}
	case *yamlish.Map:
		for _, k := range t.Keys() {
			if e, _ := t.Get(k); holdsNaN(e) {
				return true
			}
		}
	}
	return false
}

// TestSortIsCPythons holds pySortedBy — the order of the console's tiles, the office's apps and the
// agent's briefs — to sorted() itself on 600 seeded random key lists: numbers of every kind, NaN, text,
// lists (the (order, alias) keys), and the mixtures Python refuses with a TypeError. Lists holding a NaN
// stay under 64 keys (beyond, timsort merges, and NaN has no order to agree on); the others reach 90.
func TestSortIsCPythons(t *testing.T) {
	py := python(t)
	r := rand.New(rand.NewSource(7))
	number := func(nan bool) any {
		switch r.Intn(6) {
		case 0:
			return r.Intn(3) == 0
		case 1:
			return float64(r.Intn(7)) / 2
		case 2:
			if nan {
				return "NaN"
			}
		}
		return int64(r.Intn(9) - 2)
	}
	// a pair's first item: a number (NaN too, where binary insertion is the whole sort — json.loads, as
	// PyYAML, reads every NaN as one object, which tuple comparison finds equal to itself) or now and
	// then a mapping, which == compares and < refuses
	head := func(nan bool) any {
		if r.Intn(10) == 0 {
			return map[string]any{"k": number(false)}
		}
		return number(nan)
	}
	var lists [][]any
	for i := 0; i < 600; i++ {
		nan := i%3 == 0
		n := r.Intn(90)
		if nan {
			n = r.Intn(64)
		}
		keys := make([]any, n)
		var same any // now and then one head for every pair of a list: mappings equal to each other
		switch i % 12 {
		case 8:
			same = map[string]any{"k": 1}
		case 11:
			same = map[string]any{"k": "NaN"}
		}
		for j := range keys {
			switch i % 3 { // one kind of key per list: numbers (with NaN), text, (order, alias) pairs
			case 0:
				keys[j] = number(true)
			case 1:
				keys[j] = []string{"a", "b", "ab", "B", "", "é"}[r.Intn(6)]
			default:
				h := same
				if h == nil {
					h = head(n < 64)
				}
				keys[j] = []any{h, []string{"a", "b"}[r.Intn(2)]}
			}
		}
		switch i % 20 { // now and then one key Python cannot compare with the rest
		case 7:
			if n > 0 {
				keys[r.Intn(n)] = "text"
			}
		case 11:
			if n > 0 {
				keys[r.Intn(n)] = nil
			}
		}
		lists = append(lists, keys)
	}
	body, _ := json.Marshal(lists)
	text := strings.ReplaceAll(string(body), `"NaN"`, "NaN") // json.loads reads NaN as the float
	const oracle = `import json, sys
out = []
for keys in json.load(sys.stdin):
    keys = [tuple(k) if isinstance(k, list) else k for k in keys]
    try:
        out.append(sorted(range(len(keys)), key=lambda i: keys[i]))
    except TypeError:
        out.append(None)
print(json.dumps({"version": sys.version_info[:2], "orders": out}))`
	cmd := exec.Command(py[0], append(py[1:], "-c", oracle)...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	cmd.Stdin = strings.NewReader(text)
	raw, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	var answer struct {
		Version [2]int
		Orders  [][]int
	}
	if err := json.Unmarshal(raw, &answer); err != nil {
		t.Fatal(err)
	}
	want := answer.Orders
	// 3.13 counts a list's first run otherwise (gh-116554) — an order only a NaN key, which has none,
	// can tell apart; the port is of the sort through 3.12, so a newer oracle is asked the rest only
	nanAsked := answer.Version[0] == 3 && answer.Version[1] <= 12
	decoded, err := yamlish.LoadJSON(text)
	if err != nil {
		t.Fatal(err)
	}
	bad, refused, unasked := 0, 0, 0
	for i, keys := range decoded.([]any) {
		if !nanAsked && holdsNaN(keys) {
			unasked++
			continue
		}
		idx := make([]int, len(keys.([]any)))
		for j := range idx {
			idx[j] = j
		}
		ks := keys.([]any)
		got, err := pySortedBy(idx, func(j int) any { return ks[j] })
		if want[i] == nil {
			refused++
		}
		if (err != nil) != (want[i] == nil) || err == nil && fmt.Sprint(got) != fmt.Sprint(want[i]) {
			if bad++; bad <= 5 {
				t.Errorf("keys %v: dgo %v (%v), sorted() %v", ks, got, err, want[i])
			}
		}
	}
	t.Logf("%d of %d key lists ordered as sorted() %d.%d orders them (%d refused with its TypeError, %d holding NaN not asked)",
		len(lists)-bad-unasked, len(lists), answer.Version[0], answer.Version[1], refused, unasked)
}

// TestFormatIsPythons holds pyFormat — what a blueprint's !Format is filled with — to `%` itself.
func TestFormatIsPythons(t *testing.T) {
	py := python(t)
	cases := []struct {
		format string
		args   []string
	}{
		{"%s://%s", []string{"https", "x.localhost"}}, {"%s://%s/", []string{"http", "auth"}}, {"plain", nil},
		{"plain", []string{"x"}}, {"%s", nil}, {"%s %s", []string{"a"}}, {"%%s%s", []string{"a"}}, {"%5s|%-5s|", []string{"ab", "cd"}},
		{"%.2s", []string{"abcdef"}}, {"%r", []string{"it's"}}, {"%a", []string{"שלום"}}, {"%c", []string{"x"}}, {"%c", []string{"xy"}},
		{"%d", []string{"1"}}, {"%(k)s", []string{"x"}}, {"%*s", []string{"x"}}, {"%ls", []string{"x"}}, {"%", nil}, {"%y", []string{"x"}},
		{"%-08.3s|", []string{"abcdef"}}, {"a%", nil}, {"%.s|", []string{"abc"}}, {"%5%|", nil}, {"%5%|", []string{"x"}},
		{"%l%|", nil}, {"%%|", nil}, {"% s|%#s|%+s", []string{"a", "b", "c"}}, {"%05s|", []string{"ab"}}, {"%5.1c|", []string{"x"}},
	}
	const oracle = `import json, sys
out = []
for f, a in json.load(sys.stdin):
    try:
        out.append(f % tuple(a))
    except (TypeError, ValueError):
        out.append(None)
print(json.dumps(out))`
	cmd := exec.Command(py[0], append(py[1:], "-c", oracle)...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	var in []any
	for _, c := range cases {
		in = append(in, []any{c.format, append([]string{}, c.args...)})
	}
	body, _ := json.Marshal(in)
	cmd.Stdin = bytes.NewReader(body)
	raw, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	var want []*string
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatal(err)
	}
	for i, c := range cases {
		got, ok := pyFormat(c.format, c.args)
		if ok != (want[i] != nil) || ok && got != *want[i] {
			t.Errorf("%q %% %q: dgo %q (%v), Python %v", c.format, c.args, got, ok, want[i])
		}
	}
	t.Logf("%d formats filled as %% fills them", len(cases))
}

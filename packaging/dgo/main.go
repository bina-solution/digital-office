// Command dgo is the office's one native binary — core-005, step 1 of ai/context/core-native-plan.md.
//
// This slice is the CLI: it finds the checkout, answers the compiler's twenty verbs by DELEGATING to
// `platform/manager/reconcile.py` (the Python compiler stays the implementation until step 2 ports
// it verb by verb), dispatches every app's verbs from its `hooks/` directory exactly as `bbox` does,
// and hands everything else (`run`, `status`, `apps`, …) to `bbox` until a later step absorbs it.
// Nothing an app, a gate or a hook calls today changes: the contract measured in the plan's §6 is
// answered under the same names, with the same arguments and the same exit codes.
//
// WHY A BINARY THAT DELEGATES IS WORTH SHIPPING NOW: it is the surface. The day the compiler is Go
// (step 2) nothing that calls `dgo validate` notices; the day the engine provisioning moves in
// (`bbox.cmd`'s WSL hand-off, `bbox engine` on a Mac), `dgo run` is the one thing a person runs on
// any OS — and the installer (packaging/installer) already hands over to "DGO core", which is this.
//
// Build (release): go build -trimpath -ldflags "-s -w" . && go test ./...
// Cross-compile for every OS from one host: GOOS=windows|darwin|linux GOARCH=amd64|arm64 go build .
// Stdlib-only and CGO_ENABLED=0, like the two binaries before it — that property is the owner's ask.
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/console"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/edge"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/engine"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/native"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/serve"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/store"
)

var version = "dev" // -ldflags "-X main.version=…"

// compilerVerbs is the compiler's contract (reconcile.py main(), measured in the plan's §6): every
// one not answered natively is delegated to the Python compiler with the arguments untouched.
var compilerVerbs = compiler.Verbs

// roots are the two directories an app lives in — the directory is the layer.
var roots = []string{"apps", "platform-base"}

// invocation is what dgo decided to run: a native verb (the compiler in Go, step 2), or a program
// with its arguments — and one line saying why.
type invocation struct {
	native func(stdout, stderr io.Writer) int
	argv   []string
	why    string
}

// nativeVerbs are the compiler verbs answered in-process (packaging/dgo/internal/compiler), each
// diff-tested against reconcile.py, each given the arguments after its name to read as reconcile.py
// reads them. DGO_COMPILER=python delegates them to Python again — the plan's per-verb rollback, so
// a wrong answer is one environment variable away from the old one.
var nativeVerbs = map[string]func(root string, args []string, stdout, stderr io.Writer) int{
	"enabled-apps":        compiler.EnabledAppsCmd,
	"validate":            compiler.ValidateCmd,
	"services":            compiler.ServicesCmd,
	"required-by":         compiler.RequiredByCmd,
	"compose-services":    compiler.ComposeServicesCmd,
	"capability-provider": compiler.CapabilityProviderCmd,
	"blueprints":          compiler.BlueprintsCmd,
	"generations":         compiler.GenerationsCmd,
	"office-get":          compiler.OfficeGetCmd,
	"remote-get":          compiler.RemoteGetCmd,
	"render":              compiler.RenderCmd,
	"compose-files":       compiler.ComposeFilesCmd,
	"serve-plan":          compiler.ServePlanCmd,
	"set-state":           compiler.SetStateCmd,
	"office-set": func(root string, args []string, out, err io.Writer) int {
		return compiler.OfficeSetCmd(root, args, os.Stdin, out, err)
	},
	"remote-set": func(root string, args []string, out, err io.Writer) int {
		return compiler.RemoteSetCmd(root, args, os.Stdin, out, err)
	},
}

// children are the office's own long-running processes, `dgo be-child <name>` (the architecture's
// §5.1): native on every OS, each with its own rollback inside it, resolved by child() — which main()
// asks before it looks for a checkout. `be-child` is no app id, no cli.alias and no bbox verb, so it
// shadows nothing (TestBeChildShadowsNoAppAndNoBboxVerb, TestBeChildRunsTheConsoleServerAndShadowsNoApp).
var children = map[string]func(root string, args []string, stderr io.Writer) int{
	"console": console.Main, // the shell's files and file-only routes; DGO_CONSOLE=container hands them all back
	"control": serve.Main,   // app-management's routes; BBOX_CONTROL_PLANE=container hands them all back
	"edge":    edge.Main,    // the edge where there is no traefik: by host, gated through forward-auth (DGO-1090)
	"native":  native.Main,  // the phone's core in one process: edge, console, control, on its own sockets (DGO-1090)
}

func main() {
	if len(os.Args) > 1 && (os.Args[1] == "-version" || os.Args[1] == "--version") {
		fmt.Println("dgo " + version)
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "be-child" {
		// before the checkout is looked for: the office's own processes start without one (the
		// console's rollback must reach its container from anywhere), and are given it when there is
		// one — and before plan(), so no OS hands them to bbox
		root, _ := findRoot(mustCwd(), executableDir())
		if dir := os.Getenv("DGO_OFFICE_ROOT"); root == "" && dir != "" {
			// no checkout: a phone's office root, when the app names one (DGO-1090) — and why not, when
			// the one it names is refused, before the child's own refusal of no root at all
			var err error
			if root, err = officeRoot(dir); err != nil {
				fmt.Fprintln(os.Stderr, "dgo: DGO_OFFICE_ROOT:", err)
			}
		}
		inv, err := child(root, os.Args[2:])
		if err != nil {
			fatal(err.Error())
		}
		os.Exit(inv.native(os.Stdout, os.Stderr))
	}
	root, err := findRoot(mustCwd(), executableDir())
	if err != nil {
		fatal(noCheckout(runtime.GOOS, err))
	}
	if len(os.Args) < 2 || os.Args[1] == "help" || os.Args[1] == "-h" || os.Args[1] == "--help" {
		fmt.Print(help(root))
		return
	}
	inv, err := plan(root, os.Args[1:], runtime.GOOS)
	if err != nil {
		fatal(err.Error() + "\n\n" + help(root))
	}
	os.Exit(run(root, inv))
}

// ── the checkout ──────────────────────────────────────────────────────────────────────────────────

// noCheckout is what dgo says with no checkout around it — and on a phone, where the office runs
// instead: dgo for android/arm64 is met there first, in an app, before any checkout (DGO-1069).
func noCheckout(goos string, err error) string {
	if goos == "android" {
		return err.Error() + "\n\n" + engine.OnAndroid
	}
	return err.Error()
}

// findRoot walks up from each start directory to the checkout that holds the compiler and bbox.
// Both must be there: a stray copy of one file is not an office.
func findRoot(starts ...string) (string, error) {
	for _, s := range starts {
		for d := s; d != ""; {
			if isFile(filepath.Join(d, "platform", "manager", "reconcile.py")) && isFile(filepath.Join(d, "bbox")) {
				return d, nil
			}
			parent := filepath.Dir(d)
			if parent == d {
				break
			}
			d = parent
		}
	}
	return "", errors.New("dgo: not inside a DGO checkout (no platform/manager/reconcile.py + bbox above here)")
}

// ── the verbs ─────────────────────────────────────────────────────────────────────────────────────

// plan turns a command line into what to run. Order: a native compiler verb, the office's own
// processes (be-child), the store (index), `engine doctor|plan`, a compiler verb delegated to
// reconcile.py, then — on Windows — the bbox.cmd hand-off, then an app (by id or by its `cli.alias`)
// with one of its hook verbs, then bbox — which is also where a name nobody knows ends up, because
// bbox's own help is the one that lists it.
func plan(root string, args []string, goos string) (invocation, error) {
	verb := args[0]
	if fn, ok := nativeVerbs[verb]; ok && os.Getenv("DGO_COMPILER") != "python" {
		native := func(out, err io.Writer) int { return fn(root, args[1:], out, err) }
		return invocation{native: native, why: "compiler verb, native (DGO_COMPILER=python delegates it)"}, nil
	}
	if verb == "be-child" { // before the WSL hand-off below: the office's own processes run on the host
		return child(root, args[1:])
	}
	if sv, ok := store.Verbs[verb]; ok { // the store (internal/store): native on every OS, before the WSL hand-off
		return invocation{native: func(out, errw io.Writer) int { return sv(root, args[1:], out, errw) }, why: "store verb, native"}, nil
	}
	// `engine doctor|plan` read the engine natively, on every OS — so before the Windows hand-off below.
	// Every other `engine` verb (start, stop, shell …) stays bbox's; DGO_ENGINE=bbox hands these two back.
	if verb == "engine" && len(args) == 2 && engine.Owns(args[1]) && os.Getenv("DGO_ENGINE") != "bbox" {
		return invocation{native: func(out, _ io.Writer) int { return engine.Main(root, args[1], engine.Real(), out) },
			why: "engine verb, native (DGO_ENGINE=bbox hands it to bbox)"}, nil
	}
	for _, v := range compilerVerbs {
		if verb == v {
			py, err := pythonFor(goos, exec.LookPath)
			if err != nil {
				return invocation{}, err
			}
			argv := append(append([]string{}, py...), filepath.Join(root, "platform", "manager", "reconcile.py"))
			return invocation{argv: append(argv, args...), why: "compiler verb, delegated to reconcile.py"}, nil
		}
	}
	// On Windows the office runs INSIDE the project's own WSL engine (ai/context/running-on-wsl.md):
	// a hook or `run` started by the host's own bash would address an engine that is not there. So
	// everything but the compiler's verbs goes through bbox.cmd, which hands itself to WSL — until
	// step 1b moves that hand-off in here.
	if goos == "windows" {
		return invocation{argv: append([]string{"cmd", "/c", filepath.Join(root, "bbox.cmd")}, args...),
			why: "handed to bbox.cmd (the WSL hand-off)"}, nil
	}
	if aid, dir := appOf(root, verb); aid != "" {
		if len(args) < 2 {
			return invocation{}, fmt.Errorf("dgo %s needs a verb: %s", verb, strings.Join(appVerbs(dir), " "))
		}
		hook, runner, err := resolveHook(dir, args[1])
		if err != nil {
			return invocation{}, fmt.Errorf("dgo %s %s: %v (its verbs: %s)", verb, args[1], err, strings.Join(appVerbs(dir), " "))
		}
		argv := append(append([]string{}, runner...), hook)
		return invocation{argv: append(argv, args[2:]...), why: "app verb " + aid + "/" + args[1]}, nil
	}
	return invocation{argv: append([]string{"bash", filepath.Join(root, "bbox")}, args...),
		why: "handed to bbox (not absorbed yet)"}, nil
}

// pythonFor finds the compiler's interpreter the way each OS has it: `python3` where it exists,
// `python` next, and the Windows launcher (`py -3`) last — a Windows host has no `python3` on its
// PATH, and refusing there would make the binary less portable than the bash it replaces.
func pythonFor(goos string, look func(string) (string, error)) ([]string, error) {
	for _, c := range []string{"python3", "python"} {
		if p, err := look(c); err == nil {
			return []string{p}, nil
		}
	}
	if goos == "windows" {
		if p, err := look("py"); err == nil {
			return []string{p, "-3"}, nil
		}
	}
	return nil, errors.New("dgo: the compiler needs python3 and none was found on PATH (step 2 of the plan removes this)")
}

// appOf resolves a token to an app directory: the app's id, or the `cli.alias` its manifest declares.
func appOf(root, token string) (string, string) {
	for _, r := range roots {
		d := filepath.Join(root, r, token)
		if isDir(filepath.Join(d, "hooks")) {
			return token, d
		}
	}
	for _, r := range roots {
		entries, _ := os.ReadDir(filepath.Join(root, r))
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			d := filepath.Join(root, r, e.Name())
			if cliAlias(d) == token && isDir(filepath.Join(d, "hooks")) {
				return e.Name(), d
			}
		}
	}
	return "", ""
}

// cliAlias is `cli.alias` of an app's manifest, or "".
func cliAlias(appDir string) string {
	raw, err := os.ReadFile(filepath.Join(appDir, "app.json"))
	if err != nil {
		return ""
	}
	var m struct {
		CLI struct {
			Alias string `json:"alias"`
		} `json:"cli"`
	}
	if json.Unmarshal(raw, &m) != nil {
		return ""
	}
	return m.CLI.Alias
}

// appVerbs lists an app's verbs the way bbox's app_verbs does: the BASE names of the files in its
// hooks/ directory — `doc-trace`, whether the file is doc-trace, doc-trace.py or doc-trace.mjs —
// sorted, deduplicated, `__pycache__` ignored.
func appVerbs(appDir string) []string {
	entries, err := os.ReadDir(filepath.Join(appDir, "hooks"))
	if err != nil {
		return nil
	}
	seen := map[string]bool{}
	for _, e := range entries {
		n := e.Name()
		if n == "__pycache__" || strings.HasPrefix(n, ".") {
			continue
		}
		for _, ext := range []string{".py", ".mjs", ".sh"} {
			n = strings.TrimSuffix(n, ext)
		}
		seen[n] = true
	}
	out := make([]string, 0, len(seen))
	for v := range seen {
		out = append(out, v)
	}
	sort.Strings(out)
	return out
}

// resolveHook finds the file behind a verb in bbox's order — bare, .sh, .py, .mjs — and names the
// runner its extension wants. A bare file is run by bash, not executed directly: a checkout on a
// Windows drive has no execute bit to speak of.
func resolveHook(appDir, verb string) (string, []string, error) {
	for _, ext := range []string{"", ".sh", ".py", ".mjs"} {
		p := filepath.Join(appDir, "hooks", verb+ext)
		if !isFile(p) {
			continue
		}
		switch ext {
		case ".py":
			return p, []string{"python3"}, nil
		case ".mjs":
			return p, []string{"node"}, nil
		default:
			return p, []string{"bash"}, nil
		}
	}
	return "", nil, errors.New("no such hook")
}

// ── running, and saying what ─────────────────────────────────────────────────────────────────────

// run executes the invocation with this process's stdio and returns the child's exit code —
// a hook's or the compiler's exit code IS the answer, and gates read it.
func run(root string, inv invocation) int {
	if inv.native != nil {
		return inv.native(os.Stdout, os.Stderr)
	}
	cmd := exec.Command(inv.argv[0], inv.argv[1:]...)
	cmd.Dir = root
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	cmd.Env = append(os.Environ(), "DGO_ROOT="+root, "DGO_VERSION="+version)
	if err := cmd.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return ee.ExitCode()
		}
		fmt.Fprintf(os.Stderr, "dgo: %s: %v\n", inv.why, err)
		return 127
	}
	return 0
}

// help is generated from the tree, like bbox's: the compiler's verbs, then every app that has hooks.
func help(root string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "dgo %s — the office's one binary (checkout: %s)\n\n", version, root)
	native := make([]string, 0, len(nativeVerbs))
	for v := range nativeVerbs {
		native = append(native, v)
	}
	sort.Strings(native)
	fmt.Fprintf(&b, "the compiler (native: %s; the rest delegated to platform/manager/reconcile.py until step 2 is done):\n  dgo ", strings.Join(native, ", "))
	b.WriteString(strings.Join(compilerVerbs, " | "))
	b.WriteString("\n\nthe app store's signed index (native):\n  dgo index build | verify | install --dry-run")
	b.WriteString("\n\napps (each verb is a file in the app's hooks/):\n")
	for _, r := range roots {
		entries, _ := os.ReadDir(filepath.Join(root, r))
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			d := filepath.Join(root, r, e.Name())
			verbs := appVerbs(d)
			if len(verbs) == 0 {
				continue
			}
			tok := e.Name()
			if a := cliAlias(d); a != "" {
				tok = a + " (" + e.Name() + ")"
			}
			fmt.Fprintf(&b, "  dgo %-28s %s\n", tok, strings.Join(verbs, " "))
		}
	}
	fmt.Fprintf(&b, "\nthe office's own processes: dgo be-child %s\n", childNames())
	b.WriteString("\neverything else (run, status, apps, …) is handed to bbox until dgo absorbs it: dgo run\n")
	return b.String()
}

// child resolves `dgo be-child <name> <args…>`: the process, run in this one with its own flags, and
// root ("" outside a checkout) handed to it.
func child(root string, args []string) (invocation, error) {
	name := ""
	if len(args) > 0 {
		name = args[0]
	}
	run, ok := children[name]
	if !ok {
		return invocation{}, fmt.Errorf("dgo be-child %s: no such process (the office's own: %s)", name, childNames())
	}
	return invocation{native: func(_, stderr io.Writer) int { return run(root, args[1:], stderr) },
		why: "the office's own process " + name}, nil
}

// childNames lists the processes `dgo be-child` runs, sorted.
func childNames() string {
	names := make([]string, 0, len(children))
	for n := range children {
		names = append(names, n)
	}
	sort.Strings(names)
	return strings.Join(names, " | ")
}

func mustCwd() string {
	d, err := os.Getwd()
	if err != nil {
		fatal("dgo: " + err.Error())
	}
	return d
}

func executableDir() string {
	p, err := os.Executable()
	if err != nil {
		return ""
	}
	return filepath.Dir(p)
}

// officeRoot is a phone's office root (DGO-1090; ai/context/research/android-path.md): a directory the
// app unpacks into its own storage with the core's state file and the core apps' manifests — no
// compiler, no bbox — marked by `.dgo-office-root`. Only `be-child` looks for one, and only where no
// checkout was found: a stray marker inside a checkout never wins, and the CLI's verbs, which need the
// compiler, never run against a root that has none. What it holds is what this office answers, so a
// root others may write to is none, and its two files must be regular ones (a FIFO would hang every
// read). The error says why dir is not such a root.
func officeRoot(dir string) (string, error) {
	if !filepath.IsAbs(dir) {
		return "", fmt.Errorf("%q is not an absolute path", dir)
	}
	dir = filepath.Clean(dir) // the catalog's messages name its files relative to it, as Python's do
	st, err := os.Stat(dir)
	if err != nil || !st.IsDir() {
		return "", fmt.Errorf("%s is not a directory", dir)
	}
	if runtime.GOOS != "windows" && st.Mode().Perm()&0o022 != 0 {
		return "", fmt.Errorf("%s may be written by others than its owner (%v)", dir, st.Mode().Perm())
	}
	for _, f := range []string{".dgo-office-root", "platform.state.yaml"} {
		if st, err := os.Stat(filepath.Join(dir, f)); err != nil || !st.Mode().IsRegular() {
			return "", fmt.Errorf("%s holds no %s (a regular file)", dir, f)
		}
	}
	return dir, nil
}

func isFile(p string) bool { st, err := os.Stat(p); return err == nil && !st.IsDir() }
func isDir(p string) bool  { st, err := os.Stat(p); return err == nil && st.IsDir() }

func fatal(msg string) {
	fmt.Fprintln(os.Stderr, msg)
	os.Exit(2)
}

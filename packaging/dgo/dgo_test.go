package main

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"
)

// a checkout: the two files that make one, two apps (one with a cli.alias), hooks in every shape
func checkout(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	must := func(err error) {
		if err != nil {
			t.Fatal(err)
		}
	}
	must(os.MkdirAll(filepath.Join(root, "platform", "manager"), 0o755))
	must(os.WriteFile(filepath.Join(root, "platform", "manager", "reconcile.py"), []byte("# the compiler\n"), 0o644))
	must(os.WriteFile(filepath.Join(root, "bbox"), []byte("#!/usr/bin/env bash\n"), 0o755))
	hooks := filepath.Join(root, "apps", "indox", "hooks")
	must(os.MkdirAll(filepath.Join(hooks, "__pycache__"), 0o755))
	for _, f := range []string{"test", "doc-trace.py", "accept.mjs", "seed.sh", "test.py"} {
		must(os.WriteFile(filepath.Join(hooks, f), []byte("x"), 0o755))
	}
	must(os.WriteFile(filepath.Join(root, "apps", "indox", "app.json"), []byte(`{"id":"indox","cli":{"alias":"docs"}}`), 0o644))
	must(os.MkdirAll(filepath.Join(root, "platform-base", "n8n", "hooks"), 0o755))
	must(os.WriteFile(filepath.Join(root, "platform-base", "n8n", "hooks", "push"), []byte("x"), 0o755))
	must(os.MkdirAll(filepath.Join(root, "apps", "no-hooks"), 0o755))
	return root
}

func TestTheCheckoutIsFoundFromAnywhereBelowIt(t *testing.T) {
	root := checkout(t)
	deep := filepath.Join(root, "apps", "indox", "hooks", "__pycache__")
	got, err := findRoot(deep)
	if err != nil || got != root {
		t.Fatalf("findRoot(%s) = %q, %v; want %q", deep, got, err, root)
	}
	if _, err := findRoot(t.TempDir()); err == nil {
		t.Fatal("a directory with no compiler and no bbox above it is not a checkout")
	}
	// one file alone is not an office
	half := t.TempDir()
	_ = os.MkdirAll(filepath.Join(half, "platform", "manager"), 0o755)
	_ = os.WriteFile(filepath.Join(half, "platform", "manager", "reconcile.py"), []byte(""), 0o644)
	if _, err := findRoot(half); err == nil {
		t.Fatal("a compiler without bbox is not a checkout")
	}
}

// ownTempDir is t.TempDir() made its owner's alone, as an app's own storage is: under a umask of 002
// (Ubuntu's, with a group per user) t.TempDir() is 0775, which an office root rightly is not.
func ownTempDir(t *testing.T) string {
	t.Helper()
	d := t.TempDir()
	if err := os.Chmod(d, 0o700); err != nil {
		t.Fatal(err)
	}
	return d
}

// A phone's office root (DGO-1090) is known by its marker AND a state file, both regular files, in a
// directory only its owner writes, by an absolute path only; anything else is no root, and be-child
// then has none, as outside a checkout.
func TestAnOfficeRootIsKnownByItsMarker(t *testing.T) {
	file := func(dir, name string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	none := func(dir, why string) {
		t.Helper()
		if got, err := officeRoot(dir); got != "" || err == nil {
			t.Fatalf("%s was taken for an office root (%q, %v)", why, got, err)
		}
	}
	dir := ownTempDir(t)
	none(dir, "an empty directory")
	file(dir, "platform.state.yaml")
	none(dir, "a state file without the marker")
	file(dir, ".dgo-office-root")
	if got, err := officeRoot(dir); got != dir || err != nil {
		t.Fatalf("officeRoot = %q, %v; want %q", got, err, dir)
	}
	if got, _ := officeRoot(dir + string(filepath.Separator)); got != dir {
		t.Fatalf("officeRoot of %q = %q, want it clean: %q", dir+string(filepath.Separator), got, dir)
	}
	marker := ownTempDir(t)
	file(marker, ".dgo-office-root")
	none(marker, "a marker without the state file")
	dirMarker := ownTempDir(t)
	file(dirMarker, "platform.state.yaml")
	if err := os.Mkdir(filepath.Join(dirMarker, ".dgo-office-root"), 0o700); err != nil {
		t.Fatal(err)
	}
	none(dirMarker, "a marker that is a directory")
	none(filepath.Join(dir, "platform.state.yaml"), "a file")
	none("relative/dir", "a relative path")
	none("", "an empty path")
	if runtime.GOOS != "windows" {
		if err := os.Chmod(dir, 0o777); err != nil {
			t.Fatal(err)
		}
		none(dir, "a root anyone may write to")
	}
}

// main() takes the office root DGO_OFFICE_ROOT names where there is no checkout, so the control plane
// starts from it; and when the root it names is refused, says why before the control plane's refusal.
func TestBeChildFindsAnOfficeRootWhereThereIsNoCheckout(t *testing.T) {
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	control := func(root string) *exec.Cmd {
		// bounded: were a checkout found above the temp directory after all, the control plane would
		// answer from it and never exit
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		t.Cleanup(cancel)
		cmd := exec.CommandContext(ctx, exe, "be-child", "control", "--listen", "127.0.0.1:0", "--container", "http://127.0.0.1:9")
		cmd.Dir = t.TempDir()
		cmd.Env = append(os.Environ(), "DGO_TEST_MAIN=1", "BBOX_CONTROL_PLANE=", "DGO_OFFICE_ROOT="+root)
		return cmd
	}
	root := ownTempDir(t)
	for _, f := range []string{".dgo-office-root", "platform.state.yaml"} {
		if err := os.WriteFile(filepath.Join(root, f), []byte("schema_version: 1\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	cmd := control(root)
	stderr, err := cmd.StderrPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer cmd.Process.Kill()
	said := make(chan string, 1)
	go func() {
		line, _ := bufio.NewReader(stderr).ReadString('\n')
		said <- line
	}()
	select {
	case line := <-said:
		if !strings.Contains(line, "answering on http://127.0.0.1:") {
			t.Fatalf("dgo be-child control from an office root said %q", line)
		}
	case <-time.After(20 * time.Second):
		t.Fatal("dgo be-child control from an office root said nothing")
	}
	out, err := control(ownTempDir(t)).CombinedOutput()
	if err == nil || !strings.Contains(string(out), "dgo: DGO_OFFICE_ROOT:") || !strings.Contains(string(out), "holds no .dgo-office-root") {
		t.Fatalf("an unmarked root: %v, %q; want the reason it is no root, and the refusal", err, out)
	}
}

func TestAnAppsVerbsAreTheBaseNamesOfItsHooksLikeBboxLists(t *testing.T) {
	root := checkout(t)
	got := appVerbs(filepath.Join(root, "apps", "indox"))
	want := []string{"accept", "doc-trace", "seed", "test"} // test + test.py are ONE verb; __pycache__ is nothing
	if strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("appVerbs = %v, want %v", got, want)
	}
	if appVerbs(filepath.Join(root, "apps", "no-hooks")) != nil {
		t.Fatal("an app without hooks has no verbs")
	}
}

func TestAHookIsResolvedInBboxsOrderAndRunByWhatItsExtensionWants(t *testing.T) {
	root := checkout(t)
	dir := filepath.Join(root, "apps", "indox")
	cases := []struct{ verb, file, runner string }{
		{"test", "test", "bash"}, // the bare file wins over test.py
		{"doc-trace", "doc-trace.py", "python3"},
		{"accept", "accept.mjs", "node"},
		{"seed", "seed.sh", "bash"},
	}
	for _, c := range cases {
		hook, runner, err := resolveHook(dir, c.verb)
		if err != nil || filepath.Base(hook) != c.file || runner[0] != c.runner {
			t.Errorf("resolveHook(%s) = %s %v %v; want %s by %s", c.verb, hook, runner, err, c.file, c.runner)
		}
	}
	if _, _, err := resolveHook(dir, "nope"); err == nil {
		t.Fatal("a verb with no file is an error, not a silent bash of nothing")
	}
}

func TestACompilerVerbIsDelegatedToReconcileWithItsArgumentsUntouched(t *testing.T) {
	root := checkout(t)
	inv, err := plan(root, []string{"rollback", "--for", "0003", "--app", "x"}, "linux")
	if err != nil {
		t.Fatal(err)
	}
	want := []string{filepath.Join(root, "platform", "manager", "reconcile.py"), "rollback", "--for", "0003", "--app", "x"}
	if got := inv.argv[len(inv.argv)-len(want):]; strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("argv tail = %v, want %v", got, want)
	}
	if !strings.Contains(inv.argv[0], "python") {
		t.Fatalf("the compiler is run by a python, got %q", inv.argv[0])
	}
}

func TestAnAppVerbRunsItsHookByIdOrByAliasAndPassesTheRest(t *testing.T) {
	root := checkout(t)
	for _, tok := range []string{"indox", "docs"} {
		inv, err := plan(root, []string{tok, "doc-trace", "--id", "7"}, "linux")
		if err != nil {
			t.Fatal(err)
		}
		if inv.argv[0] != "python3" || filepath.Base(inv.argv[1]) != "doc-trace.py" || inv.argv[2] != "--id" || inv.argv[3] != "7" {
			t.Fatalf("plan(%s doc-trace) = %v", tok, inv.argv)
		}
	}
	if _, err := plan(root, []string{"indox"}, "linux"); err == nil || !strings.Contains(err.Error(), "accept doc-trace seed test") {
		t.Fatalf("an app without a verb names its verbs; got %v", err)
	}
	if _, err := plan(root, []string{"indox", "nope"}, "linux"); err == nil || !strings.Contains(err.Error(), "no such hook") {
		t.Fatalf("an unknown verb says so; got %v", err)
	}
}

func TestAnythingElseIsHandedToBbox(t *testing.T) {
	root := checkout(t)
	inv, err := plan(root, []string{"run", "--fast"}, "linux")
	if err != nil {
		t.Fatal(err)
	}
	if inv.argv[0] != "bash" || filepath.Base(inv.argv[1]) != "bbox" || inv.argv[2] != "run" || inv.argv[3] != "--fast" {
		t.Fatalf("plan(run) = %v", inv.argv)
	}
}

func TestOnWindowsEverythingButTheCompilerGoesThroughTheWSLHandOff(t *testing.T) {
	root := checkout(t)
	for _, args := range [][]string{{"run"}, {"indox", "test"}, {"docs", "doc-trace", "--id", "7"}} {
		inv, err := plan(root, args, "windows")
		if err != nil {
			t.Fatal(err)
		}
		if inv.argv[0] != "cmd" || inv.argv[1] != "/c" || filepath.Base(inv.argv[2]) != "bbox.cmd" || strings.Join(inv.argv[3:], " ") != strings.Join(args, " ") {
			t.Fatalf("plan(windows, %v) = %v", args, inv.argv)
		}
	}
	// a compiler verb stays on the host: ported ones in-process, the rest through reconcile.py
	inv, err := plan(root, []string{"validate"}, "windows")
	if err != nil || inv.native == nil || inv.argv != nil {
		t.Fatalf("validate is a native verb; plan(windows, validate) = %+v, %v", inv, err)
	}
	inv, err = plan(root, []string{"plan"}, "windows")
	if err != nil {
		noPython(t, err)
	}
	if inv.native != nil || filepath.Base(inv.argv[len(inv.argv)-2]) != "reconcile.py" {
		t.Fatalf("an unported compiler verb is delegated to reconcile.py on Windows too, got %v", inv.argv)
	}
}

func TestNativeVerbsAndTheirRollback(t *testing.T) {
	root := checkout(t)
	for verb := range nativeVerbs {
		inv, err := plan(root, []string{verb}, "linux")
		if err != nil || inv.native == nil {
			t.Fatalf("%s must be answered natively: %+v, %v", verb, inv, err)
		}
		// its arguments reach it, and it reads them as reconcile.py's argparse does: an option it
		// does not know is refused with exit 2 before anything is read, not run anyway
		inv, err = plan(root, []string{verb, "--extra"}, "linux")
		if err != nil || inv.native == nil {
			t.Fatalf("%s with an argument must still be answered natively: %+v, %v", verb, inv, err)
		}
		var out, errb strings.Builder
		if code := inv.native(&out, &errb); code != 2 || !strings.HasSuffix(errb.String(), "reconcile.py: error: unrecognized arguments: --extra\n") {
			t.Fatalf("%s --extra: exit %d, stderr %q", verb, code, errb.String())
		}
	}
	// an option main() takes but ignores for the verb reaches it and is ignored, as it is there
	ignored, err := plan(root, []string{"office-get", "--app", "x"}, "linux")
	var out, errb strings.Builder
	if err != nil || ignored.native == nil || ignored.native(&out, &errb) != 0 || out.String() != "{}\n" {
		t.Fatalf("office-get --app x answers {}: %q %q %v", out.String(), errb.String(), err)
	}
	t.Setenv("DGO_COMPILER", "python")
	for verb := range nativeVerbs {
		inv, err := plan(root, []string{verb, "--app", "x"}, "linux")
		if err != nil {
			noPython(t, err)
		}
		if inv.native != nil || filepath.Base(inv.argv[len(inv.argv)-4]) != "reconcile.py" || inv.argv[len(inv.argv)-3] != verb {
			t.Fatalf("DGO_COMPILER=python must delegate %s to reconcile.py with its arguments, got %+v", verb, inv)
		}
	}
}

// noPython skips a test that needs a python to delegate to — or fails it where DGO_ORACLE_REQUIRED=1
// (CI) says a green run must have proved the delegation.
func noPython(t *testing.T, err error) {
	t.Helper()
	if os.Getenv("DGO_ORACLE_REQUIRED") == "1" {
		t.Fatal("no python on this host's PATH (DGO_ORACLE_REQUIRED=1): " + err.Error())
	}
	t.Skip("no python on this host's PATH: " + err.Error())
}

// TestBeChildRunsTheConsoleServerAndShadowsNoApp: the console's server is `dgo be-child console`,
// decided before the WSL hand-off on every OS; `dgo console <verb>` stays the console APP's, resolved
// exactly as before — to bbox while the app has no hooks (as today), to its hook once it has one.
func TestBeChildRunsTheConsoleServerAndShadowsNoApp(t *testing.T) {
	root := checkout(t)
	app := filepath.Join(root, "platform-base", "console")
	if err := os.MkdirAll(app, 0o755); err != nil {
		t.Fatal(err)
	}
	inv, err := plan(root, []string{"console", "test"}, "linux")
	if err != nil || inv.native != nil || inv.argv[0] != "bash" || filepath.Base(inv.argv[1]) != "bbox" || strings.Join(inv.argv[2:], " ") != "console test" {
		t.Fatalf("plan(console test) without hooks = %+v, %v; want bbox, as before", inv, err)
	}
	if err := os.MkdirAll(filepath.Join(app, "hooks"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(app, "hooks", "test"), []byte("x"), 0o755); err != nil {
		t.Fatal(err)
	}
	inv, err = plan(root, []string{"console", "test", "--fast"}, "linux")
	if err != nil || inv.native != nil || inv.argv[0] != "bash" || filepath.Base(inv.argv[1]) != "test" || inv.argv[2] != "--fast" {
		t.Fatalf("plan(console test --fast) = %+v, %v; want the console app's hook", inv, err)
	}
	inv, err = plan(root, []string{"console", "test"}, "windows")
	if err != nil || filepath.Base(inv.argv[2]) != "bbox.cmd" || strings.Join(inv.argv[3:], " ") != "console test" {
		t.Fatalf("plan(windows, console test) = %+v, %v; want the bbox.cmd hand-off, as before", inv, err)
	}
	// the console's server is resolved by child(), which main() calls before it looks for a checkout
	// or plans anything — so on no OS is it handed to bbox, and outside a checkout root is ""
	for _, r := range []string{root, ""} {
		inv, err := child(r, []string{"console", "--listen", "127.0.0.1:0"})
		if err != nil || inv.native == nil || inv.argv != nil {
			t.Fatalf("child(%q, console) = %+v, %v; want the native process", r, inv, err)
		}
		// its flags reach the console process: without --static it answers with its usage, exit 2
		var stderr bytes.Buffer
		if code := inv.native(io.Discard, &stderr); code != 2 || !strings.Contains(stderr.String(), "usage: dgo be-child console") {
			t.Fatalf("be-child console without --static = %d %q", code, stderr.String())
		}
	}
	for _, args := range [][]string{nil, {"nope"}} {
		if _, err := child(root, args); err == nil || !strings.Contains(err.Error(), "no such process") || !strings.Contains(err.Error(), "console") {
			t.Fatalf("child(%v) = %v; want the processes named", args, err)
		}
	}
	if h := help(root); !slices.Contains(processesIn(h), "console") {
		t.Fatalf("help lacks the console's process:\n%s", h)
	}
}

// processesIn is help's list of the office's own processes — `dgo be-child a | b`, one name per child.
func processesIn(help string) []string {
	for _, l := range strings.Split(help, "\n") {
		if names, ok := strings.CutPrefix(l, "the office's own processes: dgo be-child "); ok {
			return strings.Split(names, " | ")
		}
	}
	return nil
}

// TestBeChildStartsOutsideACheckout runs dgo itself — this test binary, as dgo's main() — from a
// directory with no checkout above it: the console's rollback (DGO_CONSOLE=container) must start
// there and reach its container, where every other verb refuses ("not inside a DGO checkout").
func TestBeChildStartsOutsideACheckout(t *testing.T) {
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(exe, "be-child", "console", "--listen", "127.0.0.1:0", "--upstream", "http://127.0.0.1:9")
	cmd.Dir = t.TempDir()
	cmd.Env = append(os.Environ(), "DGO_TEST_MAIN=1", "DGO_CONSOLE=container")
	stderr, err := cmd.StderrPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer cmd.Process.Kill()
	said := make(chan string, 1)
	go func() {
		line, _ := bufio.NewReader(stderr).ReadString('\n')
		said <- line
	}()
	select {
	case line := <-said:
		if !strings.Contains(line, "dgo console: http://127.0.0.1:") {
			t.Fatalf("dgo be-child console outside a checkout said %q", line)
		}
	case <-time.After(20 * time.Second):
		t.Fatal("dgo be-child console said nothing")
	}
}

// TestMain lets a test run dgo's own main() in a child process (DGO_TEST_MAIN=1): the order in which
// main() decides is part of what is tested.
func TestMain(m *testing.M) {
	if os.Getenv("DGO_TEST_MAIN") == "1" {
		main()
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func TestThePythonIsFoundTheWayEachOSHasIt(t *testing.T) {
	have := func(names ...string) func(string) (string, error) {
		return func(n string) (string, error) {
			for _, h := range names {
				if h == n {
					return "/bin/" + n, nil
				}
			}
			return "", errors.New("not found")
		}
	}
	if p, _ := pythonFor("linux", have("python3", "python")); p[0] != "/bin/python3" {
		t.Fatalf("python3 first, got %v", p)
	}
	if p, _ := pythonFor("linux", have("python")); p[0] != "/bin/python" {
		t.Fatalf("python next, got %v", p)
	}
	if p, _ := pythonFor("windows", have("py")); strings.Join(p, " ") != "/bin/py -3" {
		t.Fatalf("the Windows launcher last, got %v", p)
	}
	if _, err := pythonFor("linux", have("py")); err == nil {
		t.Fatal("the launcher is Windows' alone")
	}
	if _, err := pythonFor("linux", have()); err == nil {
		t.Fatal("no python is an error that says so")
	}
}

func TestHelpIsGeneratedFromTheTree(t *testing.T) {
	root := checkout(t)
	h := help(root)
	for _, want := range []string{"dgo plan | render", "docs (indox)", "accept doc-trace seed test", "dgo n8n", "push", "dgo run"} {
		if !strings.Contains(h, want) {
			t.Errorf("help lacks %q:\n%s", want, h)
		}
	}
	if strings.Contains(h, "no-hooks") {
		t.Error("an app without hooks is not listed")
	}
	if !slices.Contains(processesIn(h), "control") {
		t.Errorf("help lacks the office's own processes:\n%s", h)
	}
}

// The office's own processes run natively on every OS — `be-child` is decided before the WSL hand-off —
// and an app's verbs dispatch exactly as they did before the word existed: by id and by alias, to the
// hook on Linux and macOS, through bbox.cmd on Windows.
func TestBeChildIsNativeEverywhereAndAppVerbsDispatchAsBefore(t *testing.T) {
	root := checkout(t)
	for _, goos := range []string{"linux", "darwin", "windows"} {
		inv, err := plan(root, []string{"be-child", "control", "--listen", ":0"}, goos)
		if err != nil || inv.native == nil || inv.argv != nil {
			t.Fatalf("%s: be-child control must be native: %+v, %v", goos, inv, err)
		}
		for _, tok := range []string{"indox", "docs"} {
			inv, err := plan(root, []string{tok, "doc-trace", "--id", "7"}, goos)
			if err != nil {
				t.Fatal(err)
			}
			want := []string{"python3", filepath.Join(root, "apps", "indox", "hooks", "doc-trace.py"), "--id", "7"}
			if goos == "windows" {
				want = []string{"cmd", "/c", filepath.Join(root, "bbox.cmd"), tok, "doc-trace", "--id", "7"}
			}
			if strings.Join(inv.argv, "|") != strings.Join(want, "|") || inv.native != nil {
				t.Errorf("%s: %s doc-trace = %v, want %v", goos, tok, inv.argv, want)
			}
		}
	}
	for _, args := range [][]string{{"be-child"}, {"be-child", "nope"}} {
		if _, err := plan(root, args, "linux"); err == nil || !strings.Contains(err.Error(), "control") {
			t.Errorf("%v must be refused, naming the processes there are; got %v", args, err)
		}
	}
}

// `be-child` is decided before any app, so it must be nobody's name: no app's id or cli.alias in this
// checkout, and no verb of bbox's — the tree is read, so the day one is added, this fails.
func TestBeChildShadowsNoAppAndNoBboxVerb(t *testing.T) {
	root, err := findRoot(mustCwd())
	if err != nil {
		t.Skip("not inside a checkout")
	}
	for _, r := range roots {
		entries, _ := os.ReadDir(filepath.Join(root, r))
		for _, e := range entries {
			if e.IsDir() && (e.Name() == "be-child" || cliAlias(filepath.Join(root, r, e.Name())) == "be-child") {
				t.Errorf("%s/%s is be-child by id or alias: `dgo be-child` would shadow it", r, e.Name())
			}
		}
	}
	bbox, err := os.ReadFile(filepath.Join(root, "bbox"))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(bbox), "be-child)") || strings.Contains(string(bbox), "be-child|") {
		t.Error("bbox has a verb be-child: `dgo be-child` would shadow it")
	}
}

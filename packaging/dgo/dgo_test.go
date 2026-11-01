package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
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
	inv, err := plan(root, []string{"set-state", "--app", "drive", "--state", "enabled", "--create"}, "linux")
	if err != nil {
		t.Fatal(err)
	}
	want := []string{filepath.Join(root, "platform", "manager", "reconcile.py"), "set-state", "--app", "drive", "--state", "enabled", "--create"}
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
	inv, err = plan(root, []string{"render"}, "windows")
	if err != nil {
		t.Skip("no python on this host's PATH: " + err.Error())
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
		// an extra argument is not something the native verbs take yet — it goes to Python unchanged
		inv, err = plan(root, []string{verb, "--extra"}, "linux")
		if err == nil && inv.native != nil {
			t.Fatalf("%s with an argument must be delegated, not answered natively", verb)
		}
	}
	t.Setenv("DGO_COMPILER", "python")
	inv, err := plan(root, []string{"enabled-apps"}, "linux")
	if err != nil {
		t.Skip("no python on this host's PATH: " + err.Error())
	}
	if inv.native != nil || filepath.Base(inv.argv[len(inv.argv)-2]) != "reconcile.py" {
		t.Fatalf("DGO_COMPILER=python must delegate a native verb to reconcile.py, got %+v", inv)
	}
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
}

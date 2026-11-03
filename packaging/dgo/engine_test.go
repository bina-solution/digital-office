package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestOnAPhoneWithNoCheckoutDgoSaysWhereTheOfficeRuns: dgo for android/arm64 is first met in an app,
// with no checkout around it — so there it says where the phone's office runs (DGO-1069); everywhere
// else the same refusal as always, word for word.
func TestOnAPhoneWithNoCheckoutDgoSaysWhereTheOfficeRuns(t *testing.T) {
	err := errors.New("not inside a DGO checkout")
	if got := noCheckout("linux", err); got != err.Error() {
		t.Errorf("linux: %q", got)
	}
	got := noCheckout("android", err)
	for _, want := range []string{err.Error(), "Linux development environment", "clone the office's repository",
		"./bbox install debian", "linux/arm64"} {
		if !strings.Contains(got, want) {
			t.Errorf("android: %q lacks %q", got, want)
		}
	}
}

// The engine slice owns exactly `dgo engine doctor` and `dgo engine plan`, on every OS. Every other
// `engine` verb — start, stop, status, shell, forwards (engine.sh's, on a Mac) — is handed to bbox
// exactly as before: through bbox.cmd on Windows, bash bbox elsewhere. DGO_ENGINE=bbox hands the two
// back too, so the old path stays one switch away.
func TestOnlyEngineDoctorAndPlanAreNativeEverythingElseStaysBboxs(t *testing.T) {
	root := checkout(t)
	toBbox := func(goos string, args []string) {
		t.Helper()
		inv, err := plan(root, args, goos)
		if err != nil || inv.native != nil {
			t.Fatalf("%s %v must go to bbox: %+v, %v", goos, args, inv, err)
		}
		rest := strings.Join(args, " ")
		if goos == "windows" {
			if inv.argv[0] != "cmd" || filepath.Base(inv.argv[2]) != "bbox.cmd" || strings.Join(inv.argv[3:], " ") != rest {
				t.Fatalf("windows %v: %v", args, inv.argv)
			}
		} else if inv.argv[0] != "bash" || filepath.Base(inv.argv[1]) != "bbox" || strings.Join(inv.argv[2:], " ") != rest {
			t.Fatalf("%s %v: %v", goos, args, inv.argv)
		}
	}
	for _, goos := range []string{"linux", "darwin", "windows"} {
		for _, sub := range []string{"doctor", "plan"} {
			if inv, err := plan(root, []string{"engine", sub}, goos); err != nil || inv.native == nil || inv.argv != nil {
				t.Fatalf("%s: engine %s is native: %+v, %v", goos, sub, inv, err)
			}
		}
		for _, args := range [][]string{{"engine"}, {"engine", "start"}, {"engine", "stop"}, {"engine", "status"},
			{"engine", "shell"}, {"engine", "socket"}, {"engine", "forwards", "--apply"}, {"engine", "doctor", "--json"}} {
			toBbox(goos, args)
		}
	}
	t.Setenv("DGO_ENGINE", "bbox")
	for _, goos := range []string{"linux", "darwin", "windows"} {
		toBbox(goos, []string{"engine", "doctor"})
	}
}

// `engine` is a verb of the core, so no app may take the name — `dgo engine doctor` would shadow an
// app's own hook of that name. Asked of the real tree, the way bbox resolves a token: id or cli.alias.
func TestNoAppIsCalledEngine(t *testing.T) {
	cwd, _ := os.Getwd()
	root, err := findRoot(cwd)
	if err != nil {
		t.Skip("not inside the checkout")
	}
	for _, r := range roots {
		if isDir(filepath.Join(root, r, "engine")) {
			t.Errorf("%s/engine exists: `dgo engine` is the core's verb", r)
		}
		entries, _ := os.ReadDir(filepath.Join(root, r))
		for _, e := range entries {
			if cliAlias(filepath.Join(root, r, e.Name())) == "engine" {
				t.Errorf("%s/%s declares cli.alias \"engine\": `dgo engine` is the core's verb", r, e.Name())
			}
		}
	}
}

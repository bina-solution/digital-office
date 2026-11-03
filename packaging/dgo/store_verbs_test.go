package main

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/store"
)

// The store's word is answered in-process on every OS — before the WSL hand-off, which would
// otherwise carry it to bbox.cmd — and adding it moved nothing else: an app's verb runs its hook,
// and `dgo install …` still reaches `bbox install debian|windows|macos`.
func TestTheStoreIsNativeAndEveryOtherVerbDispatchesAsBefore(t *testing.T) {
	root := checkout(t)
	for _, goos := range []string{"linux", "darwin", "windows"} {
		inv, err := plan(root, []string{"index", "verify", "out"}, goos)
		if err != nil || inv.native == nil || inv.argv != nil {
			t.Fatalf("%s: dgo index must be native, got %+v %v", goos, inv, err)
		}
		inv, _ = plan(root, []string{"index"}, goos)
		var out, errb bytes.Buffer
		if code := inv.native(&out, &errb); code != 2 || !strings.Contains(errb.String(), "dgo index install --dry-run") {
			t.Fatalf("%s: a bare dgo index prints the store's usage, got exit %d %q", goos, code, errb.String())
		}
	}
	inv, err := plan(root, []string{"install", "debian"}, "linux")
	if err != nil || inv.argv[0] != "bash" || filepath.Base(inv.argv[1]) != "bbox" || strings.Join(inv.argv[2:], " ") != "install debian" {
		t.Fatalf("dgo install debian must stay bbox's: %v %v", inv.argv, err)
	}
	inv, err = plan(root, []string{"install", "windows"}, "windows")
	if err != nil || filepath.Base(inv.argv[2]) != "bbox.cmd" {
		t.Fatalf("on Windows dgo install still goes through bbox.cmd: %v %v", inv.argv, err)
	}
	inv, err = plan(root, []string{"docs", "doc-trace", "--id", "7"}, "linux")
	if err != nil || inv.argv[0] != "python3" || filepath.Base(inv.argv[1]) != "doc-trace.py" {
		t.Fatalf("an app's verb must still run its hook: %v %v", inv.argv, err)
	}
}

// No word the store takes is already somebody's in the real checkout: not an app id, not a
// cli.alias, not a verb bbox answers at any depth of its dispatch.
func TestTheStoresWordsAreNobodyElses(t *testing.T) {
	wd, _ := os.Getwd()
	root, err := findRoot(wd)
	if err != nil {
		t.Skip("not inside the checkout")
	}
	raw, err := os.ReadFile(filepath.Join(root, "bbox"))
	if err != nil {
		t.Fatal(err)
	}
	for verb := range store.Verbs {
		if aid, dir := appOf(root, verb); aid != "" {
			t.Errorf("dgo %s would shadow the app %s (%s)", verb, aid, dir)
		}
		label := regexp.MustCompile(`(?m)^\s*(?:[a-z0-9-]+\|)*` + regexp.QuoteMeta(verb) + `(?:\|[a-z0-9-]+)*\)`)
		if loc := label.FindIndex(raw); loc != nil {
			t.Errorf("dgo %s would shadow bbox's own verb: %q", verb, strings.TrimSpace(string(raw[loc[0]:loc[1]])))
		}
	}
	if regexp.MustCompile(`(?m)^\s*install\)`).Find(raw) == nil {
		t.Error("the check above no longer finds bbox's `install)` — its pattern has gone stale")
	}
}

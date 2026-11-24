package main

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// «ניהול גרסאות»'s word is answered in-process on every OS, before the WSL hand-off (DGO-2138, M0).
func TestVersionsIsNativeOnEveryOS(t *testing.T) {
	root := checkout(t)
	for _, goos := range []string{"linux", "darwin", "windows"} {
		inv, err := plan(root, []string{"versions", "status"}, goos)
		if err != nil || inv.native == nil || inv.argv != nil {
			t.Fatalf("%s: dgo versions must be native, got %+v %v", goos, inv, err)
		}
	}
	if !strings.Contains(help(root), "dgo versions status") {
		t.Error("dgo's help names the versions verb")
	}
}

// The word is nobody else's in the real checkout: not an app id, not a cli.alias, not a verb bbox answers.
func TestVersionsIsNobodyElsesWord(t *testing.T) {
	wd, _ := os.Getwd()
	root, err := findRoot(wd)
	if err != nil {
		t.Skip("not inside the checkout")
	}
	raw, err := os.ReadFile(filepath.Join(root, "bbox"))
	if err != nil {
		t.Fatal(err)
	}
	if aid, dir := appOf(root, "versions"); aid != "" {
		t.Errorf("dgo versions would shadow the app %s (%s)", aid, dir)
	}
	if loc := regexp.MustCompile(`(?m)^\s*(?:[a-z0-9-]+\|)*versions(?:\|[a-z0-9-]+)*\)`).FindIndex(raw); loc != nil {
		t.Errorf("dgo versions would shadow bbox's own verb: %q", strings.TrimSpace(string(raw[loc[0]:loc[1]])))
	}
}

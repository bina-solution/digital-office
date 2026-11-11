//go:build !windows

package compiler

import (
	"errors"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// handBackTree is test_hand_back.py's tree: a .generated/ with nested entries and two links out of it, the files
// handBackFiles names, and two committed neighbours that are never the compiler's.
func handBackTree(t *testing.T) (repo, gen, outside string) {
	t.Helper()
	repo, outside = t.TempDir(), t.TempDir()
	gen = filepath.Join(repo, ".generated")
	must := func(err error) {
		if err != nil {
			t.Fatal(err)
		}
	}
	for _, d := range []string{"registry", "n8n/indox"} {
		must(os.MkdirAll(filepath.Join(gen, d), 0o755))
	}
	for _, f := range []string{"compose.yml", "registry/remote.hp-laptop.drive.json", "n8n/indox/a.json"} {
		must(os.WriteFile(filepath.Join(gen, f), []byte("x"), 0o644))
	}
	for _, f := range append(append([]string{}, handBackFiles...),
		filepath.Join(authentikDir, "blueprints", "deployment-apps.yaml"),
		filepath.Join("platform-base", "traefik", "config", "authentik-forwardauth.yaml")) {
		must(os.MkdirAll(filepath.Dir(filepath.Join(repo, f)), 0o755))
		must(os.WriteFile(filepath.Join(repo, f), []byte("x"), 0o644))
	}
	must(os.WriteFile(filepath.Join(outside, "secret"), []byte("x"), 0o600))
	must(os.Symlink(filepath.Join(outside, "secret"), filepath.Join(gen, "registry", "link-out")))
	must(os.Symlink(outside, filepath.Join(gen, "linked-dir")))
	return repo, gen, outside
}

// runHandBack runs handBack with owners from a table (a test is not root) and records every lchown.
func runHandBack(t *testing.T, repo string, euid, repoUID int, root, refuse []string) (int, []string) {
	t.Helper()
	roots, refused := map[string]bool{}, map[string]bool{}
	for _, p := range root {
		roots[p] = true
	}
	for _, p := range refuse {
		refused[p] = true
	}
	var called []string
	owner := func(p string, link bool) (int, int, bool) {
		if _, err := os.Lstat(p); err != nil {
			return 0, 0, false
		}
		if p == repo {
			return repoUID, repoUID, true
		}
		if !link {
			t.Errorf("owner asked to follow %s", p)
		}
		if roots[p] {
			return 0, 0, true
		}
		return 1000, 1000, true
	}
	lchown := func(p string, uid, gid int) error {
		if refused[p] {
			return errors.New("refused")
		}
		if uid != 1000 || gid != 1000 {
			t.Errorf("%s handed to %d:%d", p, uid, gid)
		}
		called = append(called, p)
		return nil
	}
	n := handBack(repo, euid, owner, lchown)
	sort.Strings(called)
	return n, called
}

func sameSet(t *testing.T, what string, got, want []string) {
	t.Helper()
	want = append([]string{}, want...)
	sort.Strings(want)
	if len(got) != len(want) {
		t.Errorf("%s: handed back %v, want %v", what, got, want)
		return
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("%s: handed back %v, want %v", what, got, want)
			return
		}
	}
}

// TestHandBack is test_hand_back.py for the twin (DGO-121).
func TestHandBack(t *testing.T) {
	repo, gen, outside := handBackTree(t)
	j := func(p ...string) string { return filepath.Join(append([]string{gen}, p...)...) }

	if n, c := runHandBack(t, repo, 1000, 1000, []string{j("compose.yml")}, nil); n != 0 || len(c) != 0 {
		t.Errorf("not root: handed back %d %v", n, c)
	}
	if n, c := runHandBack(t, repo, 0, 0, []string{j("compose.yml")}, nil); n != 0 || len(c) != 0 {
		t.Errorf("a checkout root owns: handed back %d %v", n, c)
	}
	want := []string{j("registry"), j("registry", "remote.hp-laptop.drive.json"), j("n8n"), j("n8n", "indox"), j("n8n", "indox", "a.json")}
	for _, f := range handBackFiles {
		want = append(want, filepath.Join(repo, f))
	}
	n, c := runHandBack(t, repo, 0, 1000, want, nil)
	if n != len(want) {
		t.Errorf("root-owned entries: %d handed back, want %d", n, len(want))
	}
	sameSet(t, "root-owned entries", c, want)

	committed := []string{filepath.Join(repo, authentikDir, "blueprints", "deployment-apps.yaml"),
		filepath.Join(repo, "platform-base", "traefik", "config", "authentik-forwardauth.yaml")}
	if n, c := runHandBack(t, repo, 0, 1000, committed, nil); n != 0 || len(c) != 0 {
		t.Errorf("committed files were handed back: %d %v", n, c)
	}
	// the links, what they point at, and the path THROUGH the linked directory are root's: a walk that followed
	// linked-dir would reach gen/linked-dir/secret and chown the file outside through it
	_, c = runHandBack(t, repo, 0, 1000, []string{j("registry", "link-out"), j("linked-dir"),
		filepath.Join(outside, "secret"), outside, j("linked-dir", "secret")}, nil)
	sameSet(t, "links", c, []string{j("linked-dir"), j("registry", "link-out")})

	if n, c := runHandBack(t, repo, 0, 1000, []string{j("compose.yml"), j("n8n")}, []string{j("compose.yml")}); n != 1 {
		t.Errorf("a refused entry: handed back %d %v, want only n8n", n, c)
	}
}

// TestHandBackLeavesALinkedGeneratedAlone: a .generated/ that is a link is not walked.
func TestHandBackLeavesALinkedGeneratedAlone(t *testing.T) {
	repo, real := t.TempDir(), t.TempDir()
	if err := os.WriteFile(filepath.Join(real, "f"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(real, filepath.Join(repo, ".generated")); err != nil {
		t.Fatal(err)
	}
	n, c := runHandBack(t, repo, 0, 1000, []string{filepath.Join(real, "f"), filepath.Join(repo, ".generated", "f")}, nil)
	if n != 0 || len(c) != 0 {
		t.Errorf("walked a linked .generated/: %d %v", n, c)
	}
}

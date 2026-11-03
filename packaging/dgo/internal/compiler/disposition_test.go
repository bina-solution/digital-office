package compiler

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// TestDispositionIsPythons asks reconcile.py's own disposition() the states that read apart between Go's
// strings package and Python's str — whitespace Go does not strip, letters the two lower differently —
// and every code point as the whitespace around a state: str.strip() must trim exactly what it trims.
func TestDispositionIsPythons(t *testing.T) {
	py := python(t)
	if py == nil {
		t.Skip("no python with PyYAML on PATH")
	}
	states := []string{
		"enabled", " Enabled ", "ENABLED", "Disabled", "archived", "ARCHIVED" + string(rune(0x1f)),
		string(rune(0x1c)) + "enabled", "ARCH" + string(rune(0x130)) + "VED", "di" + string(rune(0x17f)) + "abled",
		"enabled" + string(rune(0x200b)), string(rune(0x3000)) + "enabled" + string(rune(0x85)), "bogus", "",
	}
	type entry struct {
		State   string `json:"state"`
		Enabled bool   `json:"enabled"`
	}
	var entries []entry
	for _, s := range states {
		entries = append(entries, entry{s, true}, entry{s, false}) // the legacy key decides when state names none
	}
	const prog = `import sys, json
sys.path.insert(0, sys.argv[1])
from reconcile import disposition
print(json.dumps([disposition(e) for e in json.load(sys.stdin)]))
print(json.dumps([c for c in range(0x110000) if chr(c).isspace()]))`
	in, _ := json.Marshal(entries)
	cmd := exec.Command(py[0], append(py[1:], "-c", prog, filepath.Join(repoRoot(t), "platform", "manager"))...)
	cmd.Stdin = strings.NewReader(string(in))
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("reconcile.disposition: %v", err)
	}
	lines := strings.SplitN(strings.TrimSpace(string(out)), "\n", 2)
	var want []string
	var space []int
	if len(lines) != 2 || json.Unmarshal([]byte(lines[0]), &want) != nil || json.Unmarshal([]byte(lines[1]), &space) != nil {
		t.Fatalf("Python answered %q", out)
	}
	for i, e := range entries {
		m := yamlish.NewMap()
		m.Set("state", e.State)
		m.Set("enabled", e.Enabled)
		if got, err := Disposition(m); err != nil || got != want[i] {
			t.Errorf("state %q, enabled %v: %s (%v), Python says %s", e.State, e.Enabled, got, err, want[i])
		}
	}
	isSpace := map[rune]bool{}
	for _, c := range space {
		isSpace[rune(c)] = true
	}
	for c := rune(0); c <= 0x10ffff; c++ {
		if c >= 0xd800 && c <= 0xdfff {
			continue // no Go string holds one
		}
		if _, ok := namesDisposition(string(c) + "enabled"); ok != isSpace[c] {
			t.Errorf("U+%04X: stripped %v, Python's str.strip() %v", c, ok, isSpace[c])
		}
	}
	t.Logf("%d states as reconcile.disposition() reads them; str.strip()'s %d whitespace characters, exactly", len(entries), len(space))
}

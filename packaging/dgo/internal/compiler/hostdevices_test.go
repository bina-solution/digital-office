package compiler

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// The host's record of its devices (requires_host, DGO-1797) on both sides of in_container — which the render
// oracle cannot reach, since it runs inside a container where both compilers skip the record. The same cases as
// platform/manager/test_requires_host.py.
func TestTheHostsDeviceRecord(t *testing.T) {
	const missing = "/dev/dgo-no-such-device"
	repo := t.TempDir()
	gen := filepath.Join(repo, genDir)
	if err := os.MkdirAll(filepath.Join(repo, "apps", "zz-kvm"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(gen, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(repo, "apps", "zz-kvm", "app.json"),
		[]byte(manifestJSON("zz-kvm", `"requires_host":{"devices":["`+missing+`"]}`)), 0o644); err != nil {
		t.Fatal(err)
	}
	real := inContainer
	defer func() { inContainer = real }()
	record := func(text string) {
		if err := os.WriteFile(filepath.Join(gen, hostDevices), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	ask := func() []string {
		got, err := missingHostDevices(repo, "zz-kvm")
		if err != nil {
			t.Fatal(err)
		}
		return got
	}

	inContainer = func() bool { return true }
	if got := ask(); len(got) != 0 {
		t.Errorf("in a container with no record: %v, want no refusal", got)
	}
	record(`{"` + missing + `": true}`)
	if got := ask(); len(got) != 0 {
		t.Errorf("in a container, the host has it: %v, want none", got)
	}
	record(`{"` + missing + `": false}`)
	if got := ask(); len(got) != 1 || got[0] != missing {
		t.Errorf("in a container, the host said absent: %v, want [%s]", got, missing)
	}
	inContainer = func() bool { return false }
	record(`{"` + missing + `": true}`)
	if got := ask(); len(got) != 1 || got[0] != missing {
		t.Errorf("on the host a stale record must not mask /dev: %v, want [%s]", got, missing)
	}

	// the record: written on the host only, every declared device, sorted, as json.dumps(indent=2) writes it
	doc := yamlish.NewMap()
	doc.Set("requires_host", ordered("devices", []any{missing, "/dev/null", int64(5), ""}))
	cat := &Catalog{Order: []string{"zz-kvm", "x"}, Apps: map[string]*App{
		"zz-kvm": {ID: "zz-kvm", doc: doc}, "x": {ID: "x", doc: yamlish.NewMap()}}}
	if err := renderHostDevices(gen, cat); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(filepath.Join(gen, hostDevices))
	if want := "{\n  \"/dev/dgo-no-such-device\": false,\n  \"/dev/null\": true\n}\n"; string(got) != want {
		t.Errorf("the record:\n%q\nwant\n%q", got, want)
	}
	os.Remove(filepath.Join(gen, hostDevices))
	inContainer = func() bool { return true }
	if err := renderHostDevices(gen, cat); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(gen, hostDevices)); err == nil {
		t.Error("written inside a container: its /dev is not the host's")
	}
	inContainer = func() bool { return false }
	if err := renderHostDevices(gen, &Catalog{Apps: map[string]*App{}}); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(filepath.Join(gen, hostDevices)); string(got) != "{}\n" {
		t.Errorf("no declared device: %q, want {}\\n", got)
	}
}

package native

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestTheStatusSaysWhatRuns: the one file the phone's status screen reads (DGO-1723) — the core's own parts
// (forward-auth asked on its socket), «מכולות» as the app's run files and the machine's file say it in each of
// its states, and every app the state has on that runs in containers (the core's own, «מכולות» itself and an
// app that runs nothing are not listed).
func TestTheStatusSaysWhatRuns(t *testing.T) {
	root := t.TempDir()
	// a short directory: a unix socket's path has room for 103 bytes on macOS (as the sibling tests make theirs)
	dir, err := os.MkdirTemp("", "nat")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	state := "schema_version: 1\napps:\n  console: { enabled: true }\n  containers: { enabled: true }\n" +
		"  dgo-extend: { enabled: true }\n  notes: { state: enabled, by: wizard }\n  gone: { enabled: false }\n"
	files(t, root, map[string]string{
		"platform-base/console/app.json":    `{"id": "console", "layer": 2, "compose": "docker-compose.yml"}`,
		"platform-base/containers/app.json": `{"id": "containers", "layer": 1}`,
		"apps/dgo-extend/app.json":          `{"id": "dgo-extend", "layer": 3, "compose": "docker-compose.yml"}`,
		"apps/notes/app.json":               `{"id": "notes", "layer": 3}`,
		"platform.state.yaml":               state,
	})
	m := coreMachine{gate: newMachineGate(filepath.Join(dir, MachineFile), "signin.localhost", nil),
		wanted: filepath.Join(dir, MachineWanted), refused: filepath.Join(dir, MachineRefused)}
	now := time.Unix(1793560000, 0)
	cache := &appsCache{}

	s := readStatus(root, dir, m, now, cache)
	if s.At != 1793560000 || s.Containers.State != "off" {
		t.Fatalf("at %d, containers %+v", s.At, s.Containers)
	}
	if len(s.Base) != 4 || s.Base[3] != (Part{"forward-auth", false}) {
		t.Fatalf("base %+v: forward-auth is not up with no socket", s.Base)
	}
	if len(s.Apps) != 1 || s.Apps[0] != (App{"dgo-extend", "containers"}) {
		t.Fatalf("apps %+v, want dgo-extend in containers alone", s.Apps)
	}
	if cache.stamp == "" || len(cache.apps) != 1 {
		t.Fatalf("the apps were not kept for the same state: %+v", cache)
	}
	// none on, never null: the screen reads a list
	files(t, root, map[string]string{"platform.state.yaml": "schema_version: 1\napps:\n  console: { enabled: true }\n"})
	if s := readStatus(root, dir, m, now, nil); s.Apps == nil || len(s.Apps) != 0 {
		t.Fatalf("apps %#v, want an empty list", s.Apps)
	}
	files(t, root, map[string]string{"platform.state.yaml": state})

	// forward-auth answering on its socket
	ln, err := net.Listen("unix", filepath.Join(dir, ForwardAuthSocket))
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	if s := readStatus(root, dir, m, now, nil); !s.Base[3].Up {
		t.Fatal("forward-auth listens and is said down")
	}

	// the machine: asked, started (its QEMU holds a port, not proved yet), on its way, refused — each as the app says
	for _, c := range []struct {
		file, body string
		want       Containers
	}{
		{MachineWanted, "1\n", Containers{State: "wanted"}},
		{MachineFile, "40123 " + strings.Repeat("k", 32) + "\n", Containers{State: "step", Step: "the office's machine is starting"}},
		{MachineStep, "the office's machine is being unpacked: 40%\n", Containers{State: "step", Step: "the office's machine is being unpacked: 40%"}},
		{MachineRefused, "the phone has 3 GB free, and the machine needs 10 GB\n", Containers{State: "refused", Refused: "the phone has 3 GB free, and the machine needs 10 GB"}},
	} {
		if err := os.WriteFile(filepath.Join(dir, c.file), []byte(c.body), 0o600); err != nil {
			t.Fatal(err)
		}
		if got := readStatus(root, dir, m, now, nil).Containers; got != c.want {
			t.Errorf("%s: containers %+v, want %+v", c.file, got, c.want)
		}
	}

	// written whole, and read back as the app reads it
	path := filepath.Join(dir, StatusFile)
	if err := writeStatus(path, readStatus(root, dir, m, now, nil)); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var back Status
	if err := json.Unmarshal(b, &back); err != nil || back.Containers.State != "refused" || len(back.Apps) != 1 {
		t.Fatalf("read back %s: %+v (%v)", b, back, err)
	}
	if _, err := os.Stat(path + ".part"); !os.IsNotExist(err) {
		t.Fatal("the .part was left beside it")
	}
	if st, _ := os.Stat(path); st.Mode().Perm() != 0o600 {
		t.Fatalf("the status file is %v, not the app's alone", st.Mode().Perm())
	}

	// said until stopped, and gone with the core: a stopped core is never said to be up
	stop, done := make(chan struct{}), make(chan struct{})
	os.Remove(path)
	go sayStatus(root, dir, m, t.Logf, stop, done)
	for i := 0; i < 50 && !isFile(path); i++ {
		time.Sleep(20 * time.Millisecond)
	}
	if !isFile(path) {
		t.Fatal("sayStatus wrote nothing")
	}
	c := &Core{stop: stop, done: done, status: path}
	if err := c.Close(context.Background()); err != nil {
		t.Fatal(err)
	}
	if isFile(path) {
		t.Fatal("the status file outlived the core")
	}
}

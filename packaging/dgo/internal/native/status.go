package native

import (
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/compiler"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// StatusFile is the one place this phone's app reads what its office is doing (DGO-1723, the owner: «שקוף בדיוק
// מה קורה מה רץ»): the core writes it every StatusEvery, whole (a .part renamed over it), and removes it when it
// stops; the status screen shows it — it never reads a log or a run file to guess — and takes one older than a
// few StatusEvery as a core that is not running. States are said in English words; the screen says them in Hebrew.
const StatusFile = "status.json"

// StatusEvery is how often the core says it.
const StatusEvery = 2 * time.Second

// Status is the office as the status screen shows it.
type Status struct {
	At         int64      `json:"at"`         // when it was said, unix seconds
	Base       []Part     `json:"base"`       // what runs in the core itself, natively
	Containers Containers `json:"containers"` // «מכולות»: the office's machine, where every container app runs
	Apps       []App      `json:"apps"`       // every app the office has on that runs beyond the core (never null)
}

// Part is one of the core's own: the edge the WebView opens (traefik's job on every other office), the console,
// the control plane (app-management's), forward-auth.
type Part struct {
	ID string `json:"id"`
	Up bool   `json:"up"`
}

// Containers is the machine as the app reports it: "off"; "wanted" (asked, nothing heard yet); "step" (on its way —
// fetched, unpacked, starting: Step says how far); "up" (its edge proved its token); or "refused" (Refused says why,
// as the app wrote it).
type Containers struct {
	State   string `json:"state"`
	Step    string `json:"step,omitempty"`
	Refused string `json:"refused,omitempty"`
}

// App is an app the office has on and that runs: Where is "containers" (the machine runs it) — or "base", for an
// app the core answers natively beyond its own parts (none yet: each is a Part above).
type App struct {
	ID    string `json:"id"`
	Where string `json:"where"`
}

// readStatus is the office now: the core's parts (forward-auth asked on its socket — the rest are this process's
// own servers), the machine as the app's run files and the gate say, and the apps from c (nil: read anew).
func readStatus(root, dir string, m coreMachine, now time.Time, c *appsCache) Status {
	s := Status{At: now.Unix()}
	fa := false
	if conn, err := net.DialTimeout("unix", filepath.Join(dir, ForwardAuthSocket), 500*time.Millisecond); err == nil {
		conn.Close()
		fa = true
	}
	s.Base = []Part{{"edge", true}, {"console", true}, {"control", true}, {"forward-auth", fa}}
	refused, step := m.Refused(), m.Step() // each read once: the app removes them as it goes
	booting := m.gate != nil && machineStarted(m.gate.file)
	switch port, _ := m.Up(); {
	case port > 0:
		s.Containers.State = "up"
	case refused != "":
		s.Containers = Containers{State: "refused", Refused: refused}
	case step != "":
		s.Containers = Containers{State: "step", Step: step}
	case booting: // its QEMU holds the port, its edge has not proved itself yet: the boot
		s.Containers = Containers{State: "step", Step: "the office's machine is starting"}
	case isFile(m.wanted):
		s.Containers.State = "wanted"
	default:
		s.Containers.State = "off"
	}
	s.Apps = c.get(root)
	return s
}

// machineStarted: the app has started the machine — its file names a port — whether or not it proved itself yet.
func machineStarted(file string) bool {
	port, _ := machine(file)
	return port > 0
}

// appsCache keeps the apps part of the status for as long as the state file is the same (its size and time):
// the catalog only changes with an APK, which restarts the core.
type appsCache struct {
	stamp string
	apps  []App
}

// get is the apps that run beyond the core's own parts: every app the state has on that runs in containers
// («מכולות» itself, the core's own apps and the ones that run nothing — a library, a blueprint — are not listed).
func (c *appsCache) get(root string) []App {
	stamp := ""
	if st, err := os.Stat(filepath.Join(root, "platform.state.yaml")); err == nil {
		stamp = strconv.FormatInt(st.Size(), 10) + " " + st.ModTime().String()
	}
	if c != nil && stamp != "" && stamp == c.stamp {
		return c.apps
	}
	apps := []App{}
	inMachine := map[string]bool{}
	for _, aid := range machineApps(root) {
		inMachine[aid] = true
	}
	for _, aid := range enabledApps(root) {
		if inMachine[aid] && aid != "containers" {
			apps = append(apps, App{aid, "containers"})
		}
	}
	if c != nil {
		c.stamp, c.apps = stamp, apps
	}
	return apps
}

// enabledApps are the apps the office's state has on, in its order; none where the state cannot be read.
func enabledApps(root string) []string {
	doc, err := compiler.ReadState(root)
	top, isMap := doc.(*yamlish.Map)
	if err != nil || !isMap {
		return nil
	}
	raw, _ := top.Get("apps")
	apps, isMap := raw.(*yamlish.Map)
	if !isMap {
		return nil
	}
	var on []string
	for _, aid := range apps.Keys() {
		e, _ := apps.Get(aid)
		if d, err := compiler.Disposition(e); err == nil && d == "enabled" {
			on = append(on, aid)
		}
	}
	return on
}

func isFile(path string) bool {
	st, err := os.Stat(path)
	return err == nil && st.Mode().IsRegular()
}

// writeStatus puts s at path whole: a .part, then renamed — the app never reads half of one.
func writeStatus(path string, s Status) error {
	b, err := json.Marshal(s)
	if err != nil {
		return err
	}
	part := path + ".part"
	if err := os.WriteFile(part, b, 0o600); err != nil {
		return err
	}
	return os.Rename(part, path)
}

// sayStatus writes the status every StatusEvery until stop closes, then closes done; a write that fails is logged
// once, until one succeeds again.
func sayStatus(root, dir string, m coreMachine, logf func(string, ...any), stop <-chan struct{}, done chan<- struct{}) {
	defer close(done)
	path := filepath.Join(dir, StatusFile)
	cache := &appsCache{}
	failed := false
	t := time.NewTicker(StatusEvery)
	defer t.Stop()
	for {
		err := writeStatus(path, readStatus(root, dir, m, time.Now(), cache))
		if err != nil && !failed {
			logf("the status screen's file could not be written: %v", err)
		}
		failed = err != nil
		select {
		case <-stop:
			return
		case <-t.C:
		}
	}
}

// Package engine answers `dgo engine doctor` and `dgo engine plan`: which docker ENGINE this office
// runs on, decided the way bbox decides it, and the steps `bbox run` takes to provision it. It is the
// first slice of the plan's engine piece (ai/context/dgo-architecture-2026.md §5.1, "the only place
// that knows an OS"; core-native-plan.md step 1) and it only READS: starting, stopping and
// provisioning stay in bbox.cmd, bbox's need_docker and packaging/macos/engine.sh until a later
// slice moves them in here.
//
// WHERE THE QUESTIONS ARE ASKED. bbox runs where the engine is, so every question is asked there: on
// Linux this machine; on Windows the WSL distro `Ubuntu`, the way bbox.cmd hands over (never Docker
// Desktop, a different dockerd with other data — ai/context/running-on-wsl.md); on macOS the Lima/vz
// guest under ~/.bbox/macos, the way engine.sh hands over. Only HOW a command reaches that host
// differs, so the checks are bbox's Linux checks, written once.
//
// NOTHING IS STARTED. Booting a stopped distro or guest starts dockerd and the office with it, which
// is not a doctor's call; a stopped engine is reported as stopped, with the command that starts it.
//
// EVERY EXTERNAL CALL IS INJECTED (System): wsl.exe, docker, limactl, systemctl, sysctl, the /proc
// reads. The tests answer from recorded outputs and run nothing; the oracle tests run bbox's own bash
// functions and select-profile.py on the same recordings and require the same answers.
package engine

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// The names bbox gives these, each written once there and used by the same name here.
const (
	distro      = "Ubuntu"                                         // bbox.cmd: wsl.exe -d Ubuntu
	projectSock = "/run/bbox-docker.sock"                          // scripts/lib.sh: BBOX_DOCKER_SOCK's default
	composeBin  = "/usr/libexec/docker/cli-plugins/docker-compose" // scripts/lib.sh: BBOX_COMPOSE's default
	sandboxCA   = "/root/.ccr/ca-bundle.crt"                       // scripts/lib.sh: PROXY_CA's default, the cloud sandbox's tell
	pinned      = "28"                                             // debian-install.sh's DOCKER_MAJOR; engine.yaml installs 28.5.2
)

// why28 is the pin's reason in one line, the way healthy-baseline.md gives it.
const why28 = "28.x required: traefik v3.3 speaks docker API 1.24, Docker 29 refuses clients below 1.40, " +
	"so traefik finds zero routers and every *.localhost 404s while it reports healthy"

// System is every question this package can ask the machine. Real asks this one; a test answers
// from recordings, so nothing ever runs there.
type System struct {
	GOOS string
	// Run runs argv and returns its stdout. An error means it did not start or exited non-zero, and
	// carries the program's stderr: the words a fix may need (WSL's error code, docker's refusal).
	Run  func(argv ...string) (string, error)
	Read func(path string) ([]byte, error)
	Env  func(key string) string
}

// Real is this machine.
func Real() System { return System{GOOS: runtime.GOOS, Run: run, Read: os.ReadFile, Env: os.Getenv} }

// OnAndroid is where a phone's office runs and how it starts: the doctor's fix on Android, and what dgo
// says there with no checkout around it — the way it is first met on a phone (DGO-1069). This build
// runs in an Android app; the Linux terminal is a Debian VM, where dgo is the linux/arm64 one.
const OnAndroid = "On Android the office runs in the phone's Linux terminal (Android 15+, a Debian VM): " +
	"Settings → System → Developer options → Linux development environment; in its Terminal, " +
	"`sudo apt-get install -y git`, clone the office's repository, then `./bbox install debian` and `./bbox run` " +
	"(dgo there is the linux/arm64 build, not this one) — packaging/android.md"

// errTimeout is a call that did not come back: a hung wsl.exe or limactl must not hang the doctor.
var errTimeout = errors.New("no answer in time")

// callTimeout bounds every call. Killing the program at the deadline is not enough on its own:
// limactl's ssh, or a wsl.exe child, can hold the output pipe after its parent is gone, and Wait
// would wait for it — so the program's whole process group is killed where there is one (group),
// and WaitDelay stops waiting for the pipe either way.
var callTimeout = 45 * time.Second

func run(argv ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), callTimeout)
	defer cancel()
	var out, errb bytes.Buffer
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Stdout, cmd.Stderr = &out, &errb
	cmd.WaitDelay = 5 * time.Second
	group(cmd)
	err := cmd.Run()
	if ctx.Err() != nil {
		return out.String(), errTimeout
	}
	if err != nil {
		return out.String(), fmt.Errorf("%w: %s", err, strings.TrimSpace(errb.String()))
	}
	return out.String(), nil
}

// Owns says which `dgo engine` verbs this package answers. Any other (start, stop, shell …) stays
// bbox's — engine.sh's on a Mac — and main.go hands it there.
func Owns(verb string) bool { return verb == "doctor" || verb == "plan" }

// Main answers `dgo engine doctor` (exit 0 healthy, 1 not) and `dgo engine plan` (exit 0).
func Main(root, verb string, s System, w io.Writer) int {
	m := look(s, root)
	if verb == "plan" {
		writePlan(w, m)
		return 0
	}
	return doctor(w, m)
}

// doctor prints every fact, each failing one with bbox's own words for the fix, and answers 0 only
// when nothing failed.
func doctor(w io.Writer, m *machine) int {
	fmt.Fprintf(w, "dgo engine doctor · %s · %s\n", m.goos, m.kind)
	failed := 0
	for _, f := range m.facts {
		fmt.Fprintf(w, "  %-4s  %-8s  %s\n", f.state, f.name, f.said)
		if f.also != "" {
			fmt.Fprintf(w, "                  %s\n", f.also)
		}
		if f.fix != "" {
			fmt.Fprintf(w, "                  fix: %s\n", f.fix)
		}
		if f.state == fail {
			failed++
		}
	}
	if failed > 0 {
		fmt.Fprintf(w, "not healthy: %d failed\n", failed)
		return 1
	}
	fmt.Fprintln(w, "healthy")
	return 0
}

// ── one read-only look ───────────────────────────────────────────────────────────────────────────

// fact is one line of the doctor: what was found, what follows from it (also), and — when it is
// wrong — bbox's own words for the fix.
type fact struct{ state, name, said, fix, also string }

const (
	pass = "ok"
	fail = "FAIL"
	note = "info"
)

// machine is what one look found. The doctor prints its facts; the plan picks its branches by the
// same values, so the two can never describe different machines.
type machine struct {
	goos, root, kind string
	facts            []fact

	inHost                         string // the checkout's path inside the engine host
	home                           string // macOS: the $HOME the guest mounts
	limactl, limaHome, inst, state string // macOS: the runtime, its home, the guest and its state
	limaOK, rosetta                bool
	cpus, mem, disk                string // macOS: what the guest is (or will be) created with
	handoff                        string // macOS: the LAN address and UDP port handed to the guest, if any

	asked      bool              // the engine host answered at all
	have       map[string]string // docker, dockerd, systemctl → their path there
	systemd    bool              // docker.service is a systemd unit there
	sandbox    bool              // a MITM proxy CA is there (the cloud sandbox)
	mirror     string            // the sandbox's Docker Hub pull-through mirror bbox hands dockerd ("" none)
	inGuest    bool              // dgo itself runs inside the macOS engine's guest
	sock       string            // BBOX_DOCKER_SOCK before the pick: the project socket
	sockKind   string            // what that path is: socket, directory, …, missing
	dockerHost string            // what bbox exports as DOCKER_HOST; "" = nothing of ours answers
	sockAt     string            // BBOX_DOCKER_SOCK after lib.sh's pick, as need_docker sees it
	sockAtKind string            // what that path is
	provisions bool              // need_docker's ensure_project_engine runs (it is not a socket, dockerd is there)
	dropInSame bool              // with systemd: the drop-in bbox would write is already the one on disk
	envFile    bool              // the checkout has a .env
	prof       profile
}

func (m *machine) add(state, name, said, fix string) {
	m.facts = append(m.facts, fact{state: state, name: name, said: said, fix: fix})
}

// host is where bbox runs and the engine answers. via carries a command there (empty: here); env is
// bbox's knobs as that host sees them — a distro or a guest is asked with its defaults, because
// bbox.cmd and engine.sh carry none of the caller's across; root is the checkout's path inside it.
type host struct {
	name string
	via  []string
	env  func(string) string
	root string
}

func (h host) run(s System, argv ...string) (string, error) {
	return s.Run(append(append([]string(nil), h.via...), argv...)...)
}

// read is a file on the engine host: read directly here, through `cat` over there.
func (h host) read(s System, p string) (string, error) {
	if len(h.via) == 0 {
		b, err := s.Read(p)
		return string(b), err
	}
	return h.run(s, "cat", p)
}

func defaults(string) string { return "" }

func look(s System, root string) *machine {
	m := &machine{goos: s.GOOS, root: root}
	switch s.GOOS {
	case "windows":
		m.kind = "the WSL distro " + distro + " with the project's own Docker CE — never Docker Desktop"
		if h, ok := m.wsl(s); ok {
			m.inside(s, h)
		}
	case "darwin":
		m.kind = "the Lima/vz guest under ~/.bbox/macos with Docker 28 pinned — never Docker Desktop"
		if h, ok := m.lima(s); ok {
			m.inside(s, h)
		}
	case "linux":
		m.inside(s, m.linux(s))
	case "android":
		// An Android app runs no containers; the phone's office lives in its Linux terminal (Android 15+:
		// a Debian VM), where this is linux/arm64 and the case above (DGO-1069).
		m.kind = "none for an Android app: the phone's office runs in its Linux terminal, a Debian VM"
		m.add(fail, "engine", "Android runs no containers for an app — the office runs in the phone's Linux terminal", OnAndroid)
	default:
		m.kind = "none: bbox runs on Linux, and on Windows and macOS through their engines"
		m.add(fail, "engine", "dgo knows no engine for "+s.GOOS, "")
	}
	return m
}

// wsl is bbox.cmd's way in: the distro exists, runs, and resolves this checkout. The fix is bbox.cmd's
// own sentence.
func (m *machine) wsl(s System) (host, bool) {
	const fix = "Is WSL installed and the distro present?  Check: wsl -l -v"
	out, err := s.Run("wsl.exe", "-l", "--running", "-q")
	if errors.Is(err, exec.ErrNotFound) {
		m.add(fail, "wsl", "no wsl.exe on this machine", fix)
		return host{}, false
	}
	running, answered := listed(out, err)
	known := running
	if answered && !running {
		known, answered = listed(s.Run("wsl.exe", "-l", "-q"))
	}
	switch {
	case !answered:
		m.add(fail, "wsl", "WSL did not answer (Wsl/Service/0x8007274c): unknown, not missing",
			"a timeout talking to the VM, not a failure inside it — retry (ai/context/running-on-wsl.md)")
	case !known:
		m.add(fail, "wsl", "there is no WSL distro named "+distro, fix)
	case !running:
		m.add(fail, "wsl", "the distro "+distro+" is stopped — a doctor does not start it (that starts the office)",
			"bbox.cmd run — WSL is on-demand: its first call boots the distro, and docker.service with it")
	}
	if !running {
		return host{}, false
	}
	m.add(pass, "wsl", "the distro "+distro+" is running", "")
	out, err = s.Run("wsl.exe", "-d", distro, "-e", "wslpath", "-a", m.root)
	if p := strings.TrimSpace(clean(out)); err == nil && strings.HasPrefix(p, "/") {
		m.inHost = p
		return host{name: "the distro", via: []string{"wsl.exe", "-d", distro, "-u", "root", "-e"}, env: defaults, root: p}, true
	}
	m.add(fail, "checkout", "could not resolve this directory inside the WSL distro '"+distro+"'", fix)
	return host{}, false
}

// rosettaBin is where Apple installs Rosetta: engine.sh uses it when present and never requires it.
const rosettaBin = "/Library/Apple/usr/share/rosetta/rosetta"

// lima is engine.sh's way in — and everything its own doctor (`bbox engine doctor`) tells, line for
// line: the Mac, the pinned runtime and its home, the template, the guest's sizing, Rosetta, the
// guest's state and its socket on the Mac, and the pair tunnel's UDP forward chain. Each is said
// whatever else fails, so `dgo engine doctor` on a Mac never tells less than that one did; the one
// thing left out is the Lima download that one starts first — `./bbox engine start` does that.
func (m *machine) lima(s System) (host, bool) {
	home := s.Env("HOME")
	base := or(s.Env("BBOX_MACOS_HOME"), home+"/.bbox/macos")
	m.home, m.limaHome, m.inst = home, or(s.Env("LIMA_HOME"), base+"/lima"), or(s.Env("BBOX_VM_NAME"), "bbox")
	v := or(s.Env("LIMA_VERSION"), limaPin(s, m.root))
	m.limactl = base + "/lima-" + v + "/bin/limactl"
	lima := []string{"env", "LIMA_HOME=" + m.limaHome, m.limactl}
	ncpu, _ := s.Run("sysctl", "-n", "hw.ncpu")
	memsize, _ := s.Run("sysctl", "-n", "hw.memsize")
	ver, _ := s.Run("sw_vers", "-productVersion")
	arch, _ := s.Run("uname", "-m")
	gib := "?"
	if b, err := strconv.ParseInt(strings.TrimSpace(memsize), 10, 64); err == nil {
		gib = strconv.FormatInt(b/1073741824, 10)
	}
	m.add(note, "mac", "macOS "+strings.TrimSpace(ver)+" "+strings.TrimSpace(arch)+" · "+strings.TrimSpace(ncpu)+" cores · "+gib+" GiB", "")
	// fetch-runtime.sh's own no-op test: the binary runs and is the pinned version.
	out, err := s.Run(m.limactl, "--version")
	if m.limaOK = v != "" && err == nil && strings.Contains(out, v); m.limaOK {
		m.add(pass, "lima", m.limactl+" ("+strings.TrimSpace(out)+") · LIMA_HOME="+m.limaHome, "")
	} else {
		m.add(fail, "lima", "Lima "+or(v, "(no pin in packaging/macos/fetch-runtime.sh)")+" has not landed at "+m.limactl+" · LIMA_HOME="+m.limaHome,
			"./bbox engine start — it fetches Lima (pinned, sha256-verified) and boots the engine")
	}
	m.add(note, "template", m.root+"/packaging/macos/engine.yaml", "")
	dotenv, _ := s.Read(join(m.goos, m.root, ".env")) // a size the office declares (engine.sh's env_value)
	m.cpus, m.mem, m.disk = vmSize(s.Env, dotenv, ncpu, memsize)
	m.add(note, "sizing", "cpus="+m.cpus+" mem="+m.mem+"GiB disk="+m.disk+"GiB (BBOX_VM_CPUS/BBOX_VM_MEM/BBOX_VM_DISK override)", "")
	_, err = s.Run("test", "-f", rosettaBin)
	if err == nil {
		_, err = s.Run("arch", "-x86_64", "/usr/bin/true")
	}
	if m.rosetta = err == nil; m.rosetta {
		m.add(note, "rosetta", "present — amd64 images will run too", "")
	} else {
		m.add(note, "rosetta", "absent — only arm64 images will run (optional: softwareupdate --install-rosetta)", "")
	}
	under := strings.HasPrefix(m.root, home+"/")
	if !under {
		m.add(fail, "checkout", m.root+" is outside "+home+", and the guest mounts only $HOME",
			"the repo must live under "+home+" to be visible in the guest (it is at "+m.root+")")
	}
	if m.limaOK {
		out, _ = s.Run(append(lima, "list", "--format", "{{.Name}} {{.Status}}")...)
		if m.state = limaState(out, m.inst); m.state == "Running" {
			m.add(pass, "guest", "the guest "+m.inst+" is Running", "")
		} else {
			m.add(fail, "guest", "the guest "+m.inst+" is "+or(m.state, "not created")+" — a doctor does not boot it (that starts the office)",
				"./bbox engine start — boot the engine (first run: fetch Lima, download the guest image, install Docker CE 28.5.2 pinned — ~5 min on a normal line)")
		}
	}
	m.add(note, "macsock", m.limaHome+"/"+m.inst+"/sock/docker.sock — the engine's docker socket on this Mac (bbox itself runs in the guest)", "")
	m.forwards(s, lima)
	if !under || m.state != "Running" {
		return host{}, false
	}
	return host{name: "the guest", via: append(lima, "shell", m.inst, "sudo"), env: defaults, root: m.root}, true
}

// forwards is engine.sh's forward_report: the pair tunnel's UDP forward as a chain of three links that
// close in order — the instance declares the rule, the guest listens, the Mac holds the socket. Only
// the last missing with the middle one up is a fault on this Mac; the others are "not yet", said with
// the step that closes them. The guest is handed the Mac's LAN address and the port when the rule is
// declared and the Mac has an address — never waiting for the socket, which would be a closed loop.
func (m *machine) forwards(s System, lima []string) {
	lan := lanAddr(s)
	m.add(note, "lan", or(lan, "none — this Mac has no default route, so nothing on the network can dial it"), "")
	ports := udpForwards(s.Read(m.limaHome + "/" + m.inst + "/lima.yaml"))
	for _, port := range ports {
		bound, held := "no", "no"
		if m.state == "Running" {
			if out, err := s.Run(append(lima, "shell", m.inst, "--", "ss", "-lunH")...); err == nil && guestBinds(out, port) {
				bound = "yes"
			}
		}
		if out, err := s.Run("lsof", "-nP", "-iUDP:"+port); err == nil && macHolds(out, port) {
			held = "yes"
		}
		m.add(note, "udp", port+"/udp from 0.0.0.0 — instance: declared · guest listening: "+bound+" · Mac socket: "+held, "")
		switch {
		case bound == "no":
			m.facts[len(m.facts)-1].also = "the office has not published it yet: `bbox run` writes DGO_WG_PUBLISH_PORT / DGO_WG_PUBLISH_BIND=0.0.0.0 and dgo-net then listens. " +
				"Lima opens the Mac socket only after that (a rule is bound at startup only with `static: true`, TCP only)"
		case held == "no":
			m.facts[len(m.facts)-1].fix = "the guest listens and the Mac holds nothing — two candidates, in this order: " +
				"1. macOS incoming-connection consent denied: System Settings → Network → Firewall → Options " +
				"2. LIMA_SSH_PORT_FORWARDER=true: the SSH forwarder cannot do UDP at all"
		}
	}
	if len(ports) == 0 {
		fix := ""
		if len(udpForwards(s.Read(m.root+"/packaging/macos/engine.yaml"))) > 0 {
			fix = "the template declares it; apply it to this instance: ./bbox engine forwards --apply"
		}
		m.add(note, "udp", "none — this engine forwards TCP only, so the guest can only DIAL", fix)
	}
	if lan != "" && len(ports) > 0 {
		m.handoff = "BBOX_HOST_LAN_ADDR=" + lan + " BBOX_HOST_UDP_PORT=" + ports[0]
		m.add(note, "handoff", m.handoff+" → hooks/prepare declares this office dialable", "")
	} else {
		m.add(note, "handoff", "no handoff — hooks/prepare keeps DGO_WG_DIAL_ONLY=engine-guest", "")
	}
}

// lanAddr is engine.sh's lan_addr: the IPv4 of the interface this Mac's default route uses, never a
// guess — "" when there is no default route.
func lanAddr(s System) string {
	route, _ := s.Run("route", "-n", "get", "default")
	var ifaces []string
	for _, l := range strings.Split(route, "\n") {
		if strings.Contains(l, "interface:") {
			f := strings.Fields(l)
			ifaces = append(ifaces, strings.Join(f[1:min(len(f), 2)], ""))
		}
	}
	iface := strings.TrimRight(strings.Join(ifaces, "\n"), "\n")
	if iface == "" {
		return ""
	}
	addr, _ := s.Run("ipconfig", "getifaddr", iface)
	return strings.TrimRight(addr, "\n")
}

var (
	topKeyRE  = regexp.MustCompile(`^[A-Za-z_]`)
	ruleRE    = regexp.MustCompile(`^\s*-\s*([\w-]+):\s*(.*)$`)
	ruleKeyRE = regexp.MustCompile(`^\s+([\w-]+):\s*(.*)$`)
)

// udpForwards is engine.sh's ports_yaml, line for line: the guest ports of a Lima config's UDP rules
// bound to a wildcard host address — the only ones a peer on the network can reach (Lima's default
// is 127.0.0.1). Like the original it is deliberately narrow, not YAML — it reads the flat block Lima
// writes and answers one question — so both read every file the same way (TestUDPForwardsMatchEngineSh).
// A file that cannot be read forwards nothing: the safe answer, the guest stays on the dial-only path.
func udpForwards(b []byte, err error) []string {
	if err != nil {
		return nil
	}
	var rules []map[string]string
	inside := false
	for _, line := range strings.Split(strings.ReplaceAll(string(b), "\r\n", "\n"), "\n") {
		if topKeyRE.MatchString(line) { // a new top-level key ends the block
			if inside {
				break
			}
			inside = strings.HasPrefix(line, "portForwards:")
			continue
		}
		if !inside {
			continue
		}
		if r := ruleRE.FindStringSubmatch(line); r != nil {
			rules = append(rules, map[string]string{r[1]: strings.TrimSpace(r[2])})
		} else if k := ruleKeyRE.FindStringSubmatch(line); k != nil && len(rules) > 0 {
			rules[len(rules)-1][k[1]] = strings.TrimSpace(k[2])
		}
	}
	var ports []string
	for _, rule := range rules {
		val := func(k string) string { return strings.Trim(strings.Trim(strings.TrimSpace(rule[k]), `"`), `'`) }
		proto, ip, port := strings.ToLower(val("proto")), val("hostIP"), val("guestPort")
		wild := ip != "" && ip != "127.0.0.1" && ip != "localhost" && ip != "::1"
		if (proto == "udp" || proto == "any") && wild && port != "" && strings.Trim(port, "0123456789") == "" {
			ports = append(ports, port)
		}
	}
	return ports
}

// guestBinds is guest_udp_bound's match on `ss -lunH`: the port, then whitespace, so a peer address
// or a header can never satisfy it.
func guestBinds(ss, port string) bool {
	return regexp.MustCompile(`[:.]` + regexp.QuoteMeta(port) + `[[:space:]]`).MatchString(ss)
}

// macHolds is udp_listening's reading of `lsof -nP -iUDP:<port>`: a socket for the port in the NAME
// column (the 9th) that is not bound to loopback.
func macHolds(lsof, port string) bool {
	for i, l := range strings.Split(lsof, "\n") {
		if f := strings.Fields(l); i > 0 && len(f) >= 9 && strings.Contains(f[8], ":"+port) &&
			!strings.HasPrefix(f[8], "127.") && !strings.HasPrefix(f[8], "localhost") && !strings.HasPrefix(f[8], "[::1]") {
			return true
		}
	}
	return false
}

// listed reads a `wsl.exe -l … -q` answer: is the distro on it, and did WSL answer at all. WSL's own
// timeout (Wsl/Service/0x8007274c) is "unknown, retry", never "missing" (ai/context/running-on-wsl.md).
func listed(out string, err error) (found, answered bool) {
	if err != nil && (errors.Is(err, errTimeout) || strings.Contains(clean(out+err.Error()), "0x8007274c")) {
		return false, false
	}
	for _, l := range lines(clean(out)) {
		if strings.EqualFold(l, distro) {
			return true, true
		}
	}
	return false, true
}

// pinRE finds the Lima version fetch-runtime.sh pins, so the pin keeps one home.
var pinRE = regexp.MustCompile(`LIMA_VERSION="\$\{LIMA_VERSION:-([^}"]+)\}"`)

func limaPin(s System, root string) string {
	b, _ := s.Read(root + "/packaging/macos/fetch-runtime.sh")
	if p := pinRE.FindSubmatch(b); p != nil {
		return string(p[1])
	}
	return ""
}

// vmSize is engine.sh's vm_cpus, vm_mem and vm_disk. The guest is the docker host, so its memory is
// what the profiles measure: a Mac of 8 GiB or less gives it the 5 GiB the floor profile needs, a
// bigger one 60% capped at 12, and never more than 4 cpus.
func vmSize(env func(string) string, dotenv []byte, ncpu, memsize string) (cpus, mem, disk string) {
	cpus, mem, disk = declaredNum(env, dotenv, "BBOX_VM_CPUS"), declaredNum(env, dotenv, "BBOX_VM_MEM"), or(env("BBOX_VM_DISK"), "60")
	if cpus == "" {
		cpus = "?"
		if n, err := strconv.Atoi(strings.TrimSpace(ncpu)); err == nil {
			cpus = strconv.Itoa(min(n, 4))
		}
	}
	if mem == "" {
		mem = "?"
		if b, err := strconv.ParseInt(strings.TrimSpace(memsize), 10, 64); err == nil {
			g := b / 1073741824
			if g <= 8 {
				mem = "5"
			} else {
				mem = strconv.FormatInt(min(g*60/100, 12), 10)
			}
		}
	}
	return cpus, mem, disk
}

var declaredNumRE = regexp.MustCompile(`^[0-9]+(\.[0-9]+)?$`)

// declaredNum is engine.sh's declared_num: a size the office declares — in the environment, else the last
// `KEY=` line of its .env (env_value) — when it is a plain number (GiB may be fractional); anything else
// ("3GiB", "3 # small") is ignored and the default applies.
func declaredNum(env func(string) string, dotenv []byte, key string) string {
	v := env(key)
	if v == "" {
		v = dotenvValue(dotenv, key)
	}
	if !declaredNumRE.MatchString(v) {
		return ""
	}
	return v
}

// dotenvValue is engine.sh's env_value: the last line of the .env that sets key, its value with every quote
// taken out and the trailing blanks trimmed.
func dotenvValue(dotenv []byte, key string) string {
	re := regexp.MustCompile(`^[[:space:]]*` + regexp.QuoteMeta(key) + `[[:space:]]*=`)
	last := ""
	for _, l := range strings.Split(string(dotenv), "\n") {
		if re.MatchString(l) {
			last = l
		}
	}
	if last == "" {
		return ""
	}
	v := strings.NewReplacer(`"`, "", "'", "").Replace(last[strings.Index(last, "=")+1:])
	return strings.TrimRight(v, " \t\r\n\v\f")
}

// limaState is engine.sh's state(): the second field of the guest's line in `limactl list` —
// Running, Stopped, Broken … — and "" when there is no such guest.
func limaState(list, inst string) string {
	var got []string
	for _, l := range strings.Split(list, "\n") {
		if f := strings.Fields(l); len(f) > 0 && f[0] == inst {
			got = append(got, strings.Join(f[1:min(len(f), 2)], ""))
		}
	}
	return strings.Join(got, "\n")
}

func (m *machine) linux(s System) host {
	m.kind = "the docker engine of this machine"
	m.inGuest = s.Env("BBOX_IN_GUEST") != ""
	return host{name: "this machine", env: s.Env, root: m.root}
}

// inside asks the engine host what need_docker asks, in its order, then what ensure_perf_profile
// sizes the stack by: bbox's Linux questions, the same on all three systems.
func (m *machine) inside(s System, h host) {
	if len(h.via) > 0 {
		if _, err := h.run(s, "test", "-f", h.root+"/bbox"); err != nil {
			m.add(fail, "checkout", h.root+" is not visible inside "+h.name+" — bbox cannot run this checkout there", "")
			return
		}
		where := "at " + h.root
		if h.root == m.root {
			where = "at the same path"
		}
		m.add(pass, "checkout", m.root+" is visible inside "+h.name+" "+where, "")
	}
	out, err := h.run(s, "sh", "-c", "for c do command -v $c || :; done", "sh", "docker", "dockerd", "systemctl")
	if err != nil {
		m.add(fail, "engine", h.name+" did not answer: "+firstLine(err.Error()), "")
		return
	}
	m.asked, m.have = true, map[string]string{}
	for _, p := range lines(out) {
		m.have[path.Base(p)] = p
	}
	// The profile is a fact of the host, not of docker: said even when the engine is not up, so the
	// doctor and the plan show what `bbox run` will size the stack to once it is.
	defer m.profile(s, h)
	if m.have["systemctl"] != "" {
		_, err := h.run(s, "systemctl", "cat", "docker.service")
		m.systemd = err == nil
	}
	_, err = h.run(s, "test", "-f", or(h.env("PROXY_CA"), h.env("BASELINE_PROXY_CA"), sandboxCA))
	m.sandbox = err == nil
	// bbox's need_docker (d5d803b6, 2026-10-15): in the sandbox, and only there, dockerd pulls Docker
	// Hub through mirror.gcr.io unless BBOX_REGISTRY_MIRROR names another. bbox reads `${…-default}`,
	// so an EMPTY variable turns it off there; an env func cannot tell empty from unset, so here an
	// empty one is the default — the one case the two differ, named.
	if m.sandbox {
		m.mirror = or(h.env("BBOX_REGISTRY_MIRROR"), "https://mirror.gcr.io")
	}
	if m.goos == "linux" {
		m.kind = "the systemd docker service"
		if !m.systemd {
			m.kind = "a dockerd bbox starts itself — no systemd docker.service here (the cloud sandbox's case)"
		}
		if m.inGuest {
			m.kind += ", inside the macOS engine's guest"
		}
	}
	if m.sandbox {
		m.add(note, "sandbox", "a MITM egress proxy CA is here — bbox run CA-shadows every base image and builds first-party images one at a time (scripts/lib.sh ccr_*)", "")
	}
	m.sock, m.sockKind = or(h.env("BBOX_DOCKER_SOCK"), projectSock), "missing"
	if k, err := h.run(s, "stat", "-L", "-c", "%F", m.sock); err == nil {
		m.sockKind = strings.TrimSpace(k)
	}
	if m.have["docker"] == "" {
		m.add(fail, "docker", "no docker CLI on the PATH of "+h.name, "docker not found — run: bbox install <debian|windows>")
		return
	}
	// bbox sources lib.sh before anything else, and lib.sh picks the engine right there (lib.sh:276):
	// one that answers on a unix socket re-points BBOX_DOCKER_SOCK at itself. need_docker then
	// provisions the project socket only if THAT path is not a socket — so on a host whose
	// docker.service answers on /var/run/docker.sock, it never does.
	var tried []endpoint
	m.dockerHost, tried = pick(s, h, m.sock)
	m.sockAt, m.sockAtKind = exported(m.dockerHost, m.sock), m.sockKind
	if m.sockAt != m.sock {
		m.sockAtKind = "socket" // it answered `docker info`
		if tried == nil {       // BBOX_DOCKER_HOST is taken as given: nothing asked it
			m.sockAtKind = "missing"
			if k, err := h.run(s, "stat", "-L", "-c", "%F", m.sockAt); err == nil {
				m.sockAtKind = strings.TrimSpace(k)
			}
		}
	}
	m.provisions = m.sockAtKind != "socket" && m.have["dockerd"] != ""
	if m.provisions && m.systemd {
		on, _ := h.read(s, dropInConf)
		m.dropInSame = strings.TrimRight(on, "\n") == dropIn(m.sockAt)
	}
	if m.dockerHost == "" {
		var seen []string
		for _, e := range tried {
			seen = append(seen, e.addr+" ("+e.said()+")")
		}
		fix := notReachable(m.sock) // what bbox says when it cannot start one either
		switch {
		case m.provisions && !m.systemd:
			fix = "bbox run starts it — dockerd on " + m.sockAt + ", as root or with passwordless sudo (dgo engine plan)"
		case m.provisions && !m.dropInSame:
			fix = "bbox run starts it — it writes the drop-in and restarts docker.service, as root or with passwordless sudo (dgo engine plan)"
		}
		m.add(fail, "engine", "nothing of ours answers: "+strings.Join(seen, ", "), fix)
		return
	}
	m.add(pass, "engine", "DOCKER_HOST="+m.dockerHost+" — the engine bbox selects"+osOf(tried, m.dockerHost), "")
	m.version(s, h)
	m.socket()
	cb := or(h.env("BBOX_COMPOSE"), composeBin)
	if _, err := h.run(s, "test", "-x", cb); err != nil {
		m.add(fail, "compose", "no compose plugin at "+cb, "compose plugin missing at "+cb+" — run: bbox install debian (installs docker-compose-plugin)")
	} else {
		m.add(pass, "compose", cb+" — the compose binary bbox names (never the docker plugin search)", "")
	}
}

// endpoint is one address bbox tries and what answered there: `docker info`'s OperatingSystem, or
// the refusal.
type endpoint struct{ addr, os, err string }

// kind is bbox_endpoint_kind: "native", "desktop" (Docker Desktop names itself), or "" — dead.
func (e endpoint) kind() string {
	switch {
	case e.err != "" || e.os == "":
		return ""
	case strings.Contains(e.os, "Docker Desktop"):
		return "desktop"
	}
	return "native"
}

func (e endpoint) said() string {
	switch e.kind() {
	case "desktop":
		return "Docker Desktop's — never used"
	case "":
		return or(e.err, "no answer")
	}
	return e.os
}

// pick is bbox_select_engine: BBOX_DOCKER_HOST as given, else the first endpoint in bbox's order
// where an engine answers that is not Docker Desktop. It returns what bbox exports as DOCKER_HOST
// ("" when nothing of ours answers — need_docker's refusal) and what each endpoint said.
func pick(s System, h host, sock string) (string, []endpoint) {
	if v := h.env("BBOX_DOCKER_HOST"); v != "" {
		return v, nil
	}
	var tried []endpoint
	for _, ep := range []string{"unix://" + sock, h.env("DOCKER_HOST"), "unix:///var/run/docker.sock", "unix:///run/docker.sock"} {
		if ep == "" {
			continue
		}
		out, err := h.run(s, "docker", "-H", ep, "info", "--format", "{{.OperatingSystem}}")
		e := endpoint{addr: ep, os: strings.TrimRight(out, "\n")}
		if err != nil {
			e.os, e.err = "", firstLine(err.Error())
		}
		if tried = append(tried, e); e.kind() == "native" {
			return ep, tried
		}
	}
	return "", tried
}

// exported is BBOX_DOCKER_SOCK after bbox_engine_chosen: only a unix socket can be bind-mounted, so
// only a unix endpoint replaces it.
func exported(dockerHost, sock string) string {
	if p, ok := strings.CutPrefix(dockerHost, "unix://"); ok {
		return p
	}
	return sock
}

func osOf(tried []endpoint, ep string) string {
	for _, e := range tried {
		if e.addr == ep {
			return " (" + e.os + ")"
		}
	}
	return " (BBOX_DOCKER_HOST, taken as given)"
}

// dropInConf is where ensure_project_engine teaches docker.service the project socket, and dropIn
// what it writes there — compared first, so an identical file is never rewritten and the daemon
// (and every container with it) is never restarted for nothing.
const dropInConf = "/etc/systemd/system/docker.service.d/10-bbox-endpoint.conf"

func dropIn(sock string) string {
	return "[Service]\nEnvironment=DOCKER_MIN_API_VERSION=1.24\nExecStart=\n" +
		"ExecStart=/usr/bin/dockerd -H fd:// -H unix://" + sock + " --containerd=/run/containerd/containerd.sock"
}

// notReachable is need_docker's refusal, word for word.
func notReachable(sock string) string {
	return "the project engine is not reachable (tried " + sock + ", $DOCKER_HOST, /var/run/docker.sock). " +
		"Docker Desktop's engine, if running, is deliberately NOT used: every image and volume this stack owns belongs to the project engine. " +
		"Start the docker service, or set BBOX_DOCKER_HOST to choose an endpoint explicitly."
}

// version is the pin: debian-install.sh refuses any major but 28 and engine.yaml's probe refuses
// anything but 28.*, each with its own words for the fix. The API and its floor come along, as
// engine.sh's doctor prints them: the floor is what traefik's 1.24 client meets or does not.
func (m *machine) version(s System, h host) {
	out, err := h.run(s, "docker", "-H", m.dockerHost, "version", "--format", "{{.Server.Version}} {{.Server.APIVersion}} {{.Server.MinAPIVersion}}")
	f := append(strings.Fields(out), "?", "?", "?")
	v, said := f[0], "Docker "+f[0]+" (API "+f[1]+", min "+f[2]+") — "+why28
	major, _, _ := strings.Cut(v, ".")
	switch {
	case err != nil || v == "?":
		m.add(fail, "docker", "the engine at "+m.dockerHost+" gave no version: "+firstLine(fmt.Sprint(err)), notReachable(m.sock))
	case major != pinned && m.goos == "darwin":
		m.add(fail, "docker", said, "engine is "+v+", expected 28.x — packaging/macos/engine.yaml pins 28.5.2 and holds it; "+
			"See \"/var/log/cloud-init-output.log\" in the guest (limactl shell "+m.inst+" sudo cat /var/log/cloud-init-output.log)")
	case major != pinned:
		how := "BBOX_REPLACE_DOCKER=1 ./bbox install debian"
		if m.goos == "windows" {
			how = "wsl -d " + distro + " -u root -- bash -lc \"cd '" + m.inHost + "' && BBOX_REPLACE_DOCKER=1 ./bbox install windows\""
		}
		m.add(fail, "docker", said, "Docker "+v+" is installed; this platform needs Docker 28.x. "+
			"Re-run with BBOX_REPLACE_DOCKER=1 to replace it (containers stop; volumes are kept): "+how)
	default:
		m.add(pass, "docker", said, "")
	}
}

// socket is the address compose bind-mounts into traefik, machine, connections, app-management and
// any-concurrency (BBOX_DOCKER_SOCK); bbox_assert_engine_socket refuses one that is not a socket.
func (m *machine) socket() {
	switch {
	case m.sockAtKind == "socket" && m.sockAt == m.sock:
		m.add(pass, "socket", m.sock+" — the project engine's own address, which Docker Desktop never binds", "")
	case m.sockAtKind == "socket":
		m.add(pass, "socket", m.sockAt+" — lib.sh picks it when bbox loads, so the project socket "+m.sock+" ("+m.sockKind+
			") is not provisioned while this one answers", "")
	case m.sockAtKind == "directory":
		m.add(fail, "socket", "BBOX_DOCKER_SOCK="+m.sockAt+" is a DIRECTORY, not a socket — Docker created it for a bind-mount whose source was missing",
			"Remove it (sudo rmdir '"+m.sockAt+"') and re-run; the engine in use is $DOCKER_HOST="+m.dockerHost+".")
	case m.provisions:
		m.add(fail, "socket", "BBOX_DOCKER_SOCK="+m.sockAt+" is not a socket ("+m.sockAtKind+")",
			"bbox run provisions it before anything mounts it (ensure_project_engine), as root or with passwordless sudo (dgo engine plan)")
	default:
		m.add(fail, "socket", "BBOX_DOCKER_SOCK="+m.sockAt+" is not a socket ("+m.sockAtKind+")", "BBOX_DOCKER_SOCK="+m.sockAt+
			" does not exist. The engine in use is $DOCKER_HOST="+m.dockerHost+"; containers cannot be handed a socket that is not there.")
	}
}

// generatesEnv is bbox run's first branch: with no .env, on the cloud sandbox or in the macOS
// guest, scripts/ci-env.sh writes one and bbox run starts over on it.
func (m *machine) generatesEnv() bool {
	return !m.envFile && (m.sandbox || m.goos == "darwin" || m.inGuest)
}

// ciEnvRE finds the profile line scripts/ci-env.sh writes into a .env it generates (unless
// OFFICE_DOMAIN names a real office), so that line keeps one home.
var ciEnvRE = regexp.MustCompile(`\|\| echo "(PERFORMANCE_PROFILE=[^"]+)"`)

// profile is what ensure_perf_profile sizes the stack by: the engine host's cores and memory (the
// WSL VM's, the guest's — never the laptop's), the profiles' envelopes, and the .env bbox run will
// have by then — the one ci-env.sh generates, where that step runs.
func (m *machine) profile(s System, h host) {
	env, err := s.Read(join(m.goos, m.root, ".env"))
	m.envFile = err == nil
	generated := m.generatesEnv()
	if generated {
		env = nil
		ci, _ := s.Read(join(m.goos, m.root, "scripts", "ci-env.sh"))
		if l := ciEnvRE.FindSubmatch(ci); l != nil && h.env("OFFICE_DOMAIN") == "" {
			env = []byte(string(l[1]) + "\n")
		}
	}
	yml, yerr := s.Read(join(m.goos, m.root, "platform", "profiles", "perf-profiles.yml"))
	meminfo, _ := h.read(s, "/proc/meminfo")
	// Two counts: bbox says what `nproc` says (ncores), which honours OMP_NUM_THREADS; select-profile.py
	// counts the CPUs this process may run on (sched_getaffinity), which does not.
	out, _ := h.run(s, "sh", "-c", "nproc; env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc")
	n := append(strings.Fields(out), "0", "0")
	said, _ := strconv.Atoi(n[0])
	cores, _ := strconv.Atoi(n[1])
	gib := memTotal(meminfo)
	fit, ferr := selectProfile(yml, yerr, cores, gib)
	m.prof = pickProfile(env, fit, ferr, said)
	m.prof.generated = generated && m.prof.set
	where := fmt.Sprintf("%d cores, %.1f GiB in %s", cores, gib, h.name)
	switch p := m.prof; {
	case p.stop != nil:
		m.add(fail, "profile", "no answer ("+p.stop.Error()+") and .env names no PERFORMANCE_PROFILE — bbox run stops in ensure_perf_profile: "+
			"under set -e the failed `prof=$(…)` exits before its floor fallback", "PERFORMANCE_PROFILE="+floor+" in .env — the floor bbox means to fall back to "+
			"(\"profile selector unavailable — falling back to the floor profile ("+floor+").\")")
	case p.generated:
		m.add(note, "profile", strings.Join(append([]string{p.name + " (written to .env by scripts/ci-env.sh, which bbox run runs first here) · " + where}, p.said...), " · "), "")
	case p.set:
		m.add(note, "profile", strings.Join(append([]string{p.name + " (set in .env) · " + where}, p.said...), " · "), "")
	default:
		m.add(note, "profile", p.name+" · "+where+" · bbox run writes it to .env: "+strings.Join(p.said, " · "), "")
	}
}

// ── small helpers ────────────────────────────────────────────────────────────────────────────────

// clean makes wsl.exe's own output readable: it writes UTF-16, a NUL after every ASCII byte, and
// UTF-8 never holds a NUL — so dropping them (and the byte-order mark) is exact for what is read here.
func clean(s string) string {
	if !strings.Contains(s, "\x00") {
		return s
	}
	return strings.TrimPrefix(strings.ReplaceAll(s, "\x00", ""), "\xff\xfe")
}

func lines(s string) []string {
	var out []string
	for _, l := range strings.Split(s, "\n") {
		if l = strings.TrimSpace(l); l != "" {
			out = append(out, l)
		}
	}
	return out
}

func firstLine(s string) string { l, _, _ := strings.Cut(strings.TrimSpace(s), "\n"); return l }

func or(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

// join is a path on the machine being described — a Windows one when the look is from Windows,
// whatever system runs the test.
func join(goos string, elem ...string) string {
	if goos == "windows" {
		return strings.Join(elem, `\`)
	}
	return path.Join(elem...)
}

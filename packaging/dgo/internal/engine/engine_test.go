package engine

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// ── recorded machines ─────────────────────────────────────────────────────────────────────────────

// reply is one recorded answer: what a program printed, and the error it exited with (nil: 0).
type reply struct {
	out string
	err error
}

func ok(out string) reply    { return reply{out: out} }
func no(stderr string) reply { return reply{err: errors.New(stderr)} }

// rec is a recorded machine: the commands it answers (argv joined by spaces), its files, its
// environment. Asking it anything else fails the test — a new question is recorded, and reviewed,
// before any real machine is asked it.
type rec struct {
	goos, root string
	cmds       map[string]reply
	files      map[string]string
	env        map[string]string
	asked      []string
}

func (r *rec) system(t *testing.T) System {
	return System{
		GOOS: r.goos,
		Run: func(argv ...string) (string, error) {
			k := strings.Join(argv, " ")
			r.asked = append(r.asked, k)
			a, found := r.cmds[k]
			if !found {
				t.Errorf("unrecorded call: %s", k)
				return "", errors.New("unrecorded")
			}
			return a.out, a.err
		},
		Read: func(p string) ([]byte, error) {
			if b, found := r.files[p]; found {
				return []byte(b), nil
			}
			return nil, fs.ErrNotExist
		},
		Env: func(k string) string { return r.env[k] },
	}
}

func (r *rec) answer(t *testing.T, verb string) (string, int) {
	t.Helper()
	var b bytes.Buffer
	code := Main(r.root, verb, r.system(t), &b)
	return b.String(), code
}

// repoRoot is the checkout these tests live in: the real profiles file, Lima pin and bash are read
// from it.
func repoRoot(t *testing.T) string {
	t.Helper()
	d, _ := os.Getwd()
	for {
		if isFile(filepath.Join(d, "bbox")) && isFile(filepath.Join(d, "scripts", "lib.sh")) {
			return d
		}
		parent := filepath.Dir(d)
		if parent == d {
			t.Skip("not inside the checkout")
		}
		d = parent
	}
}

func isFile(p string) bool { st, err := os.Stat(p); return err == nil && !st.IsDir() }

func repoFile(t *testing.T, rel string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(repoRoot(t), filepath.FromSlash(rel)))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func meminfo(kb int) string {
	return fmt.Sprintf("MemTotal:       %d kB\nMemFree:         1234567 kB\nMemAvailable:    2345678 kB\n", kb)
}

// utf16 is how wsl.exe writes its own output.
func utf16(s string) string {
	var b strings.Builder
	b.WriteString("\xff\xfe")
	for i := 0; i < len(s); i++ {
		b.WriteByte(s[i])
		b.WriteByte(0)
	}
	return b.String()
}

// coresKey is the core count's question: nproc as bbox counts (OMP_NUM_THREADS honoured), then as
// select-profile.py counts (it is not).
const coresKey = "sh -c nproc; env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc"

func cores(n int) reply { return ok(fmt.Sprintf("%d\n%d\n", n, n)) }

// healthyHost is an engine host where all is well — Docker 28.5.2 under systemd on the project
// socket, the compose plugin bbox names, 6 cores and a 9.7 GiB VM (the HP's own numbers) — reached
// through via.
func healthyHost(via, root string) map[string]reply {
	at := func(cmd string) string { return strings.TrimSpace(via + " " + cmd) }
	r := map[string]reply{
		at("sh -c for c do command -v $c || :; done sh docker dockerd systemctl"):       ok("/usr/bin/docker\n/usr/bin/dockerd\n/usr/bin/systemctl\n"),
		at("systemctl cat docker.service"):                                              ok("# /lib/systemd/system/docker.service\n[Unit]\nDescription=Docker Application Container Engine\n"),
		at("test -f /root/.ccr/ca-bundle.crt"):                                          no(""),
		at("stat -L -c %F /run/bbox-docker.sock"):                                       ok("socket\n"),
		at("docker -H unix:///run/bbox-docker.sock info --format {{.OperatingSystem}}"): ok("Ubuntu 22.04.3 LTS\n"),
		at("docker -H unix:///run/bbox-docker.sock version --format {{.Server.Version}} {{.Server.APIVersion}} {{.Server.MinAPIVersion}}"): ok("28.5.2 1.51 1.24\n"),
		at("test -x /usr/libexec/docker/cli-plugins/docker-compose"):                                                                       ok(""),
		at(coresKey): cores(6),
	}
	if via != "" {
		r[at("test -f "+root+"/bbox")] = ok("")
		r[at("cat /proc/meminfo")] = ok(meminfo(10188772))
	}
	return r
}

const (
	winRoot = `C:\Users\u\MyDGO`
	winIn   = "/mnt/c/Users/u/MyDGO"
	winVia  = "wsl.exe -d Ubuntu -u root -e"
	macRoot = "/Users/u/MyDGO"
	macCtl  = "/Users/u/.bbox/macos/lima-2.2.0/bin/limactl"
	macLima = "env LIMA_HOME=/Users/u/.bbox/macos/lima " + macCtl
	macVia  = macLima + " shell bbox sudo"
	linRoot = "/srv/office"
	dead    = "Cannot connect to the Docker daemon at unix:///run/bbox-docker.sock. Is the docker daemon running?"
)

// windowsBox is the HP: the distro running, the checkout on C:, wsl-10g named in .env.
func windowsBox(t *testing.T) *rec {
	cmds := healthyHost(winVia, winIn)
	cmds["wsl.exe -l --running -q"] = ok(utf16("Ubuntu\r\n"))
	cmds["wsl.exe -d Ubuntu -e wslpath -a "+winRoot] = ok(winIn + "\n")
	return &rec{goos: "windows", root: winRoot, cmds: cmds, env: map[string]string{}, files: map[string]string{
		winRoot + `\.env`: "BUSINESS_NAME=x\r\nPERFORMANCE_PROFILE=wsl-10g\r\n",
		winRoot + `\platform\profiles\perf-profiles.yml`: repoFile(t, "platform/profiles/perf-profiles.yml"),
	}}
}

// The Mac's own answers: its default route, and a UDP socket the engine holds for the pair tunnel.
const (
	routeOut = "   route to: default\ndestination: default\n       mask: default\n    gateway: 192.168.1.1\n  interface: en0\n" +
		"      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING>\n"
	lsofOut = "COMMAND     PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n" +
		"limactl   41022    u   23u  IPv4 0x8f2e5a1c3b7d9e01      0t0  UDP *:51830\n"
	ssOut   = "UNCONN 0      0            0.0.0.0:51830      0.0.0.0:*\nUNCONN 0      0         127.0.0.53%lo:53         0.0.0.0:*\n"
	udpRule = "- guestPort: 51830\n  hostPort: 51830\n  hostIP: \"0.0.0.0\"\n  proto: udp\n"
)

// macBox is an 8 GB M-series Mac: the guest running with 4 cpus and 5 GiB, no .env yet, its
// instance created from the template (the pair tunnel's UDP rule declared), the guest listening on
// it and the Mac holding the socket, no Rosetta.
func macBox(t *testing.T) *rec {
	cmds := healthyHost(macVia, macRoot)
	cmds[macVia+" "+coresKey] = cores(4)
	cmds[macVia+" cat /proc/meminfo"] = ok(meminfo(4997132))
	cmds["sysctl -n hw.ncpu"] = ok("8\n")
	cmds["sysctl -n hw.memsize"] = ok("8589934592\n")
	cmds["sw_vers -productVersion"] = ok("15.3.1\n")
	cmds["uname -m"] = ok("arm64\n")
	cmds["test -f /Library/Apple/usr/share/rosetta/rosetta"] = no("")
	cmds["route -n get default"] = ok(routeOut)
	cmds["ipconfig getifaddr en0"] = ok("192.168.1.20\n")
	cmds["lsof -nP -iUDP:51830"] = ok(lsofOut)
	cmds[macCtl+" --version"] = ok("limactl version 2.2.0\n")
	cmds[macLima+" list --format {{.Name}} {{.Status}}"] = ok("bbox Running\n")
	cmds[macLima+" shell bbox -- ss -lunH"] = ok(ssOut)
	template := repoFile(t, "packaging/macos/engine.yaml")
	return &rec{goos: "darwin", root: macRoot, cmds: cmds, env: map[string]string{"HOME": "/Users/u"}, files: map[string]string{
		macRoot + "/packaging/macos/fetch-runtime.sh":    repoFile(t, "packaging/macos/fetch-runtime.sh"),
		macRoot + "/packaging/macos/engine.yaml":         template,
		"/Users/u/.bbox/macos/lima/bbox/lima.yaml":       template,
		macRoot + "/scripts/ci-env.sh":                   repoFile(t, "scripts/ci-env.sh"),
		macRoot + "/platform/profiles/perf-profiles.yml": repoFile(t, "platform/profiles/perf-profiles.yml"),
	}}
}

// linuxBox is the production VPS: 8 cores, 15.6 GiB, systemd, prod named in .env.
func linuxBox(t *testing.T) *rec {
	cmds := healthyHost("", linRoot)
	cmds[coresKey] = cores(8)
	return &rec{goos: "linux", root: linRoot, cmds: cmds, env: map[string]string{}, files: map[string]string{
		"/proc/meminfo":                                  meminfo(16365248),
		linRoot + "/.env":                                "PERFORMANCE_PROFILE=prod\n",
		linRoot + "/scripts/ci-env.sh":                   repoFile(t, "scripts/ci-env.sh"),
		linRoot + "/platform/profiles/perf-profiles.yml": repoFile(t, "platform/profiles/perf-profiles.yml"),
	}}
}

// sandboxBox is the cloud sandbox before its first run: no systemd, a proxy CA, no .env, nothing
// answering yet (bbox run starts dockerd itself), 8 cores and 15.6 GiB.
func sandboxBox(t *testing.T) *rec {
	r := linuxBox(t)
	r.cmds["sh -c for c do command -v $c || :; done sh docker dockerd systemctl"] = ok("/usr/bin/docker\n/usr/bin/dockerd\n")
	r.cmds["test -f /root/.ccr/ca-bundle.crt"] = ok("")
	r.cmds["stat -L -c %F /run/bbox-docker.sock"] = no("")
	for _, ep := range []string{"unix:///run/bbox-docker.sock", "unix:///var/run/docker.sock", "unix:///run/docker.sock"} {
		r.cmds["docker -H "+ep+" info --format {{.OperatingSystem}}"] = no("connect: no such file or directory")
	}
	delete(r.files, linRoot+"/.env")
	return r
}

// line is a doctor line as it is printed.
func line(state, name, said string) string { return fmt.Sprintf("  %-4s  %-8s  %s", state, name, said) }

func has(t *testing.T, out string, frags ...string) {
	t.Helper()
	for _, f := range frags {
		if !strings.Contains(out, f) {
			t.Errorf("missing %q in:\n%s", f, out)
		}
	}
}

func hasNot(t *testing.T, out string, frags ...string) {
	t.Helper()
	for _, f := range frags {
		if strings.Contains(out, f) {
			t.Errorf("unexpected %q in:\n%s", f, out)
		}
	}
}

// ── the doctor ────────────────────────────────────────────────────────────────────────────────────

func TestDoctorOnAHealthyEngineOfEachSystem(t *testing.T) {
	cases := []struct {
		box  *rec
		want []string
	}{
		{windowsBox(t), []string{
			"dgo engine doctor · windows · the WSL distro Ubuntu with the project's own Docker CE — never Docker Desktop\n",
			line(pass, "wsl", "the distro Ubuntu is running"),
			line(pass, "checkout", `C:\Users\u\MyDGO is visible inside the distro at /mnt/c/Users/u/MyDGO`),
			line(pass, "engine", "DOCKER_HOST=unix:///run/bbox-docker.sock — the engine bbox selects (Ubuntu 22.04.3 LTS)"),
			line(pass, "docker", "Docker 28.5.2 (API 1.51, min 1.24) — "+why28),
			line(pass, "socket", "/run/bbox-docker.sock — the project engine's own address, which Docker Desktop never binds"),
			line(pass, "compose", "/usr/libexec/docker/cli-plugins/docker-compose"),
			line(note, "profile", "wsl-10g (set in .env) · 6 cores, 9.7 GiB in the distro\n"),
			"\nhealthy\n",
		}},
		{macBox(t), []string{
			"dgo engine doctor · darwin · the Lima/vz guest under ~/.bbox/macos with Docker 28 pinned — never Docker Desktop\n",
			line(note, "mac", "macOS 15.3.1 arm64 · 8 cores · 8 GiB\n"),
			line(pass, "lima", macCtl+" (limactl version 2.2.0) · LIMA_HOME=/Users/u/.bbox/macos/lima\n"),
			line(note, "template", "/Users/u/MyDGO/packaging/macos/engine.yaml\n"),
			line(note, "sizing", "cpus=4 mem=5GiB disk=60GiB (BBOX_VM_CPUS/BBOX_VM_MEM/BBOX_VM_DISK override)"),
			line(note, "rosetta", "absent — only arm64 images will run (optional: softwareupdate --install-rosetta)\n"),
			line(pass, "guest", "the guest bbox is Running\n"),
			line(note, "macsock", "/Users/u/.bbox/macos/lima/bbox/sock/docker.sock — the engine's docker socket on this Mac"),
			line(note, "lan", "192.168.1.20\n"),
			line(note, "udp", "51830/udp from 0.0.0.0 — instance: declared · guest listening: yes · Mac socket: yes\n"),
			line(note, "handoff", "BBOX_HOST_LAN_ADDR=192.168.1.20 BBOX_HOST_UDP_PORT=51830 → hooks/prepare declares this office dialable\n"),
			line(pass, "checkout", "/Users/u/MyDGO is visible inside the guest at the same path"),
			line(pass, "docker", "Docker 28.5.2 (API 1.51, min 1.24)"),
			// no .env in the guest: bbox run's first step is scripts/ci-env.sh, which writes the floor
			line(note, "profile", "ci-small (written to .env by scripts/ci-env.sh, which bbox run runs first here) · 4 cores, 4.8 GiB in the guest\n"),
			"\nhealthy\n",
		}},
		{linuxBox(t), []string{
			"dgo engine doctor · linux · the systemd docker service\n",
			line(pass, "engine", "DOCKER_HOST=unix:///run/bbox-docker.sock"),
			line(pass, "docker", "Docker 28.5.2 (API 1.51, min 1.24)"),
			line(note, "profile", "prod (set in .env) · 8 cores, 15.6 GiB in this machine\n"),
			"\nhealthy\n",
		}},
	}
	for _, c := range cases {
		out, code := c.box.answer(t, "doctor")
		if code != 0 {
			t.Errorf("%s: exit %d, want 0:\n%s", c.box.goos, code, out)
		}
		has(t, out, c.want...)
		hasNot(t, out, "FAIL")
		t.Logf("\n%s", out)
	}
}

// broken is one way an engine fails, applied to a box, and what the doctor must say.
type broken struct {
	name   string
	box    func(*testing.T) *rec
	mutate func(*rec)
	want   []string
}

const wslFix = "fix: Is WSL installed and the distro present?  Check: wsl -l -v"

// brokenCases is every way the doctor is shown to fail — read by the doctor's test, the read-only
// check and the quotations' corpus alike.
func brokenCases() []broken {
	verFmt := " version --format {{.Server.Version}} {{.Server.APIVersion}} {{.Server.MinAPIVersion}}"
	return []broken{
		{"windows: Docker 29", windowsBox, func(r *rec) {
			r.cmds[winVia+" docker -H unix:///run/bbox-docker.sock"+verFmt] = ok("29.1.3 1.52 1.44\n")
		}, []string{
			line(fail, "docker", "Docker 29.1.3 (API 1.52, min 1.44) — "+why28),
			"fix: Docker 29.1.3 is installed; this platform needs Docker 28.x. Re-run with BBOX_REPLACE_DOCKER=1 to replace it (containers stop; volumes are kept): " +
				`wsl -d Ubuntu -u root -- bash -lc "cd '/mnt/c/Users/u/MyDGO' && BBOX_REPLACE_DOCKER=1 ./bbox install windows"`,
		}},
		{"windows: engine down, the drop-in already there", windowsBox, func(r *rec) {
			r.cmds[winVia+" stat -L -c %F /run/bbox-docker.sock"] = no("stat: cannot statx '/run/bbox-docker.sock': No such file or directory")
			for _, ep := range []string{"unix:///run/bbox-docker.sock", "unix:///var/run/docker.sock", "unix:///run/docker.sock"} {
				r.cmds[winVia+" docker -H "+ep+" info --format {{.OperatingSystem}}"] = no(dead)
			}
			r.cmds[winVia+" cat "+dropInConf] = ok(dropIn("/run/bbox-docker.sock") + "\n")
		}, []string{
			line(fail, "engine", "nothing of ours answers: unix:///run/bbox-docker.sock (Cannot connect to the Docker daemon"),
			"fix: " + notReachable("/run/bbox-docker.sock"), // the drop-in is in place: bbox restarts nothing, and refuses
		}},
		{"windows: only Docker Desktop answers", windowsBox, func(r *rec) {
			r.cmds[winVia+" docker -H unix:///run/bbox-docker.sock info --format {{.OperatingSystem}}"] = no(dead)
			r.cmds[winVia+" docker -H unix:///var/run/docker.sock info --format {{.OperatingSystem}}"] = ok("Docker Desktop\n")
			r.cmds[winVia+" docker -H unix:///run/docker.sock info --format {{.OperatingSystem}}"] = no(dead)
		}, []string{"unix:///var/run/docker.sock (Docker Desktop's — never used)", "fix: " + notReachable("/run/bbox-docker.sock")}},
		{"windows: distro missing", windowsBox, func(r *rec) {
			r.cmds["wsl.exe -l --running -q"] = ok(utf16("docker-desktop\r\n"))
			r.cmds["wsl.exe -l -q"] = ok(utf16("docker-desktop\r\n"))
		}, []string{line(fail, "wsl", "there is no WSL distro named Ubuntu"), wslFix}},
		{"windows: distro stopped", windowsBox, func(r *rec) {
			r.cmds["wsl.exe -l --running -q"] = ok("")
			r.cmds["wsl.exe -l -q"] = ok(utf16("Ubuntu\r\ndocker-desktop\r\n"))
		}, []string{line(fail, "wsl", "the distro Ubuntu is stopped — a doctor does not start it"), "fix: bbox.cmd run"}},
		{"windows: WSL does not answer", windowsBox, func(r *rec) {
			r.cmds["wsl.exe -l --running -q"] = reply{out: utf16("Error code: Wsl/Service/0x8007274c\r\n"), err: errors.New("exit status 1")}
		}, []string{line(fail, "wsl", "WSL did not answer (Wsl/Service/0x8007274c): unknown, not missing"), "retry"}},
		{"windows: our own deadline", windowsBox, func(r *rec) {
			r.cmds["wsl.exe -l --running -q"] = reply{err: errTimeout}
		}, []string{"WSL did not answer"}},
		{"windows: no wsl.exe", windowsBox, func(r *rec) {
			r.cmds["wsl.exe -l --running -q"] = reply{err: fmt.Errorf("%w: ", &exec.Error{Name: "wsl.exe", Err: exec.ErrNotFound})}
		}, []string{line(fail, "wsl", "no wsl.exe on this machine"), wslFix}},
		{"windows: the checkout does not resolve", windowsBox, func(r *rec) {
			r.cmds["wsl.exe -d Ubuntu -e wslpath -a "+winRoot] = no("wslpath: " + winRoot + ": Invalid argument")
		}, []string{line(fail, "checkout", "could not resolve this directory inside the WSL distro 'Ubuntu'"), wslFix}},
		{"windows: C: not mounted in the distro", windowsBox, func(r *rec) {
			r.cmds[winVia+" test -f "+winIn+"/bbox"] = no("")
		}, []string{line(fail, "checkout", winIn+" is not visible inside the distro")}},
		{"darwin: guest stopped", macBox, func(r *rec) {
			r.cmds[macLima+" list --format {{.Name}} {{.Status}}"] = ok("bbox Stopped\n")
		}, []string{line(fail, "guest", "the guest bbox is Stopped — a doctor does not boot it"), "fix: ./bbox engine start — boot the engine"}},
		{"darwin: guest not created", macBox, func(r *rec) {
			r.cmds[macLima+" list --format {{.Name}} {{.Status}}"] = ok("")
		}, []string{line(fail, "guest", "the guest bbox is not created")}},
		{"darwin: runtime not landed", macBox, func(r *rec) {
			r.cmds[macCtl+" --version"] = no("fork/exec " + macCtl + ": no such file or directory")
		}, []string{line(fail, "lima", "Lima 2.2.0 has not landed at "+macCtl), "fix: ./bbox engine start"}},
		{"darwin: checkout outside $HOME", macBox, func(r *rec) {
			r.root = "/Volumes/work/MyDGO"
			r.files["/Volumes/work/MyDGO/packaging/macos/fetch-runtime.sh"] = r.files[macRoot+"/packaging/macos/fetch-runtime.sh"]
		}, []string{line(fail, "checkout", "/Volumes/work/MyDGO is outside /Users/u, and the guest mounts only $HOME"),
			"fix: the repo must live under /Users/u to be visible in the guest (it is at /Volumes/work/MyDGO)"}},
		{"darwin: Docker 29 in the guest", macBox, func(r *rec) {
			r.cmds[macVia+" docker -H unix:///run/bbox-docker.sock"+verFmt] = ok("29.0.1 1.52 1.44\n")
		}, []string{line(fail, "docker", "Docker 29.0.1 (API 1.52, min 1.44)"), "fix: engine is 29.0.1, expected 28.x — packaging/macos/engine.yaml pins 28.5.2"}},
		{"linux: engine down and no dockerd", linuxBox, func(r *rec) {
			r.cmds["sh -c for c do command -v $c || :; done sh docker dockerd systemctl"] = ok("/usr/bin/docker\n/usr/bin/systemctl\n")
			r.cmds["stat -L -c %F /run/bbox-docker.sock"] = no("")
			for _, ep := range []string{"unix:///run/bbox-docker.sock", "unix:///var/run/docker.sock", "unix:///run/docker.sock"} {
				r.cmds["docker -H "+ep+" info --format {{.OperatingSystem}}"] = no(dead)
			}
		}, []string{line(fail, "engine", "nothing of ours answers"), "fix: " + notReachable("/run/bbox-docker.sock")}},
		{"linux: engine down, bbox would write the drop-in and restart docker", linuxBox, func(r *rec) {
			r.cmds["stat -L -c %F /run/bbox-docker.sock"] = no("")
			for _, ep := range []string{"unix:///run/bbox-docker.sock", "unix:///var/run/docker.sock", "unix:///run/docker.sock"} {
				r.cmds["docker -H "+ep+" info --format {{.OperatingSystem}}"] = no(dead)
			}
		}, []string{line(fail, "engine", "nothing of ours answers"),
			"fix: bbox run starts it — it writes the drop-in and restarts docker.service, as root or with passwordless sudo (dgo engine plan)"}},
		{"linux: the sandbox before its first run", sandboxBox, func(*rec) {},
			[]string{line(fail, "engine", "nothing of ours answers"), "fix: bbox run starts it — dockerd on /run/bbox-docker.sock, as root or with passwordless sudo (dgo engine plan)"}},
		{"linux: no docker CLI", linuxBox, func(r *rec) {
			r.cmds["sh -c for c do command -v $c || :; done sh docker dockerd systemctl"] = ok("/usr/bin/systemctl\n")
		}, []string{line(fail, "docker", "no docker CLI on the PATH of this machine"), "fix: docker not found — run: bbox install <debian|windows>"}},
		{"linux: Docker 29", linuxBox, func(r *rec) {
			r.cmds["docker -H unix:///run/bbox-docker.sock"+verFmt] = ok("29.1.3 1.52 1.44\n")
		}, []string{line(fail, "docker", "Docker 29.1.3 (API 1.52, min 1.44)"), "Re-run with BBOX_REPLACE_DOCKER=1 to replace it (containers stop; volumes are kept): BBOX_REPLACE_DOCKER=1 ./bbox install debian"}},
		{"linux: no compose plugin", linuxBox, func(r *rec) {
			r.cmds["test -x /usr/libexec/docker/cli-plugins/docker-compose"] = no("")
		}, []string{line(fail, "compose", "no compose plugin at /usr/libexec/docker/cli-plugins/docker-compose"),
			"fix: compose plugin missing at /usr/libexec/docker/cli-plugins/docker-compose — run: bbox install debian (installs docker-compose-plugin)"}},
		{"linux: a tcp engine and the socket path a directory", linuxBox, func(r *rec) {
			r.env["BBOX_DOCKER_HOST"] = "tcp://10.0.0.5:2375"
			r.cmds["stat -L -c %F /run/bbox-docker.sock"] = ok("directory\n")
			r.cmds["docker -H tcp://10.0.0.5:2375"+verFmt] = ok("28.5.2 1.51 1.24\n")
		}, []string{
			line(pass, "engine", "DOCKER_HOST=tcp://10.0.0.5:2375 — the engine bbox selects (BBOX_DOCKER_HOST, taken as given)"),
			line(fail, "socket", "BBOX_DOCKER_SOCK=/run/bbox-docker.sock is a DIRECTORY, not a socket"),
			"fix: Remove it (sudo rmdir '/run/bbox-docker.sock') and re-run",
		}},
		{"linux: a tcp engine and no socket yet: bbox provisions it", linuxBox, func(r *rec) {
			r.env["BBOX_DOCKER_HOST"] = "tcp://10.0.0.5:2375"
			r.cmds["stat -L -c %F /run/bbox-docker.sock"] = no("")
			r.cmds["docker -H tcp://10.0.0.5:2375"+verFmt] = ok("28.5.2 1.51 1.24\n")
		}, []string{
			line(fail, "socket", "BBOX_DOCKER_SOCK=/run/bbox-docker.sock is not a socket (missing)"),
			"fix: bbox run provisions it before anything mounts it (ensure_project_engine), as root or with passwordless sudo (dgo engine plan)",
		}},
		{"linux: a tcp engine, no socket and no dockerd to provision one", linuxBox, func(r *rec) {
			r.env["BBOX_DOCKER_HOST"] = "tcp://10.0.0.5:2375"
			r.cmds["sh -c for c do command -v $c || :; done sh docker dockerd systemctl"] = ok("/usr/bin/docker\n/usr/bin/systemctl\n")
			r.cmds["stat -L -c %F /run/bbox-docker.sock"] = no("")
			r.cmds["docker -H tcp://10.0.0.5:2375"+verFmt] = ok("28.5.2 1.51 1.24\n")
		}, []string{
			line(fail, "socket", "BBOX_DOCKER_SOCK=/run/bbox-docker.sock is not a socket (missing)"),
			"fix: BBOX_DOCKER_SOCK=/run/bbox-docker.sock does not exist. The engine in use is $DOCKER_HOST=tcp://10.0.0.5:2375; containers cannot be handed a socket that is not there.",
		}},
		{"linux: no selector answer and nothing in .env", linuxBox, func(r *rec) {
			delete(r.files, "/proc/meminfo")
			delete(r.files, linRoot+"/.env")
		}, []string{line(fail, "profile", "no answer (select-profile: could not read machine memory) and .env names no PERFORMANCE_PROFILE — bbox run stops in ensure_perf_profile"),
			"fix: PERFORMANCE_PROFILE=ci-small in .env — the floor bbox means to fall back to (\"profile selector unavailable — falling back to the floor profile (ci-small).\")"}},
	}
}

func TestDoctorNamesEachBrokenFactWithBboxsOwnFix(t *testing.T) {
	for _, c := range brokenCases() {
		box := c.box(t)
		c.mutate(box)
		out, code := box.answer(t, "doctor")
		if code != 1 {
			t.Errorf("%s: exit %d, want 1:\n%s", c.name, code, out)
		}
		has(t, out, c.want...)
		if !strings.HasSuffix(out, "not healthy: 1 failed\n") {
			t.Errorf("%s: one fact broke, so one fails:\n%s", c.name, out)
		}
	}
}

// A fresh Debian or WSL host — docker.service answering on /var/run/docker.sock, no drop-in yet — is
// where lib.sh's pick at load decides it all: BBOX_DOCKER_SOCK is that socket, so need_docker never
// provisions the project socket. Said as that, not failed; and a profile .env names that this machine
// would not get is bbox's one-line note, not a failure.
func TestTheEnginePickedWhenLibShLoadsIsWhatNeedDockerSees(t *testing.T) {
	box := linuxBox(t)
	box.cmds["stat -L -c %F /run/bbox-docker.sock"] = no("")
	box.cmds["docker -H unix:///run/bbox-docker.sock info --format {{.OperatingSystem}}"] = no("connect: no such file or directory")
	box.cmds["docker -H unix:///var/run/docker.sock info --format {{.OperatingSystem}}"] = ok("Debian GNU/Linux 12 (bookworm)\n")
	box.cmds["docker -H unix:///var/run/docker.sock version --format {{.Server.Version}} {{.Server.APIVersion}} {{.Server.MinAPIVersion}}"] = ok("28.5.2 1.51 1.24\n")
	box.files[linRoot+"/.env"] = "PERFORMANCE_PROFILE='vps' \n"
	out, code := box.answer(t, "doctor")
	if code != 0 {
		t.Fatalf("exit %d:\n%s", code, out)
	}
	has(t, out,
		line(pass, "socket", "/var/run/docker.sock — lib.sh picks it when bbox loads, so the project socket /run/bbox-docker.sock (missing) is not provisioned while this one answers"),
		line(note, "profile", "vps (set in .env) · 8 cores, 15.6 GiB in this machine · profile: vps (set in .env) — this machine (8 cores) would be sized prod; PERFORMANCE_PROFILE=prod in .env adopts it"))
	hasNot(t, out, "provisions it")
	plan, _ := box.answer(t, "plan")
	has(t, plan, "— here: nothing to do — lib.sh picked unix:///var/run/docker.sock when bbox loaded, so BBOX_DOCKER_SOCK is /var/run/docker.sock, a socket",
		"— here: skipped, lib.sh picked unix:///var/run/docker.sock")
	hasNot(t, plan, "so it runs", "it runs:")

	// BBOX_DOCKER_HOST naming a unix path that is not a socket yet: THAT path is what bbox provisions
	box = linuxBox(t)
	box.env["BBOX_DOCKER_HOST"] = "unix:///srv/engine.sock"
	box.cmds["stat -L -c %F /srv/engine.sock"] = no("")
	box.cmds["docker -H unix:///srv/engine.sock version --format {{.Server.Version}} {{.Server.APIVersion}} {{.Server.MinAPIVersion}}"] = no("connect: no such file or directory")
	out, _ = box.answer(t, "doctor")
	plan, _ = box.answer(t, "plan")
	has(t, plan, "the project socket /srv/engine.sock (ensure_project_engine)", "— here: it runs: the drop-in is written and docker.service restarted",
		"'ExecStart=/usr/bin/dockerd -H fd:// -H unix:///srv/engine.sock --containerd=/run/containerd/containerd.sock'")
}

// What the doctor gives as the fix when nothing answers is what `bbox run` does about it: it starts
// dockerd itself without systemd, it restarts docker.service when the drop-in has to be written —
// and only when neither happens is the fix need_docker's own refusal.
func TestEngineDownIsFixedByWhatBboxRunDoes(t *testing.T) {
	for _, c := range brokenCases() {
		if !strings.HasPrefix(c.name, "linux: engine down") && !strings.HasPrefix(c.name, "linux: the sandbox") && !strings.HasPrefix(c.name, "windows: engine down") {
			continue
		}
		box := c.box(t)
		c.mutate(box)
		plan, _ := box.answer(t, "plan")
		doctor, _ := box.answer(t, "doctor")
		starts := strings.Contains(plan, "— here: it runs, and bbox starts dockerd itself") || strings.Contains(plan, "— here: it runs: the drop-in is written")
		if starts != strings.Contains(doctor, "fix: bbox run starts it") {
			t.Errorf("%s: the plan and the doctor disagree on whether bbox run starts the engine:\n%s\n%s", c.name, doctor, plan)
		}
	}
}

// Where bbox run generates the .env first (the cloud sandbox, the macOS guest), ensure_perf_profile
// finds the profile scripts/ci-env.sh wrote — not the selector's answer, which it only says.
func TestTheGeneratedEnvNamesTheProfileBboxKeeps(t *testing.T) {
	box := sandboxBox(t)
	doctor, _ := box.answer(t, "doctor")
	plan, _ := box.answer(t, "plan")
	has(t, doctor, line(note, "profile", "ci-small (written to .env by scripts/ci-env.sh, which bbox run runs first here) · 8 cores, 15.6 GiB in this machine · "+
		"profile: ci-small (set in .env) — this machine (8 cores) would be sized prod; PERFORMANCE_PROFILE=prod in .env adopts it"))
	has(t, plan, "— here: PERFORMANCE_PROFILE=ci-small comes with the .env scripts/ci-env.sh writes, so it is kept")
	hasNot(t, plan, "printf '\\nPERFORMANCE_PROFILE=%s\\n'")

	// a real office's domain: ci-env.sh writes no profile, so the selector's answer is appended
	box = sandboxBox(t)
	box.env["OFFICE_DOMAIN"] = "office.example"
	plan, _ = box.answer(t, "plan")
	has(t, plan, "— here: prod is appended to .env", "printf '\\nPERFORMANCE_PROFILE=%s\\n' prod >> .env")

	// a VPS with no .env is no sandbox: nothing is generated, the selector's answer is appended
	box = linuxBox(t)
	delete(box.files, linRoot+"/.env")
	doctor, _ = box.answer(t, "doctor")
	has(t, doctor, line(note, "profile", "prod · 8 cores, 15.6 GiB in this machine · bbox run writes it to .env: no PERFORMANCE_PROFILE set — sizing to this host (8 cores → prod)"))
}

// select-profile.py counts the CPUs the process may run on; bbox's line says what nproc says, and
// nproc honours OMP_NUM_THREADS. The profile is the first's; the sentence keeps the second's number.
func TestCoresAreCountedTheWaySelectProfileCountsThem(t *testing.T) {
	box := linuxBox(t)
	delete(box.files, linRoot+"/.env")
	box.cmds[coresKey] = ok("2\n8\n") // OMP_NUM_THREADS=2 in the environment
	doctor, _ := box.answer(t, "doctor")
	has(t, doctor, line(note, "profile", "prod · 8 cores, 15.6 GiB in this machine · bbox run writes it to .env: no PERFORMANCE_PROFILE set — sizing to this host (2 cores → prod)"))
}

func TestTheCloudSandboxIsSaidAndAnUnknownSystemIsRefused(t *testing.T) {
	box := linuxBox(t)
	box.cmds["sh -c for c do command -v $c || :; done sh docker dockerd systemctl"] = ok("/usr/bin/docker\n/usr/bin/dockerd\n")
	box.cmds["test -f /root/.ccr/ca-bundle.crt"] = ok("")
	out, code := box.answer(t, "doctor")
	if code != 0 {
		t.Fatalf("exit %d:\n%s", code, out)
	}
	has(t, out, "· linux · a dockerd bbox starts itself — no systemd docker.service here (the cloud sandbox's case)\n",
		line(note, "sandbox", "a MITM egress proxy CA is here"))

	out, code = (&rec{goos: "freebsd", root: "/x"}).answer(t, "doctor")
	if code != 1 || !strings.Contains(out, "dgo knows no engine for freebsd") {
		t.Fatalf("exit %d:\n%s", code, out)
	}
}

// TestAnAndroidAppIsSentToThePhonesLinuxTerminal: dgo built for android/arm64 runs in an app's sandbox
// (Termux), where no container runs — so it says where the phone's office does run, and how (DGO-1069).
func TestAnAndroidAppIsSentToThePhonesLinuxTerminal(t *testing.T) {
	out, code := (&rec{goos: "android", root: "/x"}).answer(t, "doctor")
	if code != 1 || !strings.Contains(out, "· android · none for an Android app: the phone's office runs in its Linux terminal, a Debian VM") ||
		!strings.Contains(out, "Linux development environment") || !strings.Contains(out, "./bbox install debian") ||
		strings.Contains(out, "knows no engine") {
		t.Fatalf("exit %d:\n%s", code, out)
	}
}

// chainCases are the pair tunnel's links on a Mac, as engine.sh's forward_report says them.
func chainCases() []broken {
	return []broken{
		{"not published yet", macBox, func(r *rec) {
			r.cmds[macLima+" shell bbox -- ss -lunH"] = ok("UNCONN 0 0 127.0.0.53%lo:53 0.0.0.0:*\n")
			r.cmds["lsof -nP -iUDP:51830"] = no("")
		}, []string{line(note, "udp", "51830/udp from 0.0.0.0 — instance: declared · guest listening: no · Mac socket: no\n"),
			"                  the office has not published it yet: `bbox run` writes DGO_WG_PUBLISH_PORT / DGO_WG_PUBLISH_BIND=0.0.0.0 and dgo-net then listens."}},
		{"the guest listens, the Mac holds nothing", macBox, func(r *rec) {
			r.cmds["lsof -nP -iUDP:51830"] = ok("COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nlimactl 1 u 3u IPv4 0x1 0t0 UDP 127.0.0.1:51830\n")
		}, []string{"guest listening: yes · Mac socket: no\n",
			"fix: the guest listens and the Mac holds nothing — two candidates, in this order: 1. macOS incoming-connection consent denied"}},
		{"an engine older than the rule, no default route", macBox, func(r *rec) {
			r.files["/Users/u/.bbox/macos/lima/bbox/lima.yaml"] = strings.Replace(r.files[macRoot+"/packaging/macos/engine.yaml"], udpRule, "", 1)
			r.cmds["route -n get default"] = no("route: writing to routing socket: not in table")
		}, []string{line(note, "lan", "none — this Mac has no default route, so nothing on the network can dial it"),
			line(note, "udp", "none — this engine forwards TCP only, so the guest can only DIAL"),
			"fix: the template declares it; apply it to this instance: ./bbox engine forwards --apply",
			line(note, "handoff", "no handoff — hooks/prepare keeps DGO_WG_DIAL_ONLY=engine-guest")}},
	}
}

// The pair tunnel's chain on a Mac, link by link: what is "not yet" is said with the step that closes
// it, the one real fault with its two candidates, an engine older than the rule with the command that
// applies it. None fails the engine: it is the tunnel's.
func TestMacForwardChain(t *testing.T) {
	for _, c := range chainCases() {
		box := c.box(t)
		c.mutate(box)
		out, code := box.answer(t, "doctor")
		if code != 0 {
			t.Errorf("%s: the tunnel's chain is not the engine's health — exit %d:\n%s", c.name, code, out)
		}
		has(t, out, c.want...)
	}
}

// ── the plan ──────────────────────────────────────────────────────────────────────────────────────

func TestPlanOnWindowsIsBboxCmdThenNeedDockerInTheDistro(t *testing.T) {
	out, code := windowsBox(t).answer(t, "plan")
	if code != 0 {
		t.Fatalf("exit %d", code)
	}
	has(t, out,
		"dgo engine plan · windows · how `bbox run` provisions the WSL distro Ubuntu",
		` 1. bbox.cmd finds this checkout inside the distro`,
		`      wsl.exe -d Ubuntu -e wslpath -a "C:\Users\u\MyDGO"`,
		`      powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\u\MyDGO\scripts\windows\platform-keepalive.ps1" -Install`,
		`      powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\u\MyDGO\scripts\windows\firewall-converge.ps1"`,
		`      wsl.exe -d Ubuntu -u root -- bash -lc "cd '/mnt/c/Users/u/MyDGO' && ./bbox run"`,
		"bbox loads scripts/lib.sh, and lib.sh picks the engine right there", "— here: unix:///run/bbox-docker.sock",
		"— here: /usr/bin/docker",
		"— here: nothing to do, /run/bbox-docker.sock is a socket",
		"'ExecStart=/usr/bin/dockerd -H fd:// -H unix:///run/bbox-docker.sock --containerd=/run/containerd/containerd.sock' | tee /etc/systemd/system/docker.service.d/10-bbox-endpoint.conf",
		"      systemctl restart docker.service",
		"— here: PERFORMANCE_PROFILE=wsl-10g is in .env",
		"after the run, the firewall again")
	hasNot(t, out, "setsid", "printf '\\nPERFORMANCE_PROFILE")
	if strings.Count(out, "firewall-converge.ps1") != 2 {
		t.Errorf("bbox.cmd converges the firewall before and after the run:\n%s", out)
	}
	// bbox's order: the pick at load, need_docker, heavy_admit, the .env, render+network, the profile,
	// foreign_containers+prepare, then the ccr_* steps
	order := []string{"lib.sh picks the engine", "need_docker:", "the project socket", "heavy_admit", "no .env, on a cloud sandbox",
		"ensure_rendered", "size the stack", "foreign_containers", "ccr_clamp_nofile", "BBOX_ASSUME_DNS_OK", "CCR_BASES_READY", "docker compose up"}
	last := -1
	for _, o := range order {
		i := strings.Index(out, o)
		if i < last {
			t.Errorf("%q comes before what precedes it in bbox run", o)
		}
		last = i
	}
	t.Logf("\n%s", out)
}

func TestPlanOnMacOSFollowsTheGuestsState(t *testing.T) {
	const lima = "LIMA_HOME=/Users/u/.bbox/macos/lima " + macCtl // as a person types it
	out, _ := macBox(t).answer(t, "plan")
	has(t, out, "bash packaging/macos/engine.sh exec -- ./bbox run", "— here: it has landed", "the guest bbox — here: Running, nothing to start",
		lima+" shell --workdir /Users/u/MyDGO bbox -- sudo --preserve-env=OVERLAYS,BBOX_DOCKER_HOST,BBOX_WITH_BROWSER42,FORCE,PERFORMANCE_PROFILE"+
			" env BBOX_IN_GUEST=1 BBOX_HOST_LAN_ADDR=192.168.1.20 BBOX_HOST_UDP_PORT=51830 ./bbox run",
		"cd /Users/u/MyDGO && CI_DEPLOYMENT_NAME=local CI_EDGE_PORT=8080 bash scripts/ci-env.sh",
		"— here: PERFORMANCE_PROFILE=ci-small comes with the .env scripts/ci-env.sh writes, so it is kept", "post_run_udp_note")
	hasNot(t, out, " start --name=")

	box := macBox(t)
	box.cmds[macLima+" list --format {{.Name}} {{.Status}}"] = ok("")
	box.cmds["test -f /Library/Apple/usr/share/rosetta/rosetta"] = ok("")
	box.cmds["arch -x86_64 /usr/bin/true"] = ok("")
	delete(box.files, "/Users/u/.bbox/macos/lima/bbox/lima.yaml") // a guest not created has no instance file
	out, _ = box.answer(t, "plan")
	has(t, out, "create the guest bbox — here: it does not exist",
		lima+" start --name=bbox --tty=false --cpus=4 --memory=5 --disk=60 --mount=/Users/u:w '--set=.vmOpts.vz.rosetta.enabled=true | .vmOpts.vz.rosetta.binfmt=true' /Users/u/MyDGO/packaging/macos/engine.yaml",
		lima+" shell bbox sudo docker version --format '{{.Server.Version}}'",
		" env BBOX_IN_GUEST=1 ./bbox run") // nothing forwarded yet, so nothing handed over
	hasNot(t, out, "— here: /usr/bin/docker") // the guest was not asked: every branch, with its condition

	box = macBox(t)
	box.cmds[macLima+" list --format {{.Name}} {{.Status}}"] = ok("bbox Stopped\n")
	out, _ = box.answer(t, "plan")
	has(t, out, "start the guest bbox — here: Stopped", lima+" start --tty=false bbox")
}

func TestPlanOnTheCloudSandboxStartsDockerdAndGeneratesTheEnv(t *testing.T) {
	out, _ := sandboxBox(t).answer(t, "plan")
	has(t, out, "— here: none answers yet", "— here: it runs, and bbox starts dockerd itself",
		// the sandbox pulls Docker Hub through mirror.gcr.io, as bbox's need_docker does there (d5d803b6)
		"\"no docker daemon — starting dockerd on /run/bbox-docker.sock (DOCKER_MIN_API_VERSION=1.24, mirror https://mirror.gcr.io)…\"",
		"setsid env DOCKER_MIN_API_VERSION=1.24 dockerd -H unix:///run/bbox-docker.sock -H unix:///var/run/docker.sock --registry-mirror https://mirror.gcr.io >\"$BBOX_TMP/dockerd.log\" 2>&1 </dev/null &",
		"— here: nothing answers now, so bbox run takes this way",
		"a secretless one is generated, and bbox run starts over — here: it runs", "cd /srv/office && bash scripts/ci-env.sh",
		"(ccr_build_serial) — here: it runs", "then the stack itself, which is not the engine's")
	hasNot(t, out, "systemctl daemon-reload")
}

// ── what the look asks ────────────────────────────────────────────────────────────────────────────

// readOnly is every question the look may ask a machine. Anything that writes, starts or stops is
// not on it, and a test that records one fails here — "read-only" is checked, not promised.
var readOnly = []string{
	"wsl.exe -l --running -q", "wsl.exe -l -q", "wsl.exe -d Ubuntu -e wslpath -a ",
	"sysctl -n hw.", macCtl + " --version", macLima + " list --format {{.Name}} {{.Status}}",
	"sw_vers -productVersion", "uname -m", "arch -x86_64 /usr/bin/true", "route -n get default", "ipconfig getifaddr ",
	"lsof -nP -iUDP:", macLima + " shell bbox -- ss -lunH",
	"sh -c for c do command -v $c || :; done sh ", "systemctl cat docker.service",
	"test -f ", "test -x ", "stat -L -c %F ", "cat /proc/meminfo", "cat " + dropInConf, coresKey,
}

// TestTheLookOnlyReads asks every recorded machine — healthy, broken, the tunnel's states — both
// verbs, and checks every command asked against readOnly.
func TestTheLookOnlyReads(t *testing.T) {
	cases := append(append(brokenCases(), chainCases()...),
		broken{"windows", windowsBox, func(*rec) {}, nil}, broken{"darwin", macBox, func(*rec) {}, nil}, broken{"linux", linuxBox, func(*rec) {}, nil})
	for _, c := range cases {
		for _, verb := range []string{"doctor", "plan"} {
			box := c.box(t)
			c.mutate(box)
			box.answer(t, verb)
			for _, a := range box.asked {
				cmd := strings.TrimPrefix(strings.TrimPrefix(a, winVia+" "), macVia+" ")
				allowed := strings.HasPrefix(cmd, "docker -H ") &&
					(strings.HasSuffix(cmd, " info --format {{.OperatingSystem}}") || strings.HasSuffix(cmd, " version --format {{.Server.Version}} {{.Server.APIVersion}} {{.Server.MinAPIVersion}}"))
				for _, r := range readOnly {
					allowed = allowed || strings.HasPrefix(cmd, r)
				}
				if !allowed {
					t.Errorf("%s, %s: asked something that is not a read: %s", c.name, verb, a)
				}
			}
		}
	}
}

func TestWslOutputIsReadInEitherEncoding(t *testing.T) {
	if got := lines(clean(utf16("Ubuntu\r\ndocker-desktop\r\n"))); strings.Join(got, ",") != "Ubuntu,docker-desktop" {
		t.Fatalf("UTF-16: %q", got)
	}
	if got := clean("/mnt/c/Users/u/הלשכה\n"); got != "/mnt/c/Users/u/הלשכה\n" {
		t.Fatalf("UTF-8 must pass untouched: %q", got)
	}
}

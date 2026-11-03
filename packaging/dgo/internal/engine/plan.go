package engine

import (
	"fmt"
	"io"
	"path"
	"strings"
)

// writePlan prints — never runs — what `bbox run` does to provision the engine on this system, in
// its order: the hand-off into the engine host (bbox.cmd → WSL, engine.sh → Lima), need_docker
// there, then the adaptations bbox makes to that host before the stack itself comes up. Where the
// look could tell whether a branch applies, the step says so ("here: …"); where it could not, every
// branch is printed with its condition. TestPlanQuotesBbox holds each command to the bash it copies.
func writePlan(w io.Writer, m *machine) {
	fmt.Fprintf(w, "dgo engine plan · %s · how `bbox run` provisions %s — printed, never run\n", m.goos, m.kind)
	p := &planner{w: w}
	switch m.goos {
	case "windows":
		m.planWindows(p)
	case "darwin":
		m.planMac(p)
	case "linux":
		m.planInside(p, m.root)
	case "android":
		fmt.Fprintln(w, OnAndroid)
	}
}

// planner numbers the steps: why each runs, then its exact commands.
type planner struct {
	w io.Writer
	n int
}

func (p *planner) step(why string, cmds ...string) {
	p.n++
	fmt.Fprintf(p.w, "%2d. %s\n", p.n, why)
	p.cmds(cmds...)
}

func (p *planner) sub(why string, cmds ...string) {
	fmt.Fprintf(p.w, "    %s\n", why)
	p.cmds(cmds...)
}

func (p *planner) cmds(cmds ...string) {
	for _, c := range cmds {
		fmt.Fprintf(p.w, "      %s\n", c)
	}
}

// here is what the look found about a branch; nothing when the engine host could not be asked.
func (m *machine) here(yes bool, ifYes, ifNo string) string {
	switch {
	case !m.asked:
		return ""
	case yes:
		return " — here: " + ifYes
	}
	return " — here: " + ifNo
}

// planWindows is bbox.cmd: the checkout found in the distro, the two Windows objects the distro
// cannot reach (the keepalive task, the firewall), and the hand-off.
func (m *machine) planWindows(p *planner) {
	ps := func(script string, args ...string) string {
		return strings.TrimSpace(`powershell -NoProfile -ExecutionPolicy Bypass -File "` +
			join("windows", m.root, "scripts", "windows", script) + `" ` + strings.Join(args, " "))
	}
	in := or(m.inHost, "<this checkout, as wslpath -a gives it>")
	p.step("bbox.cmd finds this checkout inside the distro — no distro, no run: \"could not resolve this directory inside the WSL distro '"+distro+"'\"",
		`wsl.exe -d `+distro+` -e wslpath -a "`+m.root+`"`)
	p.step("reboot survival: a Task Scheduler task starts the distro at boot (WSL is on-demand); it never fails the run",
		ps("platform-keepalive.ps1", "-Install"))
	p.step("the Windows firewall, converged onto the tunnel's UDP port .env declares (it asks consent once, only when a rule must change)",
		ps("firewall-converge.ps1"))
	p.step("the hand-off: everything below runs inside the distro, as root, on this same checkout",
		`wsl.exe -d `+distro+` -u root -- bash -lc "cd '`+in+`' && ./bbox run"`)
	m.planInside(p, in)
	p.step("after the run, the firewall again: a fresh office declares its tunnel port during its first run",
		ps("firewall-converge.ps1"))
}

// planMac is engine.sh exec: the pinned runtime, the guest created or started, the power agent, and
// the hand-off.
func (m *machine) planMac(p *planner) {
	lima := "LIMA_HOME=" + m.limaHome + " " + m.limactl
	rosetta, handoff := "", ""
	if m.rosetta {
		rosetta = " '--set=.vmOpts.vz.rosetta.enabled=true | .vmOpts.vz.rosetta.binfmt=true'"
	}
	if m.handoff != "" {
		handoff = m.handoff + " "
	}
	create := lima + " start --name=" + m.inst + " --tty=false --cpus=" + m.cpus + " --memory=" + m.mem + " --disk=" + m.disk +
		" --mount=" + m.home + ":w" + rosetta + " " + m.root + "/packaging/macos/engine.yaml"
	start := lima + " start --tty=false " + m.inst
	landed := ""
	if m.limaOK {
		landed = " — here: it has landed"
	}
	p.step("bbox hands every verb but `engine` to the guest: one checkout, one engine, never Docker Desktop",
		"bash packaging/macos/engine.sh exec -- ./bbox run")
	p.step("the runtime: Lima, pinned and sha256-verified, under ~/.bbox/macos — downloaded only when it is missing"+landed,
		"bash packaging/macos/fetch-runtime.sh")
	switch {
	case !m.limaOK:
		p.step("the guest "+m.inst+": created when it does not exist (Ubuntu 24.04 + Docker CE 28.5.2 pinned by engine.yaml; the checkout must be under $HOME), started when it is stopped", create, start)
	case m.state == "":
		p.step("create the guest "+m.inst+" — here: it does not exist (Ubuntu 24.04 + Docker CE 28.5.2 pinned by engine.yaml; the checkout must be under $HOME)", create)
	case m.state != "Running":
		p.step("start the guest "+m.inst+" — here: "+m.state, start)
	default:
		p.step("the guest " + m.inst + " — here: Running, nothing to start")
	}
	if m.state != "Running" {
		p.step("prove dockerd answers inside it, else: engine is up but dockerd does not answer inside it",
			lima+" shell "+m.inst+" sudo docker version --format '{{.Server.Version}}'")
	}
	p.step("the power agent keeps the Mac awake by the console's policy, tied to the guest's host agent (none with BBOX_POWER_AGENT=0)",
		"nohup /usr/bin/python3 "+m.root+"/packaging/macos/power-agent.py --repo "+m.root+" --watch-pid <the guest's ha.pid> &")
	p.step("the hand-off: everything below runs inside the guest, as root, at the same path (the Mac's LAN address and UDP port go along only when this engine forwards one)",
		lima+" shell --workdir "+m.root+" "+m.inst+" -- sudo --preserve-env=OVERLAYS,BBOX_DOCKER_HOST,BBOX_WITH_BROWSER42,FORCE,PERFORMANCE_PROFILE env BBOX_IN_GUEST=1 "+handoff+"./bbox run")
	m.planInside(p, m.root)
	p.step("after the run, one look at the pair tunnel's UDP forward (post_run_udp_note) — said only when .env publishes a port the Mac holds no socket for")
}

// planInside is `bbox run` inside the engine host, in bbox's order: lib.sh's pick when bbox loads,
// need_docker, then what bbox adapts on that host — the .env a sandbox or the macOS guest generates,
// the profile, the ccr_* steps — with the stack's own steps named where they fall between them.
func (m *machine) planInside(p *planner, root string) {
	sock := or(m.sock, projectSock)
	at := or(m.sockAt, sock)
	var probes []string
	for _, ep := range []string{"unix://" + sock, `"$DOCKER_HOST"`, "unix:///var/run/docker.sock", "unix:///run/docker.sock"} {
		probes = append(probes, "docker -H "+ep+" info --format '{{.OperatingSystem}}'")
	}
	probes[1] += "   (only when DOCKER_HOST is set)"
	p.step("bbox loads scripts/lib.sh, and lib.sh picks the engine right there (bbox_select_engine): BBOX_DOCKER_HOST as given, else the first of these "+
		"that answers and is not Docker Desktop — exported as DOCKER_HOST, and a unix one as BBOX_DOCKER_SOCK too"+
		m.here(m.dockerHost != "", m.dockerHost, "none answers yet"), probes...)
	p.step("need_docker: the docker CLI on PATH, else: docker not found — run: bbox install <debian|windows>"+
		m.here(m.have["docker"] != "", m.have["docker"], "missing — bbox run stops here"), "command -v docker")
	var here string
	switch {
	case !m.asked:
	case m.have["docker"] == "":
		here = " — here: not reached, bbox run stops at the docker CLI"
	case m.sockAtKind == "socket" && m.sockAt != m.sock:
		here = " — here: nothing to do — lib.sh picked " + m.dockerHost + " when bbox loaded, so BBOX_DOCKER_SOCK is " + m.sockAt + ", a socket"
	case m.sockAtKind == "socket":
		here = " — here: nothing to do, " + at + " is a socket"
	case m.have["dockerd"] == "":
		here = " — here: nothing to do, no dockerd on PATH"
	case !m.systemd:
		here = " — here: it runs, and bbox starts dockerd itself"
	case m.dropInSame:
		here = " — here: it runs, and the drop-in on disk is already this one: nothing is rewritten, docker.service is not restarted"
	default:
		here = " — here: it runs: the drop-in is written and docker.service restarted — every container restarts with it"
	}
	p.step("the project socket " + at + " (ensure_project_engine), only when BBOX_DOCKER_SOCK — as lib.sh left it — is not a socket and dockerd is on PATH; " +
		"as root, or `sudo -n` before each command — else: cannot provision " + at + " (needs root or passwordless sudo) — using whichever daemon answers" + here)
	if !m.asked || m.systemd {
		cmd := "printf '%s\\n'"
		for _, l := range strings.Split(dropIn(at), "\n") {
			cmd += " '" + l + "'"
		}
		p.sub("with systemd (`systemctl cat docker.service` answers) the drop-in is written only when it differs — \"teaching docker.service to listen on "+at+"…\":",
			"mkdir -p "+path.Dir(dropInConf), cmd+" | tee "+dropInConf, "systemctl daemon-reload", "systemctl restart docker.service")
	}
	if !m.asked || !m.systemd {
		said, flags := "", ""
		if m.mirror != "" { // the sandbox's pull-through mirror (bbox's need_docker, d5d803b6)
			said, flags = ", mirror "+m.mirror, " --registry-mirror "+m.mirror
		}
		p.sub("without systemd (the cloud sandbox) bbox owns the daemon, detached from the calling session — \"no docker daemon — starting dockerd on "+at+" (DOCKER_MIN_API_VERSION=1.24"+said+")…\":",
			"setsid env DOCKER_MIN_API_VERSION=1.24 dockerd -H unix://"+at+" -H unix:///var/run/docker.sock"+flags+" >\"$BBOX_TMP/dockerd.log\" 2>&1 </dev/null &")
	}
	p.sub("then up to 30 s for " + at + " to appear")
	if !m.asked || !m.systemd { // only the dockerd bbox starts: systemd's restart returns once it is ready
		p.sub("then, a dockerd bbox started that made its socket, up to 60 s for the daemon to answer on it")
	}
	p.step("only when lib.sh picked nothing: the selection again after the socket step; still nothing: the socket step and the selection once more, then the refusal: " +
		notReachable(sock) + m.here(m.dockerHost == "", "nothing answers now, so bbox run takes this way", "skipped, lib.sh picked "+m.dockerHost))
	p.sub("then heavy_admit \"bbox run\": one heavy job at a time on this engine, admitted when memory allows (bbox's, not the engine's)")
	gen := "bash scripts/ci-env.sh"
	if m.goos == "darwin" || m.inGuest {
		gen = "CI_DEPLOYMENT_NAME=local CI_EDGE_PORT=8080 bash scripts/ci-env.sh"
	}
	skip := ".env exists"
	if !m.envFile {
		skip = "neither a sandbox nor the macOS guest"
	}
	p.step("no .env, on a cloud sandbox (a MITM proxy CA) or in the macOS guest: a secretless one is generated, and bbox run starts over"+
		m.here(m.generatesEnv(), "it runs", skip), "cd "+root+" && "+gen, "exec ./bbox run")
	p.sub("then the stack's own first steps: ensure_rendered (the compiler renders .generated/), ensure_network")
	m.planProfile(p)
	p.sub("then the stack's again: foreign_containers (a name this stack needs, held by another compose project, stops the run), run_app_hooks prepare")
	p.step("the hard nofile limit (ulimit -Hn) below PG_NOFILE_HARD (262144): PG_NOFILE_HARD and PG_NOFILE_SOFT are capped to it for this run, else n8n-postgres does not start (ccr_clamp_nofile)")
	p.step("no proxy CA, and the default bridge cannot resolve names: first-party images are built one at a time over the host network (ccr_build_serial); "+
		"bbox run probes it itself, with containers — no probe with BBOX_ASSUME_DNS_OK set"+m.here(!m.sandbox, "probed by bbox run", "the proxy step below applies instead"),
		"timeout 60 docker run --rm busybox:latest nslookup deb.debian.org", "timeout 30 docker run --rm busybox:latest true")
	p.step("a MITM proxy CA (PROXY_CA, else " + sandboxCA + ") and CCR_BASES_READY not 1: every base image re-tagged with it (ccr_shadow_bases) — one that cannot be pulled stops the run: " +
		"base images unavailable — fix the environment's network policy (see hint above), then re-run 'bbox run' — then the first-party images built one at a time over the host network (ccr_build_serial)" +
		m.here(m.sandbox, "it runs", "no proxy CA, nothing to do"))
	p.sub("then the stack itself, which is not the engine's: docker compose up -d --build --wait, the remaining hooks, convergence")
}

// planProfile is ensure_perf_profile's step, with the profile the look found.
func (m *machine) planProfile(p *planner) {
	pr := m.prof
	here := m.here(pr.set, "PERFORMANCE_PROFILE="+pr.name+" is in .env", pr.name+" is appended to .env")
	switch {
	case !m.asked:
	case pr.stop != nil:
		here = " — here: no answer and none in .env, so bbox run stops at this line"
	case pr.generated:
		here = " — here: PERFORMANCE_PROFILE=" + pr.name + " comes with the .env scripts/ci-env.sh writes, so it is kept"
	}
	var cmds []string
	if !pr.set {
		cmds = append(cmds, "printf '\\nPERFORMANCE_PROFILE=%s\\n' "+or(pr.name, "<select-profile.py's answer>")+" >> .env")
	}
	p.step("size the stack to the engine host (ensure_perf_profile): the PERFORMANCE_PROFILE .env names, else the richest profile of platform/profiles/perf-profiles.yml whose envelope fits (select-profile.py)"+here,
		append(cmds, "python3 scripts/perf-profile-apply --env-only")...)
	p.sub("then every *CPUS= value in .env above the engine host's cores is lowered to its core count (bbox_clamp_cpus_to_host)")
}

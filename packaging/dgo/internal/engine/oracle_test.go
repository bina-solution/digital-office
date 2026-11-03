package engine

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"testing"
	"time"
)

// ── the oracles: bbox's own bash and select-profile.py, run on the same recordings ────────────────
//
// Nothing here runs bbox. Each bash oracle cuts the functions it needs out of the real file — so no
// other line of it runs — and calls them with PATH holding only stubs that answer from the same
// recordings the Go side reads, plus a few real text tools: no docker, wsl.exe, sudo or systemctl can
// be reached. The tests skip where there is no bash or no python3.

// bash is a bash that is not WSL's: on Windows `bash` on PATH is often System32's launcher, which
// would run the oracle inside the office's own distro — so Git's is looked for first, and WSL's is
// never taken.
func bash(t *testing.T) string {
	t.Helper()
	var cands []string
	if runtime.GOOS == "windows" {
		if g, err := exec.LookPath("git"); err == nil {
			for d := filepath.Dir(g); d != filepath.Dir(d); d = filepath.Dir(d) {
				if c := filepath.Join(d, "bin", "bash.exe"); isFile(c) {
					cands = append(cands, c)
					break
				}
			}
		}
	}
	if p, err := exec.LookPath("bash"); err == nil {
		cands = append(cands, p)
	}
	for _, c := range cands {
		if l := strings.ToLower(c); runtime.GOOS == "windows" && (strings.Contains(l, `\system32\`) || strings.Contains(l, `\windowsapps\`)) {
			continue
		}
		return c
	}
	t.Skip("no bash here (WSL's launcher is never used)")
	return ""
}

func python(t *testing.T) []string {
	t.Helper()
	for _, c := range [][]string{{"python3"}, {"python"}, {"py", "-3"}} {
		if _, err := exec.LookPath(c[0]); err != nil {
			continue
		}
		if exec.Command(c[0], append(c[1:], "-c", "import sys; sys.exit(sys.version_info < (3, 8))")...).Run() == nil {
			return c
		}
	}
	t.Skip("no python3 here")
	return nil
}

// shFunc cuts the named functions out of a bash file of the checkout: from `name() {` to the `}` that
// closes it at the start of a line — or the same line, for a one-line function.
func shFunc(t *testing.T, rel string, names ...string) string {
	t.Helper()
	src := strings.Split(strings.ReplaceAll(repoFile(t, rel), "\r", ""), "\n")
	var b strings.Builder
	for _, name := range names {
		start := regexp.MustCompile(`^` + regexp.QuoteMeta(name) + `\(\)\s*\{`)
		i := 0
		for i < len(src) && !start.MatchString(src[i]) {
			i++
		}
		if i == len(src) {
			t.Fatalf("%s defines no %s()", rel, name)
		}
		if strings.Count(src[i], "{") == strings.Count(src[i], "}") {
			b.WriteString(src[i] + "\n")
			continue
		}
		for ; i < len(src); i++ {
			b.WriteString(src[i] + "\n")
			if src[i] == "}" {
				break
			}
		}
	}
	return b.String()
}

func sq(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }

// stub is a program answering from recorded replies, keyed by its arguments as "$*" joins them;
// anything else it is asked fails loudly, so an oracle that grows a question shows up.
func stub(name string, answers map[string]reply) string {
	keys := make([]string, 0, len(answers))
	for k := range answers {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var b strings.Builder
	b.WriteString("#!/bin/sh\ncase \"$*\" in\n")
	for _, k := range keys {
		a := answers[k]
		fmt.Fprintf(&b, "%s) printf '%%s' %s", sq(k), sq(a.out))
		if a.err != nil {
			fmt.Fprintf(&b, "; printf '%%s\\n' %s >&2; exit 1;;\n", sq(a.err.Error()))
		} else {
			b.WriteString("; exit 0;;\n")
		}
	}
	fmt.Fprintf(&b, "*) printf 'unrecorded: %s %%s\\n' \"$*\" >&2; exit 127;;\nesac\n", name)
	return b.String()
}

// shell runs funcs then body under `set -euo pipefail`, with PATH holding only the stubs and the
// real awk, grep, tail, cut, tr and cat (a stub of the same name wins); setup runs before PATH is
// narrowed (P turns a path of this machine into bash's). It returns stdout, stderr and the exit code.
func shell(t *testing.T, setup, funcs, body string, stubs map[string]string) (string, string, int) {
	t.Helper()
	sh := bash(t)
	dir := t.TempDir()
	bin := filepath.Join(dir, "bin")
	if err := os.Mkdir(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	tools := map[string]string{}
	for _, tool := range []string{"awk", "grep", "tail", "cut", "tr", "cat", "sed"} { // the real ones, nothing else
		tools[tool] = "#!/bin/sh\nPATH=/usr/bin:/bin\nexec " + tool + " \"$@\"\n"
	}
	for _, set := range []map[string]string{tools, stubs} {
		for name, src := range set {
			if err := os.WriteFile(filepath.Join(bin, name), []byte(src), 0o755); err != nil {
				t.Fatal(err)
			}
		}
	}
	script := "set -euo pipefail\nPATH=\"/usr/bin:/bin:$PATH\"\n" +
		"P() { cygpath -u \"$1\" 2>/dev/null || printf '%s' \"$1\"; }\n" +
		"BIN=\"$(P " + sq(bin) + ")\"\n" +
		"unset DOCKER_HOST BBOX_DOCKER_HOST BBOX_DOCKER_SOCK BBOX_ENGINE_RESOLVED BBOX_VM_MEM BBOX_VM_CPUS BBOX_VM_DISK\n" +
		// the sandbox's tell is a FILE (ccr_have_proxy_ca: `[ -f "$PROXY_CA" ]`), which the shim does not
		// answer: a machine that has /root/.ccr/ca-bundle.crt (a cloud sandbox) would turn every case into
		// the sandbox's. No case asks for it, so it is named missing here, and the mirror unset.
		"unset BASELINE_PROXY_CA BBOX_REGISTRY_MIRROR\nPROXY_CA=/nonexistent/dgo-oracle-no-proxy-ca\n" +
		"c0= c1= cr= cg= cy=\n" + setup + "\nPATH=\"$BIN\"\n" + funcs + "\n" + body + "\n"
	f := filepath.Join(dir, "oracle.sh")
	if err := os.WriteFile(f, []byte(script), 0o644); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(sh, filepath.ToSlash(f))
	cmd.Dir = dir
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	code := 0
	if err := cmd.Run(); err != nil {
		var ee *exec.ExitError
		if !errors.As(err, &ee) {
			t.Fatalf("bash: %v", err)
		}
		code = ee.ExitCode()
	}
	if strings.Contains(errb.String(), "unrecorded:") {
		t.Errorf("the oracle asked something unrecorded:\n%s", errb.String())
	}
	return out.String(), errb.String(), code
}

func saidLines(stdout string) []string {
	var out []string
	for _, l := range lines(stdout) {
		if s, ok := strings.CutPrefix(l, "[bbox] "); ok {
			out = append(out, s)
		}
	}
	return out
}

// ── select-profile.py ─────────────────────────────────────────────────────────────────────────────

// selectHarness runs select-profile.py's own main() once per case, with only its two facts answered
// from the case: the cores (sched_getaffinity) and /proc/meminfo. The script is loaded, not changed.
const selectHarness = `import contextlib, importlib.util, io, json, os, pathlib, sys
script = sys.argv[1]
spec = importlib.util.spec_from_file_location("select_profile", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sys.argv = [script]
res = []
for c in json.load(sys.stdin):
    mod.YML = pathlib.Path(c["yml"])
    os.sched_getaffinity = lambda pid, n=c["cores"]: set(range(n))
    def fake_open(p, *a, mem=c["meminfo"], **k):
        if p == "/proc/meminfo":
            if mem is None:
                raise OSError("no /proc/meminfo here")
            return io.StringIO(mem)
        return open(p, *a, **k)
    mod.open = fake_open
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = mod.main()
    except Exception:
        rc = 1  # an uncaught error is exit 1 and an empty stdout, which is all bbox reads
    res.append({"rc": rc, "out": buf.getvalue()})
json.dump(res, sys.stdout)
`

type selectCase struct {
	YML     string  `json:"yml"`
	Cores   int     `json:"cores"`
	Meminfo *string `json:"meminfo"`
}

// TestProfileMatchesSelectProfilePy: the office's profiles file over a grid of machines (every
// envelope edge included), what the script cannot decide on, and one fixture per selection rule —
// same stdout, same exit code, case by case.
func TestProfileMatchesSelectProfilePy(t *testing.T) {
	py := python(t)
	root := repoRoot(t)
	office := filepath.Join(root, "platform", "profiles", "perf-profiles.yml")
	dir := t.TempDir()
	fixtures := map[string]string{
		// equal host_mem: the larger core need wins, then the name (descending)
		"ties.yml": "small:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 8G\nwide:\n  requires: { cores: 4, mem_gb: 1 }\n  host_mem: 8G\n" +
			"alpha:\n  requires: { cores: 2, mem_gb: 2 }\n  host_mem: 4G\nbeta:\n  requires: { cores: 2, mem_gb: 2 }\n  host_mem: 4G\n",
		// a profile without an envelope is never chosen; one without host_mem ranks as 0
		"partial.yml": "# comment\nplain:\n  host_mem: 64G\n  env:\n    X: 1\nneedy:\n  requires: { cores: 2, mem_gb: 3 }\n",
		// nothing declares an envelope: no answer
		"none.yml": "one:\n  host_mem: 4G\n",
		// decimals, a missing key, a spaced unit, a trailing comment
		"decimals.yml": "tiny:\n  requires: { mem_gb: 0.5 }\n  host_mem: 1.5 G\nbig:\n  requires: { cores: 2.5, mem_gb: 3.25 }   # c\n  host_mem: 2G\n",
		// the line reading's corners, which a YAML reader answers otherwise: a profile named `on`, a
		// tab-indented body, a block-style or quoted value it does not see, `{}` against `{ }`, a key
		// that merely ends in `cores`, a name declared twice, CRLF, comments everywhere
		"on.yml":         "ci-small:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 7G\non:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 99G\n",
		"tab.yml":        "ci-small:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 7G\nlaptop:\n\trequires: { cores: 1, mem_gb: 1 }\n\thost_mem: 12G\n",
		"block.yml":      "big:\n  requires:\n    cores: 1\n    mem_gb: 1\n  host_mem: 99G\nsmall:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 1G\n",
		"quoted.yml":     "a:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: \"64G\"\nb:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 8G\n",
		"braces.yml":     "a:\n  requires: {}\n  host_mem: 99G\nb:\n  requires: { }\n  host_mem: 50G\nc:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 10G\n",
		"max-cores.yml":  "x:\n  requires: { max_cores: 64, mem_gb: 1 }\n  host_mem: 99G\ny:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 8G\n",
		"twice.yml":      "p:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 50G\nq:\n  requires: { cores: 1, mem_gb: 1 }\n  host_mem: 10G\np:\n  host_mem: 99G\n",
		"crlf.yml":       "a:\r\n  requires: { cores: 1, mem_gb: 1 }\r\n  host_mem: 8G\r\nb:\r\n  requires: { cores: 2, mem_gb: 1 }\r\n  host_mem: 9G\r\n",
		"comments.yml":   "  # indented comment\na:  # trailing\n  requires: { cores: 1, mem_gb: 1 } # c\n  host_mem: 8G # c\n# b:\n#  requires: { cores: 1, mem_gb: 1 }\n",
		"bad-number.yml": "z:\n  requires: { cores: 1.2.3, mem_gb: 1 }\n",
	}
	mem := func(s string) *string { return &s }
	var cases []selectCase
	for _, cores := range []int{1, 2, 3, 4, 5, 6, 8, 12, 16} {
		for _, kb := range []int{4089446, 4997132, 5242880, 7235174, 7340032, 7864320, 9332326, 9437184, 10188772,
			11429478, 11534336, 12582912, 15623782, 15728640, 16365248, 16777216, 32818892, 67108864} {
			cases = append(cases, selectCase{office, cores, mem(meminfo(kb))})
		}
	}
	cases = append(cases,
		selectCase{filepath.Join(dir, "missing.yml"), 4, mem(meminfo(10188772))},
		selectCase{office, 4, nil},
		selectCase{office, 4, mem("MemFree:  1 kB\n")},
		selectCase{office, 4, mem("MemTotal:       0 kB\n")},
		selectCase{office, 4, mem("MemTotal:\n")},
		selectCase{office, 4, mem("MemTotal: lots kB\n")})
	names := make([]string, 0, len(fixtures))
	for n := range fixtures {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		p := filepath.Join(dir, n)
		if err := os.WriteFile(p, []byte(fixtures[n]), 0o644); err != nil {
			t.Fatal(err)
		}
		for _, cores := range []int{1, 2, 3, 4} {
			for _, kb := range []int{2097152, 4194304} {
				cases = append(cases, selectCase{p, cores, mem(meminfo(kb))})
			}
		}
	}
	in, _ := json.Marshal(cases)
	cmd := exec.Command(py[0], append(py[1:], "-c", selectHarness, filepath.Join(root, "platform", "manager", "select-profile.py"))...)
	cmd.Stdin = bytes.NewReader(in)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1")
	raw, err := cmd.Output()
	if err != nil {
		t.Fatalf("the harness failed: %v", err)
	}
	var want []struct {
		RC  int    `json:"rc"`
		Out string `json:"out"`
	}
	if err := json.Unmarshal(raw, &want); err != nil || len(want) != len(cases) {
		t.Fatalf("harness answer: %v (%d of %d)", err, len(want), len(cases))
	}
	counts := map[string]int{}
	for i, c := range cases {
		yml, rerr := os.ReadFile(c.YML)
		mi := ""
		if c.Meminfo != nil {
			mi = *c.Meminfo
		}
		name, serr := selectProfile(yml, rerr, c.Cores, memTotal(mi))
		rc, out := 0, name+"\n"
		if serr != nil {
			rc, out = 1, ""
		}
		if rc != want[i].RC || out != want[i].Out {
			t.Errorf("%s, %d cores, meminfo %q: go %d %q (%v), python %d %q", filepath.Base(c.YML), c.Cores, mi, rc, out, serr, want[i].RC, want[i].Out)
		}
		counts[strings.TrimSpace(want[i].Out)]++
	}
	t.Logf("%d machines, identical to select-profile.py: %v", len(cases), counts)
}

// ── ensure_perf_profile (bbox) ─────────────────────────────────────────────────────────────────────

// TestPerfProfileMatchesBbox runs bbox's ensure_perf_profile — with the selector's answer, the core
// count and uname as stubs — beside pickProfile: the same lines said, the same line appended to
// .env, and the same stop when the selector has no answer and .env names nothing (bbox's `set -e`
// ends the run on that assignment; the floor fallback after it is never reached).
func TestPerfProfileMatchesBbox(t *testing.T) {
	funcs := shFunc(t, "bbox", "say", "ensure_perf_profile") + shFunc(t, "scripts/lib.sh", "ncores", "npath", "bbox_clamp_cpus_to_host")
	cases := []struct {
		name, env string
		noEnv     bool
		fit       string // "" = the selector has no answer (exit 1, nothing printed)
		cores     int
	}{
		{"nothing set: the answer is appended", "BUSINESS_NAME=x\n", false, "wsl-10g", 6},
		{"no .env at all", "", true, "prod", 8},
		{"set, and the same", "PERFORMANCE_PROFILE=wsl-10g\n", false, "wsl-10g", 6},
		{"set, and this machine would get another", "PERFORMANCE_PROFILE=ci-small\n", false, "wsl-10g", 6},
		{"quotes, blanks and CRLF", "PERFORMANCE_PROFILE= \"vps\" \r\n", false, "vps", 4},
		{"the last line wins", "PERFORMANCE_PROFILE=prod\nPERFORMANCE_PROFILE=laptop\n", false, "prod", 8},
		{"an empty value is not set", "PERFORMANCE_PROFILE=\n", false, "ci-small", 2},
		{"set, and no answer", "PERFORMANCE_PROFILE=prod\n", false, "", 8},
		{"nothing set, and no answer", "BUSINESS_NAME=x\n", false, "", 8},
	}
	for _, c := range cases {
		repo := t.TempDir()
		envPath := filepath.Join(repo, ".env")
		var env []byte
		if !c.noEnv {
			env = []byte(c.env)
			if err := os.WriteFile(envPath, env, 0o644); err != nil {
				t.Fatal(err)
			}
		}
		answer := "printf '%s\\n' " + sq(c.fit) + "; exit 0"
		var fitErr error
		if c.fit == "" {
			answer, fitErr = "exit 1", errors.New("select-profile: no answer")
		}
		stubs := map[string]string{
			"python3": "#!/bin/sh\ncase \"$*\" in *select-profile.py*) " + answer + ";; esac\nexit 0\n",
			"nproc":   fmt.Sprintf("#!/bin/sh\necho %d\n", c.cores),
			"uname":   "#!/bin/sh\necho Linux\n",
		}
		stdout, stderr, code := shell(t, "REPO_ROOT=\"$(P "+sq(repo)+")\"; SCRIPTS=\"$REPO_ROOT/scripts\"", funcs, "ensure_perf_profile", stubs)
		after, _ := os.ReadFile(envPath)

		p := pickProfile(env, c.fit, fitErr, c.cores)
		if got, want := strings.Join(p.said, "\n"), strings.Join(saidLines(stdout), "\n"); got != want {
			t.Errorf("%s: said\n go   %q\n bash %q", c.name, got, want)
		}
		switch {
		case p.stop != nil:
			if code == 0 || !bytes.Equal(after, env) {
				t.Errorf("%s: go says bbox stops here; bash exit %d, .env %q (stderr %s)", c.name, code, after, stderr)
			}
		case code != 0:
			t.Errorf("%s: bash exit %d: %s", c.name, code, stderr)
		case p.set && !bytes.Equal(after, env):
			t.Errorf("%s: a profile .env names is kept; bash wrote %q", c.name, after)
		case !p.set && string(after) != c.env+"\nPERFORMANCE_PROFILE="+p.name+"\n":
			t.Errorf("%s: go appends %q; bash left %q", c.name, p.name, after)
		}
	}
}

// ── need_docker and bbox_select_engine (bbox, scripts/lib.sh) ───────────────────────────────────────

// engineCase is one machine as docker answers it: what each endpoint says to `docker info`.
type engineCase struct {
	name string
	env  map[string]string
	at   map[string]reply // endpoint → its answer
}

var deadEngine = no("Cannot connect to the Docker daemon. Is the docker daemon running?")

func engineAnswers(c engineCase, sock string) map[string]reply {
	r := map[string]reply{}
	for _, ep := range []string{"unix://" + sock, c.env["DOCKER_HOST"], "unix:///var/run/docker.sock", "unix:///run/docker.sock"} {
		if ep == "" {
			continue
		}
		a, found := c.at[ep]
		if !found {
			a = deadEngine
		}
		r["-H "+ep+" info --format {{.OperatingSystem}}"] = a
	}
	return r
}

func exports(env map[string]string) string {
	var b strings.Builder
	for k, v := range env {
		fmt.Fprintf(&b, "export %s=%s\n", k, sq(v))
	}
	return b.String()
}

// TestSelectionMatchesLibSh runs scripts/lib.sh's bbox_select_engine — and bbox_endpoint_kind and
// bbox_engine_chosen under it — beside pick: the same DOCKER_HOST and BBOX_DOCKER_SOCK exported, or
// the same "nothing of ours answers".
func TestSelectionMatchesLibSh(t *testing.T) {
	funcs := shFunc(t, "scripts/lib.sh", "bbox_endpoint_kind", "bbox_engine_chosen", "bbox_select_engine")
	const sock = projectSock
	cases := []engineCase{
		{"the project socket", nil, map[string]reply{"unix://" + sock: ok("Ubuntu 22.04.3 LTS\n")}},
		{"Docker Desktop skipped, the last one taken", nil, map[string]reply{
			"unix:///var/run/docker.sock": ok("Docker Desktop\n"), "unix:///run/docker.sock": ok("Debian GNU/Linux 12 (bookworm)\n")}},
		{"an empty answer is no answer", nil, map[string]reply{
			"unix://" + sock: ok(""), "unix:///var/run/docker.sock": ok("Ubuntu 24.04.1 LTS\n")}},
		{"DOCKER_HOST before the conventional sockets", map[string]string{"DOCKER_HOST": "tcp://10.0.0.5:2375"}, map[string]reply{
			"tcp://10.0.0.5:2375": ok("Ubuntu 22.04.3 LTS\n"), "unix:///var/run/docker.sock": ok("Ubuntu 22.04.3 LTS\n")}},
		{"the project socket before DOCKER_HOST", map[string]string{"DOCKER_HOST": "tcp://10.0.0.5:2375"}, map[string]reply{
			"unix://" + sock: ok("Ubuntu 22.04.3 LTS\n"), "tcp://10.0.0.5:2375": ok("Ubuntu 22.04.3 LTS\n")}},
		{"the conventional sockets in bbox's order", nil, map[string]reply{
			"unix:///var/run/docker.sock": ok("Ubuntu 22.04.3 LTS\n"), "unix:///run/docker.sock": ok("Debian GNU/Linux 12 (bookworm)\n")}},
		{"BBOX_DOCKER_HOST is taken as given", map[string]string{"BBOX_DOCKER_HOST": "unix:///srv/other.sock"}, nil},
		{"Docker Desktop on the project socket is still Desktop", nil, map[string]reply{"unix://" + sock: ok("Docker Desktop 4.30\n")}},
		{"nothing answers", nil, nil},
	}
	for _, c := range cases {
		answers := engineAnswers(c, sock)
		stdout, stderr, _ := shell(t, exports(c.env)+"export BBOX_DOCKER_SOCK="+sock, funcs,
			`if bbox_select_engine; then printf '%s %s\n' "$DOCKER_HOST" "$BBOX_DOCKER_SOCK"; else echo none; fi`,
			map[string]string{"docker": stub("docker", answers)})

		r := &rec{goos: "linux", cmds: map[string]reply{}, env: c.env}
		for k, a := range answers {
			r.cmds["docker "+k] = a
		}
		dh, _ := pick(r.system(t), host{env: func(k string) string { return c.env[k] }}, sock)
		got := "none"
		if dh != "" {
			got = dh + " " + exported(dh, sock)
		}
		if want := strings.TrimSpace(stdout); got != want {
			t.Errorf("%s: go %q, lib.sh %q (%s)", c.name, got, want, stderr)
		}
	}
}

// libShLine is the one line of scripts/lib.sh equal to want: the oracle runs the file's own text.
func libShLine(t *testing.T, want string) string {
	t.Helper()
	for _, l := range strings.Split(strings.ReplaceAll(repoFile(t, "scripts/lib.sh"), "\r", ""), "\n") {
		if l == want {
			return l
		}
	}
	t.Fatalf("scripts/lib.sh has no line %q — the oracle must follow it", want)
	return ""
}

// socketShim answers `[ -S path ]` and `[ ! -S path ]` from $SOCKETS — the recorded fact, never the
// machine running the test, which may have a real /run/bbox-docker.sock — and every other test as bash does.
const socketShim = `[() {
  if builtin [ "$#" = 4 ] && builtin [ "$1" = "!" ] && builtin [ "$2" = "-S" ]; then case " $SOCKETS " in *" $3 "*) return 1;; *) return 0;; esac; fi
  if builtin [ "$#" = 3 ] && builtin [ "$1" = "-S" ]; then case " $SOCKETS " in *" $2 "*) return 0;; *) return 1;; esac; fi
  builtin [ "$@"
}
`

// TestNeedDockerMatchesBbox runs bbox as it runs: lib.sh's two lines at load (BBOX_DOCKER_SOCK's
// default, then bbox_select_engine — the pick that re-points BBOX_DOCKER_SOCK), then need_docker with
// ensure_project_engine, as root and not, with and without systemd, the drop-in absent or already in
// place. Every program that would change the machine is a stub that only writes what it was asked
// into a log. Beside it, the doctor and the plan on the same recordings must say what happened: the
// engine bbox ends on; whether the drop-in is written and docker restarted, dockerd started, or
// nothing; every line bbox says; and each refusal, word for word, as the doctor's fix wherever bbox
// would not start the engine itself.
func TestNeedDockerMatchesBbox(t *testing.T) {
	funcs := socketShim + shFunc(t, "bbox", "say", "die", "ensure_project_engine", "need_docker") +
		shFunc(t, "scripts/lib.sh", "bbox_endpoint_kind", "bbox_engine_chosen", "bbox_select_engine", "ccr_have_proxy_ca")
	// need_docker asks ccr_have_proxy_ca for the sandbox's mirror (d5d803b6), which reads PROXY_CA as lib.sh set it
	atLoad := libShLine(t, `PROXY_CA="${PROXY_CA:-${BASELINE_PROXY_CA:-/root/.ccr/ca-bundle.crt}}"`) + "\n" +
		libShLine(t, `export BBOX_DOCKER_SOCK="${BBOX_DOCKER_SOCK:-/run/bbox-docker.sock}"`) + "\n" + libShLine(t, "bbox_select_engine || true")
	const sock = projectSock
	native := ok("Debian GNU/Linux 12 (bookworm)\n")
	cases := []struct {
		engineCase
		root, systemd, noDocker bool
		dropIn                  string   // the drop-in on disk ("" none)
		sockets                 []string // the paths that are sockets
	}{
		{engineCase{name: "a fresh Debian: docker.service on /var/run/docker.sock, no drop-in", at: map[string]reply{"unix:///var/run/docker.sock": native}},
			true, true, false, "", []string{"/var/run/docker.sock"}},
		{engineCase{name: "nothing answers, systemd, no drop-in"}, true, true, false, "", nil},
		{engineCase{name: "nothing answers, systemd, the drop-in already there"}, true, true, false, dropIn(sock), nil},
		{engineCase{name: "nothing answers, no systemd (the sandbox)"}, true, false, false, "", nil},
		{engineCase{name: "only Docker Desktop answers, not root, no sudo", at: map[string]reply{"unix:///var/run/docker.sock": ok("Docker Desktop\n")}},
			false, true, false, "", []string{"/var/run/docker.sock"}},
		{engineCase{name: "the project socket answers", at: map[string]reply{"unix://" + sock: native}}, true, true, false, "", []string{sock}},
		{engineCase{name: "no docker CLI"}, true, true, true, "", nil},
	}
	logger := func(name string) string { return "#!/bin/sh\nprintf '" + name + " %s\\n' \"$*\" >> \"$LOG\"\n" }
	for _, c := range cases {
		dir := t.TempDir()
		logf := filepath.Join(dir, "calls.log")
		answers := engineAnswers(c.engineCase, sock)
		uid := "1000"
		if c.root {
			uid = "0"
		}
		catDropIn := "exit 1"
		if c.dropIn != "" {
			catDropIn = "printf '%s\\n' " + sq(c.dropIn)
		}
		stubs := map[string]string{
			"dockerd": "#!/bin/sh\nexit 0\n", "id": "#!/bin/sh\necho " + uid + "\n",
			"mkdir": logger("mkdir"), "setsid": logger("setsid"), "seq": "#!/bin/sh\nexit 0\n", "sleep": "#!/bin/sh\nexit 0\n",
			"tee": "#!/bin/sh\nwhile IFS= read -r _; do :; done\nprintf 'tee %s\\n' \"$*\" >> \"$LOG\"\n",
			"cat": "#!/bin/sh\ncase \"$1\" in " + dropInConf + ") " + catDropIn + ";; esac\nexit 1\n",
		}
		if c.systemd {
			stubs["systemctl"] = logger("systemctl")
		}
		if !c.noDocker {
			stubs["docker"] = stub("docker", answers)
		}
		setup := "SOCKETS=" + sq(strings.Join(c.sockets, " ")) + "; export LOG=\"$(P " + sq(logf) + ")\"; BBOX_TMP=\"$(P " + sq(dir) + ")\""
		stdout, stderr, code := shell(t, setup, funcs, "trap wait EXIT\n"+atLoad+"\nneed_docker\nprintf 'DOCKER_HOST=%s\\n' \"$DOCKER_HOST\"", stubs)
		calls, _ := os.ReadFile(logf)

		box := linuxBox(t)
		which := "/usr/bin/dockerd\n"
		if !c.noDocker {
			which = "/usr/bin/docker\n" + which
		}
		if c.systemd {
			which += "/usr/bin/systemctl\n"
		}
		box.cmds["sh -c for c do command -v $c || :; done sh docker dockerd systemctl"] = ok(which)
		box.cmds["stat -L -c %F "+sock] = no("stat: cannot statx: No such file or directory")
		for _, p := range c.sockets {
			box.cmds["stat -L -c %F "+p] = ok("socket\n")
		}
		for k, a := range answers {
			box.cmds["docker "+k] = a
		}
		for ep, a := range c.at {
			if a.out != "" && !strings.Contains(a.out, "Docker Desktop") {
				box.cmds["docker -H "+ep+" version --format {{.Server.Version}} {{.Server.APIVersion}} {{.Server.MinAPIVersion}}"] = ok("28.5.2 1.51 1.24\n")
			}
		}
		if c.dropIn != "" {
			box.files[dropInConf] = c.dropIn + "\n"
		}
		doctor, _ := box.answer(t, "doctor")
		plan, _ := box.answer(t, "plan")

		// what ensure_project_engine did, from its own calls — and what the plan says it does
		did := "nothing"
		switch log := string(calls); {
		case strings.Contains(log, "tee "+dropInConf) && strings.Contains(log, "systemctl restart docker.service"):
			did = "the drop-in is written and docker.service restarted"
		case strings.Contains(log, "setsid env DOCKER_MIN_API_VERSION=1.24 dockerd -H unix://"+sock+" -H unix:///var/run/docker.sock"):
			did = "bbox starts dockerd itself"
		case strings.Contains(log, "systemctl cat docker.service"):
			did = "nothing is rewritten, docker.service is not restarted"
		}
		said := saidLines(stdout)
		refusedRoot := len(said) > 0 && strings.HasPrefix(said[0], "cannot provision ")
		switch {
		case refusedRoot: // the plan states the condition; it cannot know who will run bbox
			has(t, plan, "else: cannot provision "+sock+" (needs root or passwordless sudo) — using whichever daemon answers")
		case did == "nothing" && c.noDocker:
			has(t, plan, "— here: not reached, bbox run stops at the docker CLI")
		case did == "nothing":
			has(t, plan, "— here: nothing to do")
		default:
			has(t, plan, did)
		}
		for _, l := range said { // every line bbox says, the plan quotes
			if !strings.Contains(plan, l) {
				t.Errorf("%s: bbox says %q, the plan does not", c.name, l)
			}
		}
		if refusal, refused := strings.CutPrefix(strings.TrimSpace(stderr), "[bbox] error: "); refused {
			starts := did == "the drop-in is written and docker.service restarted" || did == "bbox starts dockerd itself" || refusedRoot
			switch {
			case code != 1:
				t.Errorf("%s: bbox refused with exit %d", c.name, code)
			case starts && !strings.Contains(doctor, "fix: bbox run starts it"):
				t.Errorf("%s: bbox run starts the engine here (%s), and the doctor's fix does not say so:\n%s", c.name, did, doctor)
			case !starts && !strings.Contains(doctor, "fix: "+refusal+"\n"):
				t.Errorf("%s: bbox refuses with\n %s\nwhich the doctor must give as the fix:\n%s", c.name, refusal, doctor)
			}
			continue
		}
		dh := strings.TrimPrefix(lines(stdout)[len(lines(stdout))-1], "DOCKER_HOST=")
		if code != 0 || !strings.Contains(doctor, line(pass, "engine", "DOCKER_HOST="+dh+" ")) {
			t.Errorf("%s: bbox chose %q (exit %d, %s); the doctor:\n%s", c.name, dh, code, stderr, doctor)
		}
	}
}

// ── packaging/macos/engine.sh ───────────────────────────────────────────────────────────────────────

// TestMacSizingMatchesEngineSh runs engine.sh's host_mem_gib, vm_mem, vm_cpus and vm_disk, with
// sysctl a stub, beside vmSize — every branch: the 8 GiB floor, 60%, the cap at 12, the 4-cpu cap,
// the three overrides, and a size the office declares in its .env (the environment wins; the last line
// wins; a value that is not a plain number is ignored).
func TestMacSizingMatchesEngineSh(t *testing.T) {
	funcs := shFunc(t, "packaging/macos/engine.sh", "env_value", "declared_num", "declared_mem", "declared_cpus",
		"host_mem_gib", "vm_mem", "vm_cpus", "vm_disk")
	const gib = 1073741824
	cases := []struct {
		memsize, ncpu int64
		env           map[string]string
		dotenv        string
	}{
		{8 * gib, 8, nil, ""}, {8*gib + 1, 8, nil, ""}, {9 * gib, 2, nil, ""}, {12 * gib, 3, nil, ""}, {16 * gib, 10, nil, ""},
		{24 * gib, 4, nil, ""}, {64 * gib, 12, nil, ""}, {4 * gib, 1, nil, ""},
		{16 * gib, 10, map[string]string{"BBOX_VM_MEM": "7", "BBOX_VM_CPUS": "6", "BBOX_VM_DISK": "100"}, ""},
		{8 * gib, 8, nil, "BBOX_VM_MEM=3\n"},
		{8 * gib, 8, nil, "OTHER=1\nBBOX_VM_MEM=\"3.5\"\n BBOX_VM_CPUS = 2 \n"},
		{8 * gib, 8, map[string]string{"BBOX_VM_MEM": "4"}, "BBOX_VM_MEM=3\n"},
		{16 * gib, 10, nil, "BBOX_VM_MEM=2\nBBOX_VM_MEM=6\n"},
		{8 * gib, 8, nil, "BBOX_VM_MEM=3GiB\nBBOX_VM_CPUS=2 # small\n"},
		{8 * gib, 8, nil, "BBOX_VM_MEM_MAX=3\n"},
	}
	for _, c := range cases {
		ms, nc := fmt.Sprintf("%d\n", c.memsize), fmt.Sprintf("%d\n", c.ncpu)
		root := t.TempDir()
		if c.dotenv != "" {
			if err := os.WriteFile(filepath.Join(root, ".env"), []byte(c.dotenv), 0o644); err != nil {
				t.Fatal(err)
			}
		}
		stdout, stderr, code := shell(t, exports(c.env)+"REPO_ROOT=\"$(P "+sq(root)+")\"", funcs, `printf '%s %s %s\n' "$(vm_cpus)" "$(vm_mem)" "$(vm_disk)"`,
			map[string]string{"sysctl": stub("sysctl", map[string]reply{"-n hw.memsize": ok(ms), "-n hw.ncpu": ok(nc)})})
		cpus, mem, disk := vmSize(func(k string) string { return c.env[k] }, []byte(c.dotenv), nc, ms)
		if got := cpus + " " + mem + " " + disk; code != 0 || got != strings.TrimSpace(stdout) {
			t.Errorf("%d bytes, %d cpus, %v, .env %q: go %q, engine.sh %q (exit %d %s)", c.memsize, c.ncpu, c.env, c.dotenv, got, stdout, code, stderr)
		}
	}
}

// TestMacStateMatchesEngineSh runs engine.sh's state() on recorded `limactl list` answers beside
// limaState.
func TestMacStateMatchesEngineSh(t *testing.T) {
	funcs := shFunc(t, "packaging/macos/engine.sh", "lima", "state")
	for _, list := range []string{"bbox Running\n", "other Running\nbbox Stopped\n", "", "bboxer Running\n", "bbox\n", "bbox Broken extra\n"} {
		stdout, stderr, code := shell(t, "INSTANCE=bbox; LIMACTL=\"$BIN/limactl\"", funcs, `printf '[%s]\n' "$(state)"`,
			map[string]string{"limactl": stub("limactl", map[string]reply{"list --format {{.Name}} {{.Status}}": ok(list)})})
		if got := "[" + limaState(list, "bbox") + "]"; code != 0 || got != strings.TrimSpace(stdout) {
			t.Errorf("list %q: go %s, engine.sh %s (exit %d %s)", list, got, stdout, code, stderr)
		}
	}
}

// ── engine.sh's own doctor ──────────────────────────────────────────────────────────────────────────

// macFuncs is engine.sh's doctor with what it calls. Two absolute paths no PATH stub can reach are
// pointed at the test's own: /usr/bin/python3 (ports_yaml's interpreter — a stub that runs the real
// python3 on engine.sh's own reader) and Rosetta's binary ($ROSETTA, present or not by the case).
// ensure_runtime is not taken: it lands Lima, a download — the native doctor leaves that to
// `./bbox engine start`, and here the runtime is the recorded limactl.
func macFuncs(t *testing.T) string {
	src := shFunc(t, "packaging/macos/engine.sh", "cmd_doctor", "lima", "env_value", "declared_num", "declared_mem",
		"declared_cpus", "host_mem_gib", "vm_mem", "vm_cpus", "vm_disk",
		"rosetta_flags", "state", "host_socket", "forward_report", "lan_addr", "ports_yaml", "instance_ports",
		"template_udp_json", "udp_listening", "guest_udp_bound", "guest_udp_handoff")
	for _, p := range []string{"/usr/bin/python3", rosettaBin} {
		if !strings.Contains(src, p) {
			t.Fatalf("engine.sh no longer names %s — the oracle's rewrite must follow it", p)
		}
	}
	src = strings.ReplaceAll(src, "/usr/bin/python3", "python3")
	return strings.ReplaceAll(src, rosettaBin, `"$ROSETTA"`) + "ensure_runtime() { :; }\n"
}

// pythonStub runs the real interpreter, its output with the CR a Windows python adds taken out — so
// engine.sh's reader answers here as it does on a Mac.
func pythonStub(t *testing.T) string {
	py := python(t)
	p, err := exec.LookPath(py[0])
	if err != nil {
		t.Skip(err)
	}
	args := ""
	for _, a := range py[1:] {
		args += " " + sq(a)
	}
	return "#!/bin/sh\n" + sq(filepath.ToSlash(p)) + args + " \"$@\" | tr -d '\\r'\n"
}

// bashPath is a path of this machine as bash names it — the one spelling both sides print.
func bashPath(t *testing.T, p string) string {
	out, _, _ := shell(t, "", "", "P "+sq(p), nil)
	return strings.TrimSpace(out)
}

// macCase is a Mac as both doctors see it.
type macCase struct {
	name                 string
	state                string // what `limactl list` says of the guest: Running, Stopped, "" (not created)
	rosetta, route       bool
	instance             string // the instance's lima.yaml ("" = none)
	ss, lsof             reply  // the guest's `ss -lunH`, the Mac's `lsof -nP -iUDP:51830`
	version, api, minAPI string
}

// TestMacDoctorTellsEverythingEngineShTold runs engine.sh's cmd_doctor — `bbox engine doctor`, which
// `dgo engine doctor` used to reach on a Mac — on the same recordings as the native doctor, and
// requires every line it prints (and every line under it) to be told by the native doctor, in the
// fact that carries it.
func TestMacDoctorTellsEverythingEngineShTold(t *testing.T) {
	funcs := macFuncs(t)
	template := repoFile(t, "packaging/macos/engine.yaml")
	const rule = "- guestPort: 51830\n  hostPort: 51830\n  hostIP: \"0.0.0.0\"\n  proto: udp\n"
	if !strings.Contains(template, rule) {
		t.Fatal("engine.yaml no longer declares the pair tunnel's UDP rule this test is built on")
	}
	tcpOnly := strings.Replace(template, rule, "", 1)
	nothingHeld := no("") // lsof finds nothing for the port: no output, exit 1
	cases := []macCase{
		{"the chain closed", "Running", true, true, template, ok(ssOut), ok(lsofOut), "28.5.2", "1.51", "1.24"},
		{"not published yet", "Running", false, true, template, ok("UNCONN 0 0 127.0.0.53%lo:53 0.0.0.0:*\n"), nothingHeld, "28.5.2", "1.51", "1.24"},
		{"the guest listens, the Mac holds nothing", "Running", false, true, template, ok(ssOut), nothingHeld, "28.5.2", "1.51", "1.24"},
		{"an older engine, stopped, no route", "Stopped", false, false, tcpOnly, ok(""), nothingHeld, "", "", ""},
		{"no guest yet", "", true, true, "", ok(""), nothingHeld, "", "", ""},
		{"Docker 29 in the guest", "Running", false, true, template, ok(ssOut), ok(lsofOut), "29.0.1", "1.52", "1.44"},
	}
	labels := map[string]string{"": "mac", "lima": "lima", "LIMA_HOME": "lima", "template": "template", "sizing": "sizing",
		"rosetta": "rosetta", "state": "guest", "socket": "macsock", "lan": "lan", "udp": "udp", "guest": "handoff", "engine": "docker"}
	labelRE := regexp.MustCompile(`^\s*([A-Za-z_]+):\s+(.*)$`)
	collapse := func(s string) string { return strings.Join(strings.Fields(s), " ") }
	for _, c := range cases {
		dir := t.TempDir()
		home := bashPath(t, dir)
		root, limaHome, ctl := home+"/MyDGO", home+"/.bbox/macos/lima", home+"/.bbox/macos/lima-2.2.0/bin/limactl"
		write := func(rel, body string, mode os.FileMode) {
			p := filepath.Join(dir, filepath.FromSlash(rel))
			if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(p, []byte(body), mode); err != nil {
				t.Fatal(err)
			}
		}
		// one recording, read by both: the Mac's answers and limactl's
		mac := map[string]reply{"sysctl -n hw.ncpu": ok("8\n"), "sysctl -n hw.memsize": ok("8589934592\n"),
			"sw_vers -productVersion": ok("15.3.1\n"), "uname -m": ok("arm64\n"), "ipconfig getifaddr en0": ok("192.168.1.20\n"),
			"lsof -nP -iUDP:51830": c.lsof, "arch -x86_64 /usr/bin/true": ok(""), "route -n get default": ok(routeOut)}
		if !c.route {
			mac["route -n get default"] = no("route: writing to routing socket: not in table")
		}
		guest := map[string]reply{"--version": ok("limactl version 2.2.0\n"), "shell bbox -- ss -lunH": c.ss}
		guest["list --format {{.Name}} {{.Status}}"] = ok("")
		if c.state != "" {
			guest["list --format {{.Name}} {{.Status}}"] = ok("bbox " + c.state + "\n")
		}
		if c.version != "" {
			guest["shell bbox sudo docker version --format   engine:    Docker {{.Server.Version}} (API {{.Server.APIVersion}}, min {{.Server.MinAPIVersion}})"] =
				ok("  engine:    Docker " + c.version + " (API " + c.api + ", min " + c.minAPI + ")\n")
		}
		write(".bbox/macos/lima-2.2.0/bin/limactl", stub("limactl", guest), 0o755)
		write("MyDGO/packaging/macos/engine.yaml", template, 0o644)
		if c.instance != "" {
			write(".bbox/macos/lima/bbox/lima.yaml", c.instance, 0o644)
		}
		if c.rosetta {
			write("rosetta", "", 0o644)
		}
		stubs := map[string]string{"python3": pythonStub(t)}
		for _, tool := range []string{"sysctl", "sw_vers", "uname", "ipconfig", "lsof", "arch", "route"} {
			answers := map[string]reply{}
			for k, a := range mac {
				if rest, found := strings.CutPrefix(k, tool+" "); found {
					answers[rest] = a
				}
			}
			stubs[tool] = stub(tool, answers)
		}
		setup := "HOME=" + sq(home) + "; BBOX_MACOS_HOME=\"$HOME/.bbox/macos\"; LIMA_HOME=\"$BBOX_MACOS_HOME/lima\"; INSTANCE=bbox\n" +
			"REPO_ROOT=\"$HOME/MyDGO\"; HERE=\"$REPO_ROOT/packaging/macos\"; TEMPLATE=\"$HERE/engine.yaml\"; LIMACTL=" + sq(ctl) + "; ROSETTA=\"$HOME/rosetta\""
		stdout, stderr, code := shell(t, setup, funcs, "cmd_doctor", stubs)
		if code != 0 {
			t.Fatalf("%s: engine.sh's doctor exit %d: %s", c.name, code, stderr)
		}

		// the native doctor on the same Mac
		lima := "env LIMA_HOME=" + limaHome + " " + ctl
		box := &rec{goos: "darwin", root: root, env: map[string]string{"HOME": home}, cmds: map[string]reply{}, files: map[string]string{
			root + "/packaging/macos/fetch-runtime.sh":    repoFile(t, "packaging/macos/fetch-runtime.sh"),
			root + "/packaging/macos/engine.yaml":         template,
			root + "/scripts/ci-env.sh":                   repoFile(t, "scripts/ci-env.sh"),
			root + "/platform/profiles/perf-profiles.yml": repoFile(t, "platform/profiles/perf-profiles.yml"),
		}}
		if c.instance != "" {
			box.files[limaHome+"/bbox/lima.yaml"] = c.instance
		}
		for k, a := range mac {
			box.cmds[k] = a
		}
		for k, a := range guest {
			box.cmds[lima+" "+k] = a
		}
		box.cmds[ctl+" --version"] = guest["--version"]
		box.cmds["test -f "+rosettaBin] = no("")
		if c.rosetta {
			box.cmds["test -f "+rosettaBin] = ok("")
		}
		if c.state == "Running" {
			for k, a := range healthyHost(lima+" shell bbox sudo", root) {
				box.cmds[k] = a
			}
			box.cmds[lima+" shell bbox sudo docker -H unix:///run/bbox-docker.sock version --format {{.Server.Version}} {{.Server.APIVersion}} {{.Server.MinAPIVersion}}"] =
				ok(c.version + " " + c.api + " " + c.minAPI + "\n")
		}
		told := map[string]string{}
		for _, f := range look(box.system(t), root).facts {
			told[f.name] += " " + collapse(f.said+" "+f.also+" "+f.fix)
		}

		var label string
		n := 0
		for _, l := range strings.Split(stdout, "\n") {
			var want string
			switch m := labelRE.FindStringSubmatch(l); {
			case strings.TrimSpace(l) == "":
				continue
			case m != nil && labels[m[1]] != "":
				label, want = m[1], m[2]
			case strings.HasPrefix(l, " ") && label != "":
				want = l // a line under the last one: it belongs to the same fact
			default:
				label, want = "", l
			}
			n++
			if !strings.Contains(told[labels[label]], collapse(want)) {
				t.Errorf("%s: engine.sh says %q (%s:), the native doctor's %q fact does not:%s", c.name, collapse(want), label, labels[label], told[labels[label]])
			}
		}
		if n < 10 {
			t.Errorf("%s: engine.sh's doctor said only %d lines:\n%s%s", c.name, n, stdout, stderr)
		}
	}
}

// TestUDPForwardsMatchEngineSh runs engine.sh's ports_yaml — its own narrow reader, on python3 —
// beside udpForwards on the template and the shapes an instance's lima.yaml takes: the same ports,
// and the same "the template declares one" answer.
func TestUDPForwardsMatchEngineSh(t *testing.T) {
	funcs := macFuncs(t)
	template := repoFile(t, "packaging/macos/engine.yaml")
	const rule = "- guestPort: 51830\n  hostPort: 51830\n  hostIP: \"0.0.0.0\"\n  proto: udp\n"
	files := map[string]string{
		"template.yaml":   template,
		"tcp-only.yaml":   strings.Replace(template, rule, "", 1),
		"loopback.yaml":   strings.Replace(template, rule, strings.Replace(rule, `"0.0.0.0"`, `"127.0.0.1"`, 1), 1),
		"any-quoted.yaml": strings.Replace(template, rule, "- guestPort: \"51830\"\n  hostIP: 0.0.0.0\n  proto: ANY\n", 1),
		"two.yaml":        strings.Replace(template, rule, rule+strings.ReplaceAll(rule, "51830", "51831"), 1),
		// the narrow reader's corners: an inline comment becomes part of the value (a commented loopback
		// address reads as a wildcard, a commented port as no port), and CRLF lines
		"inline-comment.yaml": strings.Replace(template, rule, strings.Replace(rule, `"0.0.0.0"`, `"127.0.0.1"   # loopback`, 1), 1),
		"commented-port.yaml": strings.Replace(template, rule, strings.Replace(rule, "guestPort: 51830", "guestPort: 51830 # tunnel", 1), 1),
		"crlf.yaml":           strings.ReplaceAll(template, "\n", "\r\n"),
	}
	dir := t.TempDir()
	names := []string{"missing.yaml"}
	for n, body := range files {
		if err := os.WriteFile(filepath.Join(dir, n), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		names = append(names, n)
	}
	sort.Strings(names)
	var body strings.Builder
	for _, n := range names {
		fmt.Fprintf(&body, "F=\"$D/%s\"; printf '%%s|%%s\\n' \"$(ports_yaml \"$F\" ports)\" \"$(ports_yaml \"$F\" json)\"\n", n)
	}
	stdout, stderr, code := shell(t, "D=\"$(P "+sq(dir)+")\"", funcs, body.String(), map[string]string{"python3": pythonStub(t)})
	got := lines(stdout)
	if code != 0 || len(got) != len(names) {
		t.Fatalf("engine.sh: exit %d, %d answers for %d files: %s", code, len(got), len(names), stderr)
	}
	for i, n := range names {
		ports, json, _ := strings.Cut(got[i], "|")
		goPorts := udpForwards(os.ReadFile(filepath.Join(dir, n)))
		if strings.Join(goPorts, " ") != ports || (len(goPorts) > 0) != (json != "" && json != "[]") {
			t.Errorf("%s: go %q, engine.sh %q / %s", n, goPorts, ports, json)
		}
	}
}

// ── what the plan and the doctor copy ───────────────────────────────────────────────────────────────

// everyOutput is what the doctor and the plan print on every recorded machine of these tests —
// healthy, broken, the tunnel's states, and the plan's own variants — as one text.
func everyOutput(t *testing.T) string {
	cases := append(append(brokenCases(), chainCases()...),
		broken{"windows", windowsBox, func(*rec) {}, nil}, broken{"darwin", macBox, func(*rec) {}, nil},
		broken{"linux", linuxBox, func(*rec) {}, nil}, broken{"the sandbox", sandboxBox, func(*rec) {}, nil},
		broken{"a guest to create, with Rosetta", macBox, func(r *rec) {
			r.cmds[macLima+" list --format {{.Name}} {{.Status}}"] = ok("")
			r.cmds["test -f "+rosettaBin] = ok("")
			r.cmds["arch -x86_64 /usr/bin/true"] = ok("")
		}, nil},
		broken{"a VPS with no .env", linuxBox, func(r *rec) { delete(r.files, linRoot+"/.env") }, nil})
	var b strings.Builder
	for _, c := range cases {
		for _, verb := range []string{"doctor", "plan"} {
			box := c.box(t)
			c.mutate(box)
			out, _ := box.answer(t, verb)
			b.WriteString(out)
		}
	}
	return b.String()
}

// quote is one thing dgo copies: the bash it copies (in file), and what dgo prints for it (said).
type quote struct{ file, bash, said string }

// quotes is every command and message dgo engine copies from bbox and its neighbours.
var quotes = []quote{
	{"bbox.cmd", `wsl.exe -d Ubuntu -e wslpath -a "!BBOX_DIR!"`, `wsl.exe -d Ubuntu -e wslpath -a "C:\Users\u\MyDGO"`},
	{"bbox.cmd", `powershell -NoProfile -ExecutionPolicy Bypass -File "%BBOX_DIR%\scripts\windows\platform-keepalive.ps1" -Install`,
		`powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\u\MyDGO\scripts\windows\platform-keepalive.ps1" -Install`},
	{"bbox.cmd", `powershell -NoProfile -ExecutionPolicy Bypass -File "%BBOX_DIR%\scripts\windows\firewall-converge.ps1"`,
		`powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\u\MyDGO\scripts\windows\firewall-converge.ps1"`},
	{"bbox.cmd", `wsl.exe -d Ubuntu -u root -- bash -lc "cd '%BBOX_REPO%' && ./bbox %*"`, `wsl.exe -d Ubuntu -u root -- bash -lc "cd '/mnt/c/Users/u/MyDGO' && ./bbox run"`},
	{"bbox.cmd", "could not resolve this directory inside the WSL distro 'Ubuntu'.", "could not resolve this directory inside the WSL distro 'Ubuntu'"},
	{"bbox.cmd", "Is WSL installed and the distro present?  Check: wsl -l -v", "Is WSL installed and the distro present?  Check: wsl -l -v"},
	{"bbox", `exec bash "${REPO_ROOT}/packaging/macos/engine.sh" exec -- ./bbox "$@"`, "bash packaging/macos/engine.sh exec -- ./bbox run"},
	{"bbox", `die "docker not found — run: bbox install <debian|windows>"`, "docker not found — run: bbox install <debian|windows>"},
	{"bbox", "cannot provision ${sock} (needs root or passwordless sudo) — using whichever daemon answers",
		"cannot provision /run/bbox-docker.sock (needs root or passwordless sudo) — using whichever daemon answers"},
	{"bbox", `say "teaching docker.service to listen on ${sock}…"`, "teaching docker.service to listen on /run/bbox-docker.sock…"},
	{"bbox", `say "no docker daemon — starting dockerd on ${sock} (DOCKER_MIN_API_VERSION=1.24${mirror[1]:+, mirror ${mirror[1]}})…"`,
		"no docker daemon — starting dockerd on /run/bbox-docker.sock (DOCKER_MIN_API_VERSION=1.24)…"},
	{"bbox", "local dir=/etc/systemd/system/docker.service.d", "mkdir -p /etc/systemd/system/docker.service.d"},
	{"bbox", `conf="${dir}/10-bbox-endpoint.conf"`, "| tee /etc/systemd/system/docker.service.d/10-bbox-endpoint.conf"},
	{"bbox", "'Environment=DOCKER_MIN_API_VERSION=1.24'", "'Environment=DOCKER_MIN_API_VERSION=1.24'"},
	{"bbox", `"ExecStart=/usr/bin/dockerd -H fd:// -H unix://${sock} --containerd=/run/containerd/containerd.sock"`,
		"'ExecStart=/usr/bin/dockerd -H fd:// -H unix:///run/bbox-docker.sock --containerd=/run/containerd/containerd.sock'"},
	{"bbox", "${sudo} systemctl daemon-reload", "systemctl daemon-reload"},
	{"bbox", "${sudo} systemctl restart docker.service", "systemctl restart docker.service"},
	{"bbox", `setsid env DOCKER_MIN_API_VERSION=1.24 dockerd -H "unix://${sock}" -H unix:///var/run/docker.sock ${mirror[@]+"${mirror[@]}"} >"${BBOX_TMP:-/tmp}/dockerd.log" 2>&1 </dev/null &`,
		`setsid env DOCKER_MIN_API_VERSION=1.24 dockerd -H unix:///run/bbox-docker.sock -H unix:///var/run/docker.sock >"$BBOX_TMP/dockerd.log" 2>&1 </dev/null &`},
	{"bbox", `for _ in $(seq 1 30); do [ -S "${sock}" ] && break; sleep 1; done`, "then up to 30 s for /run/bbox-docker.sock to appear"},
	{"bbox", `[ -S "${sock}" ] || return 0`, "a dockerd bbox started that made its socket"},
	{"bbox", `for _ in $(seq 1 60); do ${sudo} docker -H "unix://${sock}" version >/dev/null 2>&1 && break; sleep 1; done`, "up to 60 s for the daemon to answer on it"},
	{"bbox", `heavy_admit "bbox run $*"`, `heavy_admit "bbox run"`},
	{"bbox", "CI_DEPLOYMENT_NAME=local CI_EDGE_PORT=8080 bash scripts/ci-env.sh", "cd /Users/u/MyDGO && CI_DEPLOYMENT_NAME=local CI_EDGE_PORT=8080 bash scripts/ci-env.sh"},
	{"bbox", `( cd "${REPO_ROOT}" && bash scripts/ci-env.sh )`, "cd /srv/office && bash scripts/ci-env.sh"},
	{"bbox", `exec "${REPO_ROOT}/bbox" run "$@"`, "exec ./bbox run"},
	{"bbox", "ensure_rendered; ensure_network; ensure_perf_profile", "ensure_rendered (the compiler renders .generated/), ensure_network"},
	{"bbox", `held="$(foreign_containers)"`, "foreign_containers (a name this stack needs, held by another compose project, stops the run)"},
	{"bbox", "run_app_hooks prepare || true", "run_app_hooks prepare"},
	{"bbox", `printf '\nPERFORMANCE_PROFILE=%s\n' "$prof" >> "${REPO_ROOT}/.env"`, `printf '\nPERFORMANCE_PROFILE=%s\n' prod >> .env`},
	{"bbox", `perf-profile-apply" --env-only`, "python3 scripts/perf-profile-apply --env-only"},
	{"bbox", `[ "${CCR_BASES_READY:-0}" != 1 ]`, "CCR_BASES_READY not 1"},
	{"bbox", "base images unavailable — fix the environment's network policy (see hint above), then re-run 'bbox run'",
		"base images unavailable — fix the environment's network policy (see hint above), then re-run 'bbox run'"},
	{"bbox", "profile selector unavailable — falling back to the floor profile (${prof}).", "profile selector unavailable — falling back to the floor profile (ci-small)."},
	{"bbox", "profile: ${cur} (set in .env) — this machine ($(ncores) cores) would be sized ${fit}; PERFORMANCE_PROFILE=${fit} in .env adopts it",
		"profile: ci-small (set in .env) — this machine (8 cores) would be sized prod; PERFORMANCE_PROFILE=prod in .env adopts it"},
	{"bbox", "no PERFORMANCE_PROFILE set — sizing to this host (${n} cores → ${prof})", "no PERFORMANCE_PROFILE set — sizing to this host (8 cores → prod)"},
	{"scripts/lib.sh", `export BBOX_DOCKER_SOCK="${BBOX_DOCKER_SOCK:-/run/bbox-docker.sock}"`, "the project socket /run/bbox-docker.sock (ensure_project_engine)"},
	{"scripts/lib.sh", "\nbbox_select_engine || true\n", "bbox loads scripts/lib.sh, and lib.sh picks the engine right there (bbox_select_engine)"},
	{"scripts/lib.sh", `for ep in "unix://${BBOX_DOCKER_SOCK}" "${DOCKER_HOST:-}" "unix:///var/run/docker.sock" "unix:///run/docker.sock"; do`,
		"docker -H unix:///run/bbox-docker.sock info --format '{{.OperatingSystem}}'\n      docker -H \"$DOCKER_HOST\" info --format '{{.OperatingSystem}}'   (only when DOCKER_HOST is set)\n" +
			"      docker -H unix:///var/run/docker.sock info --format '{{.OperatingSystem}}'\n      docker -H unix:///run/docker.sock info --format '{{.OperatingSystem}}'"},
	{"scripts/lib.sh", `case "${os}" in *"Docker Desktop"*) printf 'desktop'`, "(Docker Desktop's — never used)"},
	{"scripts/lib.sh", `BBOX_COMPOSE="${BBOX_COMPOSE:-/usr/libexec/docker/cli-plugins/docker-compose}"`, "/usr/libexec/docker/cli-plugins/docker-compose — the compose binary bbox names"},
	{"scripts/lib.sh", "compose plugin missing at ${BBOX_COMPOSE} — run: bbox install debian (installs docker-compose-plugin)",
		"compose plugin missing at /usr/libexec/docker/cli-plugins/docker-compose — run: bbox install debian (installs docker-compose-plugin)"},
	{"scripts/lib.sh", "is a DIRECTORY, not a socket — Docker created it", "is a DIRECTORY, not a socket — Docker created it"},
	{"scripts/lib.sh", "(sudo rmdir '${BBOX_DOCKER_SOCK}') and re-run; the engine in use is", "(sudo rmdir '/run/bbox-docker.sock') and re-run; the engine in use is"},
	{"scripts/lib.sh", "does not exist. The engine in use is", "does not exist. The engine in use is"},
	{"scripts/lib.sh", "containers cannot be handed a socket that is not there.", "containers cannot be handed a socket that is not there."},
	{"scripts/lib.sh", `PROXY_CA="${PROXY_CA:-${BASELINE_PROXY_CA:-/root/.ccr/ca-bundle.crt}}"`, "a MITM proxy CA (PROXY_CA, else /root/.ccr/ca-bundle.crt)"},
	{"scripts/lib.sh", `local want="${PG_NOFILE_HARD:-262144}"`, "below PG_NOFILE_HARD (262144)"},
	{"scripts/lib.sh", `timeout 60 docker run --rm "${img}" nslookup deb.debian.org`, "timeout 60 docker run --rm busybox:latest nslookup deb.debian.org"},
	{"scripts/lib.sh", `timeout 30 docker run --rm "${img}" true`, "timeout 30 docker run --rm busybox:latest true"},
	{"scripts/lib.sh", `local img="${BBOX_DNS_PROBE_IMAGE:-busybox:latest}"`, "--rm busybox:latest "},
	{"scripts/lib.sh", `[ -n "${BBOX_ASSUME_DNS_OK:-}" ] && return 1`, "no probe with BBOX_ASSUME_DNS_OK set"},
	{"packaging/macos/engine.sh", `export LIMA_HOME="${LIMA_HOME:-${BBOX_MACOS_HOME}/lima}"`, "LIMA_HOME=/Users/u/.bbox/macos/lima /Users/u/.bbox/macos/lima-2.2.0/bin/limactl"},
	{"packaging/macos/engine.sh", `INSTANCE="${BBOX_VM_NAME:-bbox}"`, "the guest bbox is Running"},
	{"packaging/macos/engine.sh", "the repo must live under ${HOME} to be visible in the guest (it is at ${REPO_ROOT})",
		"the repo must live under /Users/u to be visible in the guest (it is at /Volumes/work/MyDGO)"},
	{"packaging/macos/engine.sh", `lima start --name="${INSTANCE}" --tty=false`, " start --name=bbox --tty=false "},
	{"packaging/macos/engine.sh", `--cpus="$(vm_cpus)" --memory="$(vm_mem)" --disk="$(vm_disk)"`, "--cpus=4 --memory=5 --disk=60"},
	{"packaging/macos/engine.sh", `--mount="${HOME}:w"`, "--mount=/Users/u:w"},
	{"packaging/macos/engine.sh", `printf '%s' "--set=.vmOpts.vz.rosetta.enabled=true | .vmOpts.vz.rosetta.binfmt=true"`,
		"'--set=.vmOpts.vz.rosetta.enabled=true | .vmOpts.vz.rosetta.binfmt=true'"},
	{"packaging/macos/engine.sh", `ok "Rosetta present — amd64 images will run too"`, "present — amd64 images will run too"},
	{"packaging/macos/engine.sh", "only arm64 images will run (optional: softwareupdate --install-rosetta)", "only arm64 images will run (optional: softwareupdate --install-rosetta)"},
	{"packaging/macos/engine.sh", `lima start --tty=false "${INSTANCE}"`, " start --tty=false bbox"},
	{"packaging/macos/engine.sh", `lima shell "${INSTANCE}" sudo docker version --format '{{.Server.Version}}'`, " shell bbox sudo docker version --format '{{.Server.Version}}'"},
	{"packaging/macos/engine.sh", "engine is up but dockerd does not answer inside it", "engine is up but dockerd does not answer inside it"},
	{"packaging/macos/engine.sh", `nohup /usr/bin/python3 "${HERE}/power-agent.py" --repo "${REPO_ROOT}" --watch-pid "${ha}"`,
		"nohup /usr/bin/python3 /Users/u/MyDGO/packaging/macos/power-agent.py --repo /Users/u/MyDGO --watch-pid"},
	{"packaging/macos/engine.sh", `"${LIMACTL}" shell --workdir "${REPO_ROOT}" "${INSTANCE}" -- \`, " shell --workdir /Users/u/MyDGO bbox -- sudo"},
	{"packaging/macos/engine.sh", "sudo --preserve-env=OVERLAYS,BBOX_DOCKER_HOST,BBOX_WITH_BROWSER42,FORCE,PERFORMANCE_PROFILE",
		"sudo --preserve-env=OVERLAYS,BBOX_DOCKER_HOST,BBOX_WITH_BROWSER42,FORCE,PERFORMANCE_PROFILE env BBOX_IN_GUEST=1 "},
	{"packaging/macos/engine.sh", `env BBOX_IN_GUEST=1 ${udp_env} "$@"`, "env BBOX_IN_GUEST=1 BBOX_HOST_LAN_ADDR=192.168.1.20 BBOX_HOST_UDP_PORT=51830 ./bbox run"},
	{"packaging/macos/engine.sh", "boot the engine (first run: fetch Lima, download the guest image,",
		"boot the engine (first run: fetch Lima, download the guest image, install Docker CE 28.5.2 pinned — ~5 min on a normal line)"},
	{"packaging/macos/engine.sh", "install Docker CE 28.5.2 pinned — ~5 min on a normal line)", "install Docker CE 28.5.2 pinned — ~5 min on a normal line)"},
	{"packaging/macos/engine.sh", "post_run_udp_note() {", "(post_run_udp_note)"},
	{"packaging/macos/fetch-runtime.sh", `LIMACTL="${DEST}/bin/limactl"`, "/Users/u/.bbox/macos/lima-2.2.0/bin/limactl (limactl version 2.2.0)"},
	{"packaging/macos/fetch-runtime.sh", `DEST="${BBOX_MACOS_HOME}/lima-${LIMA_VERSION}"`, "Lima 2.2.0 has not landed at /Users/u/.bbox/macos/lima-2.2.0/bin/limactl"},
	{"packaging/macos/engine.yaml", "'ExecStart=/usr/bin/dockerd -H fd:// -H unix:///run/bbox-docker.sock --containerd=/run/containerd/containerd.sock'",
		"'ExecStart=/usr/bin/dockerd -H fd:// -H unix:///run/bbox-docker.sock --containerd=/run/containerd/containerd.sock'"},
	{"packaging/macos/engine.yaml", `case "${v}" in 28.*)`, "— 28.x required"},
	{"packaging/macos/engine.yaml", `echo >&2 "engine is ${v}, expected 28.x"`, "engine is 29.0.1, expected 28.x"},
	{"packaging/macos/engine.yaml", `See "/var/log/cloud-init-output.log" in the guest`, `See "/var/log/cloud-init-output.log" in the guest`},
	{"packaging/macos/engine.yaml", "V='5:28.5.2-1~ubuntu.24.04~noble'", "Docker CE 28.5.2 pinned"},
	{"debian-install.sh", "DOCKER_MAJOR=28", "this platform needs Docker 28.x"},
	{"debian-install.sh", `echo "Error: Docker ${have} is installed; this platform needs Docker ${DOCKER_MAJOR}.x." >&2`, "Docker 29.1.3 is installed; this platform needs Docker 28.x."},
	{"debian-install.sh", "Re-run with BBOX_REPLACE_DOCKER=1 to replace it (containers stop; volumes are kept).", "Re-run with BBOX_REPLACE_DOCKER=1 to replace it (containers stop; volumes are kept)"},
	{"scripts/ci-env.sh", `[ -n "${OFFICE_DOMAIN:-}" ] || echo "PERFORMANCE_PROFILE=ci-small"`, "PERFORMANCE_PROFILE=ci-small comes with the .env scripts/ci-env.sh writes"},
	{"platform/manager/select-profile.py", `FLOOR = "ci-small"`, "PERFORMANCE_PROFILE=ci-small in .env — the floor bbox means to fall back to"},
	{"ai/context/healthy-baseline.md", "Traefik v3.3's docker client speaks API 1.24, but Docker 29 rejects clients", "traefik v3.3 speaks docker API 1.24, Docker 29 refuses clients"},
	{"ai/context/running-on-wsl.md", "Error code: Wsl/Service/0x8007274c", "WSL did not answer (Wsl/Service/0x8007274c)"},
	{"ai/context/running-on-wsl.md", `should treat that as "unknown, retry"`, "unknown, not missing"},
}

// TestPlanQuotesBbox holds every copy both ways: the bash it copies must still say it, and dgo must
// still print it — in the doctor's or the plan's output on some recorded machine. A line that
// changes in bbox, or a copy that drifts in dgo, fails here by name. (Until a later slice moves
// provisioning into dgo, the bash owns these and dgo quotes them.)
func TestPlanQuotesBbox(t *testing.T) {
	printed := everyOutput(t)
	for _, q := range quotes {
		if !strings.Contains(repoFile(t, q.file), q.bash) {
			t.Errorf("%s no longer says %q — dgo engine copies it", q.file, q.bash)
		}
		if !strings.Contains(printed, q.said) {
			t.Errorf("dgo engine no longer prints %q — its copy of %s's %q", q.said, q.file, q.bash)
		}
	}
	if got := limaPin(System{Read: func(p string) ([]byte, error) { return os.ReadFile(filepath.FromSlash(p)) }}, filepath.ToSlash(repoRoot(t))); got == "" {
		t.Error("the Lima pin cannot be read from packaging/macos/fetch-runtime.sh")
	}
	t.Logf("%d quotations: still in the bash, still in what dgo prints", len(quotes))
}

// TestTheGeneratedEnvIsWhatCiEnvShWrites runs scripts/ci-env.sh itself — bbox run's call on the
// cloud sandbox, in a directory holding only the checkout's .env.ex, its secret source (openssl) and
// its python steps answered — and requires the profile line it writes to be the one dgo reads off it.
func TestTheGeneratedEnvIsWhatCiEnvShWrites(t *testing.T) {
	sh := bash(t)
	gen := t.TempDir()
	if err := os.WriteFile(filepath.Join(gen, ".env.ex"), []byte(repoFile(t, ".env.ex")), 0o644); err != nil {
		t.Fatal(err)
	}
	script := filepath.Join(t.TempDir(), "gen.sh")
	if err := os.WriteFile(script, []byte("set -uo pipefail\nopenssl() { echo 0123456789abcdef0123456789abcdef0123456789abcdef; }\n"+
		"python3() { :; }\nexport -f openssl python3\ncd \"$1\" && bash \"$2\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command(sh, filepath.ToSlash(script), filepath.ToSlash(gen), filepath.ToSlash(filepath.Join(repoRoot(t), "scripts", "ci-env.sh"))).CombinedOutput(); err != nil {
		t.Fatalf("scripts/ci-env.sh: %v\n%s", err, out)
	}
	env, _ := os.ReadFile(filepath.Join(gen, ".env"))
	written, found := envProfile(env)
	l := ciEnvRE.FindStringSubmatch(repoFile(t, "scripts/ci-env.sh"))
	if !found || l == nil || "PERFORMANCE_PROFILE="+written != l[1] {
		t.Fatalf("ci-env.sh wrote PERFORMANCE_PROFILE=%q (%v); dgo reads %q off the script", written, found, l)
	}
}

// TestTheDeadlineHoldsWhenAGrandchildKeepsThePipe: a call whose program has a child holding the
// output pipe (limactl's ssh) still returns at its deadline, plus the WaitDelay for the pipe.
func TestTheDeadlineHoldsWhenAGrandchildKeepsThePipe(t *testing.T) {
	sh := bash(t)
	defer func(d time.Duration) { callTimeout = d }(callTimeout)
	callTimeout = 2 * time.Second
	start := time.Now()
	_, err := run(sh, "-c", "sleep 30 & wait")
	if took := time.Since(start); !errors.Is(err, errTimeout) || took > 15*time.Second {
		t.Fatalf("returned after %s with %v: the 2 s deadline (plus 5 s for the pipe) did not hold", took.Round(time.Second), err)
	}
}

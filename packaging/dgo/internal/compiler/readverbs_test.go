package compiler

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// ── the oracle: reconcile.py's own main(), one Python process per checkout ─────────────────────────

// cmds are the native verbs as dgo routes them (main.go's nativeVerbs).
var cmds = map[string]func(string, []string, io.Writer, io.Writer) int{
	"validate": ValidateCmd, "enabled-apps": EnabledAppsCmd, "services": ServicesCmd,
	"required-by": RequiredByCmd, "compose-services": ComposeServicesCmd,
	"capability-provider": CapabilityProviderCmd, "blueprints": BlueprintsCmd,
	"generations": GenerationsCmd, "office-get": OfficeGetCmd, "remote-get": RemoteGetCmd,
}

// call is one command line — the verb, then its arguments — and the COLUMNS it runs under (nil:
// unset). stderr is compared byte for byte, except where Python's own words cannot be reproduced:
// dies is where reconcile.py dies (a traceback, or PyYAML's message) and dgo prints one FATAL line
// instead — the same exit code and stdout, dgo's line starting with dies, Python's with dies or a
// traceback; pulled compares stderr as a set of lines, each "X: pulled in as provider …" cut after
// the provider — which capability and which consumer Python names depends on the order its set
// iteration meets them in (PYTHONHASHSEED decides), dgo's on sorted order, always.
//
// write lists files to put in place before the call — a nil body removes the file — so that many
// manifests and state files are asked in one Python process. Wherever reconcile.py dies with a
// traceback, dgo must answer as a dies case does, with the prefix "FATAL ".
type call struct {
	argv   []string
	cols   *string
	dies   string
	pulled bool
	write  map[string]*string
}

type answer struct {
	Stdout, Stderr string
	Code           int
}

// driver imports reconcile.py and calls its main() once per command line the way the interpreter
// runs it: argv and COLUMNS set, stdout and stderr captured, a SystemExit turned into the exit code
// (a message printed to stderr and exit 1), an exception into a traceback line and exit 1. One
// process answers hundreds of command lines; TestTheDriverAnswersWhatReconcilePyAnswers shows that
// it answers what `python3 reconcile.py …` answers.
const driver = `import contextlib, io, json, os, sys
script = sys.argv[1]
sys.path.insert(0, os.path.dirname(script))
import reconcile
answers = []
for case in json.load(sys.stdin):
    for rel, body in (case.get("write") or {}).items():
        path = os.path.join(os.getcwd(), rel)
        if body is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(body.encode("utf-8"))
    if case["cols"] is None:
        os.environ.pop("COLUMNS", None)
    else:
        os.environ["COLUMNS"] = case["cols"]
    sys.argv = [script] + case["argv"]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = reconcile.main()
        except SystemExit as e:
            code = e.code
            if code is None:
                code = 0
            elif not isinstance(code, int):
                print(code, file=sys.stderr)
                code = 1
        except Exception as e:
            print("Traceback (most recent call last):\n%s: %s" % (type(e).__name__, e), file=sys.stderr)
            code = 1
    answers.append({"stdout": out.getvalue(), "stderr": err.getvalue(), "code": code})
sys.stdout.write(json.dumps(answers))`

// pythonAnswers runs every call through the checkout's own reconcile.py, in one process.
func pythonAnswers(t *testing.T, repo string, calls []call) []answer {
	t.Helper()
	return pythonAnswersSeeded(t, repo, calls, "0")
}

// pythonAnswersSeeded is pythonAnswers under a PYTHONHASHSEED of the caller's choice.
func pythonAnswersSeeded(t *testing.T, repo string, calls []call, seed string) []answer {
	t.Helper()
	py := python(t)
	type wire struct {
		Argv  []string           `json:"argv"`
		Cols  *string            `json:"cols"`
		Write map[string]*string `json:"write"`
	}
	in := make([]wire, len(calls))
	for i, c := range calls {
		in[i] = wire{c.argv, c.cols, c.write}
	}
	body, _ := json.Marshal(in)
	cmd := exec.Command(py[0], append(py[1:], "-c", driver, filepath.Join(repo, "platform", "manager", "reconcile.py"))...)
	cmd.Dir = repo
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONHASHSEED="+seed)
	cmd.Stdin = bytes.NewReader(body)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	raw, err := cmd.Output()
	if err != nil {
		t.Fatalf("the driver: %v\n%s", err, stderr.String())
	}
	var out []answer
	if err := json.Unmarshal(raw, &out); err != nil || len(out) != len(calls) {
		t.Fatalf("the driver answered %d of %d: %v", len(out), len(calls), err)
	}
	return out
}

// dgoAnswer runs one call through the native verb, under the call's COLUMNS, its files in place.
func dgoAnswer(repo string, c call) answer {
	for rel, body := range c.write {
		path := filepath.Join(repo, filepath.FromSlash(rel))
		if body == nil {
			os.Remove(path)
			continue
		}
		os.MkdirAll(filepath.Dir(path), 0o755)
		os.WriteFile(path, []byte(*body), 0o644)
	}
	if c.cols == nil {
		os.Unsetenv("COLUMNS")
	} else {
		os.Setenv("COLUMNS", *c.cols)
	}
	var out, errb bytes.Buffer
	code := cmds[c.argv[0]](repo, c.argv[1:], &out, &errb)
	return answer{out.String(), errb.String(), code}
}

// agree asks reconcile.py and dgo every call and reports each difference.
func agree(t *testing.T, repo string, calls []call) {
	t.Helper()
	compare(t, repo, calls, pythonAnswers(t, repo, calls))
}

// compare asks dgo every call and holds each answer against reconcile.py's.
func compare(t *testing.T, repo string, calls []call, want []answer) {
	t.Helper()
	old, had := os.LookupEnv("COLUMNS")
	defer func() {
		if had {
			os.Setenv("COLUMNS", old)
		} else {
			os.Unsetenv("COLUMNS")
		}
	}()
	for i, c := range calls {
		got, w := dgoAnswer(repo, c), want[i]
		name := strings.Join(c.argv, " ")
		if c.cols != nil {
			name = "COLUMNS=" + *c.cols + " " + name
		}
		switch {
		case got.Code != w.Code || got.Stdout != w.Stdout && !sameFailures(got.Stdout, w.Stdout):
			t.Errorf("%s\n--- dgo (exit %d):\n%s--- reconcile.py (exit %d):\n%s--- dgo stderr:\n%s--- reconcile.py stderr:\n%s",
				name, got.Code, got.Stdout, w.Code, w.Stdout, got.Stderr, w.Stderr)
		case c.dies != "" || strings.HasPrefix(w.Stderr, "Traceback"):
			dies := c.dies
			if dies == "" {
				dies = "FATAL "
			}
			if !strings.HasPrefix(got.Stderr, dies) || strings.Count(got.Stderr, "\n") != 1 ||
				!strings.HasPrefix(w.Stderr, dies) && !strings.HasPrefix(w.Stderr, "Traceback") {
				t.Errorf("%s: both must stop at %q\n--- dgo stderr:\n%s--- reconcile.py stderr:\n%s", name, dies, got.Stderr, w.Stderr)
			}
		case c.pulled:
			if a, b := lineSet(got.Stderr), lineSet(w.Stderr); a != b {
				t.Errorf("%s: stderr lines differ\n--- dgo:\n%s\n--- reconcile.py:\n%s", name, a, b)
			}
		case got.Stderr != w.Stderr:
			t.Errorf("%s: stderr differs\n--- dgo:\n%s--- reconcile.py:\n%s", name, got.Stderr, w.Stderr)
		}
	}
	t.Logf("%d command lines: dgo answers what reconcile.py answers", len(calls))
}

var pulledFor = regexp.MustCompile(`(pulled in as provider) of '.*' for \S+$`)

func lineSet(s string) string {
	lines := strings.Split(strings.TrimSuffix(s, "\n"), "\n")
	for i, l := range lines {
		lines[i] = pulledFor.ReplaceAllString(l, "$1")
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n")
}

// sameFailures: two MANIFEST VALIDATION FAILED lists with the same lines. Python meets an app's missing
// and unknown fields in a set's (hash) order; dgo in sorted order.
func sameFailures(a, b string) bool {
	const head = "MANIFEST VALIDATION FAILED:\n"
	return strings.HasPrefix(a, head) && strings.HasPrefix(b, head) && lineSet(a) == lineSet(b)
}

func argv(words ...string) call { return call{argv: words} }

// TestTheDriverAnswersWhatReconcilePyAnswers: the driver against `python3 reconcile.py …` as a
// process, on an answer, a refusal of main()'s own and one of argparse's.
func TestTheDriverAnswersWhatReconcilePyAnswers(t *testing.T) {
	py := python(t)
	root := officeRoot(t)
	calls := []call{argv("required-by", "--app", "postgres"), argv("compose-services"), argv("office-get", "--state", "x")}
	driven := pythonAnswers(t, root, calls)
	env := []string{"PYTHONUTF8=1", "PYTHONIOENCODING=utf-8"}
	for _, kv := range os.Environ() {
		if !strings.HasPrefix(kv, "COLUMNS=") { // the driven calls run with COLUMNS unset
			env = append(env, kv)
		}
	}
	for i, c := range calls {
		cmd := exec.Command(py[0], append(py[1:], append([]string{filepath.Join(root, "platform", "manager", "reconcile.py")}, c.argv...)...)...)
		cmd.Dir = root
		cmd.Env = env
		var out, errb bytes.Buffer
		cmd.Stdout, cmd.Stderr = &out, &errb
		code := 0
		if err := cmd.Run(); err != nil {
			ee, ok := err.(*exec.ExitError)
			if !ok {
				t.Fatal(err)
			}
			code = ee.ExitCode()
		}
		// a process's text-mode stdout writes CRLF on Windows; the contract (and Linux) is LF
		got := answer{strings.ReplaceAll(out.String(), "\r\n", "\n"), strings.ReplaceAll(errb.String(), "\r\n", "\n"), code}
		if got != driven[i] {
			t.Errorf("%v: the process answered %+v, the driver %+v", c.argv, got, driven[i])
		}
	}
}

// TestReadVerbsMatchPythonOnThisCheckout: every read-only verb on the office's own catalog and
// state — asked of every app and every capability the catalog declares — and main()'s own refusals.
func TestReadVerbsMatchPythonOnThisCheckout(t *testing.T) {
	root := officeRoot(t)
	cat, err := LoadCatalog(root)
	if err != nil {
		t.Fatal(err)
	}
	calls := []call{
		argv("services"), argv("services", "--exclude", "nosuch,postgres", "--exclude", "db"),
		argv("services", "--for", "nosuch"), argv("services", "--for", "indox,mail"),
		argv("required-by"), argv("required-by", "--app", "nosuch"),
		argv("compose-services"), argv("compose-services", "--app", "nosuch"),
		argv("capability-provider"), argv("capability-provider", "--capability", "nothing-provides-this"),
		argv("blueprints"), argv("blueprints", "--for", "nosuch"),
		argv("generations"), argv("office-get"), argv("remote-get"),
		argv("validate", "--app", "x", "--json"), argv("validate", "--extra"),
		argv("enabled-apps", "--for", "x"), argv("enabled-apps", "extra"),
	}
	calls[3].pulled = true // two roots: see call
	caps := map[string]bool{}
	for _, aid := range cat.Order {
		calls = append(calls, argv("services", "--for", aid), argv("required-by", "--app", aid),
			argv("compose-services", "--app", aid), argv("blueprints", "--for", aid))
		entries, err := cat.Apps[aid].entries("capabilities")
		if err != nil {
			t.Fatal(err)
		}
		for _, c := range entries {
			if n, ok := c["name"].(string); ok {
				caps[n] = true
			}
		}
	}
	for _, c := range sortedKeys(caps) {
		calls = append(calls, argv("capability-provider", "--capability", c))
	}
	agree(t, root, calls)
}

// pyFixture is fixture() with the compiler itself copied in, so that reconcile.py answers for the
// fixture's catalog and state (it finds its checkout from its own path).
func pyFixture(t *testing.T, files map[string]string, state string) string {
	t.Helper()
	repo := fixture(t, files, state)
	for _, f := range []string{"reconcile.py", "serve.py"} {
		src, err := os.ReadFile(filepath.Join(repoRoot(t), "platform", "manager", f))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(filepath.Join(repo, "platform", "manager"), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(repo, "platform", "manager", f), src, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return repo
}

// officeState: every disposition shape, an app only the state knows, the office's record with values
// of every kind str() spells, and a remote block with every kind of scalar json.dumps escapes.
const officeState = `schema_version: 1
apps:
  db:     { enabled: true }
  edge:   { state: enabled, by: cli }
  lib:    { enabled: true }
  web:    { state: enabled, by: user }
  api:    { enabled: true }
  twin:   { enabled: true }
  idle:   { state: disabled, by: user }
  up:     { state: archived }
  escape: { enabled: false }
  ghost:  { enabled: true }
office:
  name: "משרד הבדיקות"
  animal: deer
  hue: 12
  terms_version: ~
  terms_accepted_at: true
  installed_at: [a, 1.5]
  bogus: x
remote:
- office: peer
  label: {he: "שלום 🏠", en: Peer}
  address: 10.79.3.2
  fetched: 1791129653
  ratio: 0.1
  big: 1.0e+20
  inf: .inf
  nan: .nan
  ok: yes
  none: ~
  ctrl: "tab\there\u0001 del\u007f"
  quote: 'say "hi" \ back'
  nested: [1, [2, {a: b}], {}]
  80: port
  apps:
  - {app: x, alias: y, port: 8080}
`

// TestReadVerbsMatchPythonOnAFixture: a small office where every rule of the eight verbs has a case —
// the closure and its order, first mention of a service wins, a stale --exclude, the legacy-lane
// note, a library without compose, an app without one, one and two and no providers, blueprint
// directories that are trimmed, relative, the app itself, missing, outside the checkout, generations
// numbered out of order beside a file and a word, and the two blocks of the state file.
func TestReadVerbsMatchPythonOnAFixture(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"platform-base/db/app.json":                   manifest("db", 1, `"compose":"docker-compose.yml","capabilities":[{"name":"sql","type":"protocol"}]`),
		"platform-base/db/docker-compose.yml":         "services:\n  db:\n    image: postgres\n  db-backup:\n    image: x\nvolumes:\n  data: {}\n",
		"platform-base/edge/app.json":                 manifest("edge", 1, `"compose":"docker-compose.yml","capabilities":[{"name":"routing","type":"protocol"}]`),
		"platform-base/edge/docker-compose.yml":       "services:\n  edge: {image: traefik}\n  socket-proxy: {image: y}\n",
		"platform-base/lib/app.json":                  manifestRaw("lib", 2, `"title":{"he":"ספרייה"},"kind":"library","compose":null,"capabilities":[{"name":"ui-kit","type":"protocol"}],"blueprints":{"n8n":"."}`),
		"apps/web/app.json":                           manifest("web", 3, `"compose":"docker-compose.yml","use":[{"capability":"sql"},{"capability":"routing"}],"blueprints":{"n8n":"flows"}`),
		"apps/web/docker-compose.yml":                 "services:\n  web: {image: a}\n  worker: {image: b}\n  db: {image: c}\n",
		"apps/web/flows/one.json":                     "{}",
		"apps/api/app.json":                           manifest("api", 3, `"compose":"compose.yml","use":[{"capability":"sql"}],"capabilities":[{"name":"api","type":"service"}],"blueprints":{"n8n":" flows/api "}`),
		"apps/api/compose.yml":                        "services:\n  api: {image: a}\n",
		"apps/api/flows/api/x.json":                   "{}",
		"apps/twin/app.json":                          manifest("twin", 3, `"capabilities":[{"name":"api","type":"service"}]`),
		"apps/idle/app.json":                          manifest("idle", 3, `"blueprints":{"n8n":"nope"}`),
		"apps/up/app.json":                            manifest("up", 3, `"blueprints":{"n8n":"../web/flows"}`),
		"apps/escape/app.json":                        manifest("escape", 3, `"blueprints":{"n8n":"../../.."}`),
		".generated/generations/0001/compose.yml":     "x",
		".generated/generations/0001/.hidden":         "x",
		".generated/generations/0001/sub/a":           "x",
		".generated/generations/0001/sub/deeper/b":    "x",
		".generated/generations/0010/x":               "x",
		".generated/generations/9/x":                  "x",
		".generated/generations/notes/x":              "x",
		".generated/generations/0003":                 "a file named like a generation",
		".generated/generations/0002/.keep-empty-dir": "",
	}, officeState)
	if err := os.Remove(filepath.Join(repo, ".generated", "generations", "0002", ".keep-empty-dir")); err != nil {
		t.Fatal(err)
	}
	calls := []call{
		argv("services"), argv("services", "--for", "web"), argv("services", "--for", " , "),
		argv("services", "--for", "web", "--exclude", "db,ghost-svc", "--exclude", "worker"),
		{argv: []string{"services", "--for", "api", "--for", "web"}, pulled: true},
		argv("services", "--for", "ghost"),
		argv("required-by", "--app", "db"), argv("required-by", "--app", "edge"),
		argv("required-by", "--app", "web"), argv("required-by", "--app", "idle"), argv("required-by", "--app", "ghost"),
		argv("compose-services", "--app", "db"), argv("compose-services", "--app", "web"),
		argv("compose-services", "--app", "lib"), argv("compose-services", "--app", "twin"), argv("compose-services", "--app="),
		argv("capability-provider", "--capability", "sql"), argv("capability-provider", "--capability", "api"),
		argv("capability-provider", "--capability", "ui-kit"), argv("capability-provider", "--capability", "nothing"),
		argv("capability-provider", "--capability", ""),
		argv("blueprints"), argv("blueprints", "--for", "up,lib"), argv("blueprints", "--for", "idle"),
		argv("blueprints", "--for", "web,ghost", "--for", "twin"),
		{argv: []string{"blueprints", "--for", "escape"}, dies: "FATAL "},
		argv("generations"), argv("office-get"), argv("remote-get"), argv("enabled-apps"), argv("validate"),
	}
	agree(t, repo, calls)
}

// TestCapabilityProviderCountsWhatIsPulledIn (DGO-993): a provider that runs only because an enabled
// app pulls it in IS the provider. The clean install of the public copy (2026-10-22) had n8n disabled
// in the state and pulled in by bina-ds; capability-provider asked only the enabled set, found no
// `workflow`, and the agent came up with none of its workflows. Both compilers answer alike, and the
// answer is the pulled-in app; an app that is disabled and pulled in by nobody still answers nothing.
func TestCapabilityProviderCountsWhatIsPulledIn(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"apps/agent/app.json":  manifest("agent", 3, `"use":[{"capability":"workflow"}]`),
		"apps/engine/app.json": manifest("engine", 3, `"capabilities":[{"name":"workflow","type":"service"}]`),
		"apps/spare/app.json":  manifest("spare", 3, `"capabilities":[{"name":"spare-cap","type":"service"}]`),
	}, stateHead+"  agent: { enabled: true }\n  engine: { state: disabled, by: user }\n  spare: { state: disabled }\n")
	agree(t, repo, []call{
		argv("capability-provider", "--capability", "workflow"),
		argv("capability-provider", "--capability", "spare-cap"),
	})
	var out, errb bytes.Buffer
	if code := CapabilityProviderCmd(repo, []string{"--capability", "workflow"}, &out, &errb); code != 0 || out.String() != "engine\n" {
		t.Fatalf("the pulled-in provider is not the answer: exit %d, stdout %q, stderr %q", code, out.String(), errb.String())
	}
	out.Reset()
	if code := CapabilityProviderCmd(repo, []string{"--capability", "spare-cap"}, &out, &errb); code != 1 || out.String() != "" {
		t.Fatalf("a disabled app nobody pulls in answered: exit %d, stdout %q", code, out.String())
	}
	// ...and a REFUSED plan answers nothing, as enabled-apps refuses it, even for a capability its
	// closure would name (the second reader): here the agent also requires what nothing provides.
	refused := pyFixture(t, map[string]string{
		"apps/agent/app.json":  manifest("agent", 3, `"use":[{"capability":"workflow"},{"capability":"nothing-provides-this"}]`),
		"apps/engine/app.json": manifest("engine", 3, `"capabilities":[{"name":"workflow","type":"service"}]`),
	}, stateHead+"  agent: { enabled: true }\n  engine: { state: disabled, by: user }\n")
	agree(t, refused, []call{argv("capability-provider", "--capability", "workflow")})
	out.Reset()
	errb.Reset()
	if code := CapabilityProviderCmd(refused, []string{"--capability", "workflow"}, &out, &errb); code != 1 || out.String() != "" ||
		!strings.Contains(errb.String(), "  ERROR ") {
		t.Fatalf("a refused plan answered: exit %d, stdout %q, stderr %q", code, out.String(), errb.String())
	}
}

// TestBlueprintsCountWhatIsPulledIn (DGO-1001): `blueprints` lists the workflow engine's own workflows
// where the plan only pulls the engine in, as it lists an enabled app's. n8n, pulled in by bina-ds and
// off in the state, has workflows of its own, and a fresh install never got them (0 of 4). Another app
// the plan only pulls in keeps its automations off (chat pulling INDOX in on the HP), as do a disabled
// app nobody pulls in and an app whose state row names another office; a refused plan pulls nothing in.
// Both compilers answer alike.
func TestBlueprintsCountWhatIsPulledIn(t *testing.T) {
	flows := func(id, extra string) string {
		if extra != "" {
			extra = "," + extra
		}
		return manifest(id, 3, `"blueprints":{"n8n":"flows"}`+extra)
	}
	files := map[string]string{
		"apps/agent/app.json":  flows("agent", `"use":[{"capability":"workflow"},{"capability":"lib-api"}]`),
		"apps/engine/app.json": flows("engine", `"capabilities":[{"name":"workflow","type":"service"}]`),
		"apps/lib/app.json":    flows("lib", `"capabilities":[{"name":"lib-api","type":"service"}]`),
		"apps/spare/app.json":  flows("spare", ""),
		"apps/remote/app.json": flows("remote", ""),
	}
	for _, id := range []string{"agent", "engine", "lib", "spare", "remote"} {
		files["apps/"+id+"/flows/a.workflow.ts"] = "export {}\n"
	}
	state := stateHead + "  agent: { enabled: true }\n  engine: { state: disabled, by: user }\n" +
		"  lib: { state: disabled, by: cli }\n  spare: { state: disabled }\n  remote: { state: enabled, workflows: vps1 }\n"
	repo := pyFixture(t, files, state)
	agree(t, repo, []call{argv("blueprints")})
	var out, errb bytes.Buffer
	if code := BlueprintsCmd(repo, nil, &out, &errb); code != 0 || out.String() != "agent\tapps/agent/flows\nengine\tapps/engine/flows\n" {
		t.Fatalf("not the engine's and the enabled app's workflows alone: exit %d, stdout %q, stderr %q", code, out.String(), errb.String())
	}
	// ...and a REFUSED plan keeps the enabled apps: its closure would name the engine, which only the
	// refused plan pulls in.
	files["apps/agent/app.json"] = flows("agent", `"use":[{"capability":"workflow"},{"capability":"lib-api"},{"capability":"nothing-provides-this"}]`)
	refused := pyFixture(t, files, state)
	agree(t, refused, []call{argv("blueprints")})
	out.Reset()
	errb.Reset()
	if code := BlueprintsCmd(refused, nil, &out, &errb); code != 0 || out.String() != "agent\tapps/agent/flows\n" {
		t.Fatalf("a refused plan listed a pulled-in app: exit %d, stdout %q, stderr %q", code, out.String(), errb.String())
	}
}

// TestReadVerbsStopWherePythonStops: manifests and compose files reconcile.py cannot read. The verbs
// that validate print the failure list; required-by and compose-services, which do not validate,
// answer — or stop at the file they cannot read, as reconcile.py does.
func TestReadVerbsStopWherePythonStops(t *testing.T) {
	compose := func(app string) string { return "FATAL " + filepath.Join("apps", app, "c.yml") }
	repo := pyFixture(t, map[string]string{
		"apps/bad/app.json":     `{"id":"bad","layer":3,"kind":"service","compose":"c.yml"}`,
		"apps/bad/c.yml":        "services: [unclosed\n",
		"apps/list/app.json":    manifest("list", 3, `"compose":"c.yml"`),
		"apps/list/c.yml":       "- a\n- b\n",
		"apps/empty/app.json":   manifest("empty", 3, `"compose":"c.yml"`),
		"apps/empty/c.yml":      "# nothing\n",
		"apps/nulls/app.json":   manifest("nulls", 3, `"compose":"c.yml"`),
		"apps/nulls/c.yml":      "services:\nvolumes: {}\n",
		"apps/svclist/app.json": manifest("svclist", 3, `"compose":"c.yml"`),
		"apps/svclist/c.yml":    "services: [a, b]\n",
		"apps/gone/app.json":    manifest("gone", 3, `"compose":"c.yml"`),
		"apps/no/app.json":      manifest("no", 3, `"compose":false`),
	}, "schema_version: 1\napps:\n  bad: { enabled: true }\n  list: { enabled: true }\n")
	calls := []call{
		argv("services"), argv("validate"), argv("enabled-apps"), argv("blueprints"), argv("generations"),
		argv("capability-provider", "--capability", "x"), argv("capability-provider"),
		argv("required-by", "--app", "bad"), argv("required-by", "--app", "list"),
		argv("compose-services", "--app", "empty"), argv("compose-services", "--app", "nulls"),
		argv("compose-services", "--app", "no"),
		{argv: []string{"compose-services", "--app", "bad"}, dies: compose("bad")},
		{argv: []string{"compose-services", "--app", "list"}, dies: compose("list")},
		{argv: []string{"compose-services", "--app", "svclist"}, dies: compose("svclist")},
		{argv: []string{"compose-services", "--app", "gone"}, dies: compose("gone")},
		argv("office-get"), argv("remote-get"),
	}
	agree(t, repo, calls)
	// a compose that is not a path: reconcile.py's validate() itself dies on it (a TypeError where it
	// joins the path — Go's Validate reports the type instead), so only the verbs that do not
	// validate are asked
	repo = pyFixture(t, map[string]string{"apps/num/app.json": manifest("num", 3, `"compose":5`)},
		stateHead+"  num: { enabled: true }\n")
	agree(t, repo, []call{
		argv("required-by", "--app", "num"),
		{argv: []string{"compose-services", "--app", "num"}, dies: "FATAL num: "},
	})
}

// TestReadVerbsWithoutAStateFile: a checkout that has compiled before and lost its state file. The
// verbs that load the state refuse in ensure_state's words; office-get answers {}; remote-get stops.
func TestReadVerbsWithoutAStateFile(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"apps/a/app.json":        manifest("a", 3, `"compose":"c.yml"`),
		"apps/a/c.yml":           "services:\n  a: {image: x}\n",
		".generated/compose.yml": "include: []\n",
	}, "")
	agree(t, repo, []call{
		argv("services"), argv("required-by", "--app", "a"), argv("capability-provider", "--capability", "x"),
		argv("compose-services", "--app", "a"), argv("office-get"),
		{argv: []string{"remote-get"}, dies: "FATAL platform.state.yaml: "},
	})
}

// TestFirstRunCreatesTheStateLikePython: required-by on a fresh checkout creates the state file from
// the tracked default, says so on stdout before its answer, and writes the same bytes as Python —
// asked of two copies, since the first answer changes the checkout.
func TestFirstRunCreatesTheStateLikePython(t *testing.T) {
	files := map[string]string{
		"apps/a/app.json":             manifest("a", 3, `"use":[{"capability":"x"}]`),
		"platform-base/p/app.json":    manifest("p", 1, `"capabilities":[{"name":"x","type":"protocol"}]`),
		"platform.state.default.yaml": stateHead + "  a: { enabled: true }\r\n  p: { enabled: false }\n",
	}
	pyRepo, goRepo := pyFixture(t, files, ""), fixture(t, files, "")
	c := argv("required-by", "--app", "p")
	want, got := pythonAnswers(t, pyRepo, []call{c})[0], dgoAnswer(goRepo, c)
	if got != want || !strings.HasPrefix(got.Stdout, "  info  platform.state.yaml: created from") {
		t.Fatalf("dgo %+v\nreconcile.py %+v", got, want)
	}
	a, _ := os.ReadFile(filepath.Join(pyRepo, stateName))
	b, _ := os.ReadFile(filepath.Join(goRepo, stateName))
	if len(a) == 0 || !bytes.Equal(a, b) {
		t.Fatalf("the created state files differ:\n%q\n%q", a, b)
	}
}

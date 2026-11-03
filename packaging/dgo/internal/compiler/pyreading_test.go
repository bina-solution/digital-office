package compiler

import (
	"encoding/hex"
	"encoding/json"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// ── what reconcile.py makes of values no validator refused, and of what it never validates ─────────
//
// Each test asks reconcile.py and dgo the same command lines while the files under them change: a
// manifest or a state file per case, in one Python process (call.write). Where Python dies with a
// traceback, dgo must stop the same way: the same exit code and stdout, one FATAL line (compare).

func text(s string) *string { return &s }

func jsonText(s string) string { b, _ := json.Marshal(s); return string(b) }

// with is a command line asked after files are put in place.
func with(write map[string]*string, words ...string) call { return call{argv: words, write: write} }

// TestFalsyBindingsAreNoBinding: a binding left empty, an empty mapping, a null provider, false, 0, ”
// or [] binds nothing in reconcile.py (`if bound and …`), and the consumer's default_provider decides
// — required-by is what app-management asks before it takes an app away, so a wrong [] there lets it
// remove a database an enabled app still needs. Every falsy form and the truthy ones beside them,
// through services, enabled-apps and required-by; then a bindings block that is no mapping.
func TestFalsyBindingsAreNoBinding(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"platform-base/db/app.json":  manifest("db", 1, `"compose":"c.yml","capabilities":[{"name":"sql","type":"protocol"}]`),
		"platform-base/db/c.yml":     "services:\n  db: {image: x}\n",
		"platform-base/db2/app.json": manifest("db2", 1, `"compose":"c.yml","capabilities":[{"name":"sql","type":"protocol"}]`),
		"platform-base/db2/c.yml":    "services:\n  db2: {image: x}\n",
		"apps/web/app.json":          manifest("web", 3, `"compose":"c.yml","use":[{"capability":"sql","default_provider":"db"}]`),
		"apps/web/c.yml":             "services:\n  web: {image: x}\n",
	}, stateHead+"  web: { enabled: true }\n")
	var calls []call
	for _, b := range []string{"  sql:\n", "  sql: {}\n", "  sql: {provider: ~}\n", "  sql: false\n", "  sql: 0\n", "  sql: ''\n", "  sql: []\n",
		"  sql: db2\n", "  sql: {provider: db2}\n", "  sql: nope\n", "  sql: 5\n", "  sql: true\n", "  sql: [db]\n", "  other: db2\n"} {
		state := map[string]*string{stateName: text(stateHead + "  web: { enabled: true }\nbindings:\n" + b)}
		for _, words := range [][]string{{"services"}, {"services", "--for", "web"}, {"enabled-apps"},
			{"required-by", "--app", "db"}, {"required-by", "--app", "db2"}} {
			calls = append(calls, with(state, words...))
		}
	}
	for _, b := range []string{"bindings:\n", "bindings: {}\n", "bindings: [sql]\n", "bindings: x\n"} {
		state := map[string]*string{stateName: text(stateHead + "  web: { enabled: true }\n" + b)}
		calls = append(calls, with(state, "services"), with(state, "required-by", "--app", "db"))
	}
	agree(t, repo, calls)
}

// TestRequiredByReadsManifestsAsPythonDoes: required-by validates nothing, so the resolver's own
// reading of a manifest is its answer — a present null strength is no strength, ops is set(ops or [])
// ("read" is four letters), a dict's keys are a set too — and where that reading raises, it dies.
func TestRequiredByReadsManifestsAsPythonDoes(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"platform-base/p/app.json": manifest("p", 1, `"capabilities":[{"name":"x","type":"protocol","required_ops":["read"]}]`),
		"apps/a/app.json":          manifest("a", 3, ""),
	}, stateHead+"  a: { enabled: true }\n  b: { enabled: true }\n")
	var calls []call
	for _, extra := range []string{
		`"use":[{"capability":"x"}]`,
		`"use":[{"capability":"x","strength":null}]`,
		`"use":[{"capability":"x","strength":"wants"}]`,
		`"use":[{"capability":"x","strength":5}]`,
		`"use":[{"capability":"x","ops":"read"}]`,
		`"use":[{"capability":"x","ops":["read"]}]`,
		`"use":[{"capability":"x","ops":["write"]}]`,
		`"use":[{"capability":"x","ops":[]}]`,
		`"use":[{"capability":"x","ops":{"read":1}}]`,
		`"use":[{"capability":"x","ops":[1,"write"]}]`,
		`"use":[{"capability":"x","ops":5}]`,
		`"use":[{"capability":"x","ops":[["read"]]}]`,
		`"use":[{"capability":"x","after":null}]`,
		`"use":[{"capability":"x","after":0,"dependency":"weak"}]`,
		`"use":[{"capability":["x"]}]`,
		`"use":[{"strength":"wants"}]`,
		`"use":[{}]`,
		`"use":[5]`,
		`"use":null`,
		`"use":"x"`,
		`"use":""`,
		`"use":{}`,
		`"capabilities":null`,
		`"capabilities":[{"type":"protocol"}]`,
		`"capabilities":[{"name":["y"]}]`,
		`"capabilities":"abc"`,
		`"use":[{"capability":"x"}],"capabilities":[{"name":"x","required_ops":null}]`,
		`"use":[{"capability":"x","strength":"conflicts"}],"capabilities":[{"name":"x"}]`,
	} {
		m := map[string]*string{"apps/a/app.json": text(manifest("a", 3, extra))}
		calls = append(calls, with(m, "required-by", "--app", "p"), with(m, "required-by", "--app", "a"))
	}
	agree(t, repo, calls)
}

// TestStateFileShapesAsPythonReadsThem: schema_version is compared by == (1.0 and true are 1; '1' is
// not), and an `apps:` that is no mapping, or an entry whose `state` is no text, ends a verb where
// Python's own reading of it raises — and only there (`services --for` and generations never ask).
func TestStateFileShapesAsPythonReadsThem(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"platform-base/p/app.json": manifest("p", 1, `"compose":"c.yml","capabilities":[{"name":"x","type":"protocol"}],"blueprints":{"n8n":"."}`),
		"platform-base/p/c.yml":    "services:\n  p: {image: x}\n",
	}, stateHead+"  p: { enabled: true }\n")
	var calls []call
	for _, st := range []string{
		"schema_version: 1.0\napps:\n  p: { enabled: true }\n",
		"schema_version: true\napps:\n  p: { enabled: true }\n",
		"schema_version: '1'\napps:\n  p: { enabled: true }\n",
		"schema_version: 2\napps:\n  p: { enabled: true }\n",
		"schema_version: 1.5\n",
		"apps:\n  p: { enabled: true }\n",
		"schema_version: 1\napps: [p]\n",
		"schema_version: 1\napps: [offices]\n",
		"schema_version: 1\napps: [offices, dgo-extend]\n",
		"schema_version: 1\napps: p\n",
		"schema_version: 1\napps: 5\n",
		"schema_version: 1\napps: []\n",
		"schema_version: 1\napps:\n  p: { state: yes }\n",
		"schema_version: 1\napps:\n  p: { state: [enabled] }\n",
		"schema_version: 1\napps:\n  p: { state: \"\\x1cenabled\" }\n",
		"schema_version: 1\napps:\n  p: { state: '', enabled: true }\n",
		"schema_version: 1\napps:\n  q: { state: yes }\n  p: { enabled: true }\n",
		"- a\n- b\n",
		"x\n",
	} {
		state := map[string]*string{stateName: text(st)}
		for _, words := range [][]string{{"services"}, {"services", "--for", "p"}, {"required-by", "--app", "p"},
			{"capability-provider", "--capability", "x"}, {"blueprints"}, {"blueprints", "--for", "p"}, {"generations"},
			{"enabled-apps"}, {"validate"}, {"office-get"}, {"remote-get"}} {
			calls = append(calls, with(state, words...))
		}
	}
	agree(t, repo, calls)
}

// TestPathsJoinedAndResolvedAsPathlibDoes: a blueprint directory is resolve()d — ".." through a
// directory that is not there collapses, as realpath(strict=False) makes it — and joined as pathlib
// joins: a root without a drive lands on the app's drive (Windows), a drive without a root on that
// drive. A compose file is only joined (Python opens it as the OS resolves it).
func TestPathsJoinedAndResolvedAsPathlibDoes(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"apps/web/app.json":       manifest("web", 3, ""),
		"apps/web/flows/one.json": "{}",
		"apps/web/c.yml":          "services:\n  web: {image: x}\n",
	}, stateHead+"  web: { enabled: true }\n")
	abs := filepath.Join(repo, "apps", "web")
	vol := filepath.VolumeName(abs)
	rooted := filepath.ToSlash(abs[len(vol):]) // a root and, on Windows, no drive
	dirs := []string{"nope/../flows", "flows/./", "flows/../flows", "./flows", "nope/..", "nope", "../web/flows", rooted + "/flows"}
	if vol != "" {
		dirs = append(dirs, vol+"flows", strings.ToLower(vol)+"flows")
	}
	var calls []call
	for _, d := range dirs {
		m := map[string]*string{"apps/web/app.json": text(manifest("web", 3, `"blueprints":{"n8n":`+jsonText(d)+`}`))}
		calls = append(calls, with(m, "blueprints"), with(m, "blueprints", "--for", "web"))
	}
	for _, c := range []string{"nope/../c.yml", rooted + "/c.yml"} {
		m := map[string]*string{"apps/web/app.json": text(manifest("web", 3, `"compose":`+jsonText(c)))}
		calls = append(calls, with(m, "compose-services", "--app", "web"), with(m, "validate"))
	}
	agree(t, repo, calls)
}

// TestGenerationsWithTiedNumbersListAsIterdirDoes: generations are ordered by int(name); names of one
// number keep the directory's own order — what iterdir() met first — on every file system.
func TestGenerationsWithTiedNumbersListAsIterdirDoes(t *testing.T) {
	files := map[string]string{"apps/a/app.json": manifest("a", 3, "")}
	for _, g := range []string{"0010", "010", "10", "2", "0002", "1", "notes"} {
		files[".generated/generations/"+g+"/x"] = "x"
	}
	agree(t, pyFixture(t, files, stateHead+"  a: { enabled: true }\n"), []call{argv("generations")})
}

// TestValidateReadsManifestsAsPythonDoes: the validator's own reading — a list it iterates, an entry
// it indexes, a name it hashes, a path it joins, a sort of the names it claimed — and where Python's
// raises, the verbs that validate end there; `layer` is compared by ==.
func TestValidateReadsManifestsAsPythonDoes(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"apps/a/app.json": manifest("a", 3, ""),
		"apps/b/app.json": manifest("b", 3, `"routing":[{"host":"x.localhost"}]`),
	}, stateHead+"  a: { enabled: true }\n")
	var calls []call
	for _, extra := range []string{
		`"capabilities":null`, `"capabilities":"x"`, `"capabilities":[5]`, `"capabilities":[{"type":"protocol"}]`,
		`"capabilities":[{"name":["x"],"type":"protocol"}]`, `"capabilities":[{"name":5,"type":"protocol"}]`,
		`"use":null`, `"use":[5]`, `"use":[{"capability":"x","strength":["requires"]}]`, `"use":[{"capability":"x","strength":null}]`,
		`"use":[{"strength":"bogus"}]`,
		`"routing":null`, `"routing":""`, `"routing":"abc"`, `"routing":[5]`, `"routing":[{"host":["h"]}]`, `"routing":[{"host":12}]`,
		`"routing":[{"module":"m"}]`, `"routing":[{"module":{"id":["m"]}}]`, `"routing":[{"module":{"id":"m"}},{"module":{"id":"m"}}]`,
		`"agent":null`, `"agent":"x"`, `"agent":{"context":5}`, `"agent":{"context":""}`, `"agent":{"context":"it's/../x"}`,
		`"compose":5`, `"compose":false`, `"compose":null`,
		`"kind":["service"]`, `"layer":true`, `"layer":3.0`, `"layer":false`,
	} {
		m := map[string]*string{"apps/a/app.json": text(manifestRaw("a", 3, `"title":{"he":"x"},"kind":"service",`+extra))}
		calls = append(calls, with(m, "validate"), with(m, "services"), with(m, "required-by", "--app", "b"))
	}
	agree(t, repo, calls)
}

// TestHashSeedsChangeOnlyWhatTheMaskCovers: Python's set order moves with PYTHONHASHSEED; dgo's order
// is sorted. Under twelve seeds, every exit code and stdout is the same, and stderr the same line set
// once a "pulled in" line is cut after its provider — on a fixture with three roots, two consumers of
// one provider, a provider of two capabilities, providers chosen by default_provider, the bridge.
func TestHashSeedsChangeOnlyWhatTheMaskCovers(t *testing.T) {
	repo := pyFixture(t, map[string]string{
		"platform-base/db/app.json":         manifest("db", 1, `"capabilities":[{"name":"sql","type":"protocol"}]`),
		"platform-base/db2/app.json":        manifest("db2", 1, `"capabilities":[{"name":"sql","type":"protocol"}]`),
		"platform-base/mq/app.json":         manifest("mq", 1, `"capabilities":[{"name":"queue","type":"protocol"},{"name":"bus","type":"protocol"}]`),
		"apps/a/app.json":                   manifest("a", 3, `"use":[{"capability":"sql","default_provider":"db"},{"capability":"queue"},{"capability":"legacy-x"}]`),
		"apps/b/app.json":                   manifest("b", 3, `"use":[{"capability":"sql","default_provider":"db"},{"capability":"bus"},{"capability":"legacy-y"}]`),
		"apps/c/app.json":                   manifest("c", 3, `"use":[{"capability":"sql","default_provider":"db2"},{"capability":"nothing"}]`),
		"apps/d/app.json":                   manifest("d", 3, `"use":[{"capability":"sql","default_provider":"db"}]`),
		"platform/legacy-capabilities.yaml": "legacy-x: old-x\nlegacy-y: old-y\n",
	}, stateHead+"  a: { enabled: true }\n  b: { enabled: true }\n  c: { enabled: true }\n  d: { enabled: true }\n")
	calls := []call{argv("services"), argv("services", "--for", "a,b"), argv("services", "--for", "a,b,d"),
		argv("enabled-apps"), argv("required-by", "--app", "db"), argv("required-by", "--app", "mq")}
	for i := range calls {
		calls[i].pulled = true
	}
	for seed := 0; seed < 12; seed++ {
		compare(t, repo, calls, pythonAnswersSeeded(t, repo, calls, strconv.Itoa(seed)))
	}
}

// TestHashSeedsOnThisCheckout: the same, on the office's own catalog, under the seeds the reviewer
// found reconcile.py naming another capability at.
func TestHashSeedsOnThisCheckout(t *testing.T) {
	root := officeRoot(t)
	checkout := []call{{argv: []string{"services", "--for", "mail,indox,drive"}, pulled: true},
		{argv: []string{"services", "--for", "indox,mail"}, pulled: true}}
	for _, seed := range []string{"1", "5", "7"} {
		compare(t, root, checkout, pythonAnswersSeeded(t, root, checkout, seed))
	}
}

// TestOfficeAndRemoteBlocksOfOddStateFiles: office-get and remote-get on state files of every shape
// whose reading is the compiler's, not the YAML reader's — documents that are no mapping, blocks of
// the wrong kind, YAML 1.1 numbers, floats, nested values str() spells as a repr, Python's own writer.
// (A YAML construct yamlish reads otherwise than PyYAML — NEL/LS/CR line breaks, control characters,
// timestamps, `...`, anchors and tags, ints past 64 bits, keys that are no text — belongs to the YAML
// reader and is not asked here.)
func TestOfficeAndRemoteBlocksOfOddStateFiles(t *testing.T) {
	repo := pyFixture(t, map[string]string{"apps/a/app.json": manifest("a", 3, "")}, stateHead+"  a: { enabled: true }\n")
	py := python(t)
	dump := func(code string) string {
		out, err := exec.Command(py[0], append(py[1:], "-c", "import sys, yaml\n"+code)...).Output()
		if err != nil {
			t.Fatal(err)
		}
		return strings.ReplaceAll(string(out), "\r\n", "\n")
	}
	states := []*string{nil,
		text(""), text("\n"), text("# c\n"), text("---\n"), text("null\n"), text("~\n"), text("[]\n"), text("- a\n- b\n"),
		text("x\n"), text("42\n"), text("{}\n"), text("office:\n"), text("office: []\n"), text("office: x\n"),
		text("office:\n  name: a\n  name: b\n"),
		text("office:\n  name: 0x1F\n  animal: 017\n  hue: 1_000\n  terms_version: 1:30\n"),
		text("office:\n  name: .inf\n  animal: -.inf\n  hue: .nan\n  terms_version: 1.0e+20\n  installed_at: 0.1\n"),
		text("office:\n  name: [1, [2, {x: y}], {}]\n  animal: {a: 1, b: [c]}\n"),
		text("office:\n  name: \"a\\x00b\"\n"), text("office:\n  name: 'שלום'\n  animal: 😀\n"),
		text("office:\r\n  name: crlf\r\n"), text("office:\n  name: |\n    multi\n    line\n"),
		text("office:\n  name: >\n    folded\n    text\n"), text("office:\n  name: 'multi\n    line quoted'\n"),
		text("office:\n  name: plain\n    continued\n"), text("office:\n\tname: tab\n"),
		text("office:\n  name: ''\n  animal: false\n  hue: 1.5\n  terms_version: 1.0e-7\n  installed_at: ~\n"),
		text("office:\n  name: x # comment\n  animal: 'it''s'\n  hue: \"tab\\there\"\n  bogus: 1\n"),
		text("remote: {}\n"), text("remote: x\n"), text("remote:\n"),
		text("remote:\n- x: 1e5\n  y: 1.5e5\n  z: 0o17\n  w: 0b101\n  v: +12\n  u: -0\n  t: 0.\n  s: .5\n  r: 1.\n  p: 1:30\n"),
		text(dump(`sys.stdout.write("schema_version: 1\n" + yaml.safe_dump({"remote": [{"office": "peer", "label": "word " * 260, "apps": []}]}, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000))`)),
		text(dump(`sys.stdout.write("schema_version: 1\n" + yaml.safe_dump({"remote": [{"office": "peer", "label": "line one\nline two", "apps": []}]}, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000))`)),
		text(dump(`sys.stdout.write("schema_version: 1\n" + yaml.safe_dump({"office": {"name": "x" * 30 + " " + "y" * 1200}}, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000))`)),
	}
	var calls []call
	for _, st := range states {
		w := map[string]*string{stateName: st}
		calls = append(calls, with(w, "office-get"), with(w, "remote-get"))
	}
	agree(t, repo, calls)
}

// pyValuesOracle prints, for each YAML document, json.dumps / repr / str of what safe_load makes of it
// and, for each JSON text, repr / str of what json.loads makes of it; for each hex string, repr of the
// text Python holds after decoding those bytes with surrogateescape.
const pyValuesOracle = `import sys, json, yaml
cases = json.load(sys.stdin)
out = {"yaml": [], "json": [], "hex": []}
for src in cases["yaml"]:
    v = yaml.safe_load(src)
    out["yaml"].append([json.dumps(v), repr(v), str(v)])
for src in cases["json"]:
    v = json.loads(src)
    out["json"].append([repr(v), str(v)])
for h in cases["hex"]:
    out["hex"].append(repr(bytes.fromhex(h).decode("utf-8", "surrogateescape")))
sys.stdout.write(json.dumps(out))`

// TestValuesSpelledAsPythonSpellsThem: json.dumps (DumpsJSON), repr (pyval.Repr) and str (pyval.Str) of what
// yaml.safe_load and json.loads make of the same text, byte for byte — Hebrew, an emoji, controls,
// DEL, quotes, backslashes, floats of every notation, the special floats, YAML 1.1 bools, nulls,
// nested lists and mappings, JSON numbers ("-0", 1e400), and bytes that are not UTF-8.
func TestValuesSpelledAsPythonSpellsThem(t *testing.T) {
	yamls := []string{
		`s: "שלום 🏠"`,
		"s: \"tab\\there\\u0001 del\\u007f \\u00a0 \\u200b \\U000e0001\"",
		`s: 'say "hi" \ back'`, `s: "it's"`, `s: "both ' and \""`,
		"- 1791129653\n- 0.1\n- 1.0e+20\n- -0.0\n- .inf\n- -.inf\n- .nan\n- 1e5\n- 100.0",
		"- yes\n- off\n- ~\n- null\n-\n- ''",
		"a: [1, [2, {b: c}], {}, []]\nz: {y: {x: w}}",
		"label:\n  he: בינה\n  en: Bina\napps:\n- app: x\n  port: 8080\n  identity: {to: akadmin}",
		`[]`, `{}`, ``,
	}
	jsons := []string{`1`, `-0`, `1.0`, `1e5`, `1e400`, `-1e400`, `0.1`, `"x'y"`, `[1, "a", null, true, 1.5]`,
		`{"a": [1, {"b": "c"}], "d": {}}`, `"\u00e9\ud83c\udfe0"`, `false`}
	hexes := []string{"ff", "61ff62", "c3", "e29c93", "f09f8fa0", "7f", "09", "5c27"}
	in, _ := json.Marshal(map[string][]string{"yaml": yamls, "json": jsons, "hex": hexes})
	py := python(t)
	cmd := exec.Command(py[0], append(py[1:], "-c", pyValuesOracle)...)
	cmd.Env = append(cmd.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	cmd.Stdin = strings.NewReader(string(in))
	raw, err := cmd.Output()
	if err != nil {
		t.Fatalf("python: %v", err)
	}
	var want struct {
		YAML [][3]string `json:"yaml"`
		JSON [][2]string `json:"json"`
		Hex  []string    `json:"hex"`
	}
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatal(err)
	}
	for i, src := range yamls {
		v, err := yamlish.Unmarshal([]byte(src))
		if err != nil {
			t.Errorf("%q: %v", src, err)
			continue
		}
		if got := [3]string{yamlish.DumpsJSON(v), pyval.Repr(v), pyval.Str(v)}; got != want.YAML[i] {
			t.Errorf("%q:\n go     %q\n python %q", src, got, want.YAML[i])
		}
	}
	for i, src := range jsons {
		dec := json.NewDecoder(strings.NewReader(src))
		dec.UseNumber()
		var v any
		if err := dec.Decode(&v); err != nil {
			t.Fatal(err)
		}
		if got := [2]string{pyval.Repr(v), pyval.Str(v)}; got != want.JSON[i] {
			t.Errorf("json %s:\n go     %q\n python %q", src, got, want.JSON[i])
		}
	}
	for i, h := range hexes {
		b, _ := hex.DecodeString(h)
		if got := pyval.Repr(string(b)); got != want.Hex[i] {
			t.Errorf("repr of bytes %s: go %s, python %s", h, got, want.Hex[i])
		}
	}
	t.Logf("%d YAML values, %d JSON values, %d byte strings: spelled as Python spells them", len(yamls), len(jsons), len(hexes))
}

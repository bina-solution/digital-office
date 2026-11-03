package yamlish

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// marshalCases are JSON documents, one per shape the compiler writes with safe_dump (the call sites
// in platform/manager are named beside each), plus the scalars whose spelling the resolver and the
// three writers decide. Every case is dumped under each argument set a call site uses.
var marshalCases = []string{
	// reconcile.py _effective_cpu_budget: the CPU overlay
	`{"services":{"any-concurrency":{"deploy":{"resources":{"limits":{"cpus":"0.69","memory":"512M"}}}}}}`,
	// render_broker
	`{"services":{"mail":{"depends_on":{"connections":{"condition":"service_healthy"}},"volumes":["./platform-base/connections/inject.sh:/inject.sh:ro"],"environment":["CONN_URL=http://connections:8990","CONN_SERVICE=mail","SMTP_PASSWORD="],"entrypoint":["/inject.sh","python","-m","app"]}}}`,
	// render_routing: labels long enough to fold, JSON in an env value
	`{"services":{"console":{"labels":["traefik.enable=true","traefik.http.routers.console-local.rule=Host(` + "`console.localhost`" + `) && PathPrefix(` + "`/a/indox`" + `) && !PathPrefix(` + "`/a/indox/api`" + `)","traefik.http.routers.x.middlewares=x-strip,authentik@file"],"environment":["PLATFORM_SERVICES={\"drive\":\"http://drive:8975\",\"mail\":\"http://mailapi:8970\"}","MAIL_ENGINE_PROFILES={\"a\":[1,2],\"b\":\"c: d\"}","AUTH_X=${AUTH_X:-http://auth.localhost}"],"volumes":["./data/corpus:/corpus:ro"]}}}`,
	// write_plan
	`{"plan":"0001","inputs_digest":"1234567890123456","apps":23,"start_order":["traefik","postgres","n8n"],"bindings":{},"services":["traefik","postgres"],"pulled_in":[],"notes":["n8n: pulled in as provider of 'workflow' for 'indox' — and this note goes on well past eighty columns","x"]}`,
	// console.modules.yaml
	`[{"id":"drive","name":"דרייב","icon":"folder","group":"עסק","desc":"קבצים ומסמכים — כל מה שהעסק מחזיק, במקום אחד, עם חיפוש ותיקיות משותפות לכל הצוות","order":2,"external":true,"host":"drive.localhost","alias":"drive","embed":"/a/drive/","signed_in":"/.dgo/signed-in","enter":"/.dgo/enter"},{"id":"x","name":"X","icon":"🏠","group":"ראשי","embed":"/a/x/","desc":"","order":999,"alias":"x","service":"x"}]`,
	// connections.providers.yaml / connections.consumers.yaml
	`[{"id":"portainer-admin","kind":"password","label":{"he":"מנהל","en":"Portainer admin"},"fields":[{"name":"password","secret":true,"min":12}],"_app":"portainer"}]`,
	`[{"service":"mail","requires":[{"id":"smtp","required":true},{"id":"imap","required":false}]},{"service":"browser42","requires":[]}]`,
	// serve.render (traefik's file provider) and serve.render_aliases
	`{"http":{"middlewares":{"dgo-remote-vps1-identity":{"headers":{"customRequestHeaders":{"X-authentik-username":"akadmin","X-DGO-From":"a,b"}}},"dgo-remote-https":{"redirectScheme":{"scheme":"https","permanent":true}},"dgo-remote-console-returns":{"redirectRegex":{"regex":"^(https?://)[^/]+\\.(console\\.localhost)((?::[0-9]+)?)/\\.dgo/enter(.*)$","replacement":"${1}${2}${3}/#${4}"}},"asks":{"headers":{"accessControlAllowOriginList":["http://console.localhost","http://console.localhost:8080"],"accessControlAllowCredentials":true}}},"routers":{"x-console-local":{"rule":"Host(` + "`incoming.vps1.console.localhost`" + `) && (Header(` + "`Origin`" + `, ` + "`http://incoming.vps1.console.localhost`" + `) || Header(` + "`Origin`" + `, ` + "`http://incoming.vps1.console.localhost:8080`" + `))","entryPoints":["web"],"service":"svc","middlewares":["authentik@file","dgo-remote-vps1-identity"],"tls":{"certResolver":"myresolver"}}},"services":{"svc":{"loadBalancer":{"servers":[{"url":"http://incoming.vps1:9002"}],"passHostHeader":true}}}}}`,
	`{"services":{"dgo-net":{"networks":{"traefik-network":{"aliases":["incoming.vps1","pinkas.vps1"]}}}}}`,
	// set_office and set_remote
	`{"office":{"name":"הלשכה של חיים","animal":"elephant","hue":"muted","terms_version":"1","terms_accepted_at":"2026-10-09T10:00:00Z","installed_at":"2026-10-09T10:00:00Z"}}`,
	`{"remote":[{"office":"vps1","label":{"he":"שרת פיתוח","en":"Dev server"},"link":"vps1","address":"10.79.2.2","commit":"dad40e66b4dea1e100a6414779c827fd764ab446","fetched":1791129653,"apps":[{"app":"indox","alias":"incoming","port":8080,"name":"מסמכים","icon":"🏠","order":0,"module":{"kind":"embedded","path":"/a/incoming/"},"identity":{"to":"akadmin","from":["a","b"]},"agent_api_port":null,"x":[],"y":{}}],"link_port":9002}]}`,
	// the resolver: strings that would read back as something else are quoted
	`{"yes":"no","on":"off","null":"~","n":"0755","f":"1e5","g":"1.5","h":"","i":" x","j":"x ","k":"a: b","l":"a #b","m":"#c","o":"- x","p":"[x]","q":"it's","r":"@a","s":"2026-10-10","s2":"2026-1-5","s3":"2026-1-5 1:00:00","t":"12:30","u":"x:","v":"<<","w":"=","x":"!","y":"&a","z":"*a","aa":"%x","ab":"` + "`x`" + `","ac":"---","ad":"...x","ae":"-","af":"?","ag":":","ah":"? x","ai":"a:b","aj":"a#b","ak":"1_000","al":"0x1F","am":".inf","an":"-.5","ao":"+1","ap":"0o17","aq":"08","ar":"True","as":"NULL","at":"Off","au":"-x","av":"x-","aw":"a, b","ax":"{x}","ay":"|x","az":">x","ba":"x|","bb":"say \"hi\"","bc":"a\\b"}`,
	// numbers as Python spells them
	`{"floats":[0.1,2.0,1e-05,1e+17,100.0,-0.5,1234567.0,1e16,123456789012345680.0,-0.0,5e-324,1.7976931348623157e308,1e400],"ints":[0,42,-7,9007199254740993,123456789012345678901234567890,-12345678901234567890123],"special":[NaN,Infinity,-Infinity],"bools":[true,false,null]}`,
	// line breaks and characters only some styles can carry
	`{"m":"line1\nline2","n":"a \nb","o":"a\n b","p":"trail\n","p2":"\n\nlead","p3":"two\n\n\nbreaks","q":"x\u2028y","q2":"x\u0085y","r":"tab\there","s":"cr\rx","t":"nul\u0000x","u":"bom\ufeffx","v":"nbsp\u00a0x","w":"del\u007fx","x":"emoji 🏠 in quotes: yes","y":"\u0085next","z":"esc\u001bx","za":"bell\u0007","zb":"\u00e9t\u00e9","zc":"\u2029","zd":"emoji\u0001🏠","ze":"\ue000\ufffd\uffff"}`,
	// keys a simple key cannot carry, and keys that need quotes
	`{"":1,"` + strings.Repeat("k", 122) + `":"simple","` + strings.Repeat("k", 123) + `":"complex","multi\nkey":1,"k: v":2,"#k":3,"- k":4,"123":5,"true":6,"null":7,"שם":8,"a b":9}`,
	// folding: plain, single-quoted and double-quoted lines past the width, nested and at the root
	`{"long":"` + strings.Repeat("word ", 40) + `end","dq":"\u0001` + strings.Repeat("word ", 40) + `end","sq":"'` + strings.Repeat("word ", 40) + `end","nospace":"` + strings.Repeat("x", 200) + `","double space":"` + strings.Repeat("ab  ", 40) + `","he":"` + strings.Repeat("מילה ", 40) + `","deep":{"a":{"b":{"c":{"d":"` + strings.Repeat("word ", 30) + `"}}}},"seq":["` + strings.Repeat("word ", 30) + `",["` + strings.Repeat("deeper ", 20) + `"]],"dqsp":"\u0001` + strings.Repeat(" a", 60) + `","sqbreak":"` + strings.Repeat("word ", 20) + "\\n" + strings.Repeat("word ", 20) + `"}`,
	// collections inside collections, and empty ones
	`[{"k":"v"},"s",[1],[],{},[[[]]],[{"a":[{"b":[]}]}],{"x":{"y":[]},"z":[{}]}]`,
	`{}`,
	`[]`,
}

// dumpArgs are the (sort_keys, width) pairs the call sites pass: the compose overlays sort at the
// default width, the plan and the registries keep order at the default width, the state file's blocks
// and serve's traefik files keep order at width 1000.
var dumpArgs = []struct {
	sortKeys bool
	width    int
}{{true, 80}, {false, 80}, {false, 1000}}

// pyDump runs PyYAML once over every (case, arguments) pair and returns its outputs in order.
const pyDump = `import sys, json, yaml
out = []
for text, sort_keys, width in json.load(sys.stdin):
    out.append(yaml.safe_dump(json.loads(text), default_flow_style=False, allow_unicode=True,
                              sort_keys=sort_keys, width=width))
sys.stdout.write(json.dumps(out))`

func pyRun(t *testing.T, py []string, script string, input any) []byte {
	t.Helper()
	in, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(py[0], append(py[1:], "-c", script)...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	cmd.Stdin = bytes.NewReader(in)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("python: %v\n%s", err, stderr.String())
	}
	return out
}

func TestMarshalMatchesPyYAML(t *testing.T) {
	py := python(t)
	if py == nil {
		noPython(t)
	}
	var jobs [][]any
	for _, c := range marshalCases {
		for _, a := range dumpArgs {
			jobs = append(jobs, []any{c, a.sortKeys, a.width})
		}
	}
	var want []string
	if err := json.Unmarshal(pyRun(t, py, pyDump, jobs), &want); err != nil {
		t.Fatal(err)
	}
	for i, j := range jobs {
		v, err := LoadJSON(j[0].(string))
		if err != nil {
			t.Fatalf("case %d: %v", i/len(dumpArgs), err)
		}
		got, err := Marshal(v, Options{SortKeys: j[1].(bool), Width: j[2].(int)})
		if err != nil {
			t.Errorf("case %d: %v", i/len(dumpArgs), err)
			continue
		}
		if string(got) != want[i] {
			at := firstDiff(string(got), want[i])
			t.Errorf("case %d (sort_keys=%v width=%v) differs at byte %d:\n--- go ---\n%s\n--- pyyaml ---\n%s",
				i/len(dumpArgs), j[1], j[2], at, window(string(got), at), window(want[i], at))
		}
	}
	t.Logf("%d dumps byte-identical to yaml.safe_dump", len(jobs))
}

// TestTheStateFileRoundTrips reads the checkout's own platform.state.yaml and writes it back: the
// whole document under each argument set, against safe_dump(safe_load(file)) — and the `remote:`
// block, which set_remote wrote with safe_dump(width=1000), must come out as the very bytes the file
// holds.
func TestTheStateFileRoundTrips(t *testing.T) {
	py := python(t)
	if py == nil {
		noPython(t)
	}
	path := filepath.Join(repoRoot(t), "platform.state.yaml")
	src, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	doc, err := Unmarshal(src)
	if err != nil {
		t.Fatal(err)
	}
	const pyState = `import sys, json, yaml
path, args = json.load(sys.stdin)
doc = yaml.safe_load(open(path, encoding="utf-8"))
sys.stdout.write(json.dumps([yaml.safe_dump(doc, default_flow_style=False, allow_unicode=True,
                                            sort_keys=s, width=w) for s, w in args]))`
	var args [][]any
	for _, a := range dumpArgs {
		args = append(args, []any{a.sortKeys, a.width})
	}
	var want []string
	if err := json.Unmarshal(pyRun(t, py, pyState, []any{path, args}), &want); err != nil {
		t.Fatal(err)
	}
	for i, a := range dumpArgs {
		got, err := Marshal(doc, Options{SortKeys: a.sortKeys, Width: a.width})
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != want[i] {
			at := firstDiff(string(got), want[i])
			t.Errorf("platform.state.yaml (sort_keys=%v width=%d) differs at byte %d:\n--- go ---\n%s\n--- pyyaml ---\n%s",
				a.sortKeys, a.width, at, window(string(got), at), window(want[i], at))
		}
	}
	remote, ok := doc.(*Map).Get("remote")
	if !ok {
		t.Skip("this checkout's state file has no remote: block")
	}
	block := NewMap()
	block.Set("remote", remote)
	got, err := Marshal(block, Options{Width: 1000})
	if err != nil {
		t.Fatal(err)
	}
	text := strings.ReplaceAll(string(src), "\r\n", "\n")
	if i := strings.Index(text, "\nremote:\n"); i < 0 || !strings.HasPrefix(text[i+1:], string(got)) {
		t.Errorf("the remote: block written back differs from the file's own bytes:\n%s", got)
	}
}

// TestCorpusRoundTripsLikePyYAML writes back every YAML file the compiler reads, against PyYAML on the
// same value — a key written as YAML typed it (TypedKey: an `80:` key stays the int 80).
func TestCorpusRoundTripsLikePyYAML(t *testing.T) {
	py := python(t)
	if py == nil {
		noPython(t)
	}
	files := corpus(t, repoRoot(t))
	const pyCorpus = `import sys, json, yaml
out = []
for path in json.load(sys.stdin):
    v = yaml.safe_load(open(path, encoding="utf-8"))
    out.append(yaml.safe_dump(v, default_flow_style=False, allow_unicode=True, sort_keys=False)
               if isinstance(v, (dict, list)) else None)
sys.stdout.write(json.dumps(out))`
	var want []*string
	if err := json.Unmarshal(pyRun(t, py, pyCorpus, files), &want); err != nil {
		t.Fatal(err)
	}
	n := 0
	for i, f := range files {
		if want[i] == nil {
			continue // an empty file: no document to write
		}
		src, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		v, err := Unmarshal(src)
		if err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		got, err := Marshal(v, Options{})
		if err != nil {
			t.Errorf("%s: %v", f, err)
			continue
		}
		if string(got) != *want[i] {
			at := firstDiff(string(got), *want[i])
			t.Errorf("%s differs at byte %d:\n--- go ---\n%s\n--- pyyaml ---\n%s", f, at, window(string(got), at), window(*want[i], at))
		}
		n++
	}
	t.Logf("%d corpus files written back byte-identical to yaml.safe_dump", n)
}

func TestMarshalKeepsAMapsOrderUnlessSorted(t *testing.T) {
	m := NewMap()
	m.Set("z", int64(1))
	m.Set("a", int64(2))
	got, _ := Marshal(m, Options{})
	if string(got) != "z: 1\na: 2\n" {
		t.Fatalf("unsorted: %q", got)
	}
	got, _ = Marshal(m, Options{SortKeys: true})
	if string(got) != "a: 2\nz: 1\n" {
		t.Fatalf("sorted: %q", got)
	}
}

// What the emitter writes, the reader reads back as the same value — or MarshalReadBack refuses it,
// and the state file's writers with it: nothing written. A refusal must be a real one (the reader
// refuses PyYAML's document, or reads another value from it), and the cases are held apart by why:
//   - "design": what the reader cannot hold by its design — a key YAML writes as `? key` (empty,
//     multi-line, or too long for a simple key), an integer beyond 64 bits — is always refused;
//   - "corner": what it does not yet read as PyYAML does — a non-ASCII space at a value's edge, a line
//     separator inside one, int64's minimum — is refused today and reads back once it does, so it is
//     held to the rule alone;
//   - everything else reads back.
func TestMarshalRoundTripsThroughUnmarshal(t *testing.T) {
	type doc struct{ text, kind string }
	var docs []doc
	for _, c := range marshalCases {
		kind := ""
		switch {
		case strings.Contains(c, `"":`) || strings.Contains(c, "123456789012345678901234567890"):
			kind = "design"
		case strings.Contains(c, `\u2028`):
			kind = "corner"
		}
		docs = append(docs, doc{c, kind})
	}
	docs = append(docs,
		doc{`{"": 1}`, "design"}, doc{`{"` + strings.Repeat("k", 123) + `": 1}`, "design"}, doc{`{"a\nb": 1}`, "design"},
		doc{`[123456789012345678901234567890]`, "design"},
		doc{`{"name": "בינה\u00a0"}`, "corner"}, doc{`{"name": "\u3000ב"}`, "corner"}, doc{`{"desc": "שורה\u2028שנייה"}`, "corner"},
		doc{`{"desc": "a\u0085b"}`, "corner"}, doc{`{"order": -9223372036854775808}`, "corner"},
		doc{`{"to": "alice\n", "from": ["bob\n"]}`, ""}, doc{`{"desc": "line one\nline two\n\n  indented\n"}`, ""},
		doc{`{"desc": "a\tb\r\nc"}`, ""}, doc{`{"order": 9223372036854775807}`, ""},
	)
	refused := 0
	for _, d := range docs {
		v, err := LoadJSON(d.text)
		if err != nil {
			t.Fatal(err)
		}
		show := d.text
		if len(show) > 60 {
			show = show[:60] + "…"
		}
		for _, o := range []Options{{}, {Width: 1000}} {
			out, err := MarshalReadBack(v, o)
			switch {
			case err == nil:
				if back, rerr := Unmarshal(out); rerr != nil || CanonicalJSON(back) != CanonicalJSON(v) {
					t.Errorf("%s: accepted, yet it does not read back", show)
				}
				if d.kind == "design" {
					t.Errorf("%s: accepted, though the reader cannot hold it", show)
				}
			case !errors.Is(err, ErrNotReadBack):
				t.Errorf("%s: %v", show, err)
			default:
				refused++
				raw, _ := Marshal(v, o)
				if back, rerr := Unmarshal(raw); rerr == nil && CanonicalJSON(back) == CanonicalJSON(v) {
					t.Errorf("%s: refused, yet it reads back unchanged", show)
				}
				if d.kind == "" {
					t.Errorf("%s: refused (%v), though the reader reads it", show, err)
				}
			}
		}
	}
	t.Logf("%d documents at two widths: each reads back or is refused (%d refusals, each a real one)", len(docs), refused)
}

// sharedCases are documents in which one mapping appears more than once — `{"$share": name, "$value":
// {…}}` where it first appears, `{"$ref": name}` wherever it appears again — as the console registry's
// tiles share their office's label and mark. PyYAML's serializer anchors such a mapping.
var sharedCases = []string{
	// the registry's shape: the label twice in a tile and in every tile of the office, the mark once per tile
	`[{"id":"bina.macbook","label":{"$share":"l","$value":{"he":"המקבוק","en":"MacBook"}},"remote":{"label":{"$ref":"l"},"mark":{"$share":"m","$value":{"color":"lime","animal":"deer"}}}},
	  {"id":"x","order":1},
	  {"id":"drive.macbook","label":{"$ref":"l"},"remote":{"label":{"$ref":"l"},"mark":{"$ref":"m"}}}]`,
	// the names follow the order the REPEATS are met in: b repeats first, so b is id001
	`{"x":{"$share":"a","$value":{"k":1}},"y":{"$share":"b","$value":{"k":2}},"z":{"$ref":"b"},"w":{"$ref":"a"}}`,
	// an empty mapping, shared; a shared mapping as a sequence's item; one nested in another
	`{"a":{"$share":"e","$value":{}},"b":{"$ref":"e"},"s":[{"$share":"m","$value":{"k":1,"in":{"$share":"n","$value":{"z":0}}}},{"$ref":"m"},{"k":2,"n":{"$ref":"n"}}]}`,
	// more than nine names
	`[` + sharedMany(12) + `]`,
}

// sharedMany is n mappings, each written twice in a row.
func sharedMany(n int) string {
	var parts []string
	for i := 0; i < n; i++ {
		parts = append(parts, fmt.Sprintf(`{"$share":"s%d","$value":{"n":%d}}`, i, i), fmt.Sprintf(`{"$ref":"s%d"}`, i))
	}
	return strings.Join(parts, ",")
}

// share resolves a shared-case document into the value it describes: one *Map per name.
func share(v any, named map[string]*Map) any {
	switch t := v.(type) {
	case *Map:
		if name, ok := t.Get("$ref"); ok {
			return named[name.(string)]
		}
		if name, ok := t.Get("$share"); ok {
			inner, _ := t.Get("$value")
			m := share(inner, named).(*Map)
			named[name.(string)] = m
			return m
		}
		out := NewMap()
		for _, k := range t.Keys() {
			x, _ := t.Get(k)
			out.Set(k, share(x, named))
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = share(x, named)
		}
		return out
	}
	return v
}

// TestMarshalAnchorsSharedMappingsAsSafeDumpDoes: a mapping that appears more than once is written as
// safe_dump writes the same object appearing more than once — `&idNNN` the first time, `*idNNN` after,
// numbered as the repeats are met (sorted keys change the order they are met in) — and the document
// reads back as the value it was.
func TestMarshalAnchorsSharedMappingsAsSafeDumpDoes(t *testing.T) {
	py := python(t)
	if py == nil {
		noPython(t)
	}
	const pyShared = `import sys, json, yaml
def share(v, named):
    if isinstance(v, dict):
        if "$ref" in v:
            return named[v["$ref"]]
        if "$share" in v:
            named[v["$share"]] = share(v["$value"], named)
            return named[v["$share"]]
        return {k: share(x, named) for k, x in v.items()}
    if isinstance(v, list):
        return [share(x, named) for x in v]
    return v
out = []
for text, sort_keys, width in json.load(sys.stdin):
    out.append(yaml.safe_dump(share(json.loads(text), {}), default_flow_style=False, allow_unicode=True,
                              sort_keys=sort_keys, width=width))
sys.stdout.write(json.dumps(out))`
	var jobs [][]any
	for _, c := range sharedCases {
		for _, a := range dumpArgs {
			jobs = append(jobs, []any{c, a.sortKeys, a.width})
		}
	}
	var want []string
	if err := json.Unmarshal(pyRun(t, py, pyShared, jobs), &want); err != nil {
		t.Fatal(err)
	}
	for i, j := range jobs {
		raw, err := LoadJSON(j[0].(string))
		if err != nil {
			t.Fatal(err)
		}
		v := share(raw, map[string]*Map{})
		o := Options{SortKeys: j[1].(bool), Width: j[2].(int)}
		got, err := Marshal(v, o)
		if err != nil || string(got) != want[i] {
			at := firstDiff(string(got), want[i])
			t.Errorf("shared case %d (sort_keys=%v width=%v): %v\n--- go ---\n%s\n--- pyyaml ---\n%s", i/len(dumpArgs), j[1], j[2], err,
				window(string(got), at), window(want[i], at))
			continue
		}
		if _, err := MarshalReadBack(v, o); err != nil {
			t.Errorf("shared case %d: %v", i/len(dumpArgs), err)
		}
	}
	t.Logf("%d dumps of shared mappings byte-identical to yaml.safe_dump, each read back", len(jobs))
}

// TestMarshalWritesKeysAsTheyWereTyped: a mapping read from YAML with keys YAML types as numbers,
// booleans or null — a remote office's free-form `order`, a compose file's — is written back with those
// keys as PyYAML writes them (`80:`, `true:`, `null:`), never quoted as the strings the reader keys them
// by; a key that only looks typed because it was quoted stays quoted.
func TestMarshalWritesKeysAsTheyWereTyped(t *testing.T) {
	py := python(t)
	if py == nil {
		noPython(t)
	}
	docs := []string{
		"order:\n  1: a\n  2.5: b\n  null: d\n  '3': e\n  0x10: f\n",
		"80: http\n443: https\nyes: x\nOff: y\n",
		"- {1: one, 'two': 2, ~: 3}\n",
	}
	const pyTyped = `import sys, json, yaml
sys.stdout.write(json.dumps([yaml.safe_dump(yaml.safe_load(d), default_flow_style=False, allow_unicode=True,
                                            sort_keys=False) for d in json.load(sys.stdin)]))`
	var want []string
	if err := json.Unmarshal(pyRun(t, py, pyTyped, docs), &want); err != nil {
		t.Fatal(err)
	}
	for i, d := range docs {
		v, err := Unmarshal([]byte(d))
		if err != nil {
			t.Fatalf("doc %d: %v", i, err)
		}
		got, err := Marshal(v, Options{})
		if err != nil || string(got) != want[i] {
			t.Errorf("doc %d: %v\n--- go ---\n%s--- pyyaml ---\n%s", i, err, got, want[i])
		}
	}
	t.Logf("%d documents with typed keys written as safe_dump writes them", len(docs))
}

func TestMarshalRefusesWhatItCannotSpell(t *testing.T) {
	if _, err := Marshal("just a scalar", Options{}); err == nil {
		t.Fatal("a scalar root must be refused")
	}
	m := NewMap()
	m.Set("a", struct{}{})
	if _, err := Marshal(m, Options{}); err == nil {
		t.Fatal("an unknown type must be refused")
	}
	if _, err := Marshal(map[string]any{"a": 1}, Options{}); err == nil {
		t.Fatal("a Go map is not this package's mapping: it has no order to keep")
	}
}

// TestMarshalMatchesPyYAMLOnRandomValues holds the emitter to safe_dump on a seeded random corpus
// (testdata/emit_corpus.py): scalars over every class the emitter decides by — indicators, quotes,
// spaces, breaks, controls, the resolver's words — as values, as keys and inside the remote block's
// shape, long ones folded in each style and at five widths, keys about the simple key's edge, numbers
// from the edges of each type and floats from random bits; every dump byte for byte. Each document is
// held to the writers' rule too: it reads back as itself, or MarshalReadBack refuses it.
func TestMarshalMatchesPyYAMLOnRandomValues(t *testing.T) {
	t.Parallel()
	py := python(t)
	if py == nil {
		noPython(t)
	}
	var cases []struct {
		Doc  string `json:"doc"`
		SK   bool   `json:"sk"`
		W    int    `json:"w"`
		YAML string `json:"yaml"`
	}
	pyCorpus(t, py, "emit_corpus.py", 2000, &cases)
	bad, refused := 0, 0
	for _, c := range cases {
		v, err := LoadJSON(c.Doc)
		if err != nil {
			t.Fatalf("%q: %v", c.Doc, err)
		}
		o := Options{SortKeys: c.SK, Width: c.W}
		got, err := Marshal(v, o)
		if err != nil || string(got) != c.YAML {
			if bad++; bad <= 10 {
				t.Errorf("%s (sort_keys=%v width=%d): %v\n--- go ---\n%q\n--- pyyaml ---\n%q", c.Doc, c.SK, c.W, err, got, c.YAML)
			}
			continue
		}
		if _, err := MarshalReadBack(v, o); err != nil {
			refused++
			if back, rerr := Unmarshal(got); !errors.Is(err, ErrNotReadBack) || rerr == nil && CanonicalJSON(back) == CanonicalJSON(v) {
				t.Errorf("%s: refused (%v), yet it reads back", c.Doc, err)
			}
		}
	}
	t.Logf("%d of %d dumps byte-identical to yaml.safe_dump; %d refused by MarshalReadBack, each a real refusal", len(cases)-bad, len(cases), refused)
}

// pyCorpus runs a seeded generator of testdata/ and decodes the cases it prints into `into`.
func pyCorpus(t *testing.T, py []string, script string, count int, into any) {
	t.Helper()
	cmd := exec.Command(py[0], append(py[1:], filepath.Join("testdata", script), "7", strconv.Itoa(count))...)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("%s: %v\n%s", script, err, stderr.String())
	}
	if err := json.Unmarshal(out, into); err != nil {
		t.Fatalf("%s: %v", script, err)
	}
}

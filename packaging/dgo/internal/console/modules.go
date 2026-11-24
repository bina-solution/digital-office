package console

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io/fs"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/compiler"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/pyval"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// The tiles are read from what the compiler wrote — .generated/registry/console.modules.yaml — through
// the one YAML reader, exactly as app.py reads that file. They are not re-derived from the catalog
// here: deriving them is the compiler's emitter (reconcile.py render), and a second derivation would
// be a second compiler.

// modulesRoute is GET /api/modules: jsonify(modules=_tiles()).
func (s *Server) modulesRoute(w http.ResponseWriter, r *http.Request) bool {
	tiles, ok := s.tiles(r)
	if !ok {
		return false
	}
	return writeJSON(w, r, newMap("modules", tiles))
}

// versionRoute is GET /api/version: the build, the shell's digest, and the digest of the tiles as
// json.dumps(sort_keys=True, ensure_ascii=False) spells them — what an open page compares itself with.
func (s *Server) versionRoute(w http.ResponseWriter, r *http.Request) bool {
	tiles, ok := s.tiles(r)
	if !ok {
		return false
	}
	sum := sha256.Sum256([]byte(yamlish.SortedJSON(tiles)))
	return writeJSON(w, r, newMap("version", s.version, "shell", s.tree.digest, "registry", hex.EncodeToString(sum[:])[:12]))
}

// writeJSON is a jsonify answer as flask-compress leaves it: application/json, Vary, and a body of
// 500 bytes or more compressed when the client takes gzip or deflate (a buffered body may be gzip).
func writeJSON(w http.ResponseWriter, r *http.Request, v any) bool {
	ae, ok := header(r, "Accept-Encoding")
	if !ok {
		return false
	}
	body := []byte(yamlish.FlaskJSON(v) + "\n")
	coding := ""
	if len(body) >= minSize {
		if coding, ok = choose(bufferedEncodings, ae); !ok {
			return false
		}
	}
	h := w.Header()
	h["Content-Type"] = []string{"application/json"}
	h["Vary"] = []string{"Accept-Encoding"}
	if coding != "" {
		body = compress(coding, body)
		h["Content-Encoding"] = []string{coding}
	}
	h["Content-Length"] = []string{strconv.Itoa(len(body))}
	w.WriteHeader(http.StatusOK)
	if r.Method != http.MethodHead {
		w.Write(body)
	}
	return true
}

// tiles is _tiles(): every module without what is THIS server's alone (app.py SERVER_ONLY) — `door`, how
// it reaches a remote app, and `handoffs`, where it asks an app which people it is waiting for
// (DGO-1336): not the browser's business. ok is false when an input is outside what this port reads
// exactly as app.py does (including every input on which app.py itself raises and answers 500).
func (s *Server) tiles(r *http.Request) ([]any, bool) {
	mods, ok := s.modules(r)
	if !ok {
		return nil, false
	}
	out := make([]any, len(mods))
	for i, m := range mods {
		t := yamlish.NewMap()
		for _, k := range m.Keys() {
			if k != "door" && k != "handoffs" {
				t.Set(k, get(m, k))
			}
		}
		out[i] = t
	}
	return out, true
}

// modules is _modules(): the compiled registry's tiles, then each peer tile whose id the registry does
// not already hold, every linked office's tile judged by the link's last measurement, then the
// console's own views — sorted by `order` (999 when absent), stably. Without a compiled registry it is
// modules.yaml exactly as written: no peers, no judging, no sorting. On the phone's core (More) the
// machine's tiles come after the peers', on the same terms: the apps the machine runs and the offices it
// links, which no registry built into the APK can hold.
func (s *Server) modules(r *http.Request) ([]*yamlish.Map, bool) {
	peers, ok := s.peerTiles()
	if !ok {
		return nil, false
	}
	gen := filepath.Join(s.registry, "console.modules.yaml")
	if _, err := os.Stat(gen); err != nil {
		raw, err := fs.ReadFile(s.root, "modules.yaml")
		if err != nil {
			return nil, false // open() raises: app.py's 500
		}
		return parseMaps(raw)
	}
	all, ok := readMaps(gen)
	if !ok {
		return nil, false
	}
	known := map[string]bool{}
	for _, t := range all {
		k, ok := setKey(get(t, "id"))
		if !ok {
			return nil, false
		}
		known[k] = true
	}
	for _, m := range peers {
		k, ok := setKey(get(m, "id"))
		if !ok {
			return nil, false
		}
		if !known[k] {
			all = append(all, m)
		}
	}
	views, ok := s.ownViews()
	if !ok {
		return nil, false
	}
	if more := s.moreTiles(r); len(more) > 0 {
		// the machine's, once each: never one the rail already holds — the console's own views among them,
		// which the machine's console lists too — nor one whose id this port cannot key (the other console's
		// oddity costs that tile, not the rail)
		held := map[string]bool{}
		for _, t := range append(append([]*yamlish.Map{}, all...), views...) {
			if k, ok := setKey(get(t, "id")); ok {
				held[k] = true
			}
		}
		for _, m := range more {
			if k, ok := setKey(get(m, "id")); ok && !held[k] {
				held[k] = true
				all = append(all, m)
			}
		}
	}
	if !s.judge(all) {
		return nil, false
	}
	all = append(all, views...)
	return all, sortByOrder(all)
}

// moreTiles is Config.More's answer read as an /api/modules document: its modules that are mappings with
// an id, an `order` that is a whole number or none, and a `remote` that names its office in text or is
// none — what judge and sortByOrder read without failing the whole rail. None without More, when it
// answers nothing, or when what it answers does not read (the other console's answer costs its own tiles,
// never the rail).
func (s *Server) moreTiles(r *http.Request) []*yamlish.Map {
	if s.more == nil {
		return nil
	}
	raw := s.more(r)
	if len(raw) == 0 {
		return nil
	}
	v, err := loadJSON(raw)
	doc, isMap := v.(*yamlish.Map)
	if err != nil || !isMap {
		return nil
	}
	list, _ := get(doc, "modules").([]any)
	var out []*yamlish.Map
	for _, e := range list {
		m, isMap := e.(*yamlish.Map)
		if !isMap || !compiler.Truthy(get(m, "id")) {
			continue
		}
		if o := get(m, "order"); o != nil {
			if _, whole := o.(int64); !whole {
				continue
			}
		}
		if rm := get(m, "remote"); rm != nil {
			rem, isMap := rm.(*yamlish.Map)
			if !isMap {
				continue
			}
			if office := get(rem, "office"); office != nil {
				if _, isText := office.(string); !isText {
					continue
				}
			}
		}
		out = append(out, m)
	}
	return out
}

// ownViews is _own_views(): modules.yaml's entries without a truthy `embed` — none when the file
// cannot be opened.
func (s *Server) ownViews() ([]*yamlish.Map, bool) {
	raw, err := fs.ReadFile(s.root, "modules.yaml")
	if err != nil {
		return nil, true
	}
	ms, ok := parseMaps(raw)
	var out []*yamlish.Map
	for _, m := range ms {
		if !compiler.Truthy(get(m, "embed")) {
			out = append(out, m)
		}
	}
	return out, ok
}

// readMaps is yaml.safe_load(open(path)) as app.py uses it: a file that cannot be read is app.py's
// 500, so not ok.
func readMaps(path string) ([]*yamlish.Map, bool) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	return parseMaps(raw)
}

// parseMaps is `yaml.safe_load(…) or []` read as a list of mappings: a falsy document is no entries;
// a list of anything but mappings, or any other document, makes app.py raise — not ok, as is a file
// that is not UTF-8 or that yamlish refuses (PyYAML may read it).
func parseMaps(raw []byte) ([]*yamlish.Map, bool) {
	if !utf8.Valid(raw) {
		return nil, false
	}
	v, err := yamlish.Unmarshal(raw)
	if err != nil || tooDeep(v, 0) {
		return nil, false
	}
	if !compiler.Truthy(v) {
		return nil, true
	}
	list, isList := v.([]any)
	if !isList {
		return nil, false
	}
	out := make([]*yamlish.Map, len(list))
	for i, e := range list {
		m, isMap := e.(*yamlish.Map)
		if !isMap {
			return nil, false
		}
		out[i] = m
	}
	return out, true
}

// peerTiles is [_peer_module(e) for e in _peer_entries()]: each *.json of the peer directory, in name
// order, that is an object with a truthy alias and module — as its tile, marked `remote` from the
// record's own fields unless the tile already carries the mark. A file that is not an object is skipped.
func (s *Server) peerTiles() ([]*yamlish.Map, bool) {
	entries, err := os.ReadDir(s.peers)
	if err != nil {
		return nil, true
	}
	var out []*yamlish.Map
	for _, e := range entries {
		if !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(s.peers, e.Name()))
		if err != nil {
			continue
		}
		v, err := loadJSON(raw)
		if err == errUnsure {
			return nil, false
		}
		if err != nil || !compiler.Truthy(v) { // `json.load(f) or {}`
			continue
		}
		doc, isMap := v.(*yamlish.Map)
		if !isMap {
			continue // a list or a scalar is not a placement: app.py skips it by name (DGO-611; it raised, and /api/modules was a 500)
		}
		if !compiler.Truthy(get(doc, "alias")) || !compiler.Truthy(get(doc, "module")) {
			continue
		}
		mod, isMap := get(doc, "module").(*yamlish.Map)
		if !isMap {
			return nil, false // dict() of a string raises; of a list of pairs it builds a tile this port does not
		}
		t := copyMap(mod)
		if _, marked := get(t, "remote").(*yamlish.Map); !marked {
			office := or(get(doc, "office"), "")
			label := get(doc, "label")
			if label == nil {
				label = office
			}
			t.Set("remote", newMap("office", office, "label", label, "link", or(get(doc, "link"), office),
				"address", or(get(doc, "address"), ""), "commit", or(get(doc, "commit"), "")))
		}
		out = append(out, t)
	}
	return out, true
}

// judge is _judged(): a linked office's tile carries what was last measured about its office —
// remote.ok, and remote.why when it is false. Unmeasured stays absent. …and remote.herd when the office is
// one of this office's own herd (herdIDs, DGO-2122).
func (s *Server) judge(tiles []*yamlish.Map) bool {
	seen, ok := s.verdicts()
	if !ok {
		return false
	}
	herd, ok := s.herdIDs()
	if !ok {
		return false
	}
	for _, m := range tiles {
		r, isMap := get(m, "remote").(*yamlish.Map)
		if !isMap {
			continue
		}
		office, ok := pyStr(or(get(r, "office"), ""))
		sm, isMap := seen.(*yamlish.Map)
		if !ok || !isMap {
			return false // str() of a float or a container; `.get` on offices that are not an object
		}
		judged := r
		if v := get(sm, office); compiler.Truthy(v) {
			vm, isMap := v.(*yamlish.Map)
			if !isMap {
				return false // `.get` on a measurement that is not an object raises
			}
			if measured := get(vm, "ok"); measured != nil {
				judged = copyMap(r)
				judged.Set("ok", compiler.Truthy(measured))
				if !compiler.Truthy(measured) {
					why, ok := pyStr(or(get(vm, "why"), ""))
					if !ok {
						return false
					}
					judged.Set("why", why)
				}
			}
		}
		if herd[strings.ToLower(pyval.Strip(office))] {
			if judged == r {
				judged = copyMap(r)
			}
			judged.Set("herd", true)
		}
		m.Set("remote", judged)
	}
	return true
}

// herdIDs is _herd_ids(): the offices of the herd herd.offices.json names, and their other names (stripped,
// lowered) — only when THIS office is one of them (ownOffice), since every office compiles the same file, a
// client's too — or none. What app.py catches (no file, a file that is no JSON or of another shape) is none here,
// read again on the next request; not ok when app.py's reading would differ from this port's (the container's).
func (s *Server) herdIDs() (map[string]bool, bool) {
	raw, err := os.ReadFile(filepath.Join(s.registry, "herd.offices.json"))
	if err != nil {
		return nil, true
	}
	v, err := loadJSON(raw)
	if err == errUnsure {
		return nil, false
	}
	doc, isMap := v.(*yamlish.Map)
	if err != nil || !isMap {
		return nil, true // ValueError; a falsy document is `{}`, a truthy one that is no object has no `.get`: both none
	}
	om, isMap := or(get(doc, "offices"), yamlish.NewMap()).(*yamlish.Map)
	if !isMap {
		return nil, true // `.items()` of offices that are not an object: AttributeError, caught
	}
	ids := map[string]bool{}
	name := func(n string) { ids[strings.ToLower(pyval.Strip(n))] = true }
	for _, k := range om.Keys() {
		name(k)
		o, isMap := or(get(om, k), yamlish.NewMap()).(*yamlish.Map)
		if !isMap {
			return nil, true // `.get` on an office that is not an object: AttributeError, caught
		}
		switch al := or(get(o, "aliases"), []any{}).(type) {
		case []any:
			for _, a := range al {
				if !compiler.Truthy(a) {
					continue
				}
				n, ok := pyStr(a)
				if !ok {
					return nil, false // str() of a float or a container: spelled by Python, not here
				}
				name(n)
			}
		case string:
			for _, c := range al { // iterating a string is its characters, as Python does
				name(string(c))
			}
		case *yamlish.Map:
			for _, k := range al.Keys() { // …and a mapping is its keys, the falsy one ("") skipped by `if a`
				if k != "" {
					name(k)
				}
			}
		default:
			return nil, true // iterating a number or True: TypeError, caught
		}
	}
	own, ok := s.ownOffice()
	if !ok {
		return nil, false
	}
	if own == "" || !ids[own] {
		return nil, true
	}
	return ids, true
}

// ownOffice is _own_office(): DGO_OFFICE_ID, or the office record's office.id — stripped, lowered — or "" (also
// for a record whose `office` is no object: app.py's herd reading catches that). Not ok for an answer this port
// reads otherwise than Python's json does.
func (s *Server) ownOffice() (string, bool) {
	if s.own != "" {
		return s.own, true
	}
	rec, unsure := s.office.record(false, s.now())
	if unsure {
		return "", false
	}
	m, _ := rec.(*yamlish.Map)
	if m == nil {
		return "", true // a plane that could not be asked: no record (app.py's None), no id
	}
	office := or(get(m, "office"), yamlish.NewMap())
	om, isMap := office.(*yamlish.Map)
	if !isMap {
		return "", true
	}
	id, ok := pyStr(or(get(om, "id"), ""))
	if !ok {
		return "", false
	}
	return strings.ToLower(pyval.Strip(id)), true
}

// verdicts is _link_verdicts(): `offices` of link.json — {office: {ok, hop, why}} — when it was
// written in the last five minutes (it is rewritten every minute; older is not a measurement), else
// nothing.
func (s *Server) verdicts() (any, bool) {
	none := yamlish.NewMap()
	raw, err := os.ReadFile(filepath.Join(s.peers, "link.json"))
	if err != nil {
		return none, true
	}
	v, err := loadJSON(raw)
	if err == errUnsure {
		return nil, false
	}
	doc, isMap := v.(*yamlish.Map)
	if err != nil || !isMap {
		return none, true // ValueError; doc["at"] on a list or a scalar is a TypeError — both caught
	}
	var t float64
	switch a := get(doc, "at").(type) {
	case int64:
		t = float64(a)
	case float64:
		t = a
	case bool:
		if a {
			t = 1
		}
	case string:
		return nil, false // float() of a string reads more shapes than this port does
	default:
		return none, true // a missing `at` (KeyError) or float() of None or a container (TypeError): caught
	}
	if now := float64(s.now().UnixNano()) / 1e9; !(now-t < 300) {
		return none, true
	}
	return or(get(doc, "offices"), none), true
}

// sortByOrder is sorted(…, key=lambda m: m.get("order", 999)) in place, stably. Not ok when Python
// would have to compare keys it cannot order (an int with a str, None with anything) — app.py's 500
// — or keys this port does not compare as Python does (floats). One entry is never compared.
func sortByOrder(ms []*yamlish.Map) bool {
	if len(ms) < 2 {
		return true
	}
	type keyed struct {
		m   *yamlish.Map
		num int64
		str string
	}
	ks := make([]keyed, len(ms))
	nums, strs := 0, 0
	for i, m := range ms {
		v, has := m.Get("order")
		if !has {
			v = int64(999)
		}
		ks[i].m = m
		switch o := v.(type) {
		case int64:
			ks[i].num, nums = o, nums+1
		case bool:
			if o {
				ks[i].num = 1
			}
			nums++
		case string:
			ks[i].str, strs = o, strs+1
		}
	}
	if nums != len(ms) && strs != len(ms) {
		return false
	}
	sort.SliceStable(ks, func(i, j int) bool {
		if nums == len(ms) {
			return ks[i].num < ks[j].num
		}
		return ks[i].str < ks[j].str
	})
	for i := range ks {
		ms[i] = ks[i].m
	}
	return true
}

// ── Python's values, as app.py touches them ──────────────────────────────────────────────────────

var errUnsure = errors.New("python reads this file in a way this port does not")

// maxDepth is the deepest nesting answered here. Python's json and PyYAML recurse per level and stop
// at the interpreter's recursion limit — app.py then answers 500, or (a peer file read at import)
// does not start — at a depth that depends on the stack around them; well below it, both always read.
const maxDepth = 100

// loadJSON is json.load of one file: yamlish.LoadJSON, the one reader of JSON as Python reads it, into
// the values yamlish reads YAML into — with what this port leaves to the container (errUnsure): a lone
// surrogate escape (Python keeps the half character; a Go string cannot), nesting past maxDepth, and
// values this port does not answer with as app.py does (NaN or an infinity, an integer past 64 bits);
// another error when Python's json.load raises ValueError on the same bytes.
func loadJSON(raw []byte) (any, error) {
	if !utf8.Valid(raw) {
		return nil, errors.New("not UTF-8") // open(encoding="utf-8") raises UnicodeDecodeError, a ValueError
	}
	v, err := yamlish.LoadJSON(string(raw))
	switch {
	case errors.Is(err, yamlish.ErrUnpairedSurrogate), errors.Is(err, yamlish.ErrJSONTooDeep):
		return nil, errUnsure
	case err != nil:
		return nil, err
	case tooDeep(v, 0) || unanswered(v):
		return nil, errUnsure
	}
	return v, nil
}

// unanswered reports a JSON value this port leaves to the container: NaN or an infinity (Python's json
// reads them), or an integer past 64 bits.
func unanswered(v any) bool {
	switch t := v.(type) {
	case float64:
		return math.IsNaN(t) || math.IsInf(t, 0)
	case yamlish.BigInt:
		return true
	case []any:
		for _, e := range t {
			if unanswered(e) {
				return true
			}
		}
	case *yamlish.Map:
		for _, k := range t.Keys() {
			if unanswered(get(t, k)) {
				return true
			}
		}
	}
	return false
}

// tooDeep reports nesting past maxDepth.
func tooDeep(v any, depth int) bool {
	if depth > maxDepth {
		return true
	}
	switch t := v.(type) {
	case []any:
		for _, e := range t {
			if tooDeep(e, depth+1) {
				return true
			}
		}
	case *yamlish.Map:
		for _, k := range t.Keys() {
			if tooDeep(get(t, k), depth+1) {
				return true
			}
		}
	}
	return false
}

// setKey is a value's identity in a Python set — True is 1, False is 0 — or not ok for a value this
// port does not hash as Python does (a float) or Python cannot hash at all (a list, a dict).
func setKey(v any) (string, bool) {
	switch t := v.(type) {
	case nil:
		return "N", true
	case bool:
		if t {
			return "I1", true
		}
		return "I0", true
	case int64:
		return "I" + strconv.FormatInt(t, 10), true
	case string:
		return "S" + t, true
	}
	return "", false
}

// pyStr is str(v) for the values whose str() this port spells exactly — spelled by internal/pyval,
// the one copy of Python's spellings; anything else is refused here, never guessed.
func pyStr(v any) (string, bool) {
	switch v.(type) {
	case string, int64, bool, nil:
		return pyval.Str(v), true
	}
	return "", false
}

// get is dict.get(k): the value, or None when the key is absent.
func get(m *yamlish.Map, k string) any {
	v, _ := m.Get(k)
	return v
}

// or is Python's `a or b`.
func or(a, b any) any {
	if compiler.Truthy(a) {
		return a
	}
	return b
}

func copyMap(m *yamlish.Map) *yamlish.Map {
	c := yamlish.NewMap()
	for _, k := range m.Keys() {
		c.Set(k, get(m, k))
	}
	return c
}

// newMap builds a mapping from key, value pairs.
func newMap(kv ...any) *yamlish.Map {
	m := yamlish.NewMap()
	for i := 0; i+1 < len(kv); i += 2 {
		m.Set(kv[i].(string), kv[i+1])
	}
	return m
}

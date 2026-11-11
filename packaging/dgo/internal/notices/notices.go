// Package notices is «התראות» — platform-base/notifications/app.py — where the office has no container to run
// it: the phone's core (DGO-1328). On the phone the tile answered «the machine is not on this phone», and the
// notice board is exactly what the owner wants to see first; so this process answers its screen and its API.
//
// It is app.py's routes, answered as app.py answers them — the same row, the same order, the same codes:
//
//	GET    /api/notifications?unread=1&source=&level=&limit=   {"notifications": [row…], "count": n}
//	GET    /api/notifications/<id>                              row | 404 {"error":"not_found"}
//	POST   /api/notifications {source, title, …}                {"id", "created"} 201 | 200 (upsert by source+source_id)
//	POST   /api/notifications/<id>/read {read:false}            {"ok", "is_read"}
//	POST   /api/notifications/read-all · /clear-read            {"ok", "updated"|"deleted"}
//	GET    /api/notifications/unread-count · /stats              app.py's shapes
//	DELETE /api/notifications/<id>                              {"ok"} | 404
//	GET    /api/push/key                                         {"enabled": false} — no Web Push on a phone: the
//	                                                             page shows no push card (push.js start())
//	GET    /healthz                                              {"ok": true, "db": true, "poller": true, …}
//	GET    / and the screen's files                              <root>/platform-base/notifications/static
//
// What it does NOT do, said here so it is never mistaken for a gap: poll GlitchTip (a phone runs none), ring
// phones (Web Push is the server's), publish the office's stream (flow.v1 needs redis, which a phone has not).
// The store is one JSON file, written whole and atomically: a phone's notices are tens, not tens of thousands.
package notices

import (
	"bytes"
	"encoding/json"
	"errors"
	"log"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/screen"
)

// screenDir is where an office root carries the notice board's screen, as the container's image has it.
var screenDir = filepath.Join("platform-base", "notifications", "static")

// Row is one notice, as app.py's _row() writes it.
type Row struct {
	ID        int             `json:"id"`
	Source    string          `json:"source"`
	SourceID  *string         `json:"source_id"`
	Title     string          `json:"title"`
	Body      string          `json:"body"`
	Level     string          `json:"level"`
	Link      string          `json:"link"`
	Meta      json.RawMessage `json:"meta"`
	IsRead    bool            `json:"is_read"`
	CreatedAt string          `json:"created_at"`
	UpdatedAt string          `json:"updated_at"`
	LastSeen  string          `json:"last_seen"`
}

type board struct {
	Next int    `json:"next"`
	Rows []*Row `json:"rows"`
}

type server struct {
	mu    sync.Mutex
	path  string // the store: <dataDir>/notifications.json
	root  string // the office root: the screen's files
	now   func() time.Time
	cache *board
}

// New answers «התראות» from the office root (the screen) and dataDir (the store, created on the first write).
func New(root, dataDir string) http.Handler {
	return newServer(root, dataDir, time.Now)
}

func newServer(root, dataDir string, now func() time.Time) *server {
	return &server{path: filepath.Join(dataDir, "notifications.json"), root: root, now: now}
}

func (s *server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Path
	switch {
	case p == "/healthz":
		s.mu.Lock()
		_, err := s.load()
		s.mu.Unlock()
		code, detail := http.StatusOK, "ok"
		if err != nil { // app.py: RED (503) whenever this service cannot do its job
			code, detail = http.StatusServiceUnavailable, "the notice board's file cannot be read"
		}
		reply(w, code, map[string]any{"ok": err == nil, "db": err == nil, "poller": true, "token": false, "detail": detail})
	case p == "/api/push/key" && get(r):
		reply(w, http.StatusOK, map[string]any{"enabled": false, "ready": false, "key": "", "levels": []string{}, "person": ""})
	case strings.HasPrefix(p, "/api/push/"):
		reply(w, http.StatusNotFound, map[string]any{"error": "push is not on this office"})
	case p == "/api/notifications" || strings.HasPrefix(p, "/api/notifications/"):
		s.api(w, r, strings.TrimPrefix(strings.TrimPrefix(p, "/api/notifications"), "/"))
	case strings.HasPrefix(p, "/api/"):
		reply(w, http.StatusNotFound, map[string]any{"error": "not_found"})
	default:
		dir := filepath.Join(s.root, screenDir)
		if get(r) && screen.Serve(w, r, dir) {
			return
		}
		// the console container's history fallback (console/app.py): a page whose last segment has no
		// extension — a link to one notice, /a/alerts/<id> — is the screen's index.html, which routes it
		if last := p[strings.LastIndex(p, "/")+1:]; get(r) && last != "" && !strings.Contains(last, ".") {
			page := r.Clone(r.Context())
			page.URL.Path = "/"
			if screen.Serve(w, page, dir) {
				return
			}
		}
		http.NotFound(w, r)
	}
}

func get(r *http.Request) bool { return r.Method == http.MethodGet || r.Method == http.MethodHead }

func (s *server) api(w http.ResponseWriter, r *http.Request, rest string) {
	switch {
	case rest == "" && get(r):
		s.list(w, r)
	case rest == "" && r.Method == http.MethodPost:
		s.create(w, r)
	case rest == "read-all" && r.Method == http.MethodPost:
		s.bulk(w, "updated", func(b *board, now string) int {
			n := 0
			for _, x := range b.Rows {
				if !x.IsRead {
					x.IsRead, x.UpdatedAt, n = true, now, n+1
				}
			}
			return n
		})
	case rest == "clear-read" && r.Method == http.MethodPost:
		s.bulk(w, "deleted", func(b *board, _ string) int {
			kept := b.Rows[:0]
			for _, x := range b.Rows {
				if !x.IsRead {
					kept = append(kept, x)
				}
			}
			n := len(b.Rows) - len(kept)
			b.Rows = kept
			return n
		})
	case rest == "unread-count" && get(r):
		s.mu.Lock()
		defer s.mu.Unlock()
		b, err := s.load()
		if err != nil {
			fail(w, err)
			return
		}
		n := 0
		for _, x := range b.Rows {
			if !x.IsRead {
				n++
			}
		}
		reply(w, http.StatusOK, map[string]any{"count": n})
	case rest == "stats" && get(r):
		s.stats(w)
	case rest == "" || rest == "read-all" || rest == "clear-read" || rest == "unread-count" || rest == "stats":
		reply(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"}) // werkzeug: a known path
	default:
		id, tail, _ := strings.Cut(rest, "/")
		nid, err := strconv.Atoi(id)
		if err != nil || nid < 0 || id != strconv.Itoa(nid) {
			reply(w, http.StatusNotFound, map[string]any{"error": "not_found"}) // werkzeug's <int:nid> matches none
			return
		}
		switch {
		case tail == "" && get(r):
			s.one(w, nid)
		case tail == "" && r.Method == http.MethodDelete:
			s.remove(w, nid)
		case tail == "read" && r.Method == http.MethodPost:
			s.read(w, r, nid)
		default:
			reply(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
		}
	}
}

// ── the store ─────────────────────────────────────────────────────────────────────────────────────────────

func (s *server) load() (*board, error) {
	if s.cache != nil {
		return s.cache, nil
	}
	b := &board{Next: 1}
	data, err := os.ReadFile(s.path)
	switch {
	case errors.Is(err, os.ErrNotExist):
	case err != nil:
		return nil, err
	default:
		if err := json.Unmarshal(data, b); err != nil {
			return nil, err // a damaged board is said, never replaced by an empty one
		}
	}
	s.cache = b
	return b, nil
}

func (s *server) save(b *board) error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o700); err != nil {
		return err
	}
	data, err := json.Marshal(b)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(s.path), ".notifications-")
	if err != nil {
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	if err := tmp.Sync(); err != nil { // on the disk before the rename: a phone killed mid-save keeps a whole board
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	if err := os.Rename(tmp.Name(), s.path); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	s.cache = b
	return nil
}

func (s *server) stamp() string { return s.now().UTC().Format("2006-01-02T15:04:05.000000+00:00") }

// ── the routes ────────────────────────────────────────────────────────────────────────────────────────────

func bucket(level string) string {
	switch strings.ToLower(level) {
	case "error", "fatal", "critical":
		return "error"
	case "warning", "warn":
		return "warning"
	}
	return "info"
}

func (s *server) list(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := s.load()
	if err != nil {
		fail(w, err)
		return
	}
	q := r.URL.Query()
	limit := 100 // int(request.args.get("limit", 100)), and 100 when it is not an integer
	if v, err := strconv.Atoi(strings.TrimSpace(q.Get("limit"))); err == nil {
		limit = max(1, min(500, v))
	}
	lvl := strings.ToLower(q.Get("level"))
	out := []*Row{}
	for _, x := range b.Rows {
		if q.Get("unread") == "1" && x.IsRead {
			continue
		}
		if src := q.Get("source"); src != "" && x.Source != src {
			continue
		}
		if (lvl == "error" || lvl == "warning" || lvl == "info") && bucket(x.Level) != lvl {
			continue
		}
		out = append(out, x)
	}
	// app.py: ORDER BY COALESCE(last_seen, created_at) DESC, id DESC
	sort.SliceStable(out, func(i, j int) bool {
		a, c := seen(out[i]), seen(out[j])
		if a != c {
			return a > c
		}
		return out[i].ID > out[j].ID
	})
	if len(out) > limit {
		out = out[:limit]
	}
	reply(w, http.StatusOK, map[string]any{"notifications": out, "count": len(out)})
}

func seen(x *Row) string {
	if x.LastSeen != "" {
		return x.LastSeen
	}
	return x.CreatedAt
}

func (s *server) find(b *board, id int) *Row {
	for _, x := range b.Rows {
		if x.ID == id {
			return x
		}
	}
	return nil
}

func (s *server) one(w http.ResponseWriter, id int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := s.load()
	if err != nil {
		fail(w, err)
		return
	}
	if x := s.find(b, id); x != nil {
		reply(w, http.StatusOK, x)
		return
	}
	reply(w, http.StatusNotFound, map[string]any{"error": "not_found"})
}

// maxRows bounds the board: anyone who can POST adds a row, and every write rewrites the whole file. Past it,
// the oldest READ notices go first, then the oldest of all.
const maxRows = 1000

// body is get_json(silent=True) or {}: one JSON object with its keys exactly as written (Flask is case-exact),
// its numbers exact (json.Number), and nothing after it; anything else is no fields.
func body(w http.ResponseWriter, r *http.Request, limit int64) map[string]any {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, limit))
	dec.UseNumber()
	var v map[string]any
	if dec.Decode(&v) != nil || dec.Decode(new(any)) == nil {
		return map[string]any{}
	}
	if v == nil {
		return map[string]any{}
	}
	return v
}

// truthy is Python's: `if not b.get("source")` refuses None, "", 0, False, [] and {}.
func truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case string:
		return t != ""
	case json.Number:
		f, err := t.Float64()
		return err != nil || f != 0
	case bool:
		return t
	case []any:
		return len(t) > 0
	case map[string]any:
		return len(t) > 0
	}
	return true
}

func text(v any, def string) string {
	switch t := v.(type) {
	case nil:
		return def
	case string:
		return t
	case json.Number:
		return t.String()
	case bool:
		if t {
			return "True"
		}
		return "False"
	}
	b, _ := json.Marshal(v)
	return string(b)
}

// create is app.py's post_notification + create_notification: an upsert by (source, source_id), and a NEW
// occurrence (meta.count up, or meta.lastSeen later) marks it unread again and moves it to the top.
func (s *server) create(w http.ResponseWriter, r *http.Request) {
	p := body(w, r, 1<<20)
	if !truthy(p["source"]) || !truthy(p["title"]) {
		reply(w, http.StatusBadRequest, map[string]any{"error": "source and title required"})
		return
	}
	src, title := text(p["source"], ""), text(p["title"], "")
	meta := map[string]any{}
	switch m := p["meta"].(type) {
	case map[string]any:
		meta = m
	default:
		if truthy(m) { // a falsy meta ("", 0, false, [], null) was always read as {}
			reply(w, http.StatusBadRequest, map[string]any{"error": "meta is an object"})
			return
		}
	}
	var sid *string
	if v, ok := p["source_id"]; ok && v != nil {
		t := text(v, "")
		sid = &t
	}
	level, msg, link := text(p["level"], "info"), text(p["body"], ""), text(p["link"], "")
	var metaBuf bytes.Buffer
	enc := json.NewEncoder(&metaBuf)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(meta)
	metaJSON := json.RawMessage(bytes.TrimSpace(metaBuf.Bytes()))
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := s.load()
	if err != nil {
		fail(w, err)
		return
	}
	now := s.stamp()
	last := now
	if v, ok := meta["lastSeen"].(string); ok && v != "" {
		last = v
	}
	// the upsert's key: app.py's unique index (source, source_id), in which every NULL is DIFFERENT — a notice
	// with no source_id is always a row of its own
	var hit *Row
	if sid != nil {
		for _, x := range b.Rows {
			if x.Source == src && x.SourceID != nil && *x.SourceID == *sid {
				hit = x
				break
			}
		}
	}
	created := hit == nil
	if created {
		hit = &Row{ID: b.Next, Source: src, SourceID: sid, CreatedAt: now}
		b.Next++
		b.Rows = append(b.Rows, hit)
		b.Rows = trim(b.Rows)
	} else if count(meta) > count(hit.Meta) || (hit.LastSeen != "" && last > hit.LastSeen) {
		hit.IsRead = false // a NEW occurrence: re-surfaced
	}
	hit.Title, hit.Body, hit.Level, hit.Link, hit.Meta, hit.UpdatedAt, hit.LastSeen = title, msg, level, link, metaJSON, now, last
	if err := s.save(b); err != nil {
		s.cache = nil
		fail(w, err)
		return
	}
	code := http.StatusOK
	if created {
		code = http.StatusCreated
	}
	reply(w, code, map[string]any{"id": hit.ID, "created": created})
}

// trim keeps the board at maxRows: the oldest read notices go first, then the oldest of all.
func trim(rows []*Row) []*Row {
	for len(rows) > maxRows {
		drop, read := 0, false
		for i, x := range rows {
			if x.IsRead && (!read || seen(x) < seen(rows[drop])) {
				drop, read = i, true
			} else if !read && seen(x) < seen(rows[drop]) {
				drop = i
			}
		}
		rows = append(rows[:drop], rows[drop+1:]...)
	}
	return rows
}

// count is _cnt(): int(meta.count), or 0 when that is not a number.
func count(m any) float64 {
	d, _ := m.(map[string]any)
	if raw, ok := m.(json.RawMessage); ok {
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.UseNumber()
		_ = dec.Decode(&d)
	}
	switch v := d["count"].(type) {
	case json.Number:
		if f, err := v.Float64(); err == nil {
			return math.Trunc(f)
		}
	case string:
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			return float64(n)
		}
	case bool:
		if v {
			return 1
		}
	}
	return 0
}

func (s *server) read(w http.ResponseWriter, r *http.Request, id int) {
	read := body(w, r, 1<<16)["read"] != false // {read:false} marks unread; anything else, read
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := s.load()
	if err != nil {
		fail(w, err)
		return
	}
	x := s.find(b, id)
	if x == nil {
		reply(w, http.StatusNotFound, map[string]any{"error": "not_found"})
		return
	}
	x.IsRead, x.UpdatedAt = read, s.stamp()
	if err := s.save(b); err != nil {
		s.cache = nil
		fail(w, err)
		return
	}
	reply(w, http.StatusOK, map[string]any{"ok": true, "is_read": read})
}

func (s *server) bulk(w http.ResponseWriter, key string, change func(*board, string) int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := s.load()
	if err != nil {
		fail(w, err)
		return
	}
	n := change(b, s.stamp())
	if n > 0 {
		if err := s.save(b); err != nil {
			s.cache = nil
			fail(w, err)
			return
		}
	}
	reply(w, http.StatusOK, map[string]any{"ok": true, key: n})
}

func (s *server) remove(w http.ResponseWriter, id int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := s.load()
	if err != nil {
		fail(w, err)
		return
	}
	for i, x := range b.Rows {
		if x.ID == id {
			b.Rows = append(b.Rows[:i], b.Rows[i+1:]...)
			if err := s.save(b); err != nil {
				s.cache = nil
				fail(w, err)
				return
			}
			reply(w, http.StatusOK, map[string]any{"ok": true})
			return
		}
	}
	reply(w, http.StatusNotFound, map[string]any{"error": "not_found"})
}

func (s *server) stats(w http.ResponseWriter) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := s.load()
	if err != nil {
		fail(w, err)
		return
	}
	byLevel := map[string]int{"error": 0, "warning": 0, "info": 0}
	unreadByLevel := map[string]int{"error": 0, "warning": 0, "info": 0}
	bySource, unreadBySource := map[string]int{}, map[string]int{}
	unread := 0
	for _, x := range b.Rows {
		lv, src := bucket(x.Level), x.Source
		if src == "" {
			src = "system"
		}
		byLevel[lv]++
		bySource[src]++
		if !x.IsRead {
			unread++
			unreadByLevel[lv]++
			unreadBySource[src]++
		}
	}
	reply(w, http.StatusOK, map[string]any{"total": len(b.Rows), "unread": unread, "by_level": byLevel,
		"unread_by_level": unreadByLevel, "by_source": bySource, "unread_by_source": unreadBySource})
}

func reply(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

// fail is the store that cannot be read or written: said, never an empty board — its reason in the core's log,
// not on the page (an OS error names the file's path)
func fail(w http.ResponseWriter, err error) {
	log.Printf("dgo notices: the notice board's file: %v", err)
	reply(w, http.StatusInternalServerError, map[string]any{"error": "the notice board's file cannot be read or written"})
}

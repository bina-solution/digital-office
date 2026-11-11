package notices

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

type clock struct{ t time.Time }

func (c *clock) now() time.Time { return c.t }

func newBoard(t *testing.T) (*server, *clock, string) {
	t.Helper()
	root, data := t.TempDir(), t.TempDir()
	static := filepath.Join(root, screenDir)
	if err := os.MkdirAll(static, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(static, "index.html"), []byte("<!doctype html><title>התראות</title>"), 0o644); err != nil {
		t.Fatal(err)
	}
	c := &clock{time.Date(2026, 11, 4, 1, 0, 0, 0, time.UTC)}
	return newServer(root, data, c.now), c, data
}

func call(t *testing.T, h http.Handler, method, path, body string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	var out map[string]any
	if strings.HasPrefix(rec.Header().Get("Content-Type"), "application/json") {
		if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
			t.Fatalf("%s %s: %v\n%s", method, path, err, rec.Body.String())
		}
	}
	return rec.Code, out
}

func TestTheBoardAnswersAsAppPyDoes(t *testing.T) {
	s, c, _ := newBoard(t)
	code, out := call(t, s, "POST", "/api/notifications", `{"source":"core","source_id":"machine","title":"המכונה ירדה","level":"error"}`)
	if code != 201 || out["created"] != true || out["id"] != 1.0 {
		t.Fatalf("create: %d %v", code, out)
	}
	c.t = c.t.Add(time.Minute)
	call(t, s, "POST", "/api/notifications", `{"source":"core","title":"חוזר ללא source_id"}`)
	c.t = c.t.Add(time.Minute)
	code, out = call(t, s, "POST", "/api/notifications", `{"source":"core","source_id":"machine","title":"המכונה ירדה","level":"error"}`)
	if code != 200 || out["created"] != false || out["id"] != 1.0 {
		t.Fatalf("upsert: %d %v", code, out)
	}
	_, out = call(t, s, "GET", "/api/notifications", "")
	rows := out["notifications"].([]any)
	if len(rows) != 2 || rows[0].(map[string]any)["id"] != 1.0 { // a recurrence moves to the top (last_seen)
		t.Fatalf("list order: %v", rows)
	}
	first := rows[0].(map[string]any)
	for _, k := range []string{"id", "source", "source_id", "title", "body", "level", "link", "meta", "is_read", "created_at", "updated_at", "last_seen"} {
		if _, ok := first[k]; !ok {
			t.Fatalf("row lacks %q: %v", k, first)
		}
	}
	_, out = call(t, s, "GET", "/api/notifications?level=error", "")
	if out["count"] != 1.0 {
		t.Fatalf("level filter: %v", out)
	}
	_, out = call(t, s, "GET", "/api/notifications?limit=x&source=core", "")
	if out["count"] != 2.0 {
		t.Fatalf("a limit that is not a number is 100: %v", out)
	}
	if code, out = call(t, s, "POST", "/api/notifications/1/read", ``); code != 200 || out["is_read"] != true {
		t.Fatalf("read: %d %v", code, out)
	}
	_, out = call(t, s, "GET", "/api/notifications?unread=1", "")
	if out["count"] != 1.0 {
		t.Fatalf("unread: %v", out)
	}
	if _, out = call(t, s, "POST", "/api/notifications/1/read", `{"read":false}`); out["is_read"] != false {
		t.Fatalf("unread again: %v", out)
	}
	_, out = call(t, s, "GET", "/api/notifications/stats", "")
	if out["total"] != 2.0 || out["unread"] != 2.0 || out["by_level"].(map[string]any)["error"] != 1.0 ||
		out["by_source"].(map[string]any)["core"] != 2.0 {
		t.Fatalf("stats: %v", out)
	}
	if _, out = call(t, s, "POST", "/api/notifications/read-all", ""); out["updated"] != 2.0 {
		t.Fatalf("read-all: %v", out)
	}
	if _, out = call(t, s, "GET", "/api/notifications/unread-count", ""); out["count"] != 0.0 {
		t.Fatalf("unread-count: %v", out)
	}
	if code, _ = call(t, s, "DELETE", "/api/notifications/2", ""); code != 200 {
		t.Fatalf("delete: %d", code)
	}
	if code, out = call(t, s, "DELETE", "/api/notifications/2", ""); code != 404 || out["error"] != "not_found" {
		t.Fatalf("delete twice: %d %v", code, out)
	}
	if _, out = call(t, s, "POST", "/api/notifications/clear-read", ""); out["deleted"] != 1.0 {
		t.Fatalf("clear-read: %v", out)
	}
	if code, _ = call(t, s, "GET", "/api/notifications/abc", ""); code != 404 {
		t.Fatalf("a non-integer id: %d", code)
	}
}

func TestANewOccurrenceIsUnreadAgain(t *testing.T) {
	s, c, _ := newBoard(t)
	call(t, s, "POST", "/api/notifications", `{"source":"x","source_id":"1","title":"t","meta":{"count":1,"lastSeen":"2026-11-04T00:00:00+00:00"}}`)
	call(t, s, "POST", "/api/notifications/1/read", "")
	c.t = c.t.Add(time.Minute)
	call(t, s, "POST", "/api/notifications", `{"source":"x","source_id":"1","title":"t","meta":{"count":1,"lastSeen":"2026-11-04T00:00:00+00:00"}}`)
	if _, out := call(t, s, "GET", "/api/notifications/1", ""); out["is_read"] != true {
		t.Fatalf("a refresh with nothing new keeps it read: %v", out)
	}
	call(t, s, "POST", "/api/notifications", `{"source":"x","source_id":"1","title":"t","meta":{"count":2,"lastSeen":"2026-11-04T00:05:00+00:00"}}`)
	if _, out := call(t, s, "GET", "/api/notifications/1", ""); out["is_read"] != false {
		t.Fatalf("a new occurrence is unread again: %v", out)
	}
}

func TestRefusedAsAppPyRefuses(t *testing.T) {
	s, _, _ := newBoard(t)
	for _, body := range []string{``, `not json`, `{"title":"t"}`, `{"source":"s"}`, `{"source":0,"title":"t"}`, `{"source":"s","title":""}`} {
		if code, out := call(t, s, "POST", "/api/notifications", body); code != 400 || out["error"] != "source and title required" {
			t.Fatalf("%s: %d %v", body, code, out)
		}
	}
	if code, out := call(t, s, "POST", "/api/notifications", `{"source":"s","title":"t","meta":["x"]}`); code != 400 {
		t.Fatalf("a meta that is a list: %d %v", code, out)
	}
	if code, _ := call(t, s, "POST", "/api/notifications", `{"source":"s","title":"t","meta":""}`); code != 201 {
		t.Fatalf("a falsy meta is {}: %d", code)
	}
}

func TestTheBoardSurvivesARestartAndADamagedFileIsSaid(t *testing.T) {
	s, _, data := newBoard(t)
	call(t, s, "POST", "/api/notifications", `{"source":"core","title":"נשמר"}`)
	again := newServer(s.root, data, time.Now)
	if _, out := call(t, again, "GET", "/api/notifications", ""); out["count"] != 1.0 {
		t.Fatalf("after a restart: %v", out)
	}
	if err := os.WriteFile(filepath.Join(data, "notifications.json"), []byte("{broken"), 0o600); err != nil {
		t.Fatal(err)
	}
	broken := newServer(s.root, data, time.Now)
	if code, out := call(t, broken, "GET", "/api/notifications", ""); code != 500 || !strings.Contains(out["error"].(string), "notice board") {
		t.Fatalf("a damaged board: %d %v", code, out)
	}
	if b, _ := os.ReadFile(filepath.Join(data, "notifications.json")); string(b) != "{broken" {
		t.Fatalf("a damaged board was replaced: %q", b)
	}
}

func TestNoticesWithNoSourceIDAreEachARow(t *testing.T) {
	s, _, _ := newBoard(t)
	for i, title := range []string{"ראשונה", "שנייה"} {
		if code, out := call(t, s, "POST", "/api/notifications", `{"source":"core","title":"`+title+`"}`); code != 201 || out["id"] != float64(i+1) {
			t.Fatalf("%s: %d %v", title, code, out)
		}
	}
	if _, out := call(t, s, "GET", "/api/notifications", ""); out["count"] != 2.0 {
		t.Fatalf("two notices with no source_id are two rows: %v", out)
	}
}

func TestTheBodyIsReadAsFlaskReadsIt(t *testing.T) {
	s, _, _ := newBoard(t)
	for _, b := range []string{`{"Source":"s","Title":"t"}`, `{"source":"s","title":"t"} {}`, `[1]`, `{"source":[],"title":"t"}`} {
		if code, _ := call(t, s, "POST", "/api/notifications", b); code != 400 {
			t.Fatalf("%s: %d", b, code)
		}
	}
	for _, m := range []string{`[]`, `0`, `false`, `null`, `""`} {
		if code, _ := call(t, s, "POST", "/api/notifications", `{"source":"s","title":"t","meta":`+m+`}`); code != 201 {
			t.Fatalf("a falsy meta %s is {}: %d", m, code)
		}
	}
	call(t, s, "POST", "/api/notifications", `{"source":"big","source_id":9007199254740993,"title":"t"}`)
	call(t, s, "POST", "/api/notifications", `{"source":"big","source_id":9007199254740992,"title":"t"}`)
	if _, out := call(t, s, "GET", "/api/notifications?source=big", ""); out["count"] != 2.0 {
		t.Fatalf("two ids past 2^53 stay two: %v", out)
	}
	if code, _ := call(t, s, "GET", "/api/notifications/read-all", ""); code != 405 {
		t.Fatalf("a known path, another method: %d", code)
	}
	_, out := call(t, s, "GET", "/api/notifications?limit=-3", "")
	if out["count"] != 1.0 {
		t.Fatalf("limit is at least 1: %v", out)
	}
}

func TestTheBoardIsBounded(t *testing.T) {
	s, c, _ := newBoard(t)
	call(t, s, "POST", "/api/notifications", `{"source":"keep","source_id":"0","title":"לא נקראה, הכי ישנה"}`)
	for i := 1; i <= maxRows+5; i++ {
		c.t = c.t.Add(time.Second)
		call(t, s, "POST", "/api/notifications", `{"source":"x","source_id":"`+strconv.Itoa(i)+`","title":"t"}`)
		if i <= 10 {
			call(t, s, "POST", "/api/notifications/"+strconv.Itoa(i+1)+"/read", "")
		}
	}
	b, _ := s.load()
	if len(b.Rows) != maxRows {
		t.Fatalf("rows: %d", len(b.Rows))
	}
	if s.find(b, 1) == nil {
		t.Fatalf("an unread notice went before the read ones")
	}
}

func TestReadersAndWritersTogether(t *testing.T) { // go test -race
	s, _, _ := newBoard(t)
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			for j := 0; j < 20; j++ {
				call(t, s, "POST", "/api/notifications", `{"source":"r","title":"t"}`)
				call(t, s, "GET", "/api/notifications/unread-count", "")
				call(t, s, "GET", "/healthz", "")
				call(t, s, "POST", "/api/notifications/clear-read", "")
				call(t, s, "POST", "/api/notifications/read-all", "")
			}
		}(i)
	}
	wg.Wait()
}

func TestTheScreenAndNoPushOnAPhone(t *testing.T) {
	s, _, _ := newBoard(t)
	req := httptest.NewRequest("GET", "/", nil)
	rec := httptest.NewRecorder()
	s.ServeHTTP(rec, req)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), "התראות") {
		t.Fatalf("the screen: %d %q", rec.Code, rec.Body.String())
	}
	if _, out := call(t, s, "GET", "/api/push/key", ""); out["enabled"] != false {
		t.Fatalf("push key: %v", out)
	}
	if code, _ := call(t, s, "POST", "/api/push/subscribe", "{}"); code != 404 {
		t.Fatalf("push subscribe: %d", code)
	}
	if code, out := call(t, s, "GET", "/healthz", ""); code != 200 || out["ok"] != true {
		t.Fatalf("healthz: %d %v", code, out)
	}
	for _, p := range []string{"/../app.json", "/.hidden", "/nope.js"} {
		rec := httptest.NewRecorder()
		s.ServeHTTP(rec, httptest.NewRequest("GET", p, nil))
		if rec.Code != 404 {
			t.Fatalf("%s: %d", p, rec.Code)
		}
	}
	rec = httptest.NewRecorder() // a link to one notice is the screen's page, which routes it
	s.ServeHTTP(rec, httptest.NewRequest("GET", "/5", nil))
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), "התראות") {
		t.Fatalf("/5: %d", rec.Code)
	}
}

func TestADamagedBoardIsUnhealthy(t *testing.T) {
	s, _, data := newBoard(t)
	if err := os.WriteFile(filepath.Join(data, "notifications.json"), []byte("{"), 0o600); err != nil {
		t.Fatal(err)
	}
	code, out := call(t, s, "GET", "/healthz", "")
	if code != 503 || out["ok"] != false {
		t.Fatalf("healthz on a damaged board: %d %v", code, out)
	}
	if _, out = call(t, s, "GET", "/api/notifications", ""); strings.Contains(out["error"].(string), data) {
		t.Fatalf("the error names the file's path: %v", out)
	}
}

package extend

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func newExtend(t *testing.T, door string) *server {
	t.Helper()
	root := t.TempDir()
	static := filepath.Join(root, screenDir)
	if err := os.MkdirAll(static, 0o755); err != nil {
		t.Fatal(err)
	}
	for name, body := range map[string]string{
		"index.html":   "<!doctype html><html><head><title>הרחבת הלשכה</title></head></html>",
		"app.js":       "// the page's code",
		"connect.html": "<!doctype html><title>צימוד</title>",
	} {
		if err := os.WriteFile(filepath.Join(static, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return New(Config{Root: root, Label: "הטלפון של שלמה", Door: door}).(*server)
}

func do(t *testing.T, s *server, method, path string) (int, map[string]any, string) {
	t.Helper()
	rec := httptest.NewRecorder()
	s.ServeHTTP(rec, httptest.NewRequest(method, path, strings.NewReader("{}")))
	var out map[string]any
	if strings.HasPrefix(rec.Header().Get("Content-Type"), "application/json") {
		if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
			t.Fatalf("%s %s: %v", method, path, err)
		}
	}
	return rec.Code, out, rec.Body.String()
}

func TestTheScreenOpensAndSaysWhatAPhoneIs(t *testing.T) {
	s := newExtend(t, "https://console.staging.digital-office.co.il/")
	code, out, _ := do(t, s, "GET", "/api/pair")
	if code != 409 || !strings.Contains(out["error"].(string), "console.staging.digital-office.co.il") {
		t.Fatalf("pair: %d %v", code, out) // the screen draws a 409 as the office's state (loadSelf)
	}
	if code, _, _ = do(t, s, "GET", "/api/pair/giving"); code != 404 {
		t.Fatalf("giving: %d", code)
	}
	_, out, _ = do(t, s, "GET", "/api/context")
	if out["home"].(map[string]any)["error"] == "" || len(out["machines"].([]any)) != 0 {
		t.Fatalf("context: %v", out) // home.error: «add an office» drawn disabled
	}
	for _, p := range []string{"/api/office", "/api/link", "/api/invite"} {
		if code, out, _ = do(t, s, "GET", p); code != 200 || len(out["items"].([]any)) != 0 {
			t.Fatalf("%s: %d %v", p, code, out)
		}
	}
	_, out, _ = do(t, s, "GET", "/api/join")
	if out["door"].(map[string]any)["host"] != "" || len(out["requests"].([]any)) != 0 {
		t.Fatalf("join: %v", out) // no hub: no join card, no «invite»
	}
	_, out, _ = do(t, s, "GET", "/api/map")
	if out["home"].(map[string]any)["label"] != "הטלפון של שלמה" || len(out["items"].([]any)) != 0 {
		t.Fatalf("map: %v", out)
	}
}

func TestEveryVerbOfLinkingIsRefusedInWords(t *testing.T) {
	s := newExtend(t, "")
	for _, c := range [][2]string{{"POST", "/api/pair/offer"}, {"POST", "/api/office"}, {"DELETE", "/api/pair/x"},
		{"POST", "/api/join/r/approve"}, {"POST", "/api/invite"}, {"POST", "/api/office/x/converge"}} {
		code, out, _ := do(t, s, c[0], c[1])
		if code != 409 || !strings.Contains(out["error"].(string), "לבד") {
			t.Fatalf("%s %s: %d %v", c[0], c[1], code, out)
		}
	}
}

func TestTheScreensFilesAndItsPages(t *testing.T) {
	s := newExtend(t, "")
	for _, p := range []string{"/", "/map/vps1/meet", "/office"} {
		if code, _, body := do(t, s, "GET", p); code != 200 || !strings.Contains(body, "הרחבת הלשכה") {
			t.Fatalf("%s: %d", p, code)
		}
	}
	// the page loads its code at static/ (app.py's mount), and the pairing screen is /connect
	if code, _, body := do(t, s, "GET", "/static/app.js"); code != 200 || !strings.Contains(body, "the page's code") {
		t.Fatalf("/static/app.js: %d", code)
	}
	if code, _, body := do(t, s, "GET", "/connect"); code != 200 || !strings.Contains(body, "צימוד") {
		t.Fatalf("/connect: %d", code)
	}
	// a deep page carries the console's <base>, so its relative static/ and api/ resolve under the app
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/map/vps1/meet", nil)
	req.Header.Set("X-Forwarded-Prefix", "/a/dgo-extend")
	s.ServeHTTP(rec, req)
	if !strings.Contains(rec.Body.String(), `<head><base href="/a/dgo-extend/">`) {
		t.Fatalf("a deep page without its base: %q", rec.Body.String())
	}
	// an API path under a deep page is JSON's or nothing — never the page
	for _, p := range []string{"/nope.js", "/../app.json", "/.git", "/map/vps1/api/office", "/static/../app.json"} {
		if code, _, _ := do(t, s, "GET", p); code != 404 {
			t.Fatalf("%s: %d", p, code)
		}
	}
}

func TestNothingOnTheScreenOffersWhatIsRefused(t *testing.T) {
	s := newExtend(t, "")
	_, out, _ := do(t, s, "GET", "/api/join")
	if out["joiner"].(map[string]any)["state"] != "off" {
		t.Fatalf("a joiner that is not off draws a join card: %v", out)
	}
	_, out, _ = do(t, s, "GET", "/api/context")
	if out["home"].(map[string]any)["refused"] != true {
		t.Fatalf("context: %v", out)
	}
	_, out, _ = do(t, s, "GET", "/api/map")
	if out["home"].(map[string]any)["label"] != "הטלפון הזה" && newExtend(t, "").c.Label == "" {
		t.Fatalf("map: %v", out)
	}
}

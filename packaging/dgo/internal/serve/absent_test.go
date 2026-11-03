package serve

import (
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

// absentMachine is a phone's machine that is not up: its refusal or its step, as the app writes them.
type absentMachine struct{ refused, step string }

func (absentMachine) Up() (int, string) { return 0, "" }
func (absentMachine) Want() error       { return nil }
func (m absentMachine) Refused() string { return m.refused }
func (absentMachine) Forget()           {}
func (m absentMachine) Step() string    { return m.step }

// The owner's taps on a phone with no machine (DGO-1084, android-0.1.54): a page for a navigation or a
// frame, JSON for a script's call — 503 either way, never the proxy's error — with the app's own reason.
func TestAbsentAnswersAPageOrJSON(t *testing.T) {
	for _, c := range []struct {
		name   string
		header map[string]string
		m      Machine
		page   bool
		has    string
	}{
		{"a frame's navigation", map[string]string{"Sec-Fetch-Dest": "iframe"},
			absentMachine{refused: "the machine is not on this phone yet"}, true, "the machine is not on this phone yet"},
		{"a document with no fetch headers", map[string]string{"Accept": "text/html,application/xhtml+xml"},
			nil, true, "המכונה עוד לא נמצאת בטלפון הזה"},
		{"a script's call", map[string]string{"Sec-Fetch-Dest": "empty", "Accept": "application/json"},
			absentMachine{step: "unpacking the machine's disk"}, false, `"error":"machine_absent"`},
	} {
		r := httptest.NewRequest(http.MethodGet, "/a/app-management/api/apps", nil)
		for k, v := range c.header {
			r.Header.Set(k, v)
		}
		w := httptest.NewRecorder()
		Absent(c.m).ServeHTTP(w, r)
		body := w.Body.String()
		if w.Code != http.StatusServiceUnavailable {
			t.Errorf("%s: status %d, want 503", c.name, w.Code)
		}
		ct := w.Header().Get("Content-Type")
		if c.page != strings.HasPrefix(ct, "text/html") {
			t.Errorf("%s: Content-Type %q, a page wanted: %v", c.name, ct, c.page)
		}
		if !strings.Contains(body, c.has) {
			t.Errorf("%s: the answer lacks %q:\n%s", c.name, c.has, body)
		}
		if strings.Contains(body, "did not answer") || strings.Contains(body, "127.0.0.1") {
			t.Errorf("%s: the proxy's error reached the owner:\n%s", c.name, body)
		}
	}
}

// The proxy itself, with nothing listening where the container should be: Absent answers, not the 502.
func TestToContainerHandsAnUnreachableContainerToAbsent(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	ln.Close() // nothing answers there now: a refused connection, as the phone's 127.0.0.1:9 is
	u, _ := url.Parse("http://" + addr)
	h := toContainer(u, log.New(io.Discard, "", 0), Absent(absentMachine{}))
	r := httptest.NewRequest(http.MethodGet, "/api/apps", nil)
	r.Header.Set("Sec-Fetch-Dest", "document")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != http.StatusServiceUnavailable || !strings.Contains(w.Body.String(), "המכונה עוד לא נמצאת") {
		t.Fatalf("an unreachable container: %d\n%s", w.Code, w.Body.String())
	}
	// and with no Absent, the error it always was
	w = httptest.NewRecorder()
	toContainer(u, log.New(io.Discard, "", 0), nil).ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/apps", nil))
	if w.Code != http.StatusBadGateway || !strings.Contains(w.Body.String(), "did not answer") {
		t.Fatalf("no Absent: %d\n%s", w.Code, w.Body.String())
	}
}

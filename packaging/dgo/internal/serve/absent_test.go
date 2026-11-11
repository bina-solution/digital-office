package serve

import (
	"errors"
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

// askingMachine counts the asks: a phone's machine that is not up, as absentMachine.
type askingMachine struct {
	absentMachine
	wants *int
}

func (m askingMachine) Want() error { *m.wants++; return nil }

// The owner's thin APK, 2026-11-03 (DGO-1089): «אפליקציות» said "not on this phone yet" and the machine's
// 648 MB were never fetched — the page asked for nothing and never loaded again. A page asks for the machine
// and reloads itself, showing the app's step as a percent; a refusal is shown and asks nothing; a script's
// call asks nothing.
func TestAbsentAsksForTheMachineAndShowsItsProgress(t *testing.T) {
	page := map[string]string{"Sec-Fetch-Dest": "iframe"}
	script := map[string]string{"Sec-Fetch-Dest": "empty", "Accept": "application/json"}
	for _, c := range []struct {
		name   string
		header map[string]string
		m      absentMachine
		asks   int
		has    []string
		hasNot []string
	}{
		{"nothing said yet", page, absentMachine{}, 1,
			[]string{`http-equiv="refresh" content="5"`, "<h1>מכונת הלשכה עולה</h1>", "המכונה התבקשה"},
			[]string{"<progress", "not on this phone yet", `class="raw"`}},
		{"fetching", page, absentMachine{step: "the office's machine is being fetched: 34%"}, 1,
			[]string{"<h1>מורידים את מכונת הלשכה: 34%</h1>", `<progress max="100" value="34">`,
				`<p class="raw" dir="ltr">the office&#39;s machine is being fetched: 34%</p>`}, nil},
		{"unpacking", page, absentMachine{step: "the office's machine is being unpacked: 7%"}, 1,
			[]string{"<h1>פורסים את מכונת הלשכה: 7%</h1>", `value="7"`}, nil},
		{"refused: metered", page, absentMachine{refused: "the machine is 1 GB to fetch and the phone's network is metered: on Wi-Fi it is fetched — open the app again there"}, 0,
			[]string{"<h1>מכונת הלשכה לא עולה כרגע</h1>", "והמכונה (1 GB) מורדת רק ברשת Wi-Fi", "the phone&#39;s network is metered", `http-equiv="refresh"`},
			[]string{"<progress"}},
		{"refused: no room", page, absentMachine{refused: "the phone has 3 GB free, and the machine needs 11 GB"}, 0,
			[]string{"פנויים 3 GB, והמכונה צריכה 11 GB"}, nil},
		// DGO-1723: «מכולות» is the owner's to install — the page says so in Hebrew and points to the one place that
		// installs them; no raw English, no bar, and it asks nothing (a page that reloads never starts a 2 GB fetch)
		{"refused: «מכולות» not installed", page, absentMachine{refused: "containers are not installed: the owner installs them from the status screen"}, 0,
			[]string{"<h1>האפליקציה הזו רצה על «מכולות»</h1>", "עוד לא מותקנות בטלפון הזה", `<a class="door" href="dgo://status" target="_top">התקנת מכולות</a>`},
			[]string{`class="raw"`, "containers are not installed", "<progress"}},
		{"refused, in words the page does not know", page, absentMachine{refused: "something new <b>"}, 0,
			[]string{"האפליקציה אומרת למה, במילים שלה", `<p class="raw" dir="ltr">something new &lt;b&gt;</p>`}, []string{"<b>"}},
		{"a script's call", script, absentMachine{step: "the office's machine is being fetched: 34%"}, 0,
			[]string{`"detail":"the office's machine is being fetched: 34%"`}, nil},
	} {
		n := 0
		r := httptest.NewRequest(http.MethodGet, "/a/app-management/", nil)
		for k, v := range c.header {
			r.Header.Set(k, v)
		}
		w := httptest.NewRecorder()
		Absent(askingMachine{c.m, &n}).ServeHTTP(w, r)
		body := w.Body.String()
		if w.Code != http.StatusServiceUnavailable {
			t.Errorf("%s: status %d, want 503", c.name, w.Code)
		}
		if n != c.asks {
			t.Errorf("%s: the machine asked for %d times, want %d", c.name, n, c.asks)
		}
		for _, s := range c.has {
			if !strings.Contains(body, s) {
				t.Errorf("%s: the answer lacks %q:\n%s", c.name, s, body)
			}
		}
		for _, s := range c.hasNot {
			if strings.Contains(body, s) {
				t.Errorf("%s: the answer has %q:\n%s", c.name, s, body)
			}
		}
	}
}

// upMachine runs (a port), or fails its ask (err): the two answers that are neither a step nor a refusal.
type upMachine struct {
	absentMachine
	port  int
	err   error
	wants *int
}

func (m upMachine) Up() (int, string) { return m.port, "t" }
func (m upMachine) Want() error       { *m.wants++; return m.err }

// The machine up and the app's container not answering yet is no ask (the second reader of DGO-1089); an
// ask the app cannot be given is said as such, never as "asked".
func TestAbsentSaysAMachineUpOrAnAskThatFailed(t *testing.T) {
	for _, c := range []struct {
		name string
		m    upMachine
		asks int
		has  string
	}{
		{"up", upMachine{port: 40123}, 0, "<h1>מכונת הלשכה פועלת</h1>"},
		{"the ask not written", upMachine{err: errors.New("open run/machine-wanted: no space left on device")}, 1,
			"<h1>מכונת הלשכה לא התבקשה</h1>"},
	} {
		n := 0
		c.m.wants = &n
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		r.Header.Set("Sec-Fetch-Dest", "document")
		w := httptest.NewRecorder()
		Absent(c.m).ServeHTTP(w, r)
		if n != c.asks || !strings.Contains(w.Body.String(), c.has) {
			t.Errorf("%s: asked %d times (want %d), the page lacks %q:\n%s", c.name, n, c.asks, c.has, w.Body.String())
		}
	}
}

// A phone with no machine and a door to the business's offices (DGO-1328): the page says the app runs THERE
// and opens the door at the top of the window — never «install a new version». Without a door, or with one
// that is no https URL, the page is as before; and a refusal of another kind (a metered network) keeps its own.
func TestAbsentOpensTheDoorOnAPhoneWithNoMachine(t *testing.T) {
	const noMachine = "this app carries no machine (DGO-1089): a container app cannot start"
	page := func(door, refused string) string {
		t.Setenv("DGO_PHONE_DOOR", door)
		r := httptest.NewRequest(http.MethodGet, "/a/alerts/", nil)
		r.Header.Set("Sec-Fetch-Dest", "iframe")
		w := httptest.NewRecorder()
		Absent(absentMachine{refused: refused}).ServeHTTP(w, r)
		return w.Body.String()
	}
	link := `<a class="door" href="https://console.staging.digital-office.co.il/" target="_top">`
	if p := page("https://console.staging.digital-office.co.il/", noMachine); !strings.Contains(p, link) ||
		!strings.Contains(p, "<h1>האפליקציה הזו רצה בלשכות של העסק</h1>") || strings.Contains(p, "צריך להתקין גרסה חדשה") ||
		strings.Contains(p, absentReload) || strings.Contains(p, absentAgain) {
		t.Errorf("a door and no machine: the page does not open the door:\n%s", p)
	}
	for _, door := range []string{"", "http://console.staging.digital-office.co.il/", "https://user@door.example/", "door.example"} {
		if p := page(door, noMachine); strings.Contains(p, `class="door"`) || !strings.Contains(p, "צריך להתקין גרסה חדשה") ||
			!strings.Contains(p, absentReload) {
			t.Errorf("door %q is no door: the page changed:\n%s", door, p)
		}
	}
	metered := "the machine is 1 GB to fetch and the phone's network is metered: on Wi-Fi it is fetched — open the app again there"
	if p := page("https://console.staging.digital-office.co.il/", metered); strings.Contains(p, `class="door"`) {
		t.Errorf("a metered network is not «no machine»: the door was offered:\n%s", p)
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
	if w.Code != http.StatusServiceUnavailable || !strings.Contains(w.Body.String(), "מכונת הלשכה") {
		t.Fatalf("an unreachable container: %d\n%s", w.Code, w.Body.String())
	}
	// and with no Absent, the error it always was
	w = httptest.NewRecorder()
	toContainer(u, log.New(io.Discard, "", 0), nil).ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/apps", nil))
	if w.Code != http.StatusBadGateway || !strings.Contains(w.Body.String(), "did not answer") {
		t.Fatalf("no Absent: %d\n%s", w.Code, w.Body.String())
	}
}

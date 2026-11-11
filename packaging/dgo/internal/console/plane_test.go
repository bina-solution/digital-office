package console

import (
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// The phone's core (DGO-1090): the shell's page reaches app-management's API at /a/app-management/ over
// the control plane's own socket — the prefix off, the query verbatim, the body and its type on, as a
// local request (Host localhost, the browser's Origin and Sec-Fetch-* off); a page of another origin, or
// one the browser says is cross-site, never reaches it; a path werkzeug would read its own way is the
// container's; and where the control plane is a URL (an office with its console container) nothing of
// this applies.
func TestTheShellsPageReachesTheControlPlanesSocket(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the control plane's socket is the phone's")
	}
	dir, err := os.MkdirTemp("", "pl")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	sock := filepath.Join(dir, "control.sock")
	ln, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	var got *http.Request
	var body string
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		got, body = r.Clone(r.Context()), string(b)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"apps":[]}`)
	})}
	go srv.Serve(ln)
	t.Cleanup(func() { srv.Close() })

	static, vars := shell(t)
	s, proxied := counted(t, Config{Static: static, Lookup: env(vars, "APP_MANAGEMENT_URL", "unix:"+sock)})
	call := func(method, target, body string, headers ...string) *httptest.ResponseRecorder {
		t.Helper()
		got = nil
		r := httptest.NewRequest(method, target, strings.NewReader(body))
		r.Host = "console.localhost:8080"
		for i := 0; i+1 < len(headers); i += 2 {
			r.Header.Set(headers[i], headers[i+1])
		}
		w := httptest.NewRecorder()
		s.ServeHTTP(w, r)
		return w
	}

	w := call("GET", "/a/app-management/api/apps?x=1&y=%3F", "", "Origin", "http://console.localhost:8080", "Sec-Fetch-Site", "same-origin")
	if w.Code != http.StatusOK || got == nil {
		t.Fatalf("the shell's GET = %d (reached: %v)", w.Code, got != nil)
	}
	if got.URL.Path != "/api/apps" || got.URL.RawQuery != "x=1&y=%3F" || got.Host != "localhost" ||
		got.Header.Get("Origin") != "" || got.Header.Get("Sec-Fetch-Site") != "" || got.Header.Get("X-Forwarded-Prefix") != "/a/app-management" {
		t.Fatalf("handed on as %s %s?%s Host %s, Origin %q, Sec-Fetch-Site %q, prefix %q", got.Method, got.URL.Path, got.URL.RawQuery,
			got.Host, got.Header.Get("Origin"), got.Header.Get("Sec-Fetch-Site"), got.Header.Get("X-Forwarded-Prefix"))
	}
	// the type is what the control plane's guard reads a write by: a client's X-DGO-* never gets this far
	// (the edge removes it, and screen() from a caller it does not trust)
	w = call("PUT", "/a/app-management/api/office", `{"name":"x"}`, "Content-Type", "application/json")
	if w.Code != http.StatusOK || got == nil || got.Method != "PUT" || body != `{"name":"x"}` ||
		got.Header.Get("Content-Type") != "application/json" {
		t.Fatalf("the shell's PUT = %d, handed on: %v, body %q", w.Code, got != nil, body)
	}
	for _, h := range [][]string{
		{"Origin", "http://evil.example"}, {"Origin", "http://console.localhost:9999"}, {"Sec-Fetch-Site", "cross-site"}, {"Sec-Fetch-Site", "same-site"},
	} {
		if w := call("POST", "/a/app-management/api/apps/x/enable", `{}`, "Content-Type", "application/json", h[0], h[1]); w.Code != http.StatusForbidden || got != nil {
			t.Errorf("%s: %s = %d, reached the control plane: %v", h[0], h[1], w.Code, got != nil)
		}
	}
	before := *proxied
	for _, p := range []string{"/a/app-management/%2e%2e/x", "/a/app-management/a%2Fb", "/a/app-management", "/a/drive/x"} {
		if call("GET", p, ""); got != nil {
			t.Errorf("%s reached the control plane", p)
		}
	}
	if *proxied-before != 4 {
		t.Errorf("%d of 4 unproven paths went to the container", *proxied-before)
	}

	// an office with its console container: the URL plane changes nothing
	desk, deskProxied := counted(t, Config{Static: static, Lookup: env(vars, "APP_MANAGEMENT_URL", "http://app-management:8080")})
	r := httptest.NewRequest("GET", "/a/app-management/api/apps", nil)
	desk.ServeHTTP(httptest.NewRecorder(), r)
	if *deskProxied != 1 {
		t.Fatal("with a control plane at a URL, /a/app-management/ is not the container's")
	}
}

// The phone's core apps answered in its own process (DGO-1328): /a/<id>/… reaches the app's handler as
// app_proxy hands an app a request — the prefix off, the query verbatim, X-Forwarded-Prefix /a/<id>, the
// body on — from the shell's page only; a page of another origin never reaches it; a path of another
// spelling, or an app with no door, is the container's; and where the office runs its console container
// (DGO_CONSOLE=container) no door is opened.
func TestTheShellsPageReachesAnAppAnsweredInProcess(t *testing.T) {
	var got *http.Request
	var body string
	app := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		got, body = r.Clone(r.Context()), string(b)
		_, _ = io.WriteString(w, `{"computers":[]}`)
	})
	static, vars := shell(t)
	s, proxied := counted(t, Config{Static: static, Lookup: env(vars), Doors: map[string]http.Handler{"computers": app}})
	call := func(method, target, body string, headers ...string) *httptest.ResponseRecorder {
		t.Helper()
		got = nil
		r := httptest.NewRequest(method, target, strings.NewReader(body))
		r.Host = "console.localhost:8080"
		for i := 0; i+1 < len(headers); i += 2 {
			r.Header.Set(headers[i], headers[i+1])
		}
		w := httptest.NewRecorder()
		s.ServeHTTP(w, r)
		return w
	}

	w := call("GET", "/a/computers/api/computers?probe=0&x=%3F", "", "Origin", "http://console.localhost:8080", "Sec-Fetch-Site", "same-origin")
	if w.Code != http.StatusOK || got == nil || w.Body.String() != `{"computers":[]}` {
		t.Fatalf("the shell's GET = %d %q (reached: %v)", w.Code, w.Body.String(), got != nil)
	}
	if got.URL.Path != "/api/computers" || got.URL.RawQuery != "probe=0&x=%3F" || got.Header.Get("Origin") != "" ||
		got.Header.Get("Sec-Fetch-Site") != "" || got.Header.Get("X-Forwarded-Prefix") != "/a/computers" {
		t.Fatalf("handed on as %s?%s, Origin %q, Sec-Fetch-Site %q, prefix %q", got.URL.Path, got.URL.RawQuery,
			got.Header.Get("Origin"), got.Header.Get("Sec-Fetch-Site"), got.Header.Get("X-Forwarded-Prefix"))
	}
	if call("GET", "/a/computers/", "", "Referer", "http://console.localhost:8080/", "Sec-Fetch-Mode", "navigate",
		"Sec-Fetch-Dest", "iframe", "X-Forwarded-Prefix", "/elsewhere", "X-authentik-username", "intruder"); got == nil || got.URL.Path != "/" ||
		got.Header.Get("Referer") != "" || got.Header.Get("Sec-Fetch-Mode") != "" || got.Header.Get("Sec-Fetch-Dest") != "iframe" ||
		got.Header.Get("X-Forwarded-Prefix") != "/a/computers" || got.Header.Get("X-authentik-username") != "" {
		t.Fatalf("the screen's own page: reached %v (an untrusted caller's identity, the client's prefix and the page's headers must not reach it)", got != nil)
	}
	for _, ct := range []string{"", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "text/plain"} {
		if w := call("POST", "/a/computers/api/computers", "host=x", "Content-Type", ct); w.Code != http.StatusForbidden || got != nil {
			t.Errorf("a POST any page could send (Content-Type %q) = %d, reached the app: %v", ct, w.Code, got != nil)
		}
	}
	if w := call("DELETE", "/a/computers/api/computers/x", ""); w.Code != http.StatusOK || got == nil || got.Method != "DELETE" {
		t.Errorf("the screen's DELETE (no page sends one unasked) = %d", w.Code)
	}
	if w := call("GET", "/a/computers/", "", "Sec-Fetch-Site", "cross-site"); w.Code != http.StatusForbidden || got != nil {
		t.Errorf("another site's frame of the screen = %d", w.Code)
	}
	if w := call("POST", "/a/computers/api/computers", `{"host":"x"}`, "Content-Type", "application/json"); w.Code != http.StatusOK ||
		got == nil || got.Method != "POST" || body != `{"host":"x"}` || got.Header.Get("Content-Type") != "application/json" {
		t.Fatalf("the shell's POST = %d, handed on: %v, body %q", w.Code, got != nil, body)
	}
	for _, h := range [][]string{
		{"Origin", "http://evil.example"}, {"Origin", "http://console.localhost:9999"}, {"Sec-Fetch-Site", "cross-site"}, {"Sec-Fetch-Site", "same-site"},
	} {
		if w := call("POST", "/a/computers/api/computers", `{}`, "Content-Type", "application/json", h[0], h[1]); w.Code != http.StatusForbidden || got != nil {
			t.Errorf("%s: %s = %d, reached the app: %v", h[0], h[1], w.Code, got != nil)
		}
	}
	before := *proxied
	for _, p := range []string{"/a/computers/%2e%2e/x", "/a/computers/a%2Fb", "/a/computers", "/a/computersx/", "/a/drive/x"} {
		if call("GET", p, ""); got != nil {
			t.Errorf("%s reached the app", p)
		}
	}
	if *proxied-before != 5 {
		t.Errorf("%d of 5 paths outside the door went to the container", *proxied-before)
	}

	// an office with its console container: no door at all
	desk, deskProxied := counted(t, Config{Static: static, Lookup: env(vars, "DGO_CONSOLE", "container"), Doors: map[string]http.Handler{"computers": app}})
	got = nil
	desk.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/a/computers/api/computers", nil))
	if *deskProxied != 1 || got != nil {
		t.Fatal("with the console container, /a/computers/ is not the container's")
	}
}

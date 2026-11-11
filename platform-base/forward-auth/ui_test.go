package main

// ui_test.go — the pages a person sees here are THE card on the logo wall, in the office's palette, and
// a failure is said as one (DGO-1501). Until then every page was an unstyled form.

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func uiGet(t *testing.T, s *server, target string) *httptest.ResponseRecorder {
	t.Helper()
	w := httptest.NewRecorder()
	s.routes().ServeHTTP(w, httptest.NewRequest("GET", target, nil))
	return w
}

// Every page is the card, wears the mark, and asks for the stylesheet by an address that changes with it.
func TestEveryPageIsTheCardOnTheWall(t *testing.T) {
	s := testServer(t)
	for _, target := range []string{"/login", "/logout", "/nothing-here"} {
		w := uiGet(t, s, target)
		body := w.Body.String()
		for _, want := range []string{`data-card`, `class="xn"`, `class="xn-card"`, `/ui/page.css?v=` + pageCSSVersion, `<svg`} {
			if !strings.Contains(body, want) {
				t.Errorf("%s: the page has no %q", target, want)
			}
		}
		if strings.Contains(body, "@bina-brand") {
			t.Errorf("%s: the mark's markers reached the page (html/template drops comments)", target)
		}
		// a page with a form is never framed; a card with nothing to press may be (the console frames refusals)
		want := "DENY"
		if target == "/nothing-here" {
			want = ""
		}
		if got := w.Header().Get("X-Frame-Options"); got != want {
			t.Errorf("%s: X-Frame-Options = %q, want %q", target, got, want)
		}
	}
}

// The stylesheet is the office's palette and THE card, and names the wall where every surface serves it.
func TestTheStylesheetCarriesThePaletteAndTheCard(t *testing.T) {
	w := uiGet(t, testServer(t), "/ui/page.css")
	if w.Code != http.StatusOK || !strings.HasPrefix(w.Header().Get("Content-Type"), "text/css") {
		t.Fatalf("/ui/page.css = %d %q, want 200 text/css", w.Code, w.Header().Get("Content-Type"))
	}
	body := w.Body.String()
	for _, want := range []string{"--olive:", "--surface:", ".xn-card{", ".xn::after{", `url("/bina-wall.svg")`} {
		if !strings.Contains(body, want) {
			t.Errorf("the stylesheet has no %q — were its blocks stamped (theme-token-lint.py --fix)?", want)
		}
	}
}

// The wall is an image and only an image: shapes, no colour of its own, nothing it may run.
func TestTheWallIsShapesOnly(t *testing.T) {
	w := uiGet(t, testServer(t), "/bina-wall.svg")
	if w.Code != http.StatusOK || w.Header().Get("Content-Type") != "image/svg+xml" {
		t.Fatalf("/bina-wall.svg = %d %q, want 200 image/svg+xml", w.Code, w.Header().Get("Content-Type"))
	}
	if w.Header().Get("Content-Security-Policy") != "default-src 'none'" {
		t.Errorf("the wall is served without a CSP that lets it run nothing")
	}
	if w.Header().Get("Access-Control-Allow-Origin") != "*" {
		t.Errorf("the wall is a mask image, fetched in CORS mode from an app's host: it needs Access-Control-Allow-Origin")
	}
	body := w.Body.String()
	if !strings.HasPrefix(body, "<svg") || strings.Contains(body, "fill=\"#") || strings.Contains(body, "<script") {
		t.Errorf("the wall is not a bare shape file (a colour or a script in it)")
	}
}

// A return-to outside the office is refused with the card, in Hebrew, without the refused address.
func TestARefusedReturnToIsACardThatDoesNotEchoTheHost(t *testing.T) {
	s := testServer(t)
	w := httptest.NewRecorder()
	s.forwardAuth(w, fwdReq("GET", "evil.example", "/<script>", nil))
	body := w.Body.String()
	if w.Code != http.StatusBadRequest || !strings.Contains(body, `class="xn-card"`) {
		t.Fatalf("status %d, card %v — want 400 and the card", w.Code, strings.Contains(body, "xn-card"))
	}
	if strings.Contains(body, "evil.example") || strings.Contains(body, "<script>") || strings.Contains(body, "forward-auth:") {
		t.Errorf("the refusal writes back what it refused, or speaks the engine's English")
	}
	// it is shown on the APP's host, so its look comes from the sign-in host, and a console may frame it
	if !strings.Contains(body, `href="`+s.external+`/ui/page.css?v=`) {
		t.Errorf("the refusal asks for its stylesheet on the host it is shown on, where /ui/page.css is not ours")
	}
	if w.Header().Get("X-Frame-Options") != "" {
		t.Errorf("the refusal may not be framed, so inside the console's frame it is a blank box")
	}
}

// A page that does not exist is the card with the way to the sign-in page, not "404 page not found".
func TestAnUnknownAddressIsTheCard(t *testing.T) {
	w := uiGet(t, testServer(t), "/nothing-here")
	if w.Code != http.StatusNotFound || !strings.Contains(w.Body.String(), `href="/login"`) {
		t.Fatalf("/nothing-here = %d, want 404 and a way to /login", w.Code)
	}
}

// A deep link's screen (`#/m/<app>/<path>`) survives the sign-in (DGO-569). The fragment never reaches this
// server, so the sign-in form asks for the one script that puts it back on its return-to — after the field it
// fills, by an address that changes with the script — and the script is served as a script, nothing else.
func TestTheSignInFormAsksForTheScriptThatKeepsADeepLinksScreen(t *testing.T) {
	s := testServer(t)
	body := uiGet(t, s, "/login?rd="+url.QueryEscape("http://console.localhost/")).Body.String()
	tag := `<script src="/ui/return.js?v=` + returnJSVersion + `"></script>`
	at, field := strings.Index(body, tag), strings.Index(body, `name="rd"`)
	if at < 0 {
		t.Fatalf("the sign-in page does not ask for %s", tag)
	}
	if field < 0 || at < field {
		t.Errorf("the script stands before the return-to field it fills (script at %d, field at %d)", at, field)
	}
	w := uiGet(t, s, "/ui/return.js")
	if w.Code != http.StatusOK || w.Header().Get("Content-Type") != "text/javascript; charset=utf-8" ||
		w.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatalf("/ui/return.js = %d %q nosniff=%q, want 200 text/javascript and nosniff",
			w.Code, w.Header().Get("Content-Type"), w.Header().Get("X-Content-Type-Options"))
	}
	for _, want := range []string{"location.hash", `input[name="rd"]`, `indexOf("#") < 0`} {
		if !strings.Contains(w.Body.String(), want) {
			t.Errorf("the script has no %q", want)
		}
	}
}

// …and what the form sends back with the fragment is handed back with it: the 303 keeps the screen, a hand-off
// code for the app's host goes into the query BEFORE it, and the host is checked exactly as without one.
func TestASignInHandsBackTheReturnTosFragment(t *testing.T) {
	const rd = "http://console.localhost/#/m/browser42.hp-laptop/view/"
	for _, st := range []string{"", strings.Repeat("a", 64)} {
		s := testServer(t)
		form := url.Values{"user": {"owner"}, "password": {testPassword}, "rd": {rd}, "st": {st}}
		r := httptest.NewRequest("POST", "/login", strings.NewReader(form.Encode()))
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		w := httptest.NewRecorder()
		s.login(w, r)
		loc := w.Header().Get("Location")
		if w.Code != http.StatusSeeOther {
			t.Fatalf("st=%q: status = %d, want 303", st, w.Code)
		}
		u, err := url.Parse(loc)
		if err != nil || u.Host != "console.localhost" || u.Fragment != "/m/browser42.hp-laptop/view/" {
			t.Errorf("st=%q: Location = %q, want console.localhost with the fragment kept", st, loc)
		}
		if hasCode := u != nil && u.Query().Get(codeParam) != ""; hasCode != (st != "") {
			t.Errorf("st=%q: Location = %q — a hand-off code only when the app host sent its state", st, loc)
		}
	}
	// a fragment moves no host: a return-to outside the office is still dropped
	s := testServer(t)
	form := url.Values{"user": {"owner"}, "password": {testPassword}, "rd": {"http://evil.example/#/m/x"}}
	r := httptest.NewRequest("POST", "/login", strings.NewReader(form.Encode()))
	r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	w := httptest.NewRecorder()
	s.login(w, r)
	if strings.Contains(w.Header().Get("Location"), "evil.example") {
		t.Errorf("a return-to outside the office was followed because it carried a fragment: %q", w.Header().Get("Location"))
	}
}

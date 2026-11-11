package main

// ui.go — what the sign-in app shows a person: THE card, on the logo wall, in the office's palette (DGO-1501).
//
// Until 2026-11-09 these pages were the browser's default type on a blank page, on the reasoning that a
// service which cannot read the palette must not invent a second one. It reads the palette now the way
// every other screen of the office does — a kept copy: ui/page.css carries the palette and THE card,
// stamped from platform-base/bina-ui by gate G27; ui/bina-wall.svg is a copy of bina-ui/brand/bina-wall.svg
// the same gate keeps byte-identical; ui/pages.html carries the office's mark the same way. All three are
// embedded, so the image stays one binary and a page never waits on another service. Nothing in ui/ names
// a colour: the wall is shapes, painted through a mask with the palette's tokens.

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"html/template"
	"net/http"
)

//go:embed ui/page.css ui/bina-wall.svg ui/pages.html ui/return.js
var uiFiles embed.FS

var (
	pageCSS = uiFile("ui/page.css")
	wallSVG = uiFile("ui/bina-wall.svg")
	// the sign-in form's one script: a deep link's `#…` put back on the return-to (ui/return.js, DGO-569) — a
	// file of this host's, never inline, so the page can still be held to `script-src 'self'`
	returnJS = uiFile("ui/return.js")
	// The stylesheet's address carries its own hash: it is cached for a day, and a binary with a new
	// sheet asks for a new address instead of being served yesterday's. The script's the same way.
	pageCSSVersion  = version(pageCSS)
	returnJSVersion = version(returnJS)
	pages           = template.Must(template.New("pages").
			Funcs(template.FuncMap{
			"css":  func() string { return pageCSSVersion },
			"js":   func() string { return returnJSVersion },
			"head": func(title, base string) pageHead { return pageHead{Title: title, Base: base} },
		}).
		ParseFS(uiFiles, "ui/pages.html"))
)

// pageHead is what the top of every page needs: its title, and where this app's own files are — nothing
// (this host) on a page answered here, the sign-in host's address on one answered on another host.
type pageHead struct{ Title, Base string }

func version(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:6]) }

func uiFile(name string) []byte {
	b, err := uiFiles.ReadFile(name)
	if err != nil {
		panic("forward-auth: " + name + " is not embedded: " + err.Error())
	}
	return b
}

// renderPage writes one page with the headers every page here carries. This is the one screen an
// anonymous caller reaches: nobody may frame it, and no shared proxy may keep it.
func renderPage(w http.ResponseWriter, status int, name string, data any) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("X-Frame-Options", "DENY")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = pages.ExecuteTemplate(w, name, data)
}

// problem is a failure a person can meet on this app, said as the office says one: what it is (Title),
// which case of it (Sub), what to do (Text), and at most one way on (Action, ActionText). Never the
// engine's sentence, never English, never the address that was refused. Base is where this app's files
// are when the page is answered on another host (see pageHead).
type problem struct {
	Title, Sub, Text   string
	Action, ActionText string
	Base               string
}

// renderProblem is the card with no form on it, so nothing on it can be clicked into by a page that
// frames it — and a refusal traefik hands to an app's host is often shown INSIDE the console's frame,
// where a page that may not be framed is a blank box. Never kept by a shared proxy all the same.
func renderProblem(w http.ResponseWriter, status int, p problem) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = pages.ExecuteTemplate(w, "problem", p)
}

// notFound is an address on this app that is no page: the card, with the way to the sign-in page.
func notFound(w http.ResponseWriter, _ *http.Request) {
	renderProblem(w, http.StatusNotFound, problem{
		Title: "הדף הזה לא קיים", Sub: "כניסה ללשכה",
		Text:   "בכתובת הזאת אין דף של הלשכה. הכניסה נמצאת בדף הכניסה.",
		Action: "/login", ActionText: "לדף הכניסה",
	})
}

// serveUI answers the files the pages ask for. They are public — the sign-in page is shown to
// anybody, and its look is no secret — and an image here is only ever an image: it may run nothing.
func serveUI(w http.ResponseWriter, r *http.Request) {
	var body []byte
	switch r.URL.Path {
	case "/ui/page.css":
		body = pageCSS
		w.Header().Set("Content-Type", "text/css; charset=utf-8")
	case "/ui/return.js":
		body = returnJS
		w.Header().Set("Content-Type", "text/javascript; charset=utf-8")
	case "/bina-wall.svg":
		body = wallSVG
		w.Header().Set("Content-Type", "image/svg+xml")
		w.Header().Set("Content-Security-Policy", "default-src 'none'")
		// A mask image is fetched in CORS mode: the refusal card on an app's host asks for it from here.
		// It is the same public picture for everybody, and no credentials go with it.
		w.Header().Set("Access-Control-Allow-Origin", "*")
	default:
		notFound(w, r)
		return
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Cache-Control", "public, max-age=86400")
	_, _ = w.Write(body)
}

package console

import (
	"context"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
)

// planePrefix is app-management's door in the shell, as app.py's app_proxy serves /a/<name>/.
const planePrefix = "/a/app-management/"

// newPlane is the door to the control plane where it is a socket of this office's own — the phone's
// native core (DGO-1090: APP_MANAGEMENT_URL=unix:<path>), with no console container to proxy through:
// the shell's own page — the install wizard, the apps screen — reaches app-management's API at
// /a/app-management/<sub> as app.py's app_proxy hands it on (the prefix off, the query verbatim,
// X-Forwarded-Prefix). The control plane answers a request addressed to localhost by no page but its
// own (serve.outsider), so this door speaks for the shell's page: it lets through only a request whose
// page is the shell's (Origin this host, or none; Sec-Fetch-Site same-origin, none, or absent) and
// hands it on as the local caller it then is, its Content-Type kept for the control plane's own check of
// writes a page could send without asking (a client's X-DGO-* never reaches here: the edge removes it).
func newPlane(path string, logf func(string, ...any)) http.Handler {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil
	t.DisableCompression = true
	t.DialContext = func(ctx context.Context, _, _ string) (net.Conn, error) {
		var d net.Dialer
		return d.DialContext(ctx, "unix", path)
	}
	to := &url.URL{Scheme: "http", Host: "localhost"}
	proxy := &httputil.ReverseProxy{
		Transport: t,
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(to)
			pr.Out.Host = "localhost"
			pr.Out.URL.Path = "/" + strings.TrimPrefix(pr.In.URL.Path, planePrefix)
			pr.Out.URL.RawPath = ""
			pr.Out.URL.RawQuery = pr.In.URL.RawQuery
			for _, h := range []string{"Origin", "Referer", "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-Dest", "Sec-Fetch-User"} {
				pr.Out.Header.Del(h)
			}
			pr.Out.Header.Set("X-Forwarded-Prefix", strings.TrimSuffix(planePrefix, "/"))
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			logf("dgo console: %s %s: the control plane did not answer: %v", r.Method, r.URL.Path, err)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadGateway)
			_, _ = w.Write([]byte(`{"app":"app-management","error":"app_unreachable"}` + "\n"))
		},
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !shellsPage(r) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"error":"the control plane answers no page but the shell's"}` + "\n"))
			return
		}
		proxy.ServeHTTP(w, r)
	})
}

// planeRequest is a request for that door: under its prefix, by a path that is its own spelling — no
// `.` or `..` segment and no encoded slash, which app.py's werkzeug would read its own way (those stay
// the container's).
func planeRequest(r *http.Request) bool {
	return ownSpelling(r, planePrefix)
}

// ownSpelling is a request under prefix whose path is its own spelling: no `.` or `..` segment and no
// encoded slash, which an app's server would read its own way.
func ownSpelling(r *http.Request, prefix string) bool {
	p := r.URL.Path
	if !strings.HasPrefix(p, prefix) || strings.Contains(strings.ToLower(r.URL.EscapedPath()), "%2f") {
		return false
	}
	for _, seg := range strings.Split(p, "/") {
		if seg == "." || seg == ".." {
			return false
		}
	}
	return true
}

// doorOf is the app a request is for when this office answers that app in its own process — the phone's
// core, whose apps have no container to proxy to (Config.Doors, DGO-1328) — and the handler, or "" and nil.
// The app's handler sees what the console container's app_proxy hands an app: the request at "/" + the
// rest of the path, the query verbatim, X-Forwarded-Prefix /a/<id>; the shell's own page only, as at the
// control plane's door, and a path of its own spelling only (anything else is the container's, which on a
// phone is Absent's page).
func (s *Server) doorOf(r *http.Request) (string, http.Handler) {
	rest, ok := strings.CutPrefix(r.URL.Path, "/a/")
	if !ok {
		return "", nil
	}
	id, _, ok := strings.Cut(rest, "/")
	h := s.doors[id]
	if !ok || h == nil || !ownSpelling(r, "/a/"+id+"/") {
		return "", nil
	}
	return id, h
}

// throughDoor hands r to an app answered in this process (doorOf), as newPlane hands one to the control plane.
func throughDoor(id string, h http.Handler, w http.ResponseWriter, r *http.Request) {
	why := ""
	switch {
	case !shellsPage(r):
		why = "this app answers no page but the shell's"
	case pageCouldSend(r):
		why = "this app takes a change as JSON — any page could send this one"
	}
	if why != "" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"error":"` + why + `"}` + "\n"))
		return
	}
	prefix := "/a/" + id
	out := r.Clone(r.Context())
	out.URL.Path = strings.TrimPrefix(r.URL.Path, prefix)
	out.URL.RawPath = ""
	out.RequestURI = ""
	for _, k := range []string{"Origin", "Referer", "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User"} {
		out.Header.Del(k)
	}
	out.Header.Set("X-Forwarded-Prefix", prefix)
	h.ServeHTTP(w, out)
}

// pageCouldSend is a write any page could send without asking first, for the browser that names neither
// its Origin nor its Sec-Fetch-Site (serve.formable's rule, which the control plane runs behind its door —
// a door's app has no such guard of its own once the door drops those headers): a POST, the one write
// method a form or a no-cors fetch can send, with no Content-Type or a form's own (form-urlencoded,
// multipart, text/plain). The apps' screens send their writes as JSON; serve.formable's X-DGO-Request way
// out is not one here, the console having removed a client's X-DGO-* before any door.
func pageCouldSend(r *http.Request) bool {
	if !strings.EqualFold(r.Method, http.MethodPost) {
		return false
	}
	mt, _, _ := strings.Cut(strings.Join(r.Header.Values("Content-Type"), ","), ";")
	switch strings.ToLower(strings.TrimSpace(mt)) {
	case "", "application/x-www-form-urlencoded", "multipart/form-data", "text/plain":
		return true
	}
	return false
}

// shellsPage is a request the shell's own page sent, as the browser names its page: an Origin of this
// host (http or https) or none, and a Sec-Fetch-Site of same-origin or none, or none at all.
func shellsPage(r *http.Request) bool {
	if o := r.Header.Get("Origin"); o != "" && !strings.EqualFold(o, "http://"+r.Host) && !strings.EqualFold(o, "https://"+r.Host) {
		return false
	}
	switch r.Header.Get("Sec-Fetch-Site") {
	case "", "same-origin", "none":
		return true
	}
	return false
}

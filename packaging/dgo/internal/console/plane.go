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
	p := r.URL.Path
	if !strings.HasPrefix(p, planePrefix) || strings.Contains(strings.ToLower(r.URL.EscapedPath()), "%2f") {
		return false
	}
	for _, seg := range strings.Split(p, "/") {
		if seg == "." || seg == ".." {
			return false
		}
	}
	return true
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

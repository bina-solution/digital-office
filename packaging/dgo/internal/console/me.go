package console

import (
	"net/http"
	"strings"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// officeRoute is app.py's api_office(): the office's record as the control plane holds it — what the
// shell's brand line reads — and, from a plane that cannot be asked, {} and `installed` null (unknown,
// never "fresh"). The phone's shell asks it on its first screen after the wizard (DGO-1090).
func (s *Server) officeRoute(w http.ResponseWriter, r *http.Request) bool {
	rec, unsure := s.office.record(false, s.now())
	if unsure {
		return false
	}
	if rec == nil {
		return writeJSON(w, r, newMap("office", newMap(), "installed", nil))
	}
	m, _ := rec.(*yamlish.Map)
	office := get(m, "office")
	if !compiler.Truthy(office) {
		office = newMap() // `rec.get("office") or {}`
	}
	return writeJSON(w, r, newMap("office", office, "installed", compiler.Truthy(get(m, "installed"))))
}

// guest is app.py's name for nobody: what /api/me answers when the edge named no one.
const guest = "אורח"

// meRoute is app.py's me(): who the edge says is calling — X-authentik-username, -email, -name and
// -groups as the edge wrote them (screen() has removed any a caller wrote) — and «אורח» for nobody.
// The phone's native core needs it on its first screen, where no console container runs (DGO-1090).
//
// One value a header, as the edge writes it: two are the container's. A value is read as the UTF-8
// forward-auth writes, so a display name in Hebrew reads as itself — gunicorn hands app.py the same
// bytes as latin-1, so behind the container such a name is mojibake, the one place this answer is meant
// to differ (TestMeReadsWhatForwardAuthWrites); bytes that are not UTF-8 at all are the container's.
func (s *Server) meRoute(w http.ResponseWriter, r *http.Request) bool {
	vals := map[string]*string{}
	for _, k := range []string{"username", "email", "name", "groups"} {
		vs := r.Header.Values("X-authentik-" + k)
		switch {
		case len(vs) > 1:
			return false
		case len(vs) == 1:
			if !utf8.ValidString(vs[0]) {
				return false
			}
			v := vs[0]
			vals[k] = &v
		}
	}
	str := func(k string) string {
		if p := vals[k]; p != nil {
			return *p
		}
		return ""
	}
	// `u.get(a) or u.get(b) or "אורח"`: an empty value is as good as none
	first := func(ks ...string) string {
		for _, k := range ks {
			if v := str(k); v != "" {
				return v
			}
		}
		return guest
	}
	var email any // None, unless the header is there — "" included
	if p := vals["email"]; p != nil {
		email = *p
	}
	groups := []any{}
	if g := str("groups"); g != "" {
		for _, x := range strings.Split(g, "|") {
			groups = append(groups, x)
		}
	}
	return writeJSON(w, r, newMap("user", first("username"), "email", email, "name", first("name", "username"), "groups", groups))
}

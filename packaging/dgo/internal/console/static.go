package console

import (
	"compress/zlib"
	"fmt"
	"hash/adler32"
	"io"
	"math"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// file answers a path of the shell as app.py's spa() does — `/` (the shell, or the install wizard on
// a fresh office), the file a path names, else index.html (a deep link into the shell) — from the
// tree read at start, with send_file's headers, make_conditional's 304/412 and flask-compress's
// streamed compression. false, with nothing written, outside what is proven.
func (s *Server) file(w http.ResponseWriter, r *http.Request) bool {
	rel := r.URL.Path[1:]
	switch {
	case rel == "":
		first, ok := s.firstRun()
		if !ok {
			return false
		}
		if rel = "index.html"; first {
			rel = "install.html"
		}
	case !plain(rel) || rel == "index.html": // index.html by name is werkzeug's 308 to `/`
		return false
	}
	if _, ranged := r.Header["Range"]; ranged {
		return false
	}
	ae, ok := header(r, "Accept-Encoding")
	if !ok {
		return false
	}
	f, refused := s.tree.find(rel)
	if f == nil && !refused {
		rel = "index.html"
		f, refused = s.tree.find(rel)
	}
	if f == nil { // a link out of --static, or no shell to fall back to: werkzeug's NotFound
		return notFound(w, r)
	}

	name := rel[strings.LastIndexByte(rel, '/')+1:]
	typ, enc := guessType(name)
	if typ == "" {
		typ = "application/octet-stream"
	}
	size := int64(len(f.body))
	mtime := stMtime(f.mod)
	lastMod := pySecond(mtime)
	// safe_join's path — the static directory, a slash, the URL path — is what the ETag hashes
	etag := fmt.Sprintf("%s-%d-%d", yamlish.FloatRepr(mtime), size, adler32.Checksum([]byte(s.static+"/"+rel)))
	status, ok := conditional(r, etag, lastMod)
	if !ok {
		return false
	}
	// flask-compress runs after the conditional answer: a 200 of a compressible type, 500 bytes or
	// more and not already encoded is streamed compressed — and its ETag says by what. The ETag the
	// client gets back is then never the one make_conditional compares with, so a compressed file
	// never revalidates to a 304 in app.py; kept, because this is app.py's answer.
	coding := ""
	if status == http.StatusOK && enc == "" && compressible[typ] && size >= minSize {
		if coding, ok = choose(streamedEncodings, ae); !ok {
			return false
		}
	}

	h := w.Header()
	set := func(k, v string) { h[k] = []string{v} } // werkzeug's spelling: ETag, where Go would write Etag
	set("Content-Disposition", "inline; filename="+quoteHeaderValue(name))
	if status != http.StatusNotModified { // a 304 carries no entity headers (werkzeug's remove_entity_headers)
		set("Content-Type", contentType(typ))
		if enc != "" {
			set("Content-Encoding", enc)
		}
		set("Content-Length", strconv.FormatInt(size, 10))
		set("Last-Modified", time.Unix(lastMod, 0).UTC().Format(http.TimeFormat))
	}
	set("Cache-Control", "no-cache")
	set("Accept-Ranges", "bytes")
	set("Vary", "Accept-Encoding")
	if coding != "" {
		set("Content-Encoding", coding)
		delete(h, "Content-Length")
		etag += ":" + coding
	}
	set("ETag", `"`+etag+`"`)
	w.WriteHeader(status)
	if r.Method == http.MethodHead || status == http.StatusNotModified {
		return true
	}
	if coding == "" {
		w.Write(f.body)
		return true
	}
	zw := zlib.NewWriter(w) // the only streamed coding: deflate, at zlib's default level as flask-compress has it
	zw.Write(f.body)
	zw.Close()
	return true
}

// notFound is werkzeug's NotFound as app.py answers it — its page, and the Vary flask-compress adds.
func notFound(w http.ResponseWriter, r *http.Request) bool {
	h := w.Header()
	h["Content-Type"] = []string{"text/html; charset=utf-8"}
	h["Content-Length"] = []string{strconv.Itoa(len(notFoundPage))}
	h["Vary"] = []string{"Accept-Encoding"}
	w.WriteHeader(http.StatusNotFound)
	if r.Method != http.MethodHead {
		io.WriteString(w, notFoundPage)
	}
	return true
}

const notFoundPage = "<!doctype html>\n<html lang=en>\n<title>404 Not Found</title>\n<h1>Not Found</h1>\n" +
	"<p>The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.</p>\n"

// plain reports whether a URL path (after its slash) is one this port serves exactly as Flask does:
// segments of printable ASCII, none empty — werkzeug redirects a doubled slash — and none `.` or
// `..`, without `\` or `:` (separators and drives to Windows, a scheme to mimetypes). Everything
// else, a non-ASCII name included (send_file would NFKD-normalise it), is the container's.
func plain(rel string) bool {
	if rel == "" {
		return false
	}
	for _, seg := range strings.Split(rel, "/") {
		if seg == "" || seg == "." || seg == ".." {
			return false
		}
	}
	for i := 0; i < len(rel); i++ {
		if c := rel[i]; c < 0x20 || c > 0x7e || c == '\\' || c == ':' {
			return false
		}
	}
	return true
}

// header is a request header as werkzeug reads it, when this port reads it the same way: absent is
// "", a single line of printable ASCII (and tabs) is itself. A repeated header or another byte is
// not ok — WSGI servers join and decode those in ways this port does not repeat.
func header(r *http.Request, name string) (string, bool) {
	vs := r.Header[name]
	if len(vs) == 0 {
		return "", true
	}
	if len(vs) > 1 {
		return "", false
	}
	for i := 0; i < len(vs[0]); i++ {
		if c := vs[0][i]; c != '\t' && (c < 0x20 || c > 0x7e) {
			return "", false
		}
	}
	return vs[0], true
}

// stMtime is os.stat().st_mtime as CPython computes it: seconds + nanoseconds * 1e-9 in doubles.
// The conversion of the product stops the compiler fusing a multiply-add, which CPython does not.
func stMtime(t time.Time) float64 {
	return float64(t.Unix()) + float64(float64(t.Nanosecond())*1e-9)
}

// pySecond is the second of datetime.fromtimestamp(st_mtime), which is what Last-Modified says:
// the float rounded to microseconds half to even, which can carry into the next second.
func pySecond(f float64) int64 {
	sec, frac := math.Modf(f)
	us := math.RoundToEven(frac * 1e6)
	if us >= 1e6 {
		sec++
	} else if us < 0 {
		sec--
	}
	return int64(sec)
}

// conditional is werkzeug's make_conditional for a file without a Range: 304 when the client's
// validators match, 412 when If-Match is given and does not hold — `*` included, which werkzeug
// never counts as a match — else 200. ok is false for a date in any shape but the one HTTP writes
// (Python's email parser reads many more, and reads some zones differently from Go's).
func conditional(r *http.Request, etag string, lastMod int64) (int, bool) {
	inm, ok1 := header(r, "If-None-Match")
	im, ok2 := header(r, "If-Match")
	ims, ok3 := header(r, "If-Modified-Since")
	if !ok1 || !ok2 || !ok3 {
		return 0, false
	}
	unmodified := false
	if ims != "" {
		t, err := time.Parse(http.TimeFormat, ims)
		if err != nil {
			return 0, false
		}
		unmodified = lastMod <= t.Unix()
	}
	if n := parseETags(inm); n.any() {
		unmodified = n.star || n.strong[etag] || n.weak[etag] // weak comparison
	}
	m := parseETags(im)
	if m.any() {
		unmodified = !m.strong[etag] // strong comparison, and a star is not a strong tag
	}
	switch {
	case !unmodified:
		return http.StatusOK, true
	case m.any():
		return http.StatusPreconditionFailed, true
	}
	return http.StatusNotModified, true
}

// etagRe is werkzeug's _etag_re as of 3.1.9, the console image's (pinned in its requirements.txt): one
// tag at the position, then nothing but blanks before a comma or the end. Go's `$` is Python's `\Z`
// here (no multi-line flag), and RE2's leftmost-first submatches are a backtracker's — so `W/` alone
// is an unquoted tag, as werkzeug reads it.
var etagRe = regexp.MustCompile(`^[ \t]*([Ww]/)?(?:"([^"]*)"|([^" \t,]+))[ \t]*(?:,|$)`)

// etags is werkzeug's ETags as parse_etags fills it. A tag werkzeug records as None (an empty
// quoted one) is kept under "\x00" — no ETag of a file can be it, yet it makes the set non-empty.
type etags struct {
	star         bool
	strong, weak map[string]bool
}

func (e etags) any() bool { return e.star || len(e.strong) > 0 || len(e.weak) > 0 }

// parseETags is werkzeug 3.1.9's parse_etags: `*` is the wildcard only as the whole header (in a list
// it is a tag like any other), and what does not read as a tag is skipped, with whatever follows it, to
// the next comma.
func parseETags(v string) etags {
	e := etags{strong: map[string]bool{}, weak: map[string]bool{}}
	if v == "*" {
		return etags{star: true}
	}
	for pos := 0; pos < len(v); {
		m := etagRe.FindStringSubmatchIndex(v[pos:])
		if m == nil {
			next := strings.IndexByte(v[pos:], ',')
			if next < 0 {
				break
			}
			pos += next + 1
			continue
		}
		group := func(i int) (string, bool) {
			if m[2*i] < 0 {
				return "", false
			}
			return v[pos+m[2*i] : pos+m[2*i+1]], true
		}
		quoted, isQuoted := group(2)
		raw, isRaw := group(3)
		switch {
		case isQuoted && quoted != "":
			raw = quoted
		case !isRaw:
			raw = "\x00"
		}
		if _, weak := group(1); weak {
			e.weak[raw] = true
		} else {
			e.strong[raw] = true
		}
		pos += m[1]
	}
	return e
}

// quoteHeaderValue is werkzeug's quote_header_value: a token as it is, anything else quoted.
func quoteHeaderValue(v string) string {
	if v == "" {
		return `""`
	}
	for i := 0; i < len(v); i++ {
		if !strings.ContainsRune(tokenChars, rune(v[i])) {
			return `"` + strings.NewReplacer(`\`, `\\`, `"`, `\"`).Replace(v) + `"`
		}
	}
	return v
}

const tokenChars = "!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

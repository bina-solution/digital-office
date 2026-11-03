package console

import (
	"context"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// officeRecord is app.py's _office_record(): this office's record as app-management keeps it —
// `{office, installed}` from its /api/office — remembered for CONSOLE_OFFICE_TTL_S seconds.
type officeRecord struct {
	url    string
	ttl    time.Duration
	client *http.Client
	mu     sync.Mutex
	at     time.Time
	asked  bool
	rec    any // the record, nil when the plane could not be asked
	unsure bool
}

// newOfficeRecord asks app-management at its URL, or at `unix:<absolute path>`: the control plane on a
// socket of its own, as the phone's native core runs it (DGO-1090) — asked as http://localhost there.
func newOfficeRecord(url string, ttlSeconds float64) *officeRecord {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil // app-management is on the office's own network; no HTTP_PROXY reroutes the question
	if path, ok := strings.CutPrefix(url, "unix:"); ok {
		url = "http://localhost"
		t.DialContext = func(ctx context.Context, _, _ string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "unix", path)
		}
	}
	return &officeRecord{url: strings.TrimRight(url, "/"), ttl: time.Duration(ttlSeconds * float64(time.Second)),
		client: &http.Client{Timeout: 3 * time.Second, Transport: t}}
}

// record is the remembered answer, or a fresh one when it is older than the TTL — or when fresh is
// asked for. unsure is an answer this port would read otherwise than Python's json does.
func (o *officeRecord) record(fresh bool, now time.Time) (rec any, unsure bool) {
	o.mu.Lock()
	if !fresh && o.asked && now.Sub(o.at) < o.ttl {
		defer o.mu.Unlock()
		return o.rec, o.unsure
	}
	o.mu.Unlock()
	rec, unsure = o.ask() // not under the lock: app.py does not serialise the question either
	o.mu.Lock()
	o.at, o.asked, o.rec, o.unsure = now, true, rec, unsure
	o.mu.Unlock()
	return rec, unsure
}

// ask is the request itself: an answer below 400 whose body is a JSON object is the record; a plane
// that does not answer, answers an error, or answers anything else has no record (app.py's None).
func (o *officeRecord) ask() (any, bool) {
	res, err := o.client.Get(o.url + "/api/office")
	if err != nil {
		return nil, false
	}
	defer res.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(res.Body, 1<<20))
	if err != nil || res.StatusCode >= 400 {
		return nil, false
	}
	v, err := loadJSON(raw)
	if err == errUnsure {
		return nil, true
	}
	if m, ok := v.(*yamlish.Map); ok && err == nil {
		return m, false
	}
	return nil, false
}

// firstRun is app.py's _first_run(): true only when the plane SAYS the wizard has not run. A plane
// that cannot be asked is not a fresh office; a fresh answer is asked again rather than remembered,
// so the entry right after the wizard's last step sees the record it just wrote. ok is false when the
// answer is one this port would read otherwise than app.py: the entry is then the container's.
func (s *Server) firstRun() (first, ok bool) {
	installed := func(rec any) bool { m, _ := rec.(*yamlish.Map); return compiler.Truthy(get(m, "installed")) }
	rec, unsure := s.office.record(false, s.now())
	if rec != nil && !unsure && !installed(rec) {
		rec, unsure = s.office.record(true, s.now())
	}
	return rec != nil && !installed(rec), !unsure
}

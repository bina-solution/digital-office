package serve

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/edge"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// Machine is the phone's machine as the native core sees it (native.go, android-path.md "the machine on
// demand"): Up once it has proved its token; Want to ask the app for it; Refused, the app's reason it
// could not start it (not on this phone yet, its own office running, a start Android refused), or "";
// Forget drops that reason, so the next Want is asked anew; Step, what the app is doing toward it now
// (its disk being unpacked), or "".
type Machine interface {
	Up() (port int, token string)
	Want() error
	Refused() string
	Forget()
	Step() string
}

// starting is what a container app's enable and job answer while the machine comes up: install.js
// follows a 202 and shows its step.
const starting = "the office's machine is starting — the first time takes a while"

// appSet is a set of keys — app ids, or "<aid> <state>" for a switch handed on — safe across requests, each
// with the machine's boot ("<port> <token>") it was added for, or "" for none.
type appSet struct {
	mu  sync.Mutex
	set map[string]string
}

func (q *appSet) add(aid string) { q.addFor(aid, "") }

// addFor adds aid for a boot of the machine's.
func (q *appSet) addFor(aid, boot string) {
	q.mu.Lock()
	defer q.mu.Unlock()
	if q.set == nil {
		q.set = map[string]string{}
	}
	q.set[aid] = boot
}

func (q *appSet) has(aid string) bool {
	q.mu.Lock()
	defer q.mu.Unlock()
	_, in := q.set[aid]
	return in
}

// dropOthers removes what was added for another boot than this one (what was added for none stays).
func (q *appSet) dropOthers(boot string) {
	q.mu.Lock()
	defer q.mu.Unlock()
	for k, b := range q.set {
		if b != "" && b != boot {
			delete(q.set, k)
		}
	}
}

// take is true once for an app in the set.
func (q *appSet) take(aid string) bool {
	q.mu.Lock()
	defer q.mu.Unlock()
	_, was := q.set[aid]
	delete(q.set, aid)
	return was
}

// containerApp is aid, when it names an installable app that runs in containers — layer 3, its compose
// declared — on an office whose core has a machine to run it.
func (s *server) containerApp(r *http.Request, verb string) (string, bool) {
	if !s.engineless || s.machine == nil {
		return "", false
	}
	aid, ok := strings.CutPrefix(r.URL.Path, "/api/apps/")
	if !ok {
		return "", false
	}
	if aid, ok = strings.CutSuffix(aid, "/"+verb); !ok || aid == "" || strings.Contains(aid, "/") {
		return "", false
	}
	cat, err := compiler.LoadCatalog(s.repo)
	if err != nil {
		return "", false
	}
	app := cat.Apps[aid]
	if app == nil || app.Root != "apps" {
		return "", false
	}
	c, isText := get(app.Doc(), "compose").(string)
	return aid, isText && c != ""
}

// down answers a container app's enable or job while the machine is not up: asked for (again — a start
// that did not happen is asked for anew), 202 while it starts, or 503 with the app's reason it cannot.
// An enable is the owner asking again: the reason the app last gave is forgotten first, and the app says
// it again only if it still holds (the owner back in the app, room made, its own office stopped: not).
func (s *server) down(w http.ResponseWriter, r *http.Request, again bool) bool {
	if again {
		s.machine.Forget()
	}
	if why := s.machine.Refused(); why != "" {
		reply(w, http.StatusServiceUnavailable, object("ok", false, "error", why))
		return true
	}
	if err := s.machine.Want(); err != nil {
		return s.unvouched(r, err)
	}
	step := s.machine.Step()
	if step == "" {
		step = starting
	}
	reply(w, http.StatusAccepted, object("ok", true, "step", step))
	return true
}

// enableInMachine is a container app's enable on the phone's core: handed to the machine's app-management
// when the machine is up — else the machine asked for, and the enable answered 202 while it starts; its
// job hands the enable on once it is up (jobInMachine).
func (s *server) enableInMachine(w http.ResponseWriter, r *http.Request) bool {
	aid, ok := s.containerApp(r, "enable")
	if !ok {
		return false
	}
	port, token := s.machine.Up()
	if port == 0 {
		s.waiting.add(aid)
		return s.down(w, r, true)
	}
	// handed on now: an enable asked before the machine was up is this one (taken first, so a job poll at the
	// same moment does not hand it on twice; if the machine does not answer, the owner's retry asks again)
	s.waiting.take(aid)
	body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	return s.toMachine(w, r, port, token, "POST", "/api/apps/"+aid+"/enable", body, aid)
}

// disableInMachine is a container app's disable on the phone's core: handed to the machine's
// app-management when the machine is up — the core's mirror set off once it says done, as an enable's sets
// it on. While the machine is down the app runs nowhere, and its switch is the machine's state: the
// machine is asked for, and the disable answered 503 until it is up (app.py's disable is no job to follow).
func (s *server) disableInMachine(w http.ResponseWriter, r *http.Request) bool {
	aid, ok := s.containerApp(r, "disable")
	if !ok {
		return false
	}
	port, token := s.machine.Up()
	if port == 0 {
		s.waiting.take(aid) // the owner wants it off: an enable asked before the machine was up is not handed on
		if why := s.machine.Refused(); why != "" {
			reply(w, http.StatusServiceUnavailable, object("ok", false, "error", why))
			return true
		}
		if err := s.machine.Want(); err != nil {
			return s.unvouched(r, err)
		}
		reply(w, http.StatusServiceUnavailable, object("ok", false, "error",
			"the office's machine is not up — it is starting now; switch the app off once it is"))
		return true
	}
	body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	return s.toMachine(w, r, port, token, "POST", "/api/apps/"+aid+"/disable", body, aid)
}

// jobInMachine is a container app's job on the phone's core: 202 while the machine starts; the enable
// handed on once it is up, if it was asked before; then the machine's own job, as its app-management keeps it.
func (s *server) jobInMachine(w http.ResponseWriter, r *http.Request) bool {
	aid, ok := s.containerApp(r, "job")
	if !ok {
		return false
	}
	port, token := s.machine.Up()
	if port == 0 {
		if !s.waiting.has(aid) {
			return false
		}
		return s.down(w, r, false)
	}
	if s.waiting.take(aid) {
		return s.toMachine(w, r, port, token, "POST", "/api/apps/"+aid+"/enable", []byte("{}"), aid)
	}
	return s.toMachine(w, r, port, token, "GET", "/api/apps/"+aid+"/job", nil, aid)
}

// done is an answer of the machine's app-management that says its work is done and good: 2xx but 202
// (still running), a JSON object whose `ok` is true.
func done(status int, body []byte) bool {
	var said struct {
		OK *bool `json:"ok"`
	}
	return status/100 == 2 && status != http.StatusAccepted && json.Unmarshal(body, &said) == nil && said.OK != nil && *said.OK
}

// signed is one request to the machine's app-management, through the machine's edge as the core's edge
// sends it: the identity in ids (the caller's), signed for that one request (edge.SignForMachine), the core's
// sign-in never.
func (s *server) signed(ctx context.Context, ids http.Header, port int, token, method, path string, body []byte) (*http.Response, error) {
	host := "apps." + s.domain
	req, err := http.NewRequestWithContext(ctx, method, "http://"+net.JoinHostPort("127.0.0.1", strconv.Itoa(port))+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Host = host
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for _, k := range edge.Identity {
		if v := ids.Get(k); v != "" {
			req.Header.Set(k, v)
		}
	}
	edge.SignForMachine(req.Header, token, method, host, path)
	return s.toMachineClient.Do(req)
}

// syncMachine sets the core's mirror to the machine's own state, once each time the machine comes up (a
// new port and token), in the background of the first catalog asked for while it is up — which answers the
// mirror as it is, so no catalog waits on the machine: the machine's state is the app's own and wins where
// the two differ (android-path.md). Nothing else of the core's state is touched; a machine that does not
// answer in 10 s, or a switch of the owner's made meanwhile, is asked again at the next catalog.
func (s *server) syncMachine(in *http.Request) {
	if !s.engineless || s.machine == nil {
		return
	}
	port, token := s.machine.Up()
	if port == 0 {
		return
	}
	key := strconv.Itoa(port) + " " + token
	s.syncMu.Lock()
	if s.synced == key {
		s.syncMu.Unlock()
		return
	}
	s.synced = key // one sync a boot, however many catalogs are asked for at once
	s.syncMu.Unlock()
	// a switch handed to an earlier boot ended with it: never this boot's to wait for
	s.handed.dropOthers(key)
	ids := http.Header{} // the caller's identity, copied: the request is answered before the sync ends
	for _, k := range edge.Identity {
		if v := in.Header.Get(k); v != "" {
			ids.Set(k, v)
		}
	}
	s.syncing.Add(1)
	go func() {
		defer s.syncing.Done()
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := s.mirror(ctx, ids, port, token); err != nil {
			s.log.Printf("the core's mirror of the machine's apps is not set, asked again at the next catalog: %v", err)
			s.syncMu.Lock()
			if s.synced == key {
				s.synced = ""
			}
			s.syncMu.Unlock()
		}
	}()
}

// mirror is syncMachine's work: the machine's app list (its GET /api/apps, as app.py answers it), and the
// core's state set to it, container app by container app — one the machine has on is on here (by:
// machine), one the core has on by: machine that the machine has off or archived is so here. An app with a
// switch of the owner's under way is left to it; a switch that ends while the list is read voids the list.
func (s *server) mirror(ctx context.Context, ids http.Header, port int, token string) error {
	before := s.switched.Load()
	res, err := s.signed(ctx, ids, port, token, "GET", "/api/apps", nil)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("its app list answered %d", res.StatusCode)
	}
	var said struct {
		Apps []struct {
			ID      string `json:"id"`
			Enabled bool   `json:"enabled"`
			Desired string `json:"state_desired"`
		} `json:"apps"`
	}
	if err := json.NewDecoder(io.LimitReader(res.Body, 8<<20)).Decode(&said); err != nil {
		return fmt.Errorf("its app list does not read: %v", err)
	}
	cat, err := compiler.LoadCatalog(s.repo)
	if err != nil {
		return err
	}
	entries, err := stateApps(s.repo)
	if err != nil {
		return err
	}
	// from the check through the writes, no switch's own write: one that ends meanwhile writes after these
	s.mirrorMu.Lock()
	defer s.mirrorMu.Unlock()
	if s.switched.Load() != before {
		return errors.New("a switch ended while the machine's list was read: it is read again")
	}
	var failed []error
	for _, a := range said.Apps {
		app := cat.Apps[a.ID]
		if app == nil || app.Root != "apps" {
			continue
		}
		if c, isText := get(app.Doc(), "compose").(string); !isText || c == "" {
			continue // not a container app: never the machine's to say
		}
		if s.waiting.has(a.ID) || s.handed.has(a.ID+" enabled") || s.handed.has(a.ID+" disabled") {
			continue // the owner's switch under way: its end is the one mirrored
		}
		raw, _ := entries.Get(a.ID)
		dispo, err := compiler.Disposition(raw)
		if err != nil {
			continue
		}
		var by any
		if e, isMap := raw.(*yamlish.Map); isMap {
			by, _ = e.Get("by")
		}
		there := a.Desired
		if there != "enabled" && there != "disabled" && there != "archived" {
			there = map[bool]string{true: "enabled", false: "disabled"}[a.Enabled]
		}
		to := ""
		switch {
		case there == "enabled" && dispo != "enabled":
			to = "enabled"
		case there != "enabled" && dispo == "enabled" && by == "machine":
			to = there
		}
		if to == "" {
			continue
		}
		var out, errs bytes.Buffer
		if compiler.SetStateCmd(s.repo, []string{"--app", a.ID, "--state", to, "--by", "machine", "--create"}, &out, &errs) != 0 {
			failed = append(failed, fmt.Errorf("%s %s: %s", a.ID, to, strings.TrimSpace(errs.String())))
			continue
		}
		s.log.Printf("the machine has %s %s: the core's mirror follows", a.ID, to)
	}
	return errors.Join(failed...)
}

// toMachine asks the machine's app-management, through the machine's edge as the core's edge would —
// the caller's identity, the request signed (edge.SignForMachine), the core's own sign-in never — and
// answers with what it said. A switch the core handed on — an enable, once the machine says it is done (its
// own answer, or its job's), or a disable, done at once — mirrors the app on or off in the core's state
// (`by: machine`), which the core's screens read; the machine's state is the app's own, and nothing else the
// machine says writes the core's.
func (s *server) toMachine(w http.ResponseWriter, in *http.Request, port int, token, method, path string, body []byte, aid string) bool {
	ctx := in.Context()
	if method == "POST" {
		// a switch is carried to its end whoever stops listening: app.py finishes it, and the core's mirror
		// must hear how it ended (a browser that drops the request cancels nothing here)
		ctx = context.WithoutCancel(ctx)
	}
	res, err := s.signed(ctx, in.Header, port, token, method, path, body)
	if err != nil {
		reply(w, http.StatusBadGateway, object("ok", false, "error", "the office's machine did not answer: "+err.Error()))
		return true
	}
	defer res.Body.Close()
	said, _ := io.ReadAll(io.LimitReader(res.Body, 1<<20))
	to := "enabled" // an enable, or its job; a disable is answered at once
	if strings.HasSuffix(path, "/disable") {
		to = "disabled"
	}
	if method == "POST" {
		// a switch this core handed on, to this boot: its end is the one the core mirrors
		s.handed.addFor(aid+" "+to, strconv.Itoa(port)+" "+token)
		s.switched.Add(1)
	}
	if done(res.StatusCode, said) && s.handed.take(aid+" "+to) {
		// a mirror read before this is of a state that is no longer so
		s.switched.Add(1)
		if to == "disabled" { // a done disable ends what was pending to switch it on: its job's old "done" is not this
			s.handed.take(aid + " enabled")
			s.waiting.take(aid)
		}
		s.mirrorMu.Lock() // never between a mirror's check and its writes
		var out, errs bytes.Buffer
		if compiler.SetStateCmd(s.repo, []string{"--app", aid, "--state", to, "--by", "machine", "--create"}, &out, &errs) != 0 {
			s.log.Printf("the machine switched %s %s, and the core's state did not take it: %s", aid, to, strings.TrimSpace(errs.String()))
		}
		s.mirrorMu.Unlock()
	} else if res.StatusCode != http.StatusAccepted && !done(res.StatusCode, said) &&
		strings.HasPrefix(res.Header.Get("Content-Type"), "application/json") {
		// refused, or failed, by app.py itself (its 409s, its own 500s, ok: false — answers it makes are JSON;
		// the machine edge's own 502 is not, and says nothing of the switch, nor is an exception app.py does
		// not catch, whose mark stays until the next boot): no switch is under way — the mark goes, or the
		// mirror would leave this app alone for as long as this boot runs
		s.handed.take(aid + " " + to)
	}
	if ct := res.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
	}
	w.WriteHeader(res.StatusCode)
	_, _ = w.Write(said)
	return true
}

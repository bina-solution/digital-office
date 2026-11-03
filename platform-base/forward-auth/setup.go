package main

import (
	"bufio"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"html/template"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode"
)

// First-run setup (DGO-1090): how a FRESH office gets its owner.
//
// WHY IT EXISTS: a fresh office has no users, and the old answer — a random password written into the
// office's .env — is a password nobody is ever shown. On the phone it lives inside the VM's disk, and
// the person holding the phone could not sign in at all.
//
// THE SHAPE: before the office starts, the app's prepare hook mints a one-time setup code and writes
// ONLY ITS SHA-256 next to the users file (`setup`). The code itself goes to one place: the office's
// own console output — on Android the VM's serial console, which lives in the app's private storage,
// so no other app on the phone can read it; on a server, the terminal of whoever ran `bbox run`.
// `/setup?code=<code>` then asks for a name and a password, writes the users file, deletes the code,
// and signs the browser in. Without the code there is no form. Once a user exists there is no setup
// at all — the endpoint answers 404 — so this is a door that exists exactly once, for exactly the
// person who started the office.
//
// One writer: from here on this service owns its users file. The file is the vault of exactly one
// fact (who may sign in), and the service that reads it is the only one that has to understand it.

const (
	minPassword = 12
	setupGroups = "admins"
)

var userNameRE = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{0,31}$`)

// setup holds the pending code's hash while the office has no users. Its zero value — no hash — is the
// steady state: every office after its first minute.
type setup struct {
	mu        sync.Mutex
	usersFile string
	codeFile  string
	hash      []byte // sha256 of the code; nil when there is no setup pending
}

// loadSetup reads the pending code's hash, if the office has none of its users yet. A users file that
// exists means setup is over, whatever else is lying around: the code file is then ignored.
func loadSetup(usersFile, codeFile string) (*setup, error) {
	st := &setup{usersFile: usersFile, codeFile: codeFile}
	if _, err := os.Stat(usersFile); err == nil {
		return st, nil
	}
	raw, err := os.ReadFile(codeFile)
	if err != nil {
		return nil, fmt.Errorf("no users file (%s) and no first-run code (%s): nobody could ever sign in", usersFile, codeFile)
	}
	h, err := hex.DecodeString(strings.TrimSpace(string(raw)))
	if err != nil || len(h) != sha256.Size {
		return nil, fmt.Errorf("%s: want the hex sha256 of the first-run code", codeFile)
	}
	st.hash = h
	return st, nil
}

func (st *setup) pending() bool {
	st.mu.Lock()
	defer st.mu.Unlock()
	return st.hash != nil
}

// check is the code test: constant-time, and against a hash, so the file on disk is useless to anyone
// who reads it.
func (st *setup) check(code string) bool {
	st.mu.Lock()
	defer st.mu.Unlock()
	if st.hash == nil || code == "" {
		return false
	}
	got := sha256.Sum256([]byte(code))
	return subtle.ConstantTimeCompare(got[:], st.hash) == 1
}

// finish writes the owner's line and spends the code — the file first, through a temporary file and a
// rename, so a crash leaves either no users file (setup still pending) or a whole one.
func (st *setup) finish(line string) error {
	st.mu.Lock()
	defer st.mu.Unlock()
	if st.hash == nil {
		return errors.New("setup is over")
	}
	tmp, err := os.CreateTemp(filepath.Dir(st.usersFile), ".users-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.WriteString("# written by forward-auth's first-run setup\n" + line + "\n"); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	// The file must LOAD before it is put in place: a line the reader would refuse spends the code,
	// leaves nobody able to sign in, and makes the next start fatal (the third reader: an email with
	// a no-break space split into seven fields).
	if _, err := loadUsers(tmp.Name()); err != nil {
		return err
	}
	// Placed only where there is no users file yet (placeNew): one that appeared since boot (another
	// writer, a restore) is never overwritten.
	if err := placeNew(tmp.Name(), st.usersFile); err != nil {
		return err
	}
	st.hash = nil
	if err := os.Remove(st.codeFile); err != nil && !errors.Is(err, os.ErrNotExist) {
		log.Printf("forward-auth: setup done, but the spent code file stays (%v); it is ignored now that users exist", err)
	}
	return nil
}

// writeFirstRun is `forward-auth -first-run`: the prepare hook's way into this service's own volume
// (a scratch image has no shell to write with). It reads a first-run code on stdin and, while the
// office has no users file, keeps the code's SHA-256 as the setup file, mode 0600 — never the code.
// It prints one word for the hook: "owner-exists" (nothing written; the hook forgets its code) or
// "pending" (the link the hook prints will work). 2 on a code too short to be one, or a failed write.
func writeFirstRun(usersFile, codeFile string, in io.Reader, out io.Writer) int {
	if _, err := os.Stat(usersFile); err == nil {
		fmt.Fprintln(out, "owner-exists")
		return 0
	}
	line, _ := bufio.NewReader(in).ReadString('\n')
	code := strings.TrimSpace(line)
	if len(code) < 32 {
		fmt.Fprintln(os.Stderr, "forward-auth: -first-run: want a first-run code of 32 characters or more on stdin")
		return 2
	}
	sum := sha256.Sum256([]byte(code))
	want := hex.EncodeToString(sum[:]) + "\n"
	if have, err := os.ReadFile(codeFile); err == nil && string(have) == want {
		fmt.Fprintln(out, "pending")
		return 0
	}
	tmp, err := os.CreateTemp(filepath.Dir(codeFile), ".setup-*")
	if err != nil {
		fmt.Fprintln(os.Stderr, "forward-auth: -first-run:", err)
		return 2
	}
	defer os.Remove(tmp.Name())
	_, werr := tmp.WriteString(want)
	if werr == nil {
		werr = tmp.Sync()
	}
	if cerr := tmp.Close(); werr == nil {
		werr = cerr
	}
	if werr == nil {
		werr = os.Chmod(tmp.Name(), 0o600)
	}
	if werr == nil {
		werr = os.Rename(tmp.Name(), codeFile)
	}
	if werr != nil {
		fmt.Fprintln(os.Stderr, "forward-auth: -first-run:", werr)
		return 2
	}
	fmt.Fprintln(out, "pending")
	return 0
}

// link is os.Link, a test's to replace.
var link = os.Link

// placeNew puts the finished, synced file tmp at dst only while there is no dst. A hard link does that
// atomically and is what this uses — but an app on Android may not make one (SELinux: no untrusted app
// links a file; the phone's native core, DGO-1090), and there a rename takes its place, after dst is
// seen not to be there: atomic for the file, with a moment between the look and the rename that the
// phone's one writer never shares.
func placeNew(tmp, dst string) error {
	err := link(tmp, dst)
	if err == nil || !errors.Is(err, os.ErrPermission) {
		return err
	}
	if _, serr := os.Lstat(dst); serr == nil {
		return fmt.Errorf("%s is there already", dst)
	} else if !errors.Is(serr, os.ErrNotExist) {
		return serr
	}
	return os.Rename(tmp, dst)
}

// importUsers is `forward-auth -import-users`: a users file that lived on the host before the service
// kept its state in a volume (/var/lib/forward-auth, the migration's prep) comes in once, on stdin. It
// must load as the service would load it; it is written 0600 only where there is no users file yet. One
// word for the hook: "imported", or "owner-exists" (nothing written). 2 on a file that does not load.
func importUsers(usersFile string, in io.Reader, out io.Writer) int {
	if _, err := os.Stat(usersFile); err == nil {
		fmt.Fprintln(out, "owner-exists")
		return 0
	}
	const limit = 1 << 20
	raw, err := io.ReadAll(io.LimitReader(in, limit+1))
	if err != nil {
		fmt.Fprintln(os.Stderr, "forward-auth: -import-users:", err)
		return 2
	}
	if len(raw) > limit {
		fmt.Fprintln(os.Stderr, "forward-auth: -import-users: the file is over 1 MiB, which no users file is")
		return 2
	}
	tmp, err := os.CreateTemp(filepath.Dir(usersFile), ".users-*")
	if err != nil {
		fmt.Fprintln(os.Stderr, "forward-auth: -import-users:", err)
		return 2
	}
	defer os.Remove(tmp.Name())
	_, werr := tmp.Write(raw)
	if werr == nil {
		werr = tmp.Sync() // on disk before it is put in place: a VM killed mid-way leaves no torn file
	}
	if cerr := tmp.Close(); werr == nil {
		werr = cerr
	}
	if werr == nil {
		werr = os.Chmod(tmp.Name(), 0o600)
	}
	if werr == nil {
		if _, err := loadUsers(tmp.Name()); err != nil {
			// not the reader's own message: it can quote a stored hash, and this goes to a console
			werr = errors.New("the file does not load as the service loads it (one line per user: name email display uid groups hash)")
		}
	}
	if werr == nil {
		werr = placeNew(tmp.Name(), usersFile)
	}
	if werr != nil {
		fmt.Fprintln(os.Stderr, "forward-auth: -import-users:", werr)
		return 2
	}
	fmt.Fprintln(out, "imported")
	return 0
}

var setupPage = template.Must(template.New("setup").Parse(`<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>הלשכה החדשה</title></head><body>
<main>
<h1>ברוכים הבאים ללשכה</h1>
{{if .Code}}
<p>בחרו שם משתמש וסיסמה לבעלים של הלשכה.</p>
{{if .Error}}<p role="alert">{{.Error}}</p>{{end}}
<form method="post" action="/setup">
<input type="hidden" name="code" value="{{.Code}}">
<input type="hidden" name="rd" value="{{.ReturnTo}}">
<p><label>שם משתמש <input name="user" autocomplete="username" pattern="[a-z0-9][a-z0-9._\-]{0,31}" value="{{.User}}" required autofocus></label></p>
<p><label>אימייל (לא חובה) <input type="email" name="email" autocomplete="email" value="{{.Email}}"></label></p>
<p><label>סיסמה <input type="password" name="password" autocomplete="new-password" minlength="12" required></label></p>
<p><label>שוב הסיסמה <input type="password" name="again" autocomplete="new-password" minlength="12" required></label></p>
<p><button type="submit">יצירת הבעלים</button></p>
</form>
{{else}}
<p>ללשכה הזאת עוד אין בעלים. פתחו את הקישור שהמכשיר שהפעיל אותה הציג.</p>
{{end}}
</main></body></html>
`))

type setupForm struct {
	Code, ReturnTo, User, Email, Error string
}

func (s *server) renderSetup(w http.ResponseWriter, status int, f setupForm) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("X-Frame-Options", "DENY")
	w.Header().Set("Cache-Control", "no-store")
	// the code is in this page's URL: it must not leave in a Referer to anywhere
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.WriteHeader(status)
	_ = setupPage.Execute(w, f)
}

func (s *server) setupHandler(w http.ResponseWriter, r *http.Request) {
	if s.firstRun == nil || !s.firstRun.pending() {
		// Setup is over. A link to it that is opened again — the app keeps the console line it came
		// from — leads on to where it was going, or to the sign-in page; it never shows a form again.
		if r.Method == http.MethodGet || r.Method == http.MethodHead {
			rd := r.URL.Query().Get("rd")
			if !s.okReturnTo(rd) {
				rd = s.external + "/login"
			}
			http.Redirect(w, r, rd, http.StatusFound)
			return
		}
		http.NotFound(w, r)
		return
	}
	switch r.Method {
	case http.MethodGet, http.MethodHead:
		q := r.URL.Query()
		rd := q.Get("rd")
		if !s.okReturnTo(rd) {
			rd = ""
		}
		code := q.Get("code")
		if !s.firstRun.check(code) {
			code = "" // the page without a form: the code is the only way in
		}
		s.renderSetup(w, http.StatusOK, setupForm{Code: code, ReturnTo: rd})
	case http.MethodPost:
		s.doSetup(w, r)
	default:
		w.Header().Set("Allow", "GET, HEAD, POST")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *server) doSetup(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		s.renderSetup(w, http.StatusBadRequest, setupForm{Error: "הבקשה לא נקראה."})
		return
	}
	// The code is checked FIRST — a constant-time SHA-256, cheap — and a right one always goes through:
	// a limit that a right code had to pass would let a stranger who sends a few wrong codes keep the
	// owner out of his own setup for good (the third reader). Wrong codes are what is limited, per
	// address; at 192 bits a code is not something a limit has to protect.
	code := r.PostFormValue("code")
	if !s.firstRun.check(code) {
		keys := []string{"setup-ip:" + clientKey(clientIP(r))}
		if left := s.limit.begin(time.Now(), keys...); left > 0 {
			w.Header().Set("Retry-After", fmt.Sprint(int(left/time.Second)+1))
			s.renderSetup(w, http.StatusTooManyRequests, setupForm{})
			return
		}
		s.limit.end(time.Now(), false, keys...)
		log.Printf("forward-auth: first-run setup refused, wrong code: ip=%q", clientIP(r))
		s.renderSetup(w, http.StatusForbidden, setupForm{})
		return
	}
	rd := r.PostFormValue("rd")
	if !s.okReturnTo(rd) {
		rd = ""
	}
	f := setupForm{Code: code, ReturnTo: rd, User: strings.ToLower(strings.TrimSpace(r.PostFormValue("user"))),
		Email: strings.TrimSpace(r.PostFormValue("email"))}
	password := r.PostFormValue("password")
	switch {
	case !userNameRE.MatchString(f.User):
		f.Error = "שם המשתמש: אותיות לטיניות קטנות, ספרות, נקודה, מקף או קו תחתון — עד 32 תווים."
	case f.Email != "" && (strings.IndexFunc(f.Email, unicode.IsSpace) >= 0 || !strings.Contains(f.Email, "@")):
		f.Error = "האימייל לא נראה תקין."
	case len([]rune(password)) < minPassword:
		f.Error = fmt.Sprintf("הסיסמה צריכה להיות לפחות %d תווים.", minPassword)
	case password != r.PostFormValue("again"):
		f.Error = "שתי הסיסמאות שונות."
	}
	if f.Error != "" {
		s.renderSetup(w, http.StatusBadRequest, f)
		return
	}
	email := f.Email
	if email == "" {
		email = f.User + "@localhost"
	}
	hash, err := hashPassword(password)
	if err != nil {
		http.Error(w, "forward-auth: could not hash the password", http.StatusInternalServerError)
		return
	}
	// name email display uid groups hash — the display is the name (the file is whitespace-separated)
	line := strings.Join([]string{f.User, email, f.User, randomToken(16), setupGroups, hash}, " ")
	if err := s.firstRun.finish(line); err != nil {
		log.Printf("forward-auth: first-run setup could not write the users file: %v", err)
		http.Error(w, "forward-auth: could not write the users file", http.StatusInternalServerError)
		return
	}
	log.Printf("forward-auth: first-run setup done: owner=%q ip=%q", f.User, clientIP(r))
	// The new file is read now, not at the next once-a-second check, so the cookie below names a
	// user the store already knows.
	if s.live != nil {
		s.live.reload()
	}
	s.sign.set(w, f.User, s.secureCookie, s.cookieDomain)
	if rd == "" {
		rd = s.external + "/"
	}
	// No code: the app host the owner goes on to challenges with its own state, comes back to the
	// sign-in page — where this browser is now signed in — and gets its code then (handoff.go).
	w.Header().Set("Cache-Control", "no-store")
	http.Redirect(w, r, rd, http.StatusSeeOther)
}

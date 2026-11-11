package main

import (
	"bufio"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unicode"
)

// Invitations (DGO-1751): how the owner brings a person into his office.
//
// WHY: a client's office had exactly one sign-in — the owner's, made by first-run setup — and nothing in
// the product could add a second (Exampleu, 2026-11-10: three of its people could not enter their own
// office). Writing a password for someone else is the wrong shape: it passes through the owner, a terminal,
// a chat. So the person chooses their own.
//
// THE SHAPE mirrors first-run (setup.go). `forward-auth -invite` reads «user email [display]» on stdin,
// mints a one-time code, and keeps ONLY its SHA-256 — with the person's name, email, display and an expiry
// (7 days) — as one JSON line of the invites file beside the users file (0600). It prints the code once;
// the hook (`bbox forward-auth invite`) prints the link `<external>/invite?code=<code>` to whoever ran it,
// and the owner sends it to the person. `/invite?code=` shows THE card with the person's name and two
// password fields; the POST checks the code (constant time, against hashes; wrong codes limited per
// address like setup's), adds the person's line to the users file, spends the invitation, and signs the
// browser in. The person's group is `people`: never an admin by this door (users.go: effective), so the
// apps that declare `people: admins` — the office's root apps (computers, app-management, connections, n8n,
// security, dgo-extend, the agents …) and those that act as the owner's own accounts (telegram, the social
// networks, domains …) — answer them 403, at their own host (/auth/traefik/admins) and at the console's doors,
// and so does every app of a linked office (DGO-1755). The office's work apps open for them as for the owner.
//
// TWO WRITERS, ONE LOCK: the -invite process (a `dc run` of this image on the same volume) and this
// service when a person accepts. Both hold an exclusive flock on `<invites>.lock` for the whole
// read-modify-write of the invites file AND (for an acceptance) the users file, and every file is written
// through a temporary file and a rename, so a reader — the live users reload — never sees half a file.

const (
	inviteTTL          = 7 * 24 * time.Hour
	inviteGroups       = peopleGroup
	defaultInvitesFile = "/etc/forward-auth/invites"
	inviteDisplayMax   = 64
)

type invite struct {
	Hash    string `json:"hash"` // hex sha256 of the code; the code itself is never kept
	User    string `json:"user"`
	Email   string `json:"email"`
	Display string `json:"display"`
	Expires int64  `json:"expires"` // unix seconds
}

// invites is the pending invitations of one office, and the users file they turn into lines of.
type invites struct {
	path      string
	usersFile string
}

// locked runs fn holding the exclusive lock both writers share.
func (iv *invites) locked(fn func() error) error {
	f, err := os.OpenFile(iv.path+".lock", os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return err
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN) //nolint:errcheck
	return fn()
}

// read is the file's invitations; a missing file is none. A line that does not parse is an error: a file
// this service cannot read is not one it may rewrite.
func (iv *invites) read() ([]invite, error) {
	raw, err := os.ReadFile(iv.path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []invite
	for i, line := range strings.Split(string(raw), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var v invite
		if err := json.Unmarshal([]byte(line), &v); err != nil || v.Hash == "" || v.User == "" {
			return nil, fmt.Errorf("%s:%d: not an invitation line", iv.path, i+1)
		}
		out = append(out, v)
	}
	return out, nil
}

// write replaces the file with list (the expired ones already left out by the caller).
func (iv *invites) write(list []invite) error {
	var b strings.Builder
	for _, v := range list {
		j, err := json.Marshal(v)
		if err != nil {
			return err
		}
		b.Write(j)
		b.WriteByte('\n')
	}
	return replaceFile(iv.path, []byte(b.String()))
}

// replaceFile writes data to path through a synced 0600 temporary file and a rename.
func replaceFile(path string, data []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+"-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	_, werr := tmp.Write(data)
	if werr == nil {
		werr = tmp.Chmod(0o600)
	}
	if werr == nil {
		werr = tmp.Sync()
	}
	if cerr := tmp.Close(); werr == nil {
		werr = cerr
	}
	if werr != nil {
		return werr
	}
	return os.Rename(tmp.Name(), path)
}

func codeHash(code string) string {
	h := sha256.Sum256([]byte(code))
	return hex.EncodeToString(h[:])
}

// live is list without the invitations that expired by now.
func liveInvites(list []invite, now time.Time) []invite {
	out := list[:0:0]
	for _, v := range list {
		if v.Expires > now.Unix() {
			out = append(out, v)
		}
	}
	return out
}

// find is the live invitation this code opens, compared in constant time against every stored hash.
func (iv *invites) find(code string, now time.Time) (invite, bool) {
	if code == "" {
		return invite{}, false
	}
	list, err := iv.read()
	if err != nil {
		log.Printf("forward-auth: invitations: %v", err)
		return invite{}, false
	}
	want := []byte(codeHash(code))
	var got invite
	found := false
	for _, v := range liveInvites(list, now) {
		if subtle.ConstantTimeCompare([]byte(v.Hash), want) == 1 {
			got, found = v, true
		}
	}
	return got, found
}

var errInviteGone = errors.New("the invitation is not there any more")

// accept turns the invitation this code opens into the person's line of the users file, and spends it.
// The users file is rewritten whole — what it holds, byte for byte, and the new line — and the new file
// must LOAD, with the person in it, before it is put in place (setup.go's rule: a line the reader would
// refuse leaves nobody able to sign in).
func (iv *invites) accept(code, line string, now time.Time) (invite, error) {
	var got invite
	err := iv.locked(func() error {
		list, err := iv.read()
		if err != nil {
			return err
		}
		list = liveInvites(list, now)
		want := []byte(codeHash(code))
		idx := -1
		for i, v := range list {
			if subtle.ConstantTimeCompare([]byte(v.Hash), want) == 1 {
				idx = i
			}
		}
		if idx < 0 {
			return errInviteGone
		}
		got = list[idx]
		raw, err := os.ReadFile(iv.usersFile)
		if err != nil {
			return err
		}
		// Already a user (an acceptance whose spend was cut after the users file was in place): the
		// invitation has done its work — it is spent now, and the link answers «not valid» from here on.
		if cur, err := loadUsers(iv.usersFile); err == nil {
			if _, ok := cur.byName[got.User]; ok {
				if err := iv.write(append(list[:idx:idx], list[idx+1:]...)); err != nil {
					return err
				}
				return errInviteGone
			}
		}
		text := string(raw)
		if text != "" && !strings.HasSuffix(text, "\n") {
			text += "\n"
		}
		text += line + "\n"
		tmp, err := os.CreateTemp(filepath.Dir(iv.usersFile), ".users-*")
		if err != nil {
			return err
		}
		tmpName := tmp.Name()
		defer os.Remove(tmpName)
		_, werr := tmp.WriteString(text)
		if werr == nil {
			werr = tmp.Chmod(0o600)
		}
		if werr == nil {
			werr = tmp.Sync()
		}
		if cerr := tmp.Close(); werr == nil {
			werr = cerr
		}
		if werr != nil {
			return werr
		}
		st, err := loadUsers(tmpName)
		if err != nil {
			// not the reader's own message: it can quote a stored hash
			return errors.New("the users file with the new line does not load")
		}
		if _, ok := st.byName[got.User]; !ok {
			return errors.New("the new line did not make the person a user")
		}
		if err := os.Rename(tmpName, iv.usersFile); err != nil {
			return err
		}
		// spent: the users file is in place, so the invitation goes, with every one that expired. The person
		// IS a user now whatever happens next: a spend that fails here is said in the log and left to the
		// check above, which spends it at the link's next use (the second reader of DGO-1751).
		if err := iv.write(append(list[:idx:idx], list[idx+1:]...)); err != nil {
			log.Printf("forward-auth: invitation for %q accepted; its spend waits for the link's next use (%v)", got.User, err)
		}
		return nil
	})
	return got, err
}

// ── the commands: `forward-auth -invite`, `-invites`, `-revoke-invite` ─────────────────────────────────

// mintInvite is `forward-auth -invite`: «user email [display]» on stdin. It prints the code on one line
// (the hook turns it into the link), and nothing else; 2 with the reason on stderr.
func mintInvite(iv *invites, in io.Reader, out io.Writer, now time.Time) int {
	fail := func(why string) int {
		fmt.Fprintln(os.Stderr, "forward-auth: -invite:", why)
		return 2
	}
	line, _ := bufio.NewReader(in).ReadString('\n')
	f := strings.Fields(line)
	if len(f) < 2 || len(f) > 3 {
		return fail("want «user email [display]» on stdin")
	}
	user, email := strings.ToLower(f[0]), f[1]
	display := user
	if len(f) == 3 {
		display = f[2]
	}
	switch {
	case !userNameRE.MatchString(user):
		return fail("the user name: small Latin letters, digits, . _ - — up to 32")
	case !strings.Contains(email, "@") || strings.IndexFunc(email, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }) >= 0:
		return fail("the email does not look like one")
	case len([]rune(display)) > inviteDisplayMax || strings.IndexFunc(display, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }) >= 0:
		return fail(fmt.Sprintf("the display name is one word of at most %d characters (the users file is space-separated)", inviteDisplayMax))
	}
	if _, err := os.Stat(iv.usersFile); err != nil {
		return fail("this office has no owner yet — its first-run link comes first")
	}
	code := randomToken(24) // 192 bits, 32 characters
	err := iv.locked(func() error {
		st, err := loadUsers(iv.usersFile)
		if err != nil {
			return errors.New("the users file does not load")
		}
		if _, ok := st.byName[user]; ok {
			return fmt.Errorf("%s is already a user of this office", user)
		}
		list, err := iv.read()
		if err != nil {
			return err
		}
		kept := []invite{}
		for _, v := range liveInvites(list, now) {
			if v.User != user { // a new invitation for the same person replaces the old: one live link each
				kept = append(kept, v)
			}
		}
		kept = append(kept, invite{Hash: codeHash(code), User: user, Email: email, Display: display,
			Expires: now.Add(inviteTTL).Unix()})
		return iv.write(kept)
	})
	if err != nil {
		return fail(err.Error())
	}
	fmt.Fprintln(out, code)
	return 0
}

// listInvites is `forward-auth -invites`: the live invitations, one per line — user, email, display, the
// expiry (UTC). Never a code: the file holds none.
func listInvites(iv *invites, out io.Writer, now time.Time) int {
	list, err := iv.read()
	if err != nil {
		fmt.Fprintln(os.Stderr, "forward-auth: -invites:", err)
		return 2
	}
	for _, v := range liveInvites(list, now) {
		fmt.Fprintf(out, "%s %s %s %s\n", v.User, v.Email, v.Display, time.Unix(v.Expires, 0).UTC().Format(time.RFC3339))
	}
	return 0
}

// revokeInvite is `forward-auth -revoke-invite`: a user name on stdin; its invitation goes. One word:
// "revoked" or "none".
func revokeInvite(iv *invites, in io.Reader, out io.Writer, now time.Time) int {
	line, _ := bufio.NewReader(in).ReadString('\n')
	user := strings.ToLower(strings.TrimSpace(line))
	gone := false
	err := iv.locked(func() error {
		list, err := iv.read()
		if err != nil {
			return err
		}
		kept := []invite{}
		for _, v := range liveInvites(list, now) {
			if v.User == user {
				gone = true
				continue
			}
			kept = append(kept, v)
		}
		return iv.write(kept)
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, "forward-auth: -revoke-invite:", err)
		return 2
	}
	if gone {
		fmt.Fprintln(out, "revoked")
	} else {
		fmt.Fprintln(out, "none")
	}
	return 0
}

// ── the page ────────────────────────────────────────────────────────────────────────────────────────

// The invited person's page is ui/pages.html `invite`: THE card, their name, two password fields.
type inviteForm struct {
	Code, ReturnTo, User, Display, Error string
}

func renderInvite(w http.ResponseWriter, status int, f inviteForm) {
	// the code is in this page's URL: it must not leave in a Referer, not even for the page's stylesheet
	w.Header().Set("Referrer-Policy", "no-referrer")
	renderPage(w, status, "invite", f)
}

func (s *server) inviteHandler(w http.ResponseWriter, r *http.Request) {
	if s.invites == nil {
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
		v, ok := s.invites.find(code, time.Now())
		if !ok {
			renderInvite(w, http.StatusOK, inviteForm{}) // the page without a form: says the link is not valid
			return
		}
		renderInvite(w, http.StatusOK, inviteForm{Code: code, ReturnTo: rd, User: v.User, Display: v.Display})
	case http.MethodPost:
		s.doInvite(w, r)
	default:
		w.Header().Set("Allow", "GET, HEAD, POST")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *server) doInvite(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		renderInvite(w, http.StatusBadRequest, inviteForm{Error: "הבקשה לא נקראה."})
		return
	}
	now := time.Now()
	code := r.PostFormValue("code")
	v, ok := s.invites.find(code, now)
	if !ok {
		// wrong codes are what is limited, per address (setup.go's rule): a right one always goes through
		keys := []string{"invite-ip:" + clientKey(clientIP(r))}
		if left := s.limit.begin(now, keys...); left > 0 {
			w.Header().Set("Retry-After", fmt.Sprint(int(left/time.Second)+1))
			renderInvite(w, http.StatusTooManyRequests, inviteForm{})
			return
		}
		s.limit.end(now, false, keys...)
		log.Printf("forward-auth: invitation refused, no such code: ip=%q", clientIP(r))
		renderInvite(w, http.StatusForbidden, inviteForm{})
		return
	}
	rd := r.PostFormValue("rd")
	if !s.okReturnTo(rd) {
		rd = ""
	}
	f := inviteForm{Code: code, ReturnTo: rd, User: v.User, Display: v.Display}
	password := r.PostFormValue("password")
	switch {
	case len([]rune(password)) < minPassword:
		f.Error = fmt.Sprintf("הסיסמה צריכה להיות לפחות %d תווים.", minPassword)
	case password != r.PostFormValue("again"):
		f.Error = "שתי הסיסמאות שונות."
	}
	if f.Error != "" {
		renderInvite(w, http.StatusBadRequest, f)
		return
	}
	hash, err := hashPassword(password)
	if err != nil {
		log.Printf("forward-auth: invitation: could not hash the password: %v", err)
		inviteFailed(w)
		return
	}
	// name email display uid groups hash
	line := strings.Join([]string{v.User, v.Email, v.Display, randomToken(16), inviteGroups, hash}, " ")
	if _, err := s.invites.accept(code, line, now); err != nil {
		if errors.Is(err, errInviteGone) {
			renderInvite(w, http.StatusGone, inviteForm{}) // spent between the page and the press (a second tab)
			return
		}
		log.Printf("forward-auth: invitation for %q could not be saved: %v", v.User, err)
		inviteFailed(w)
		return
	}
	log.Printf("forward-auth: invitation accepted: user=%q ip=%q", v.User, clientIP(r))
	if s.live != nil {
		s.live.reload() // the cookie below names a user the store already knows
	}
	s.sign.set(w, v.User, s.secureCookie, s.cookieDomain)
	if rd == "" {
		rd = s.external + "/"
	}
	w.Header().Set("Cache-Control", "no-store")
	http.Redirect(w, r, rd, http.StatusSeeOther)
}

func inviteFailed(w http.ResponseWriter) {
	renderProblem(w, http.StatusInternalServerError, problem{
		Title: "ההצטרפות לא נשמרה", Sub: "השמירה נכשלה",
		Text: "הלשכה לא הצליחה לשמור את הסיסמה. פתחו שוב את הקישור ונסו בעוד רגע.",
	})
}

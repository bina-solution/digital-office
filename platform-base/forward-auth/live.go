package main

import (
	"errors"
	"log"
	"os"
	"sync"
	"time"
)

// liveUsers is the users file as it stands NOW (review finding F4, .claude/needs-azaria.md §2): it is
// re-read when it changes, checked at most once a second, so a line the credential plane removes ends
// that person's sessions within a second, and an owner whose password first-run setup just wrote can
// sign in without a restart.
//
// A change is a different FILE (a writer that renames a new one into place — the only safe way to
// write it — makes a new inode: a password change keeps a PBKDF2 line's length, so size and a coarse
// mtime alone would miss it), or a different mtime or size.
//
// A file that changes into something unreadable or malformed does NOT empty the office: the store it
// replaced keeps answering, the failure is logged once, and the next change is tried again. Refusing
// to start on a bad file is right at boot (main); at runtime the same refusal would lock everybody out
// because of one bad write.
type liveUsers struct {
	path    string
	mu      sync.Mutex
	cur     *userStore
	seen    os.FileInfo // the file when cur was read, or when a bad version was seen; nil: none yet
	checked time.Time
	loading bool
}

// newLiveUsers loads the file. It may be missing only while first-run setup is pending (allowMissing):
// the store is then empty — every sign-in refused — until setup writes the file.
func newLiveUsers(path string, allowMissing bool) (*liveUsers, error) {
	fi, err := os.Stat(path)
	if err != nil {
		if allowMissing && errors.Is(err, os.ErrNotExist) {
			return &liveUsers{path: path, cur: &userStore{byName: map[string]*user{}}}, nil
		}
		return nil, err
	}
	st, err := loadUsers(path)
	if err != nil {
		return nil, err
	}
	return &liveUsers{path: path, cur: st, seen: fi}, nil
}

func changed(seen, now os.FileInfo) bool {
	return seen == nil || !os.SameFile(seen, now) || !now.ModTime().Equal(seen.ModTime()) || now.Size() != seen.Size()
}

func (l *liveUsers) get(now time.Time) *userStore {
	l.mu.Lock()
	if l.loading || now.Sub(l.checked) < time.Second {
		cur := l.cur
		l.mu.Unlock()
		return cur
	}
	l.checked = now
	fi, err := os.Stat(l.path)
	if err != nil || !changed(l.seen, fi) {
		cur := l.cur
		l.mu.Unlock()
		return cur
	}
	l.seen = fi
	l.loading = true
	l.mu.Unlock()

	// Outside the lock: a load hashes a fresh burn value (PBKDF2), and every request would wait on it.
	// Meanwhile the store that was current keeps answering.
	st, err := loadUsers(l.path)

	l.mu.Lock()
	defer l.mu.Unlock()
	l.loading = false
	if err != nil {
		log.Printf("forward-auth: the users file changed and does not load (%v) — the previous %d user(s) still answer", err, len(l.cur.byName))
		return l.cur
	}
	l.cur = st
	log.Printf("forward-auth: the users file changed: %d user(s)", len(st.byName))
	return l.cur
}

// reload reads the file now, without waiting for the next once-a-second check — for the one writer
// in this process (first-run setup), whose next step names the user it just wrote. A load already
// running is waited for, so the file this one reads is the one just written.
func (l *liveUsers) reload() {
	for {
		l.mu.Lock()
		if !l.loading {
			l.checked = time.Time{}
			l.mu.Unlock()
			break
		}
		l.mu.Unlock()
		time.Sleep(10 * time.Millisecond)
	}
	l.get(time.Now())
}

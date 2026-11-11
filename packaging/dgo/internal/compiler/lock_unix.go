//go:build !windows

package compiler

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"syscall"
)

// lockFile blocks until this process holds the exclusive flock(2) on f — the lock bash's `flock`
// takes, so a shell writer can join the same rule.
func lockFile(f *os.File) error { return syscall.Flock(int(f.Fd()), syscall.LOCK_EX) }

// denied is an open(2), creat or rename(2) refused for want of permission (EACCES) — what Python
// reports as PermissionError: [Errno 13].
func denied(err error) bool { return errors.Is(err, syscall.EACCES) }

// keepOwner gives the new file the old one's owner and group, which only root may do — and only a
// writer running as root (a container that mounts the checkout) needs to.
func keepOwner(path string, old os.FileInfo) {
	if st, ok := old.Sys().(*syscall.Stat_t); ok && (int(st.Uid) != os.Getuid() || int(st.Gid) != os.Getgid()) {
		_ = os.Chown(path, int(st.Uid), int(st.Gid)) // not root: the file stays this process's, as a new file is
	}
}

// handBackFiles is reconcile.py's HAND_BACK_FILES: what the compiler writes outside .generated/, into committed
// directories — the sign-in's blueprint and the edge's two files.
var handBackFiles = []string{
	filepath.Join(authentikDir, "blueprints", generatedBlueprint),
	filepath.Join("platform-base", "traefik", "config", "zz-https.yaml"),
	filepath.Join("platform-base", "traefik", "config", "zz-serve.yaml"),
}

// HandBack gives the checkout's owner what a compile run as root left root's in it — every entry under
// .generated/ and handBackFiles — and returns how many (reconcile.py's hand_back, DGO-121: the control plane
// compiles as root on the office's checkout, and on the Dell 843 of 1,077 entries of .generated/ were root's). A
// no-op unless this process is root and the checkout is not root's. The last part of a path is never followed
// (Lchown), WalkDir does not descend into a linked directory, and a .generated/ that is a link is not walked.
// Nothing is printed and nothing fails: callers read the verb's own output.
func HandBack(repo string) int {
	return handBack(repo, os.Geteuid(), ownerOf, os.Lchown)
}

// ownerOf is path's uid and gid — of the link itself when link is true (lstat), else of what it names.
func ownerOf(path string, link bool) (uid, gid int, ok bool) {
	stat := os.Stat
	if link {
		stat = os.Lstat
	}
	fi, err := stat(path)
	if err != nil {
		return 0, 0, false
	}
	st, isUnix := fi.Sys().(*syscall.Stat_t)
	if !isUnix {
		return 0, 0, false
	}
	return int(st.Uid), int(st.Gid), true
}

func handBack(repo string, euid int, owner func(string, bool) (int, int, bool), lchown func(string, int, int) error) int {
	if euid != 0 {
		return 0
	}
	uid, gid, ok := owner(repo, false)
	if !ok || uid == 0 {
		return 0
	}
	n := 0
	give := func(p string) {
		if u, _, ok := owner(p, true); ok && u == 0 && lchown(p, uid, gid) == nil {
			n++
		}
	}
	gen := filepath.Join(repo, ".generated")
	if li, err := os.Lstat(gen); err == nil && li.IsDir() {
		_ = filepath.WalkDir(gen, func(p string, _ fs.DirEntry, err error) error {
			if err == nil {
				give(p)
			}
			return nil
		})
	}
	for _, f := range handBackFiles {
		give(filepath.Join(repo, f))
	}
	return n
}

//go:build !windows

package compiler

import (
	"errors"
	"os"
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

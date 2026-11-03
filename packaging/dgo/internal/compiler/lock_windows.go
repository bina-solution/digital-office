//go:build windows

package compiler

import (
	"errors"
	"os"
	"syscall"
	"unsafe"
)

// lockFileEx is kernel32's LockFileEx. kernel32.dll is loaded into every Go program on Windows, so
// naming it searches no directory a planted DLL could sit in.
var lockFileEx = syscall.NewLazyDLL("kernel32.dll").NewProc("LockFileEx")

// lockFile blocks until this process holds an exclusive lock on f's first byte. Windows releases it
// when the handle is closed or the process ends.
func lockFile(f *os.File) error {
	const exclusive = 0x2 // LOCKFILE_EXCLUSIVE_LOCK
	var ol syscall.Overlapped
	if ok, _, err := lockFileEx.Call(f.Fd(), exclusive, 0, 1, 0, uintptr(unsafe.Pointer(&ol))); ok == 0 {
		return err
	}
	return nil
}

// keepOwner has nothing to carry over on Windows: the new file takes the directory's inherited
// permissions, which is what the checkout's files have.
func keepOwner(string, os.FileInfo) {}

// The errors CreateFile and MoveFileEx answer for a file's read-only attribute, its ACL, or another
// process's handle that does not share the access asked for.
const (
	errAccessDenied     = syscall.Errno(5)  // ERROR_ACCESS_DENIED
	errSharingViolation = syscall.Errno(32) // ERROR_SHARING_VIOLATION
	errLockViolation    = syscall.Errno(33) // ERROR_LOCK_VIOLATION
)

// denied is one of them — what CPython reports as PermissionError: [Errno 13]. A rename over a file
// another process holds open without sharing its deletion fails so, though a write into it does not.
func denied(err error) bool {
	var errno syscall.Errno
	return errors.As(err, &errno) && (errno == errAccessDenied || errno == errSharingViolation || errno == errLockViolation)
}

//go:build windows

package compiler

import (
	"syscall"
	"testing"
)

// lockedOut makes path a file no one else may read until release: it is held open with no sharing,
// which is how a file this user cannot read shows on Windows — what a root-owned 0600 file is on Linux.
func lockedOut(t *testing.T, path string) (release func()) {
	t.Helper()
	name, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		t.Fatal(err)
	}
	h, err := syscall.CreateFile(name, syscall.GENERIC_READ, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		t.Fatal(err)
	}
	return func() { syscall.CloseHandle(h) }
}

//go:build !windows

package compiler

import (
	"os"
	"testing"
)

// lockedOut makes path a file this user cannot read until release: mode 0, as a root-owned 0600 file
// is to anyone else. Root reads it all the same, and then the case is the ordinary archive.
func lockedOut(t *testing.T, path string) (release func()) {
	t.Helper()
	fi, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0); err != nil {
		t.Fatal(err)
	}
	return func() { os.Chmod(path, fi.Mode().Perm()) }
}

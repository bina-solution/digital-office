package main

import (
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The phone's native core (DGO-1090): forward-auth on a Unix socket only its owner may open; a socket a
// dead process left is replaced, one a live forward-auth answers on and a file that is not a socket are
// never touched, and a relative path is refused.
func TestListenOnAUnixSocket(t *testing.T) {
	dir, err := os.MkdirTemp("", "fa") // short: a socket's path has a limit of ~100 bytes
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	path := filepath.Join(dir, "fa.sock")

	ln, err := listen("unix:" + path)
	if err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode().Perm() != 0o600 {
		t.Fatalf("the socket's mode is %v, want 0600", st.Mode().Perm())
	}
	if _, err := listen("unix:" + path); err == nil || !strings.Contains(err.Error(), "another process answers") {
		t.Fatalf("a socket a live listener holds was taken over: %v", err)
	}
	// a process that died: its socket stays behind
	ln.(*net.UnixListener).SetUnlinkOnClose(false)
	ln.Close()
	if _, err := os.Lstat(path); err != nil {
		t.Fatalf("the dead listener's socket is gone already (%v): nothing is tested", err)
	}
	again, err := listen("unix:" + path)
	if err != nil {
		t.Fatalf("a dead process's socket was not replaced: %v", err)
	}
	again.Close()

	plain := filepath.Join(dir, "users.json")
	if err := os.WriteFile(plain, []byte("{}"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := listen("unix:" + plain); err == nil || !strings.Contains(err.Error(), "is not a socket") {
		t.Fatalf("a file that is not a socket: %v", err)
	}
	if b, err := os.ReadFile(plain); err != nil || string(b) != "{}" {
		t.Fatalf("the file that is not a socket was touched: %q %v", b, err)
	}
	if _, err := listen("unix:fa.sock"); err == nil {
		t.Fatal("a relative socket path was taken")
	}
}

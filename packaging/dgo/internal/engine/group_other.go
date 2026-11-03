//go:build !unix

package engine

import "os/exec"

// group has no process group to kill here (Windows): the program itself is killed at the deadline,
// and WaitDelay stops the wait for a child that still holds its output pipe.
func group(*exec.Cmd) {}

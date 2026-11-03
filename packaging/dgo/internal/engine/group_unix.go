//go:build unix

package engine

import (
	"os/exec"
	"syscall"
)

// group gives the call a process group of its own and, at its deadline, kills the whole group —
// limactl's ssh, a shell's children — not only the program dgo started.
func group(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
}

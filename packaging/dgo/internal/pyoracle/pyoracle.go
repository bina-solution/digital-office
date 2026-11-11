// Package pyoracle names the Python interpreters the ORACLE tests run the originals with — reconcile.py,
// serve.py, catalog.py, PyYAML — and says which one a test got (DGO-1108). Not engine.sh's: that runs
// /usr/bin/python3, the system's, so the engine package asks for python3 first.
//
// The oracles compare the Go code with CPython 3.12's exact answers: refusal messages, nesting and digit
// limits, address tables. Another version answers some inputs differently (in WSL's 3.10 five cases of the
// compiler lanes differed, 2026-10-15; the net lane needs 3.12.4 or later), so a red there is the
// interpreter's, not the port's. CI pins 3.12 (.github/workflows/go-test.yml); a developer's machine asked
// for `python3` first and got whatever that was. Now 3.12 is asked for first by its own name, and the test
// log says which interpreter answered.
package pyoracle

import (
	"os/exec"
	"strings"
)

// Candidates in the order a test asks them: CPython 3.12 by its own name (Unix, then Windows' launcher),
// then the usual names.
var Candidates = [][]string{{"python3.12"}, {"py", "-3.12"}, {"python3"}, {"python"}, {"py", "-3"}}

// Pinned is the line a test logs for the interpreter it got: "oracle pinned to 3.12", or which version it is
// instead and what that means for a red.
func Pinned(c []string) string {
	out, err := exec.Command(c[0], append(append([]string{}, c[1:]...), "-c",
		"import sys; print('%d.%d.%d' % sys.version_info[:3])")...).Output()
	v := strings.TrimSpace(string(out))
	if err != nil || v == "" {
		return "oracle on " + strings.Join(c, " ") + " (its version did not answer)"
	}
	if strings.HasPrefix(v, "3.12.") {
		return "oracle pinned to 3.12 (" + v + ", " + strings.Join(c, " ") + ")"
	}
	return "oracle on Python " + v + ", not 3.12: an answer that differs may be the interpreter's, not the port's"
}

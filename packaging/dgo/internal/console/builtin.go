//go:build consoleembed

package console

import (
	"embed"
	"io/fs"
)

// The console's files inside dgo — the release build's: packaging/build-binaries.sh builds dgo with
// -tags consoleembed after filling snapshot/, in a throwaway copy of this module, with
// platform-base/console's static/ and modules.yaml exactly as committed at HEAD, and commit-time, that
// commit's time. snapshot/ is git-ignored: platform-base/console stays the one source, and a tagged
// build without the copy stops here ("no matching files") instead of serving an empty shell. `all:`
// keeps a file whose name starts with `.` or `_` — app.py serves those too.
//
//go:embed all:snapshot
var snapshot embed.FS

func init() {
	builtIn, _ = fs.Sub(snapshot, "snapshot") // a valid constant name: fs.Sub has no error to give
}

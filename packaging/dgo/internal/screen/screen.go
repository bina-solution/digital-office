// Package screen serves an app's static screen from the office root, in the app's place, where the office
// has no container to serve it — the phone's core (DGO-1328): send_from_directory's files, as each app's
// server sends its static/.
package screen

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// Serve answers r from dir — r.URL.Path is the name under it, "/" its index.html — and reports true, or
// reports false having written nothing: a regular file under dir, reached through no link, no `..`, no
// backslash, no hidden name; anything else, or a dir that is not there, is the caller's to answer.
func Serve(w http.ResponseWriter, r *http.Request, dir string) bool {
	name := strings.TrimPrefix(r.URL.Path, "/")
	if name == "" {
		name = "index.html"
	}
	for _, seg := range strings.Split(name, "/") {
		if seg == "" || seg == "." || seg == ".." || strings.HasPrefix(seg, ".") {
			return false
		}
	}
	if strings.ContainsRune(name, '\\') || !filepath.IsLocal(filepath.FromSlash(name)) {
		return false // a separator of another OS, or a name that leaves the directory where it is read
	}
	path := filepath.Join(dir, filepath.FromSlash(name))
	// the file as opened, not as named: a regular one, whose real path is the name under the screen's real
	// directory — a link between the two (the leaf, a directory under dir) leaves it to the caller. A link
	// above it is the root's own place (on a phone /data/user/0 is often a link to /data/data)
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil || !st.Mode().IsRegular() {
		return false
	}
	realDir, err1 := filepath.EvalSymlinks(dir)
	realPath, err2 := filepath.EvalSymlinks(path)
	if err1 != nil || err2 != nil || realPath != filepath.Join(realDir, filepath.FromSlash(name)) {
		return false
	}
	w.Header().Set("Cache-Control", "no-cache")
	http.ServeContent(w, r, st.Name(), st.ModTime(), f)
	return true
}

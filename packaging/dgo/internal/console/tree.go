package console

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// maxShell is how many bytes of --static are read before the start is refused: the shell is a few
// hundred kilobytes, and a --static pointed at the wrong directory must not fill the memory.
const maxShell = 128 << 20

// tree is --static as it was at start, or the copy built into dgo — what /app/static is to app.py in
// the image. Every file is in memory under the exact name a URL must spell: a lookup is a map's, so no
// case folding, trailing dot or space, or device name of the host's filesystem can name a file the
// Linux image would not have. A link that leads out of --static is answered 404 (app.py would follow
// it, but in the image a link reaches only the image; here --static is a checkout several writers
// share). The digest is app.py's _shell_build() of the same bytes that are served.
type tree struct {
	files   map[string]*shellFile // URL path below `/` → the file
	refused map[string]bool       // a link that resolves outside --static: 404 at it and below it
	digest  string
}

type shellFile struct {
	body []byte
	mod  time.Time
}

// find returns the file a URL path names, or refused when the path runs through a refused link.
func (t *tree) find(rel string) (*shellFile, bool) {
	for i := 0; i <= len(rel); i++ {
		if (i == len(rel) || rel[i] == '/') && t.refused[rel[:i]] {
			return nil, true
		}
	}
	return t.files[rel], false
}

// readTree walks --static as os.walk does for the digest and as send_from_directory reaches for
// serving. A link — a symlink, or a Windows junction — counts only when its target is under --static:
// a link to a file is served and digested (os.walk lists it with the files and open() reads through
// it), a link to a directory is served but not digested (os.walk lists it with the directories and
// does not walk it), each linked directory once. A link to nothing makes app.py fail to start, and so
// it makes this refuse to.
func readTree(static string) (*tree, error) {
	top, err := filepath.EvalSymlinks(static)
	if err != nil {
		return nil, err
	}
	t := &tree{files: map[string]*shellFile{}, refused: map[string]bool{}}
	type sub struct {
		path, rel string
		digest    bool
	}
	var digested []shellDir
	var total int64
	walked := map[string]bool{top: true}
	var walk func(path, rel string, digest bool) error
	walk = func(path, rel string, digest bool) error {
		entries, err := os.ReadDir(path)
		if err != nil {
			return nil // os.walk passes over a directory it cannot list
		}
		d := shellDir{rel: strings.TrimSuffix(rel, "/")}
		var subs []sub
		for _, e := range entries {
			full, name := filepath.Join(path, e.Name()), rel+e.Name()
			real, kind := full, e.Type()
			if kind&(fs.ModeSymlink|fs.ModeIrregular) != 0 { // a symlink, or a junction (Go 1.23+ reports it irregular)
				if real, err = filepath.EvalSymlinks(full); err != nil {
					return fmt.Errorf("%s: a link to nothing (app.py fails to start on it too)", full)
				}
				if real != top && !strings.HasPrefix(real, top+string(filepath.Separator)) {
					t.refused[name] = true
					continue
				}
				st, err := os.Stat(real)
				if err != nil {
					return err
				}
				if st.IsDir() {
					if !walked[real] {
						walked[real] = true
						subs = append(subs, sub{real, name + "/", false})
					}
					continue
				}
				kind = st.Mode().Type()
			}
			switch {
			case kind.IsDir():
				subs = append(subs, sub{full, name + "/", digest})
			case kind.IsRegular():
				st, err := os.Stat(real)
				if err != nil {
					return err
				}
				body, err := os.ReadFile(real)
				if err != nil {
					return err
				}
				if total += int64(len(body)); total > maxShell {
					return fmt.Errorf("%s holds more than %d MiB — the shell is a few hundred KB: is --static right?", static, maxShell>>20)
				}
				t.files[name] = &shellFile{body: body, mod: st.ModTime()}
				if digest {
					d.files = append(d.files, e.Name())
				}
			} // a device, a socket or a pipe is no file of the shell
		}
		if digest {
			digested = append(digested, d)
		}
		for _, s := range subs {
			if err := walk(s.path, s.rel, s.digest); err != nil {
				return err
			}
		}
		return nil
	}
	if err := walk(static, "", true); err != nil {
		return nil, err
	}
	t.seal(digested, string(filepath.Separator)) // app.py on this host writes its own separator
	return t, nil
}

// imageStatic is app.py's STATIC in the console's image — WORKDIR /app, `COPY static/ ./static/` —
// the path the ETag of a file built into dgo hashes, as the image's would.
const imageStatic = "/app/static"

// readBuiltIn is the console's files built into dgo (builtin.go) as the tree: snapshot/static is the
// shell, each file under its own name — go:embed carries regular files and nothing else, so there is no
// link to judge — and commit-time, the time of the commit the build copied them from, stands for every
// file's modification time: the Last-Modified it answers, and what its ETag counts. The digest is app.py's
// in its Linux image, whose paths are written with `/`.
func readBuiltIn(snapshot fs.FS) (*tree, error) {
	raw, err := fs.ReadFile(snapshot, "commit-time")
	if err != nil {
		return nil, err
	}
	sec, err := strconv.ParseInt(strings.TrimSpace(string(raw)), 10, 64)
	if err != nil {
		return nil, fmt.Errorf("commit-time %q is not a number of seconds", raw)
	}
	if st, err := fs.Stat(snapshot, "static"); err != nil || !st.IsDir() {
		return nil, fmt.Errorf("no static/ directory in it")
	}
	static, _ := fs.Sub(snapshot, "static") // a valid constant name: fs.Sub has no error to give
	mod := time.Unix(sec, 0)
	t := &tree{files: map[string]*shellFile{}, refused: map[string]bool{}}
	var dirs []shellDir
	at := map[string]int{} // a directory's index in dirs
	err = fs.WalkDir(static, ".", func(p string, e fs.DirEntry, err error) error {
		switch {
		case err != nil:
			return err
		case e.IsDir():
			at[p] = len(dirs)
			if p == "." {
				p = ""
			}
			dirs = append(dirs, shellDir{rel: p})
			return nil
		case !e.Type().IsRegular():
			return fmt.Errorf("static/%s is not a file", p)
		}
		body, err := fs.ReadFile(static, p)
		if err != nil {
			return err
		}
		t.files[p] = &shellFile{body: body, mod: mod}
		d := &dirs[at[path.Dir(p)]]
		d.files = append(d.files, path.Base(p))
		return nil
	})
	if err != nil {
		return nil, err
	}
	t.seal(dirs, "/")
	return t, nil
}

// shellDir is a directory os.walk lists for the digest: its path below STATIC, `/`-separated ("" for
// STATIC itself), and the names of its files.
type shellDir struct {
	rel   string
	files []string
}

// seal sets the digest: app.py's _shell_build() — sha256 over (the path relative to STATIC, the bytes)
// of every file, the directories in the sorted order of their full paths and the files of each sorted —
// its first 12 hex digits. sep is the separator app.py writes those paths with. Every full path is
// STATIC itself or STATIC, sep and the relative path, so ordering the relative paths (STATIC's own ""
// first) is ordering the full ones.
func (t *tree) seal(dirs []shellDir, sep string) {
	native := func(rel string) string { return strings.ReplaceAll(rel, "/", sep) }
	sort.Slice(dirs, func(i, j int) bool { return native(dirs[i].rel) < native(dirs[j].rel) })
	h := sha256.New()
	for _, d := range dirs {
		sort.Strings(d.files)
		for _, name := range d.files {
			rel := name
			if d.rel != "" {
				rel = d.rel + "/" + name
			}
			h.Write([]byte(native(rel)))
			h.Write(t.files[rel].body)
		}
	}
	t.digest = hex.EncodeToString(h.Sum(nil))[:12]
}

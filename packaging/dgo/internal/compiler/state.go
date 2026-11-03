package compiler

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

const (
	stateName   = "platform.state.yaml"
	defaultName = "platform.state.default.yaml"
	genDir      = ".generated"
)

// legacyAppIDs mirrors LEGACY_APP_IDS: renamed apps whose old id may still be in a state file.
var legacyAppIDs = map[string]string{"offices": "dgo-extend"}

// dispositions mirrors DISPOSITIONS, in its order (argparse lists them so as --state's choices).
var dispositions = []string{"enabled", "disabled", "archived"}

// State is platform.state.yaml as load_state() returns it.
type State struct {
	Doc  *yamlish.Map
	Apps *yamlish.Map // `apps:` (never nil; empty when absent)
	// appsNot is what `apps:` holds when it is set to something other than a mapping: load_state()
	// keeps it, and enabled_ids() dies on it (.items()) — so does EnabledIDs.
	appsNot any
}

// LoadState is load_state(): ensure the file exists (the three answers of ensure_state, in order),
// refuse a schema_version that is not 1 (by Python's ==, so 1.0 and true are 1), normalise a legacy
// app id. Info lines go where Python's print() sends them: the restore notices to stdout, the
// legacy-id notice to stderr.
func LoadState(repo string, stdout, stderr io.Writer) (*State, error) {
	path := filepath.Join(repo, stateName)
	if err := ensureState(repo, path, stdout); err != nil {
		return nil, err
	}
	v, err := ReadState(repo)
	if err != nil {
		return nil, fmt.Errorf("FATAL %s: %v", stateName, err)
	}
	doc, err := mapping(v, stateName)
	if err != nil {
		return nil, err
	}
	sv, _ := doc.Get("schema_version")
	if !pyEqual(sv, int64(1)) {
		return nil, fmt.Errorf("FATAL platform.state.yaml schema_version %s unsupported (expected 1)", pyval.Str(sv))
	}
	apps := yamlish.NewMap()
	av, _ := doc.Get("apps")
	if m, ok := av.(*yamlish.Map); ok {
		apps = m
	} else if truthy(av) {
		// Kept as it is, as load_state() keeps it — which first asks it, as a container, whether it
		// holds a legacy id: a number or a bool is no container, and a list or a text that holds one
		// has no way to rename it.
		for old, now := range legacyAppIDs {
			has, ok := holds(av, old)
			if !ok {
				return nil, died("%s: apps is %s, not a mapping", stateName, pyval.Repr(av))
			}
			if hasNew, _ := holds(av, now); has && !hasNew {
				return nil, died("%s: apps is %s, not a mapping", stateName, pyval.Repr(av))
			}
		}
		return &State{Doc: doc, Apps: apps, appsNot: av}, nil
	}
	for old, now := range legacyAppIDs {
		if e, has := apps.Get(old); has {
			if _, hasNew := apps.Get(now); !hasNew {
				apps.Set(now, e)
				apps.Delete(old)
				fmt.Fprintf(stderr, "  info  platform.state.yaml: legacy app id '%s' is '%s' now — run apps/dgo-extend/hooks/migrate to rewrite the file\n", old, now)
			}
		}
	}
	return &State{Doc: doc, Apps: apps}, nil
}

// holds is `x in c` for a value that is not a mapping: a list's items, a text's substrings; ok is
// false where Python raises (a number or a bool is no container).
func holds(c any, x string) (has, ok bool) {
	switch t := c.(type) {
	case []any:
		for _, e := range t {
			if pyEqual(e, x) {
				return true, true
			}
		}
		return false, true
	case string:
		return strings.Contains(t, x), true
	}
	return false, false
}

// ReadState is the state file as reconcile.py's readers parse it — yaml.safe_load(read_text()) —
// without load_state()'s first-run creation, schema check and legacy rename: what office_block()
// and remote_block() read, and what LoadState reads after ensure_state(). The text is readText's, the
// one reader of the file the writers read too. A file that cannot be read is an *fs.PathError
// (Python's OSError, which office_block() answers with {}); text that is not UTF-8 is not one: it is
// Python's UnicodeDecodeError, which no caller catches, in its own words.
func ReadState(repo string) (any, error) {
	text, err := readText(statePath(repo))
	var d *dies
	if errors.As(err, &d) {
		return nil, errors.New("UnicodeDecodeError: " + d.codec)
	}
	if err != nil {
		return nil, err
	}
	return yamlish.Unmarshal([]byte(text))
}

// mapping is `value or {}` where the value is then read as a mapping (.get, .items): empty is {}, a
// mapping is itself, and anything else is where Python raises.
func mapping(v any, what string) (*yamlish.Map, error) {
	if !truthy(v) {
		return yamlish.NewMap(), nil
	}
	if m, ok := v.(*yamlish.Map); ok {
		return m, nil
	}
	return nil, died("%s is %s, not a mapping", what, pyval.Repr(v))
}

// ensureState mirrors ensure_state(): 1. the file is there; 2. missing but ORIG_HEAD carried it;
// 3. a real first run → the tracked default — refused on a checkout that has compiled before.
func ensureState(repo, path string, stdout io.Writer) error {
	if _, err := os.Stat(path); err == nil {
		return nil
	}
	var restored []byte
	if out, err := exec.Command("git", "-C", repo, "rev-parse", "--verify", "--quiet", "ORIG_HEAD").Output(); err == nil && strings.TrimSpace(string(out)) != "" {
		show, err := exec.Command("git", "-C", repo, "show", strings.TrimSpace(string(out))+":"+stateName).Output()
		if err == nil && strings.TrimSpace(string(show)) != "" {
			restored = show
		}
	}
	if restored == nil {
		if st, err := os.Stat(filepath.Join(repo, genDir)); err == nil && st.IsDir() {
			return fmt.Errorf("FATAL %s is missing on a checkout that has compiled before (%s/ is here) — refusing to start it from %s. Restore this office's own %s, or remove %s/ to install the product default on purpose.",
				stateName, genDir, defaultName, stateName, genDir)
		}
		def, err := os.ReadFile(filepath.Join(repo, defaultName))
		if err != nil {
			return fmt.Errorf("FATAL %s is missing and there is no %s to create it from", stateName, defaultName)
		}
		restored = def
		fmt.Fprintf(stdout, "  info  %s: created from %s (this checkout's first run)\n", stateName, defaultName)
	} else {
		fmt.Fprintf(stdout, "  info  %s: restored from the commit this checkout was on (ORIG_HEAD)\n", stateName)
	}
	// written as Python writes text it read in text mode: every \r\n and lone \r is a \n — and with the
	// mode Python's open() gives a new file, 0666 less the umask, as every other writer here: a fixed 0644
	// read 0664 against reconcile.py's for a user whose umask is 002 (DGO-1038)
	text := strings.ReplaceAll(strings.ReplaceAll(string(restored), "\r\n", "\n"), "\r", "\n")
	return os.WriteFile(path, []byte(text), 0o666)
}

// Disposition mirrors disposition(): the declared disposition of one `apps.<id>` entry — the
// `{state: enabled|disabled|archived}` form, or the legacy `{enabled: bool}` form, else disabled. A
// `state` set to something that is not text is where Python's .strip() raises.
func Disposition(entry any) (string, error) {
	m, isMap := entry.(*yamlish.Map)
	if !truthy(entry) || !isMap {
		return "disabled", nil
	}
	if sv, _ := m.Get("state"); truthy(sv) {
		s, ok := sv.(string)
		if !ok {
			return "", fmt.Errorf("state %s is not text", pyval.Repr(sv))
		}
		if st, ok := namesDisposition(s); ok {
			return st, nil
		}
	}
	if ev, ok := m.Get("enabled"); ok && truthy(ev) {
		return "enabled", nil
	}
	return "disabled", nil
}

// namesDisposition is disposition()'s `state.strip().lower() in DISPOSITIONS`, as Python answers it:
// str.strip() is pyval.Strip and str.lower() is pyLower — İ lowers to i and U+0307, never to the ASCII
// i, and the Kelvin sign's k is in no disposition (TestDispositionIsPythons asks Python).
func namesDisposition(s string) (string, bool) {
	s = pyLower(pyval.Strip(s))
	return s, contains(dispositions, s)
}

// EnabledIDs mirrors enabled_ids(): the apps the platform should RUN — in the state, in the
// catalog, disposition enabled. Archived is deliberately not running.
func EnabledIDs(st *State, cat *Catalog) (map[string]bool, error) {
	if st.appsNot != nil {
		return nil, died("%s: apps is %s, not a mapping", stateName, pyval.Repr(st.appsNot))
	}
	out := map[string]bool{}
	for _, aid := range st.Apps.Keys() {
		if _, inCat := cat.Apps[aid]; !inCat {
			continue
		}
		e, _ := st.Apps.Get(aid)
		d, err := Disposition(e)
		if err != nil {
			return nil, died("%s: apps.%s: %v", stateName, aid, err)
		}
		if d == "enabled" {
			out[aid] = true
		}
	}
	return out, nil
}

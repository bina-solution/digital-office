package compiler

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

const (
	stateName   = "platform.state.yaml"
	defaultName = "platform.state.default.yaml"
	genDir      = ".generated"
)

// legacyAppIDs mirrors LEGACY_APP_IDS: renamed apps whose old id may still be in a state file.
var legacyAppIDs = map[string]string{"offices": "dgo-extend"}

// dispositions mirrors DISPOSITIONS.
var dispositions = map[string]bool{"enabled": true, "disabled": true, "archived": true}

// State is platform.state.yaml as load_state() returns it.
type State struct {
	Doc  *yamlish.Map
	Apps *yamlish.Map // `apps:` (never nil; empty when absent)
}

// LoadState is load_state(): ensure the file exists (the three answers of ensure_state, in order),
// refuse an unknown schema_version, normalise a legacy app id. Info lines go where Python's print()
// sends them: the restore notices to stdout, the legacy-id notice to stderr.
func LoadState(repo string, stdout, stderr io.Writer) (*State, error) {
	path := filepath.Join(repo, stateName)
	if err := ensureState(repo, path, stdout); err != nil {
		return nil, err
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("FATAL %s: %v", stateName, err)
	}
	v, err := yamlish.Unmarshal(raw)
	if err != nil {
		return nil, fmt.Errorf("FATAL %s: %v", stateName, err)
	}
	doc, _ := v.(*yamlish.Map)
	if doc == nil {
		doc = yamlish.NewMap()
	}
	sv, _ := doc.Get("schema_version")
	if n, ok := sv.(int64); !ok || n != 1 {
		return nil, fmt.Errorf("FATAL platform.state.yaml schema_version %s unsupported (expected 1)", pyRepr(sv))
	}
	apps := yamlish.NewMap()
	if av, ok := doc.Get("apps"); ok {
		if m, ok := av.(*yamlish.Map); ok {
			apps = m
		}
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
	return os.WriteFile(path, bytes.ReplaceAll(restored, []byte("\r\n"), []byte("\n")), 0o644)
}

// Disposition mirrors disposition(): the declared disposition of one `apps.<id>` entry — the
// `{state: enabled|disabled|archived}` form, or the legacy `{enabled: bool}` form, else disabled.
func Disposition(entry any) string {
	if !truthy(entry) {
		return "disabled"
	}
	m, isMap := entry.(*yamlish.Map)
	if isMap {
		if sv, ok := m.Get("state"); ok {
			if s, ok := sv.(string); ok {
				if st := strings.ToLower(strings.TrimSpace(s)); dispositions[st] {
					return st
				}
			}
		}
		if ev, ok := m.Get("enabled"); ok {
			if truthy(ev) {
				return "enabled"
			}
			return "disabled"
		}
	}
	return "disabled"
}

// EnabledIDs mirrors enabled_ids(): the apps the platform should RUN — in the state, in the
// catalog, disposition enabled. Archived is deliberately not running.
func EnabledIDs(st *State, cat *Catalog) map[string]bool {
	out := map[string]bool{}
	for _, aid := range st.Apps.Keys() {
		if _, inCat := cat.Apps[aid]; !inCat {
			continue
		}
		e, _ := st.Apps.Get(aid)
		if Disposition(e) == "enabled" {
			out[aid] = true
		}
	}
	return out
}

// truthy is Python truth: None, False, 0, "", [] and {} are false.
func truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case bool:
		return t
	case int64:
		return t != 0
	case int:
		return t != 0
	case float64:
		return t != 0
	case string:
		return t != ""
	case []any:
		return len(t) > 0
	case *yamlish.Map:
		return t.Len() > 0
	}
	return true
}

// pyRepr is repr() for the scalars a state file holds — used in FATAL text.
func pyRepr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case string:
		return "'" + t + "'"
	default:
		return pyStr(v)
	}
}

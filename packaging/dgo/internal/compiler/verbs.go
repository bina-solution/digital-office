package compiler

import (
	"fmt"
	"io"
	"sort"
	"strings"
)

// loadAndValidate is what reconcile.py's main() does before every verb that is not an early one:
// the catalog, the state (ensure_state's side effects included), then validate(cat) — printing
// "MANIFEST VALIDATION FAILED:" and each error, and refusing, when a manifest is wrong.
func loadAndValidate(repo string, stdout, stderr io.Writer) (*Catalog, *State, map[string][]string, int) {
	cat, err := LoadCatalog(repo)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return nil, nil, nil, 1
	}
	st, err := LoadState(repo, stdout, stderr)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return nil, nil, nil, 1
	}
	errs, provided, err := Validate(repo, cat)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return nil, nil, nil, 1
	}
	if len(errs) > 0 {
		fmt.Fprintln(stdout, "MANIFEST VALIDATION FAILED:")
		for _, e := range errs {
			fmt.Fprintln(stdout, "  -", e)
		}
		return nil, nil, nil, 1
	}
	return cat, st, provided, 0
}

// ValidateVerb is `reconcile.py validate`: the OK line with every provided capability, or the
// failure list and exit 1.
func ValidateVerb(repo string, stdout, stderr io.Writer) int {
	cat, _, provided, code := loadAndValidate(repo, stdout, stderr)
	if code != 0 {
		return code
	}
	caps := make([]string, 0, len(provided))
	for c := range provided {
		caps = append(caps, c)
	}
	sort.Strings(caps)
	joined := strings.Join(caps, ", ")
	if joined == "" {
		joined = "(none)"
	}
	fmt.Fprintf(stdout, "OK — %d manifest(s) valid; capabilities: %s\n", len(cat.Apps), joined)
	return 0
}

// EnabledApps is `reconcile.py enabled-apps`: "<root> <id>" per app the platform should be running,
// in resolve() order; every error diagnostic as "  ERROR …" on stderr and exit 1 when there is one.
// bbox runs each enabled app's own bring-up hook from this list without knowing a single app id.
func EnabledApps(repo string, stdout, stderr io.Writer) int {
	cat, st, _, code := loadAndValidate(repo, stdout, stderr)
	if code != 0 {
		return code
	}
	order, diags, err := Resolve(repo, cat, st, nil)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	failed := false
	for _, d := range diags {
		if d.Level == "error" {
			fmt.Fprintln(stderr, "  ERROR "+d.Msg)
			failed = true
		}
	}
	if failed {
		return 1
	}
	for _, aid := range order {
		if app := cat.Apps[aid]; app != nil {
			fmt.Fprintf(stdout, "%s %s\n", app.Root, aid)
		}
	}
	return 0
}

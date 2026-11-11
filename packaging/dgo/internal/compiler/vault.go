package compiler

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/pyval"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// ── the office's vault (DGO-1642): render_vault() and its helpers ─────────────────────────────────────
//
// The app declares what a vault holds (apps/obsidian/vault.yaml) and the compiler renders it into
// .generated/vault/: the declared documents with their sources' fingerprints, one note per enabled app, the
// inventory, the architecture diagrams and the start note — the herd's own documents only where this office
// is one of the herd. Derived and deterministic, scoped failing closed, and no secret read: reconcile.py's
// three properties, held here by the render oracle. Batch 33 gave reconcile.py this section with no Go side
// (issues/dgo-does-not-compile-the-office-vault-…yaml).

const vaultManifestRel = "apps/obsidian/vault.yaml"

// vaultManifest is _vault_manifest(): the declaration — ok false for none (no file, YAML PyYAML refuses, or a
// truthy document that is not a mapping); a falsy document is an empty one. A file that cannot be read, or is
// not UTF-8, stops (nothing catches either there); one only this reader cannot read is its gap.
func vaultManifest(repo string) (*yamlish.Map, bool, error) {
	p := joinPath(repo, vaultManifestRel)
	if !isRegular(p) {
		return nil, false, nil
	}
	text, err := readText(p)
	if err != nil {
		return nil, false, err
	}
	v, err := readYAML(p, text)
	if isGap(err) {
		return nil, false, err
	}
	if err != nil {
		return nil, false, nil
	}
	if !truthy(v) {
		return yamlish.NewMap(), true, nil
	}
	m, ok := v.(*yamlish.Map)
	return m, ok, nil
}

// Python's `\s` (a str's: Unicode spaces, \v and \x1c–\x1f too) and `\S`, not Go's ASCII ones.
var (
	herdOfficesLine = regexp.MustCompile(`^offices:` + pyval.SpaceClass + `*$`)
	herdTopLine     = regexp.MustCompile(`^[^` + pyval.SpaceClass[1:])
	herdOfficeLine  = regexp.MustCompile(`^  ([a-z0-9][a-z0-9._-]*):` + pyval.SpaceClass + `*$`)
)

// herdOfficeIDs is _herd_office_ids(): the ids under `offices:` in apps/computers/herd.yaml, read as text —
// a herd file that cannot be read answers NO.
func herdOfficeIDs(repo string) map[string]bool {
	ids := map[string]bool{}
	text, err := readEnvText(filepath.Join(repo, "apps", "computers", "herd.yaml"))
	if err != nil {
		return ids
	}
	inside := false
	for _, line := range strings.Split(text, "\n") {
		if herdOfficesLine.MatchString(line) {
			inside = true
			continue
		}
		if inside {
			if herdTopLine.MatchString(line) && !strings.HasPrefix(line, "#") {
				break // a new top-level key ends the block
			}
			if m := herdOfficeLine.FindStringSubmatch(line); m != nil {
				ids[m[1]] = true
			}
		}
	}
	return ids
}

// vaultFrontMatter is _vault_front_matter(source, sha16, body): "" for body is None.
func vaultFrontMatter(source, sha16, lines string) string {
	out := []string{"---", "generated: true", "source: " + source, "source_sha: " + sha16}
	if lines != "" {
		out = append(out, "lines: "+lines)
	}
	out = append(out, "---")
	return strings.Join(out, "\n") + "\n\n"
}

// vaultNoteFromFile is _vault_note_from_file(repo, rel)[0]: the declared source with its fingerprint — or,
// when it cannot be read, a note that says so loudly.
func vaultNoteFromFile(repo, rel string) string {
	raw, err := os.ReadFile(joinPath(repo, rel))
	if err != nil {
		return vaultFrontMatter(rel, "missing", "") + "# ⚠ המקור של הפתק הזה חסר\n\n" +
			"הכספת מצהירה על `" + rel + "` (apps/obsidian/vault.yaml), והקובץ הזה אינו בריפו.\n\n" +
			"אל תסתמך על הפתק הזה: הוא לא מעודכן. תקן את `" + vaultManifestRel + "` או את הקובץ, " +
			"והרץ `./bbox obsidian sync`.\n"
	}
	body := decodeReplace(raw)
	n := strings.Count(body, "\n")
	if !strings.HasSuffix(body, "\n") {
		n++
	}
	return vaultFrontMatter(rel, sha256Hex(raw)[:16], strconv.Itoa(n)) + body
}

func sha256Hex(b []byte) string { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }

// first16 is sha[:16] — "missing" stays itself.
func first16(s string) string { return s[:min(16, len(s))] }

// vaultApp is one row of _vault_apps_index(): an enabled app with a brief.
type vaultApp struct {
	aid, title, text, rel, sha string
	doc                        *yamlish.Map
}

// vaultAppsIndex is _vault_apps_index(cat, order): the enabled apps with a brief, in the compiler's order — a
// brief that cannot be read becomes a loud line, one that is not UTF-8 stops.
func vaultAppsIndex(cat *Catalog, order []string) ([]vaultApp, error) {
	var rows []vaultApp
	for _, aid := range order {
		app := cat.Apps[aid]
		doc := app.doc
		agent, err := dict(get(doc, "agent"), aid+": agent")
		if err != nil {
			return nil, err
		}
		rel, err := asText(either(get(agent, "context"), ""), aid+": agent.context")
		if err != nil {
			return nil, err
		}
		if rel = pyval.Strip(rel); rel == "" {
			continue
		}
		path := joinPath(app.Dir, rel)
		text, sha := "", "missing"
		body, err := readText(path)
		if derr, isDecode := err.(*dies); isDecode {
			return nil, derr
		}
		raw, rerr := os.ReadFile(path)
		if err != nil || rerr != nil {
			text = "!!! `" + aid + "` declares agent.context '" + rel + "' but the file is unreadable — the app " +
				"is installed and this note cannot tell you how to operate it."
		} else {
			text, sha = pyval.Strip(body), sha256Hex(raw)
		}
		title, err := dict(get(doc, "title"), aid+": title")
		if err != nil {
			return nil, err
		}
		rows = append(rows, vaultApp{aid, pyval.Str(either(get(title, "he"), aid)), text, rel, sha, doc})
	}
	return rows, nil
}

// vaultDiagram is one row of _vault_diagrams(): an archify source's name, title, type and repo path.
type vaultDiagram struct{ name, title, kind, rel string }

// vaultDiagrams is _vault_diagrams(repo): one row per apps/archify/diagrams/*.json that reads as JSON.
func vaultDiagrams(repo string) ([]vaultDiagram, error) {
	d := filepath.Join(repo, "apps", "archify", "diagrams")
	if fi, err := os.Stat(d); err != nil || !fi.IsDir() {
		return nil, nil
	}
	paths, _ := filepath.Glob(filepath.Join(d, "*.json"))
	sort.Strings(paths)
	var out []vaultDiagram
	for _, p := range paths {
		text, err := readText(p)
		if err != nil {
			continue // an OSError, or a UnicodeDecodeError — a ValueError, caught there too
		}
		name := filepath.Base(p)
		v, err := yamlish.LoadJSON(text)
		switch {
		case errors.Is(err, yamlish.ErrUnpairedSurrogate): // Python keeps the half character
			return nil, &gapError{name, err}
		case errors.Is(err, yamlish.ErrJSONTooDeep): // a RecursionError, which `except ValueError` lets through
			return nil, died("%s: RecursionError: %v", name, err)
		case err != nil:
			continue // a JSONDecodeError (a ValueError): skipped there
		}
		src, err := asDict(v, name)
		if err != nil {
			return nil, err
		}
		meta, err := dict(get(src, "meta"), name+": meta")
		if err != nil {
			return nil, err
		}
		stem := strings.TrimSuffix(name, ".json") // Path.stem: a file named only «.json» is its own stem
		if stem == "" {
			stem = name
		}
		title, err := asText(either(get(meta, "title"), stem), name+": meta.title")
		if err != nil {
			return nil, err
		}
		kind, err := asText(either(get(src, "diagram_type"), ""), name+": diagram_type")
		if err != nil {
			return nil, err
		}
		rel, _ := filepath.Rel(repo, p)
		out = append(out, vaultDiagram{name, pyval.Strip(title), pyval.Strip(kind), filepath.ToSlash(rel)})
	}
	return out, nil
}

// vaultLink is one (to, title) of the start note's reading order.
type vaultLink struct{ to, title string }

// vaultStartNote is _vault_start_note(): «00 - START HERE», the map of the rest.
func vaultStartNote(name, officeID string, herd, declared []vaultLink, apps []vaultApp, diagrams []vaultDiagram) string {
	who := "זו הכספת של לשכה דיגיטלית **" + name + "**"
	if officeID != "" {
		who += " (מזהה העדרי: `" + officeID + "`)"
	}
	lines := []string{
		"# 00 — מתחילים כאן",
		"",
		who + ".",
		"",
		"היא **נבנית מהריפו בכל `bbox run`** ואינה נכתבת ביד: כל פתק שכתוב בו `generated: true` בהתחלה מגיע מהמקור שכתוב בו, ומתעדכן מעצמו. אל תערוך פתקים כאלה — ערוך את המקור.",
		"",
		"## לאן כותבים אדם וסוכן",
		"",
		"| תיקייה | של מי | מה קורה לה בסינכרון |",
		"|---|---|---|",
		"| `Office/`, `Architecture/`, `Apps/`, `Herd/`, `00 - START HERE.md` | המקמפל | נכתב מחדש מהמקור |",
		"| `Notes/`, `Projects/`, `Sessions/`, `Memory/`, `_Hooks/`, `Operatives/` | שלך | לא נוגעים בה לעולם |",
		"",
		"הפתקים שמקורם נעלם אינם נמחקים: הם נשארים ומסומנים ברשימה ב-`.office/stale.txt`.",
		"",
		"## סדר הקריאה",
		"",
	}
	for i, l := range declared {
		lines = append(lines, strconv.Itoa(i+1)+". [["+l.to+"]] — "+l.title)
	}
	if len(herd) > 0 {
		lines = append(lines, "", "### העדר (המשרדים של העסק עצמו)", "")
		for _, l := range herd {
			lines = append(lines, "- [["+l.to+"]] — "+l.title)
		}
	}
	lines = append(lines, "", "## האפליקציות שמותקנות בלשכה הזו", "")
	for _, a := range apps {
		lines = append(lines, "- [[Apps/"+a.aid+".md]] — "+a.title)
	}
	if len(apps) == 0 {
		lines = append(lines, "- (אין אפליקציה עם בריף בלשכה הזו)")
	}
	if len(diagrams) > 0 {
		lines = append(lines, "", "## הארכיטקטורה, כציור", "",
			"הציורים החיים נפתחים בלשכה עצמה ב-`/a/archify/`; הפתקים כאן מפנים אליהם.", "")
		for _, d := range diagrams {
			lines = append(lines, "- [[Architecture/ציור — "+strings.TrimSuffix(d.name, ".json")+".md]] — "+d.title+" ("+d.kind+")")
		}
	}
	lines = append(lines, "", "## מה שהכספת הזו אינה מכילה", "",
		"הרשימה המלאה היא `excluded:` ב-`apps/obsidian/vault.yaml`, ו-`./bbox obsidian sync` מדפיס אותה. העיקרון: זהו תיעוד-הכוונה של הלשכה, לא ארכיון שלה — מסמכי מחקר, דוחות תאריך,תוכניות ופתקי עבודה נשארים בריפו.",
		"")
	return strings.Join(lines, "\n")
}

// pyIn is `word in v` for v = `x or []`: an item of a list, a substring of a str, a key of a mapping — and the
// TypeError for anything else.
func pyIn(word string, v any, where string) (bool, error) {
	if !truthy(v) {
		return false, nil
	}
	switch t := v.(type) {
	case string:
		return strings.Contains(t, word), nil
	case []any:
		for _, x := range t {
			if pyEqual(x, word) {
				return true, nil
			}
		}
		return false, nil
	case *yamlish.Map:
		_, ok := t.Get(word)
		return ok, nil
	}
	return false, died("%s: TypeError: argument of type '%s' is not iterable", where, pyTypeName(v))
}

// vaultLinks is the declared rows of `notes` (or `herd_docs`): each `to` gets its source's note in want. A `to`
// that is not a str is `late`: Python goes on with it and stops only at sorted(want) or `out / rel` — after
// .generated/vault/ is made, before a note is written — so the render returns it there.
func vaultLinks(repo string, rows any, where string, want map[string]string) (links []vaultLink, late, err error) {
	items, err := list(rows, where)
	if err != nil {
		return nil, nil, err
	}
	for _, item := range items {
		row, err := dict(item, where)
		if err != nil {
			return nil, nil, err
		}
		to, frm := get(row, "to"), get(row, "from")
		if !truthy(to) || !truthy(frm) {
			continue
		}
		if _, hashable := pyKey(to); !hashable { // want[to] raises at once for a list or a mapping
			return nil, nil, died("%s.to: TypeError: unhashable type: '%s'", where, pyTypeName(to))
		}
		text := vaultNoteFromFile(repo, pyval.Str(frm))
		key, kerr := asText(to, where+".to")
		if kerr != nil && late == nil {
			late = kerr
		}
		if kerr == nil {
			want[key] = text
		}
		title, err := asText(either(get(row, "title"), frm), where+".title")
		if err != nil {
			return nil, nil, err
		}
		links = append(links, vaultLink{pyval.Str(to), pyval.Strip(title)})
	}
	return links, late, nil
}

// renderVault is render_vault(cat, order): .generated/vault/ compiled from the declaration — or, without one,
// removed.
func renderVault(repo, gen string, cat *Catalog, order []string, env *dotenv) error {
	out := filepath.Join(gen, "vault")
	man, ok, err := vaultManifest(repo)
	if err != nil {
		return err
	}
	if !ok {
		if exists(out) {
			for _, p := range treeBelow(out) {
				if err := os.Remove(p); err != nil {
					return died("%v", err)
				}
			}
			if err := os.Remove(out); err != nil {
				return died("%v", err)
			}
		}
		return nil
	}
	officeID := pyval.Strip(env.value("DGO_OFFICE_ID"))
	inHerd := officeID != "" && herdOfficeIDs(repo)[officeID]
	name := pyval.Strip(env.value("DEPLOYMENT_NAME"))
	if name == "" {
		name = "office"
	}
	apps, err := vaultAppsIndex(cat, order)
	if err != nil {
		return err
	}
	diagrams, err := vaultDiagrams(repo)
	if err != nil {
		return err
	}
	want := map[string]string{}
	declared, late, err := vaultLinks(repo, get(man, "notes"), "vault.yaml: notes", want)
	if err != nil {
		return err
	}
	var herd []vaultLink
	if inHerd {
		var herdLate error
		if herd, herdLate, err = vaultLinks(repo, get(man, "herd_docs"), "vault.yaml: herd_docs", want); err != nil {
			return err
		}
		if late == nil {
			late = herdLate
		}
	}
	generated := get(man, "generated")
	has := func(word string) (bool, error) { return pyIn(word, generated, "vault.yaml: generated") }

	if yes, err := has("apps"); err != nil {
		return err
	} else if yes {
		for _, a := range apps {
			head := []string{"# " + a.title + " — `" + a.aid + "`", ""}
			caps, err := dicts(get(a.doc, "capabilities"), a.aid+": capabilities")
			if err != nil {
				return err
			}
			for _, c := range caps {
				bits := []string{"capability `" + pyval.Str(get(c, "name")) + "`"}
				if truthy(get(c, "endpoint")) {
					bits = append(bits, "→ `"+pyval.Str(get(c, "endpoint"))+"`")
				}
				head = append(head, "- "+strings.Join(bits, " · "))
			}
			aliases, err := vaultUIAliases(a)
			if err != nil {
				return err
			}
			for _, al := range aliases {
				head = append(head, "- UI: `/a/"+pyval.Str(al)+"/` על מארח הקונסול") // an f-string: str() of it
			}
			want["Apps/"+a.aid+".md"] = vaultFrontMatter("apps/"+a.aid+"/"+a.rel, first16(a.sha), "") +
				strings.Join(head, "\n") + "\n\n" + a.text + "\n"
		}
	}

	if yes, err := has("inventory"); err != nil {
		return err
	} else if yes {
		lines := []string{"# מה מותקן בלשכה הזו", "",
			"נכון להרצת הקומפילציה האחרונה: **" + strconv.Itoa(len(apps)) + "** אפליקציות עם בריף.", "",
			"| אפליקציה | שם | שכבה | הכי גבוה | דלת |", "|---|---|---|---|---|"}
		for _, a := range apps {
			caps, err := dicts(get(a.doc, "capabilities"), a.aid+": capabilities")
			if err != nil {
				return err
			}
			ep := "—"
			for _, c := range caps {
				if v := get(c, "endpoint"); truthy(v) {
					ep = pyval.Str(v)
					break
				}
			}
			door := "—"
			if aliases, err := vaultUIAliases(a); err != nil {
				return err
			} else if len(aliases) > 0 {
				alias, err := asText(aliases[0], a.aid+": routing.module.alias") // '/a/' + alias + '/'
				if err != nil {
					return err
				}
				door = "/a/" + alias + "/"
			}
			lines = append(lines, "| `"+a.aid+"` | "+a.title+" | "+pyval.Str(get(a.doc, "layer"))+" | "+ep+" | "+door+" |")
		}
		want["Office/מה מותקן.md"] = vaultFrontMatter("platform.state.yaml", "state", "") + strings.Join(lines, "\n") + "\n"
	}

	if yes, err := has("diagrams"); err != nil {
		return err
	} else if yes {
		for _, d := range diagrams {
			text := vaultFrontMatter(d.rel, "diagram", "") + "# " + d.title + "\n\n"
			if d.kind != "" {
				text += "סוג: `" + d.kind + "`\n\n"
			}
			text += "הציור החי: `/a/archify/` בלשכה הזו. המקור (וממה הוא נבנה) בריפו: `" + d.rel + "`.\n"
			want["Architecture/ציור — "+strings.TrimSuffix(d.name, ".json")+".md"] = text
		}
	}

	if yes, err := has("index"); err != nil {
		return err
	} else if yes {
		want["00 - START HERE.md"] = vaultFrontMatter(vaultManifestRel, "index", "") +
			vaultStartNote(name, officeID, herd, declared, apps, diagrams)
	}

	// every note, then the manifest the sync reads; a note no longer wanted leaves .generated only
	if err := mkdir(out); err != nil {
		return err
	}
	if late != nil {
		return late // a `to` that is not a str: sorted(want) / `out / rel` raises here, before any note
	}
	rels := make([]string, 0, len(want))
	for rel := range want {
		rels = append(rels, rel)
	}
	sort.Strings(rels)
	notes := yamlish.NewMap()
	for _, rel := range rels {
		p := joinPath(out, rel)
		if err := mkdir(filepath.Dir(p)); err != nil {
			return err
		}
		if err := write(p, want[rel]); err != nil {
			return err
		}
		source := ""
		if lines := strings.Split(want[rel], "\n"); len(lines) > 1 {
			for _, ln := range lines[1:min(6, len(lines))] {
				if strings.HasPrefix(ln, "source: ") {
					source = strings.SplitN(ln, ": ", 2)[1]
					break
				}
			}
		}
		notes.Set(rel, ordered("source", source, "rendered_sha256", sha256Hex([]byte(want[rel]))))
	}
	for _, p := range treeBelow(out) {
		rel, _ := filepath.Rel(out, p)
		rel = filepath.ToSlash(rel)
		fi, err := os.Stat(p)
		if err != nil {
			continue
		}
		if _, wanted := want[rel]; fi.Mode().IsRegular() && !wanted && rel != ".vault-manifest.json" {
			if err := os.Remove(p); err != nil {
				return died("%v", err)
			}
		} else if fi.IsDir() {
			if entries, err := os.ReadDir(p); err == nil && len(entries) == 0 {
				if err := os.Remove(p); err != nil {
					return died("%v", err)
				}
			}
		}
	}
	return write(filepath.Join(out, ".vault-manifest.json"),
		yamlish.IndentOneSortedJSON(ordered("version", int64(1), "notes", notes))+"\n")
}

// vaultUIAliases are the aliases of an app's routes that have a module the console embeds — `module.alias`
// set and `embed` not False (a missing embed is True; 0 is not False).
func vaultUIAliases(a vaultApp) ([]any, error) {
	routes, err := list(get(a.doc, "routing"), a.aid+": routing")
	if err != nil {
		return nil, err
	}
	var out []any
	for _, item := range routes {
		r, err := asDict(item, a.aid+": routing")
		if err != nil {
			return nil, err
		}
		m, err := dict(get(r, "module"), a.aid+": routing.module")
		if err != nil {
			return nil, err
		}
		if !truthy(get(m, "alias")) {
			continue
		}
		if embed, has := m.Get("embed"); has && embed == false {
			continue
		}
		out = append(out, get(m, "alias"))
	}
	return out, nil
}

// treeBelow is every path below dir, children before their parents (sorted(dir.rglob("*"), reverse=True):
// links are not followed into).
func treeBelow(dir string) []string {
	var out []string
	_ = filepath.WalkDir(dir, func(p string, _ os.DirEntry, err error) error {
		if err == nil && p != dir {
			out = append(out, p)
		}
		return nil
	})
	sort.Sort(sort.Reverse(sort.StringSlice(out)))
	return out
}

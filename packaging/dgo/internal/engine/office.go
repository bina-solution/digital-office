package engine

import (
	"path"
	"regexp"
	"strings"
)

// The office a checkout is, as `bbox run` guards it before it brings one up (DGO-1782, DGO-1802): lib.sh's
// office_project, office_holds_data and office_unnamed, and the .env reading they stand on (_env_raw, read_env,
// read_env_value) — so `dgo engine doctor` and `plan` say the run bbox does: with no .env, a local office made
// on ANY host, refused over a checkout whose office already has data; with one, refused while it names no office.

// envRaw is lib.sh's _env_raw: the first line of .env that begins `key=`, all after its first «=», every \r out.
// (grep -E "^key=" reads the key as a regex: for a reference like ${A.} bash matches `Ax=`, this does not —
// .env keys are [A-Za-z0-9_], so the key reads as itself for every name a .env really uses.)
func envRaw(dotenv []byte, key string) string {
	for _, l := range strings.Split(string(dotenv), "\n") {
		if strings.HasPrefix(l, key+"=") {
			return strings.ReplaceAll(l[len(key)+1:], "\r", "")
		}
	}
	return ""
}

// readEnv is lib.sh's read_env: envRaw with `${NAME}` / `${NAME:-default}` resolved leftmost first, at most 20
// times; an unset or empty NAME is its default, or nothing. Each bash expansion, as bash does it:
// ${v%%"${"*} is all before the first «${», ${v#*"${"} all after it, ${rest%%\}*} all before the first «}» (the
// whole rest when there is none), ${rest#*\}} all after it (the rest unchanged when there is none).
func readEnv(dotenv []byte, key string) string {
	v := envRaw(dotenv, key)
	for i := 0; i < 20 && strings.Contains(v, "${"); i++ {
		at := strings.Index(v, "${")
		pre, rest := v[:at], v[at+2:]
		sub := rest
		if j := strings.Index(rest, "}"); j >= 0 {
			sub, rest = rest[:j], rest[j+1:]
		}
		name, def := sub, ""
		if j := strings.Index(sub, ":-"); j >= 0 {
			name, def = sub[:j], sub[j+2:]
		}
		val := envRaw(dotenv, name)
		if val == "" {
			val = def
		}
		v = pre + val + rest
	}
	return v
}

// readEnvValue is lib.sh's read_env_value: a quoted value up to its closing quote (a « #» inside kept), a bare
// one up to its first « #» (a trailing comment is not the value).
func readEnvValue(dotenv []byte, key string) string {
	v := readEnv(dotenv, key)
	if v != "" && (v[0] == '"' || v[0] == '\'') {
		q := v[:1]
		v = v[1:]
		if j := strings.Index(v, q); j >= 0 {
			v = v[:j]
		}
		return v
	}
	if j := strings.Index(v, " #"); j >= 0 {
		v = v[:j]
	}
	return v
}

// officeUnnamed is lib.sh's office_unnamed: BUSINESS_NAME empty once its blanks are out ([[:space:]]: the six
// ASCII ones, as in the C locale — under a UTF-8 locale bash also drops Unicode spaces such as U+3000, so a name
// of only those is unnamed there and named here), AND DEPLOYMENT_DOMAIN, resolved and its quotes out, beginning with «.» — every
// address derives from a slug, so with neither a name nor a slug they read `console..digital-office.co.il`.
func officeUnnamed(dotenv []byte) bool {
	n := strings.Map(func(r rune) rune {
		if strings.ContainsRune(" \t\n\v\f\r", r) {
			return -1
		}
		return r
	}, readEnvValue(dotenv, "BUSINESS_NAME"))
	if n != "" {
		return false
	}
	d := strings.NewReplacer(`"`, "", "'", "").Replace(readEnv(dotenv, "DEPLOYMENT_DOMAIN"))
	return strings.HasPrefix(d, ".")
}

var (
	projectDrop = regexp.MustCompile(`[^a-z0-9_-]`)
	projectLead = regexp.MustCompile(`^[^a-z0-9]*`)
)

// officeProject is lib.sh's office_project: COMPOSE_PROJECT_NAME as given, else the checkout's physical folder
// name lower-cased (tr: ASCII), every character but [a-z0-9_-] dropped and the leading non-alphanumerics, as
// compose normalises it — and «digital-office» when nothing is left (a folder named in Hebrew, say).
func officeProject(composeProject, physicalRoot string) string {
	pn := composeProject
	if pn == "" {
		b := []byte(path.Base(physicalRoot))
		for i, c := range b {
			if 'A' <= c && c <= 'Z' {
				b[i] = c + 'a' - 'A'
			}
		}
		pn = projectLead.ReplaceAllString(projectDrop.ReplaceAllString(string(b), ""), "")
	}
	if pn == "" {
		return "digital-office"
	}
	return pn
}

// holds is what the look knows of bbox run's question «does this checkout's office already hold data»: not
// asked (the zero value: a .env is there, or the engine does not answer yet but will), asked and answered
// (office_holds_data's 0, 1 and 2), or never reached — bbox run stops at need_docker first (no docker, nothing
// it can start).
const (
	holdsUnasked = iota
	holdsData
	holdsNothing
	holdsUnsaid
	holdsUnreached
)

// officeHoldsData is office_holds_data, its exit code: 0 the project has containers or volumes, 1 none, 2 the
// engine did not say — the engine bbox exported (need_docker) asked, its containers, then its volumes. A failed
// query is «did not say»: never an empty office.
func officeHoldsData(s System, h host, dockerHost, pn string) int {
	label := "label=com.docker.compose.project=" + pn
	c, err := h.run(s, "docker", "-H", dockerHost, "ps", "-aq", "--filter", label)
	if err != nil {
		return 2
	}
	v, err := h.run(s, "docker", "-H", dockerHost, "volume", "ls", "-q", "--filter", label)
	if err != nil {
		return 2
	}
	// "$(…)" drops the trailing newlines of each answer: whatever is left is a container or a volume
	if strings.TrimRight(c, "\n")+strings.TrimRight(v, "\n") != "" {
		return 0
	}
	return 1
}

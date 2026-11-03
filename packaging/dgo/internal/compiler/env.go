package compiler

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
)

// ── the office's .env, as render reads it ─────────────────────────────────────────────────────────
//
// render first makes every `#@derived slug` line agree with BUSINESS_NAME (sync_identity) — compose
// reads .env next, so the slug must be right before a host is rendered — and then builds hosts and
// ports from this machine's values (_envfile_value, its ${NAME} / ${NAME:-default} references
// resolved from the same file). reconcile.py reads the file again on every lookup; nothing writes it
// after sync_identity, so dotenv reads it once, after.

const derivedMarker = "#@derived slug"

var (
	envAssign  = regexp.MustCompile(`^([A-Za-z_][A-Za-z0-9_]*)=(.*)$`)
	envRef     = regexp.MustCompile(`\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}`)
	slugBreaks = regexp.MustCompile(`[^a-z0-9]+`)
	hostPort   = regexp.MustCompile(`^[A-Za-z0-9.-]+:\p{Nd}+$`) // re.fullmatch; \d is any decimal digit
)

// dotenv is this machine's .env as _envfile_value reads it: each assignment's value, the last one of
// a name winning, quotes and spaces stripped. nil vals is no .env.
type dotenv struct {
	vals map[string]string
}

// envPath is ENVFILE.
func envPath(repo string) string { return filepath.Join(repo, ".env") }

// isRegular is Path.is_file(): there, and a regular file once links are followed.
func isRegular(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.Mode().IsRegular()
}

// readEnvText is ENVFILE.read_text(encoding="utf-8", errors="replace"): bytes that are not UTF-8 read
// as U+FFFD — one per bad sequence, where CPython's decoder puts one — and universal newlines.
func readEnvText(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	var b strings.Builder
	for len(raw) > 0 {
		if utf8.Valid(raw) {
			b.Write(raw)
			break
		}
		start, end, _ := badUTF8(raw)
		b.Write(raw[:start])
		b.WriteRune(utf8.RuneError)
		raw = raw[end:]
	}
	return strings.NewReplacer("\r\n", "\n", "\r", "\n").Replace(b.String()), nil
}

// envAssignment is _env_assign: (key, value) of an assignment line, ok false for anything else.
func envAssignment(line string) (string, string, bool) {
	m := envAssign.FindStringSubmatch(line)
	if m == nil {
		return "", "", false
	}
	return m[1], m[2], true
}

// unquoteEnv is `v.strip().strip('"').strip("'")`.
func unquoteEnv(v string) string {
	return strings.Trim(strings.Trim(pyval.Strip(v), `"`), "'")
}

// readDotenv reads .env for the lookups: no file (or not a regular one) is no values; one that cannot
// be read is where Python raises.
func readDotenv(repo string) (*dotenv, error) {
	path := envPath(repo)
	if !isRegular(path) {
		return &dotenv{}, nil
	}
	text, err := readEnvText(path)
	if err != nil {
		return nil, died(".env: %v", err)
	}
	vals := map[string]string{}
	for _, ln := range strings.Split(text, "\n") {
		if k, v, ok := envAssignment(ln); ok {
			vals[k] = unquoteEnv(v)
		}
	}
	return &dotenv{vals: vals}, nil
}

// value is _envfile_value(name): its value with every ${NAME} / ${NAME:-default} resolved from the
// same file, at most twenty times (a reference to itself ends there), and what is still a reference
// then given its default or nothing — "" where Python answers None or "" (no caller tells them apart).
func (e *dotenv) value(name string) string {
	val, ok := e.vals[name]
	if !ok {
		return ""
	}
	for i := 0; i < 20; i++ {
		m := envRef.FindStringSubmatchIndex(val)
		if m == nil {
			break
		}
		val = val[:m[0]] + either(e.vals[val[m[2]:m[3]]], group(val, m, 2)).(string) + val[m[1]:]
	}
	return envRef.ReplaceAllStringFunc(val, func(ref string) string {
		return group(ref, envRef.FindStringSubmatchIndex(ref), 2)
	})
}

// group is m.group(n) or "": a reference's default, "" when it has none.
func group(s string, m []int, n int) string {
	if m[2*n] < 0 {
		return ""
	}
	return s[m[2*n]:m[2*n+1]]
}

// here is _here(text): text with every ${NAME} / ${NAME:-default} resolved from this machine's .env,
// at most twenty times.
func (e *dotenv) here(text string) string {
	for i := 0; i < 20; i++ {
		m := envRef.FindStringSubmatchIndex(text)
		if m == nil {
			break
		}
		text = text[:m[0]] + either(e.value(text[m[2]:m[3]]), group(text, m, 2)).(string) + text[m[1]:]
	}
	return text
}

// envHere is _env_here: what a blueprint's `!Env [name, default]` is on this machine — this office's
// .env, else the fallback compiled onto the container that applies it, else the blueprint's default.
func (e *dotenv) envHere(name, def string, hostEnv map[string]string) string {
	return e.here(either(either(e.value(name), hostEnv[name]), def).(string))
}

// traefikHost is traefik_host: `${var:-fallback}` — or, where this machine's value of var carries a
// port, the host part as a literal (traefik matches Host() without the request's port).
func (e *dotenv) traefikHost(name, fallback string) string {
	if v := e.value(name); v != "" && hostPort.MatchString(v) {
		return v[:strings.LastIndex(v, ":")]
	}
	return "${" + name + ":-" + fallback + "}"
}

// domain is `_envfile_value("DEPLOYMENT_DOMAIN") or "localhost"`.
func (e *dotenv) domain() string { return either(e.value("DEPLOYMENT_DOMAIN"), "localhost").(string) }

// consolePort is _console_port(): the port of CONSOLE_BASE_URL, "" when it names none.
func (e *dotenv) consolePort() string {
	parts := strings.Split(e.value("CONSOLE_BASE_URL"), "//")
	tail := parts[len(parts)-1]
	if i := strings.LastIndex(tail, ":"); i >= 0 {
		return tail[i+1:]
	}
	return ""
}

// lanName is lan_name(order): the NAME and port this office's console has on its local network, or
// ("", "") — only while apps/lan-console is enabled; LAN_DOMAIN, else the address as a name
// (`192-168-16-100.sslip.io`, which public DNS answers with that same address). DGO-1126.
func (e *dotenv) lanName(order []string) (string, string) {
	if !contains(order, "lan-console") {
		return "", ""
	}
	addr := pyval.Strip(e.value("LAN_ADDRESS"))
	name := pyval.Strip(e.value("LAN_DOMAIN"))
	if name == "" && addr != "" {
		name = strings.ReplaceAll(addr, ".", "-") + ".sslip.io"
	}
	if name == "" {
		return "", ""
	}
	return name, pyval.Strip(either(e.value("LAN_PORT"), "8080").(string))
}

// slugify is slugify(): "Bina Solutions Ltd." → "bina-solutions-ltd".
func slugify(name string) string {
	return strings.Trim(slugBreaks.ReplaceAllString(pyLower(pyval.Strip(name)), "-"), "-")
}

// syncIdentity is sync_identity(): every `#@derived slug` line of .env set to slugify(BUSINESS_NAME),
// and COMPANY_SLUG planted under BUSINESS_NAME when no marked line names it — written only when a value
// changes, and said on stderr. Nothing happens without a .env, a BUSINESS_NAME, or a name that
// slugifies to something.
//
// reconcile.py means to keep a CRLF file's line endings, but read_text has already read every ending
// as \n by then (universal newlines): a file it rewrites is written with \n endings. So is it here.
func syncIdentity(repo string, stderr io.Writer) error {
	path := envPath(repo)
	if !isRegular(path) {
		return nil
	}
	raw, err := readEnvText(path)
	if err != nil {
		return died(".env: %v", err)
	}
	lines := strings.Split(raw, "\n")
	business := ""
	for _, ln := range lines {
		if k, v, ok := envAssignment(ln); ok && k == "BUSINESS_NAME" {
			business = unquoteEnv(v)
		}
	}
	slug := slugify(business)
	if slug == "" {
		return nil
	}
	var changed []string
	haveSlugVar := false
	for i := 0; i < len(lines); i++ {
		if pyval.Strip(lines[i]) != derivedMarker || i+1 >= len(lines) {
			continue
		}
		key, val, ok := envAssignment(lines[i+1])
		if !ok { // a dangling marker (CI strips the line under it) is left alone
			continue
		}
		if key == "COMPANY_SLUG" {
			haveSlugVar = true
		}
		if val != slug {
			lines[i+1] = key + "=" + slug
			changed = append(changed, fmt.Sprintf("%s: %s -> %s", key, either(val, "(empty)"), slug))
		}
	}
	if !haveSlugVar { // compose's interpolation is ordered: the slug goes right under BUSINESS_NAME
		for i, ln := range lines {
			if k, _, ok := envAssignment(ln); ok && k == "BUSINESS_NAME" {
				lines = slices.Insert(lines, i+1, derivedMarker, "COMPANY_SLUG="+slug)
				changed = append(changed, "COMPANY_SLUG: (absent) -> "+slug+"   [inserted under BUSINESS_NAME]")
				break
			}
		}
	}
	if len(changed) == 0 {
		return nil
	}
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0o666); err != nil {
		return died(".env: %v", err)
	}
	fmt.Fprintf(stderr, "  identity  BUSINESS_NAME=%s -> slug %s\n", pyval.Repr(business), pyval.Repr(slug))
	for _, c := range changed {
		fmt.Fprintf(stderr, "  identity  .env %s\n", c)
	}
	return nil
}

// hostOf is _host_of(url): `host[:port]` of a URL or of a bare host, lowered.
func hostOf(url string) string {
	if _, after, ok := strings.Cut(url, "//"); ok {
		url = after
	}
	url, _, _ = strings.Cut(url, "/")
	return pyLower(pyval.Strip(url))
}

// baseURLEnv is base_url_env(): machine → MACHINE_BASE_URL, any-concurrency → ANY_CONCURRENCY_BASE_URL.
func baseURLEnv(appID string) string {
	return strings.ReplaceAll(pyUpper(appID), "-", "_") + "_BASE_URL"
}

// pyUpper is str.upper() of an app id. Python's full case mapping expands 102 characters (ß is SS,
// the ligatures) that Go's maps to one; an id is its directory's name, which the schema spells
// [a-z][a-z0-9-] — ASCII, where the two agree.
func pyUpper(s string) string { return strings.ToUpper(s) }

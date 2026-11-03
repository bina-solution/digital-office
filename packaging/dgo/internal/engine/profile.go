package engine

import (
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

// floor is select-profile.py's FLOOR, the answer when nothing fits: under-sizing costs speed,
// over-sizing is what took a host down 42 times.
const floor = "ci-small"

// envelope is one profile's `requires:` — the machine it needs — and its host_mem, how much of that
// machine it asks for. sized: it declares the envelope at all.
type envelope struct {
	name                string
	sized               bool
	cores, mem, hostMem float64
}

var (
	requiresRE = regexp.MustCompile(`^\s*requires:\s*\{(.+?)\}`)
	coresRE    = regexp.MustCompile(`cores:\s*([0-9.]+)`)
	memGBRE    = regexp.MustCompile(`mem_gb:\s*([0-9.]+)`)
	hostMemRE  = regexp.MustCompile(`^\s*host_mem:\s*([0-9.]+)\s*G`)
)

// envelopes is select-profile.py's parse_profiles, line for line. It is deliberately not a YAML
// reader — the script runs before any venv exists and reads two keys by their lines — so its
// answers are the line reading's, corners included: a profile named `on` is "on", a tab-indented body
// is read, a block-style `requires:` is not. dgo reads the file the same way, so it answers the same
// (TestProfileMatchesSelectProfilePy, corners and all); a number float() refuses is no answer there,
// and an error here.
func envelopes(yml []byte) ([]envelope, error) {
	var out []envelope
	at := map[string]int{}
	cur := -1
	for _, raw := range strings.Split(strings.ReplaceAll(string(yml), "\r\n", "\n"), "\n") {
		body := strings.TrimLeftFunc(raw, unicode.IsSpace)
		if strings.HasPrefix(body, "#") {
			continue
		}
		line, _, _ := strings.Cut(raw, "#")
		if line = strings.TrimRightFunc(line, unicode.IsSpace); strings.TrimSpace(line) == "" {
			continue
		}
		if len(body) == len(raw) && strings.HasSuffix(line, ":") { // indent 0: a profile — again, it starts over
			name := strings.TrimRight(strings.TrimSpace(line), ":")
			if i, seen := at[name]; seen {
				out[i], cur = envelope{name: name}, i
			} else {
				at[name], cur, out = len(out), len(out), append(out, envelope{name: name})
			}
			continue
		}
		if cur < 0 {
			continue
		}
		if r := requiresRE.FindStringSubmatch(line); r != nil {
			c, err := number(coresRE, r[1])
			g, err2 := number(memGBRE, r[1])
			if err = errors.Join(err, err2); err != nil {
				return nil, err
			}
			out[cur].sized, out[cur].cores, out[cur].mem = true, c, g
			continue
		}
		if h := hostMemRE.FindStringSubmatch(line); h != nil {
			v, err := strconv.ParseFloat(h[1], 64)
			if err != nil {
				return nil, err
			}
			out[cur].hostMem = v
		}
	}
	return out, nil
}

// number is the first match of re in s as float() reads it; 0 when there is none.
func number(re *regexp.Regexp, s string) (float64, error) {
	if m := re.FindStringSubmatch(s); m != nil {
		return strconv.ParseFloat(m[1], 64)
	}
	return 0, nil
}

// memTotal is machine_mem_gb(): MemTotal of the engine host's /proc/meminfo in GiB, 0 when it cannot
// be read. The DOCKER host's memory — the WSL VM, the Lima guest — because that is where containers
// land, never the laptop's.
func memTotal(meminfo string) float64 {
	for _, l := range strings.Split(meminfo, "\n") {
		if strings.HasPrefix(l, "MemTotal:") {
			f := strings.Fields(l)
			if len(f) < 2 {
				return 0
			}
			kb, err := strconv.ParseInt(f[1], 10, 64)
			if err != nil {
				return 0
			}
			return float64(kb) / (1024.0 * 1024.0)
		}
	}
	return 0
}

// selectProfile is select-profile.py — the one owner of "which profile does this machine get": the
// richest profile whose envelope the engine host satisfies on cores AND memory, the floor when none
// fits, and, when it cannot decide, its reason (it prints nothing and exits 1 there).
func selectProfile(yml []byte, ymlErr error, cores int, memGiB float64) (string, error) {
	if ymlErr != nil {
		return "", errors.New("select-profile: platform/profiles/perf-profiles.yml not found")
	}
	envs, err := envelopes(yml)
	if err != nil {
		return "", fmt.Errorf("select-profile: perf-profiles.yml: %v", err)
	}
	var sized []envelope
	for _, e := range envs {
		if e.sized {
			sized = append(sized, e)
		}
	}
	if len(sized) == 0 {
		return "", errors.New("select-profile: no profile declares a `requires:` envelope")
	}
	if memGiB <= 0 {
		return "", errors.New("select-profile: could not read machine memory")
	}
	var best *envelope
	for i := range sized {
		e := &sized[i]
		if float64(cores) >= e.cores && memGiB >= e.mem && (best == nil || richer(e, best)) {
			best = e
		}
	}
	if best == nil {
		return floor, nil
	}
	return best.name, nil
}

// richer is select()'s order: the larger host_mem, then the larger core need, then the name — so a
// reordered file cannot change the answer.
func richer(a, b *envelope) bool {
	if a.hostMem != b.hostMem {
		return a.hostMem > b.hostMem
	}
	if a.cores != b.cores {
		return a.cores > b.cores
	}
	return a.name > b.name
}

// profile is what ensure_perf_profile makes of .env and the selector's answer: the profile `bbox run`
// applies, whether .env already names it, and what bbox says about it, in its own words.
type profile struct {
	name      string
	set       bool
	generated bool // set by the .env ci-env.sh generates, which bbox run writes first
	said      []string
	stop      error // no answer and nothing in .env: bbox run stops there (see pickProfile)
}

// pickProfile is ensure_perf_profile. A profile .env names is kept — said once when this machine
// would be sized otherwise; with none, the selector's answer is what bbox appends to .env.
//
// With none AND no answer, bbox means to fall back to the floor ("profile selector unavailable —
// falling back to the floor profile") and never gets there: `prof="$(python3 …select-profile.py)"`
// is a failed assignment under `set -e`, so bbox run exits on that line without a word (stderr is
// discarded). That is what bbox does, so that is what this says; TestPerfProfileMatchesBbox runs
// bbox's own function to prove it.
func pickProfile(env []byte, fit string, fitErr error, cores int) profile {
	if cur, ok := envProfile(env); ok {
		p := profile{name: cur, set: true}
		if fit != "" && fit != cur {
			p.said = []string{fmt.Sprintf("profile: %s (set in .env) — this machine (%d cores) would be sized %s; PERFORMANCE_PROFILE=%s in .env adopts it", cur, cores, fit, fit)}
		}
		return p
	}
	if fitErr != nil {
		return profile{stop: fitErr}
	}
	return profile{name: fit, said: []string{fmt.Sprintf("no PERFORMANCE_PROFILE set — sizing to this host (%d cores → %s)", cores, fit)}}
}

// envProfile is ensure_perf_profile's reading of .env: the last `PERFORMANCE_PROFILE=` line with a
// value, every quote and blank taken out of it (`tr -d "\"'[:space:]"`).
func envProfile(env []byte) (string, bool) {
	cur, found := "", false
	for _, l := range strings.Split(string(env), "\n") {
		if v, ok := strings.CutPrefix(l, "PERFORMANCE_PROFILE="); ok && v != "" {
			cur, found = strings.Map(func(r rune) rune {
				if strings.ContainsRune("\"' \t\n\v\f\r", r) {
					return -1
				}
				return r
			}, v), true
		}
	}
	return cur, found
}

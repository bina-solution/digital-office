package compiler

import (
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/pyval"
	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// ── a memory limit this machine cannot give, said at render (DGO-1797, package 7) ──────────────────────────────
// ceiling_warnings() in reconcile.py: the Dell's .env gave Ollama 9G of its 15.4 GB while the app declares 6g, and
// nothing said a word. Warnings only, for every app alike; the lines are Python's, byte for byte (the oracle).

var (
	// memSize is MEM_SIZE (docker's own reading of a size), matched whole as fullmatch does
	memSize = regexp.MustCompile(`^([0-9]+(?:\.[0-9]+)?) ?([kKmMgGtTpP])?[iI]?[bB]?$`)
	// envOnly is ENV_ONLY: a compose value that is ONE reference to .env, matched whole
	envOnly = regexp.MustCompile(`^\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?-)([^}]*))?\}$`)
	// memTotal is MemTotal's line, as re.search(…, re.M) finds it
	memTotal = regexp.MustCompile(`(?m)^MemTotal:[ \t]+([0-9]+) kB$`)
	// memInfo is MEMINFO: where the machine says how much memory it has (a test points it elsewhere)
	memInfo = "/proc/meminfo"
	// limit62 is 2 ** 62, past which a size is not one (Python's bound, so the two never part on overflow)
	limit62 = new(big.Int).Lsh(big.NewInt(1), 62)
)

// hostSharePct is HOST_SHARE_PCT: one service may take this share of the machine's memory before render says so.
const hostSharePct = 50

// memBytes is _mem_bytes(v): a memory size as docker reads it, in bytes, exactly — or nil for what is not one.
func memBytes(v any) *big.Int {
	switch x := v.(type) {
	case bool:
		return nil
	case int64:
		if n := big.NewInt(x); n.Sign() >= 0 && n.Cmp(limit62) < 0 {
			return n
		}
		return nil
	case string:
		m := memSize.FindStringSubmatch(x)
		if m == nil {
			return nil
		}
		whole, frac, _ := strings.Cut(m[1], ".")
		unit := strings.ToLower(m[2])
		if unit == "" {
			unit = "_"
		}
		mult := new(big.Int).Exp(big.NewInt(1024), big.NewInt(int64(strings.Index("_kmgtp", unit))), nil)
		n, _ := new(big.Int).SetString(whole, 10)
		n.Mul(n, mult)
		if frac != "" {
			f, _ := new(big.Int).SetString(frac, 10)
			f.Mul(f, mult)
			f.Quo(f, new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(len(frac))), nil))
			n.Add(n, f)
		}
		if n.Cmp(limit62) >= 0 {
			return nil
		}
		return n
	}
	return nil
}

// hostMemBytes is _host_mem_bytes(): the machine's MemTotal in bytes, or nil where there is none.
func hostMemBytes() *big.Int {
	raw, err := os.ReadFile(memInfo)
	if err != nil {
		return nil
	}
	m := memTotal.FindStringSubmatch(decodeReplace(raw))
	if m == nil {
		return nil
	}
	n, _ := new(big.Int).SetString(m[1], 10)
	n.Mul(n, big.NewInt(1024))
	if n.Sign() <= 0 || n.Cmp(limit62) >= 0 {
		return nil
	}
	return n
}

// ceilingWarnings is ceiling_warnings(cat, order): the warnings of a memory limit an .env sets too high, every
// enabled app's own compose in order — above the memory its APP declares, or above hostSharePct % of this machine.
// Only what an .env sets (a compose's own figure is G30's). A compose this reader cannot read where PyYAML can is
// its gap; a service named by anything but a string is not read, as reconcile.py skips it.
func ceilingWarnings(repo string, cat *Catalog, order []string, env *dotenv) ([]string, error) {
	total := hostMemBytes()
	var out []string
	for _, aid := range order {
		app := cat.Apps[aid]
		comp := get(app.doc, "compose")
		if !truthy(comp) {
			continue
		}
		rel, err := checkoutPath(repo, app.Dir, comp, aid+": compose")
		if err != nil {
			return nil, err
		}
		doc, err := loadYAML(filepath.Join(repo, filepath.FromSlash(rel)))
		if isGap(err) {
			return nil, err
		}
		if err != nil {
			continue // OSError, UnicodeDecodeError or PyYAML's refusal: left to the stages that read it
		}
		m, _ := doc.(*yamlish.Map)
		services, _ := get(m, "services").(*yamlish.Map)
		if services == nil {
			continue
		}
		res, err := dict(get(app.doc, "resources"), aid+": resources")
		if err != nil {
			return nil, err
		}
		declared := get(res, "memory")
		cap := memBytes(declared)
		for _, k := range services.Keys() {
			if _, isText := services.TypedKey(k).(string); !isText {
				continue
			}
			var lim any = get(services, k)
			for _, key := range []string{"deploy", "resources", "limits", "memory"} {
				mm, ok := lim.(*yamlish.Map)
				if !ok {
					lim = nil
					break
				}
				lim = get(mm, key)
			}
			setby, effective := "", lim
			if text, ok := lim.(string); ok {
				if ref := envOnly.FindStringSubmatch(text); ref != nil {
					name, op, def := ref[1], ref[2], ref[3]
					if env.present(name) && (env.value(name) != "" || op == "-") {
						setby, effective = name, env.value(name)
					} else {
						effective = def
					}
				}
			}
			size := memBytes(effective)
			if size == nil || setby == "" {
				continue
			}
			if cap != nil && size.Cmp(cap) > 0 {
				out = append(out, fmt.Sprintf("warning: %s/%s: .env sets %s=%s, above the %s the app declares "+
					"(app.json resources.memory) — the budget gates count %s", aid, k, setby, pyval.Str(effective),
					pyval.Str(declared), pyval.Str(declared)))
			}
			if total == nil {
				continue
			}
			hundred := new(big.Int).Mul(size, big.NewInt(100))
			if hundred.Cmp(new(big.Int).Mul(total, big.NewInt(hostSharePct))) <= 0 {
				continue
			}
			pct := new(big.Int).Quo(hundred, total)
			tenths := new(big.Int).Quo(new(big.Int).Mul(total, big.NewInt(10)), new(big.Int).Lsh(big.NewInt(1), 30))
			whole, rest := new(big.Int).QuoRem(tenths, big.NewInt(10), new(big.Int))
			out = append(out, fmt.Sprintf("warning: %s/%s: a memory limit of %s (%s in .env) is %s%% of this machine's "+
				"%s.%s GiB — more than %d%% for one service", aid, k, pyval.Str(effective), setby, pct, whole, rest, hostSharePct))
		}
	}
	return out, nil
}

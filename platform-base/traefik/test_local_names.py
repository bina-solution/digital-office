"""A `.localhost` name is never served to a client outside the machine (DGO-1633), run by G72.

Every app has a local twin, `<app>.localhost`, and the edge routes by the Host header alone: on 2026-11-09 a
`curl -H 'Host: supabase.localhost'` from the internet reached Supabase's gateway on Exampleu and on vps1, and
`glitchtip.localhost` answered on vps1 — apps that declare no public host at all. config/local-names.yaml
refuses every `.localhost` name to sources outside loopback and the private ranges, above every router.

This holds that file to what it must do, and enumerates every router the repo writes under a `.localhost`
name — the compose labels, and the compiler's twin in both its Python and its Go form — to prove each one is
behind it: its host is matched by the guard's pattern, it sits on an entrypoint the guard covers, and its own
priority is below the guard's. Without the file — the code before DGO-1633 — it fails. Plain Python: no YAML
package, the gate machine need not have one.

What a test of the file cannot show is the source traefik sees: over IPv6, docker's proxy hands a client on
from the bridge's own (private) address, and the guard admits it (measured on Exampleu and vps1; dgo-security).
"""
import ipaddress
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
GUARD = HERE / "config" / "local-names.yaml"

# What "the machine's own networks" means, exactly: loopback, the private ranges docker, a LAN and an engine's
# port forward use, a tailnet, and nothing routable on the internet.
PRIVATE = {"127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
           "::1/128", "fc00::/7", "fe80::/10"}
# measured outsiders of 2026-11-09 (the Mac's public address, vps1, Exampleu, a public resolver, a public v6)
# and the office's own sources (a container on traefik-network, the bridge, Lima's forward, loopback)
OUTSIDE = ["93.184.216.8", "93.184.216.5", "93.184.216.11", "8.8.8.8", "2001:4860:4860::8888"]
INSIDE = ["172.18.0.25", "172.18.0.1", "192.168.5.2", "127.0.0.1", "::1", "10.0.2.15"]
NAMES = ["supabase.localhost", "SUPABASE.LocalHost", "supabase.localhost.", "glitchtip.localhost",
         "plane.hp-laptop.localhost", "localhost"]
PUBLIC_NAMES = ["meet.exampleu.digital-office.co.il", "console.staging.digital-office.co.il", "localhost.evil.com",
                "notlocalhost", "supabase.localhost.evil.com"]
# the compiler's twin router, in both its forms (reconcile.py and its Go successor write the same text)
COMPILER = (("platform/manager/reconcile.py", r'router\("local", f"Host\(`\{host\}\.localhost`\)", "web"'),
            ("packaging/dgo/internal/compiler/routing.go", r'router\("local", "Host\(`"\+host\+"\.localhost`\)", "web"'))


def routers(text):
    """{name: {key: value}} of the file's `http.routers`, read line by line (the file's own shape)."""
    out, cur, inside = {}, None, False
    for ln in text.splitlines():
        if re.match(r"^  routers:\s*$", ln):
            inside = True
            continue
        if inside and re.match(r"^  \S", ln):
            inside = False
        if not inside:
            continue
        m = re.match(r"^    ([A-Za-z0-9_-]+):\s*$", ln)
        if m:
            cur = out.setdefault(m.group(1), {})
            continue
        m = re.match(r"^      ([A-Za-z]+):\s*(.*?)\s*$", ln)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)
    return out


def listed(value):
    return [x.strip() for x in value.strip("[] ").split(",") if x.strip()]


def middleware_ranges(text, name):
    m = re.search(rf"^    {re.escape(name)}:\n      ipAllowList:\n        sourceRange: \[(.*?)\]", text, re.M)
    return None if not m else [s.strip().strip("\"'") for s in m.group(1).split(",") if s.strip()]


def unquote(rule):
    return rule[1:-1] if len(rule) > 1 and rule[0] == rule[-1] == "'" else rule


def host_pattern(rule):
    m = re.search(r"HostRegexp\(`([^`]+)`\)", rule)
    return re.compile(m.group(1)) if m else None


def exempt(rule):
    """The ClientIP ranges the rule lets through: `&& !(ClientIP(a) || ClientIP(b) …)`."""
    m = re.search(r"&&\s*!\((.*)\)\s*$", rule)
    return set(re.findall(r"ClientIP\(`([^`]+)`\)", m.group(1))) if m else set()


def refused(rule, host, ip):
    """Does the guard's rule pick this request (and so refuse it)?"""
    pat = host_pattern(rule)
    if not pat or not pat.search(host):
        return False
    addr = ipaddress.ip_address(ip)
    return not any(addr in ipaddress.ip_network(n) for n in exempt(rule))


def repo_routers():
    """Every router the repo writes under a `.localhost` name: (where, router, host, priority, entrypoints),
    the compose files scanned, and the compiler forms that were NOT found."""
    found = []
    labels = re.compile(r"traefik\.http\.routers\.([^.\s]+)\.rule=(.*)$")
    files = sorted(list(REPO.glob("apps/*/docker-compose*.yml")) + list(REPO.glob("platform-base/*/docker-compose*.yml")))
    for f in files:
        text = f.read_text(encoding="utf-8")
        prio = {m.group(1): int(m.group(2)) for m in
                re.finditer(r"traefik\.http\.routers\.([^.\s]+)\.priority=[\"']?(\d+)", text)}
        eps = {m.group(1): m.group(2).strip().strip("\"'") for m in
               re.finditer(r"traefik\.http\.routers\.([^.\s]+)\.entrypoints=(\S+)", text)}
        for ln in text.splitlines():
            m = labels.search(ln)
            if not m:
                continue
            for raw in re.findall(r"Host\(`([^`]+)`\)", m.group(2)):
                host = re.sub(r"\$\{[A-Z0-9_]+:-([^}]*)\}", r"\1", raw)   # `${X:-link.localhost}` → its default
                if host.lower().rstrip(".").endswith("localhost"):
                    # no entrypoints label: traefik puts it on every default one (web and websecure)
                    found.append((f.relative_to(REPO).as_posix(), m.group(1), host, prio.get(m.group(1), 0),
                                  eps.get(m.group(1), "web,websecure")))
    missing = []
    for f, pat in COMPILER:
        p = REPO / f
        if p.exists() and re.search(pat, p.read_text(encoding="utf-8")):
            found.append((f, "<app>-local", "anyapp.localhost", 0, "web"))
        else:
            missing.append(f)
    return found, len(files), missing


def highest_priority():
    """The highest router priority written anywhere the offices' routers come from."""
    top = 0
    for f in list(REPO.glob("apps/*/docker-compose*.yml")) + list(REPO.glob("platform-base/*/docker-compose*.yml")) \
            + list(REPO.glob("platform-base/traefik/config/*.yaml")) + [REPO / "platform/manager/reconcile.py"]:
        if f.resolve() == GUARD.resolve() or not f.exists():
            continue
        for m in re.finditer(r"priority[=:]\s*[\"']?(\d+)", f.read_text(encoding="utf-8")):
            top = max(top, int(m.group(1)))
    return top


def check(text):
    problems = []
    rs = routers(text)
    plain = [(n, r) for n, r in rs.items() if "tls" not in r]
    tls = [(n, r) for n, r in rs.items() if "tls" in r]
    shapes = ((plain, {"web", "websecure"}, "plain HTTP on :80 and :443"), (tls, {"websecure"}, "https"))
    prio_of = {}
    for rows, want_eps, what in shapes:
        if len(rows) != 1:
            problems.append(f"{what}: {len(rows)} guard routers, not one")
            continue
        name, r = rows[0]
        if set(listed(r.get("entryPoints", ""))) != want_eps:
            problems.append(f"{name} ({what}) is on {listed(r.get('entryPoints', ''))}, not {sorted(want_eps)}")
        rule = unquote(r.get("rule", ""))
        if exempt(rule) != PRIVATE:
            problems.append(f"{name} lets through {sorted(exempt(rule))}, not exactly the machine's own ranges")
        for host in NAMES:
            for ip in OUTSIDE:
                if not refused(rule, host, ip):
                    problems.append(f"{name} serves {host} to {ip}")
            for ip in INSIDE:
                if refused(rule, host, ip):
                    problems.append(f"{name} refuses {host} to the machine's own {ip}")
        for host in PUBLIC_NAMES:
            if refused(rule, host, OUTSIDE[0]):
                problems.append(f"{name} takes the public name {host}")
        try:
            prio_of[name] = int(r.get("priority", "0"))
        except ValueError:
            prio_of[name] = 0
        if prio_of[name] <= highest_priority():
            problems.append(f"{name} has priority {prio_of[name]}; a router the offices compile reaches "
                            f"{highest_priority()}")
        mws = listed(r.get("middlewares", ""))
        if len(mws) != 1 or middleware_ranges(text, mws[0]) != ["255.255.255.255/32"]:
            problems.append(f"{name} must end in a middleware that admits nobody, got {mws}")
    if any("certResolver" in ln.split("#", 1)[0] for ln in text.splitlines()):
        problems.append("the guard names a certResolver: a `.localhost` name asks Let's Encrypt for nothing")
    if problems:
        return problems
    rule = unquote(plain[0][1]["rule"])
    floor = min(prio_of.values())
    found, scanned, missing = repo_routers()
    for f in missing:
        problems.append(f"{f}: the compiler's `.localhost` twin is not where this test looks — the scan is blind")
    if len(found) < 20:
        problems.append(f"only {len(found)} `.localhost` routers found in {scanned} compose files — the scan is blind")
    for where, name, host, prio, eps in found:
        if not refused(rule, host, OUTSIDE[0]):
            problems.append(f"{where}: router {name} ({host}) is not matched by the guard")
        if prio >= floor:
            problems.append(f"{where}: router {name} has priority {prio}, not below the guard's {floor}")
        off = set(listed(eps)) - {"web", "websecure"}
        if off:
            problems.append(f"{where}: router {name} ({host}) is on {sorted(off)}, which the guard does not cover")
    return problems


CASES = []


def case(name):
    def wrap(fn):
        CASES.append((name, fn))
        return fn
    return wrap


def selftest(good):
    assert check(good) == [], check(good)

    @case("the code before DGO-1633: no guard at all")
    def _():
        return any("0 guard routers" in p for p in check(""))

    @case("a public range let through")
    def _():
        return any("not exactly" in p for p in check(good.replace("ClientIP(`10.0.0.0/8`)", "ClientIP(`0.0.0.0/0`)")))

    @case("https forgotten")
    def _():
        return any("https: 0 guard routers" in p for p in check(good.replace("      tls: {}\n", "")))

    @case("plain HTTP on :443 forgotten")
    def _():
        return any("is on ['web']" in p for p in check(good.replace("[web, websecure]", "[web]")))

    @case("below the routers it must shadow")
    def _():
        return any("priority 150" in p for p in check(good.replace("priority: 2000000000", "priority: 150")))

    @case("a middleware that lets someone in")
    def _():
        return any("admits nobody" in p for p in
                   check(good.replace('sourceRange: ["255.255.255.255/32"]', 'sourceRange: ["0.0.0.0/0"]')))

    @case("a pattern that misses the trailing-dot and upper-case spellings")
    def _():
        narrow = good.replace("(?i)^(.+\\.)?localhost\\.?$", "^.+\\.localhost$")
        return narrow != good and any("serves SUPABASE.LocalHost" in p for p in check(narrow))

    @case("the compiler's twin moved where the scan does not look")
    def _():
        global COMPILER
        saved = COMPILER
        COMPILER = (("platform/manager/reconcile.py", r"no such text"),) + saved[1:]
        try:
            return any("the scan is blind" in p for p in check(good))
        finally:
            COMPILER = saved

    failed = [name for name, fn in CASES if not fn()]
    assert not failed, failed
    return len(CASES)


if __name__ == "__main__":
    if not GUARD.exists():
        print(f"FAIL: {GUARD.relative_to(REPO)} is missing — every `.localhost` twin answers the internet")
        sys.exit(1)
    text = GUARD.read_text(encoding="utf-8")
    problems = check(text)
    for p in problems:
        print("FAIL:", p)
    if problems:
        sys.exit(1)
    n = selftest(text)
    found, scanned, _ = repo_routers()
    print(f"ok: {len(found)} `.localhost` routers in {scanned} compose files and the compiler's two twins are behind "
          f"the guard; outsiders refused, the machine's own sources served ({n} cases)")

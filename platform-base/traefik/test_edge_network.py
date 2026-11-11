"""The edge dials every app on the network it is on, run by the gate that runs every plane's tests (G72).

A routed container on two networks has two addresses, and traefik's docker provider, told nothing, takes
whichever its iteration over the container's networks meets first — Go's map order, chosen again at every
reload. When that is the app's private network the edge cannot reach it: the dial times out after 30 s
and the browser gets a 504, or gives up first. Measured on Exampleu's office, 2026-11-09 (DGO-1592): the
edge's access log named `http://172.21.0.3:8080` — meet-start's address on meet-net — for all five
signed-in requests since its start, 0 of them answered, and on the owner's phone the console drew
«האפליקציה לא נטענה בתוך הלשכה». An app could carry `traefik.docker.network` itself (seventeen labels in
fifteen compose files do); meet-start did not, and the next app that forgets would be the same bug. So the
edge says it once, for every container: `--providers.docker.network=<the network the edge is on>`.

This holds the two halves of that sentence together: the flag is in the edge's command, and the network
it names is one the edge is on — a default naming a network the edge is not on would send every app to an
address it cannot reach.

ONE NETWORK TO DIAL, AND THE DOOR'S (DGO-1652). The edge may sit on one more network: the internal one it
shares with its docker door (docker-socket-proxy), so that no app can reach the door at all. On Exampleu the
door had been on traefik-network, and from inside n8n it handed out the sign-in's secrets and the edge's
TLS keys (DGO-1647). Such a second network keeps the rule's point only if three things hold:
  - it is declared `internal: true` in this file, so it has no route out and nothing is published on it;
  - no routed service sits on it, so the edge never has an app's address there to pick by mistake;
  - it is not the network the edge dials.
Anything else on a second network, such as an app's private network like meet-net, is the bug of DGO-1592
again, and still fails.
"""
import pathlib
import re
import sys

COMPOSE = pathlib.Path(__file__).with_name("docker-compose.yml")


def edge_block(text):
    """The edge service's block: from `traefik-deployment:` to the next service at the same indent."""
    m = re.search(r"^(  )traefik-deployment:\n(.*?)(?=^  \S|^\S)", text, re.M | re.S)
    if not m:
        raise SystemExit("FAIL: no traefik-deployment service in " + str(COMPOSE))
    return m.group(2)


def list_under(block, key):
    """The `- item` lines directly under `    key:` (four-space service keys, as the file writes them)."""
    m = re.search(rf"^    {key}:\n((?:    - .*\n|    #.*\n)+)", block, re.M)
    if not m:
        return []
    return [ln.strip()[2:].strip() for ln in m.group(1).splitlines() if ln.strip().startswith("- ")]


def internal_networks(text):
    """The file's top-level networks declared `internal: true`."""
    m = re.search(r"^networks:\n((?:[ \t#].*\n?|\n)+)", text, re.M)
    if not m:
        return set()
    found, name = set(), None
    for ln in m.group(1).splitlines():
        head = re.match(r"^  ([A-Za-z0-9_.-]+):", ln)
        if head:
            name = head.group(1)
        elif name and re.match(r"^    internal:\s*true\b", ln):
            found.add(name)
    return found


def routed_on(text, net):
    """The routed services (traefik.enable=true) other than the edge that sit on `net`."""
    out = []
    for m in re.finditer(r"^  ([A-Za-z0-9_.-]+):\n(.*?)(?=^  \S|^\S|\Z)", text.split("\nnetworks:\n", 1)[0] + "\n", re.M | re.S):
        name, block = m.group(1), m.group(2)
        if name == "traefik-deployment":
            continue
        # a service's list may sit at any indent below its key (the door's is at six spaces)
        lm = re.search(r"^    networks:\n((?:[ ]{4,}- .*\n|[ ]{4,}#.*\n)+)", block, re.M)
        nets = [ln.strip()[2:].strip() for ln in (lm.group(1).splitlines() if lm else []) if ln.strip().startswith("- ")]
        if net in nets and re.search(r"traefik\.enable=true", block):
            out.append(name)
    return out


def check(text):
    block = edge_block(text)
    command = list_under(block, "command")
    networks = list_under(block, "networks")
    defaults = [c.split("=", 1)[1] for c in command if c.startswith("--providers.docker.network=")]
    problems = []
    if len(defaults) != 1:
        problems.append(f"the edge's command names the docker provider's network {len(defaults)} times, not once")
    if not networks:
        problems.append("the edge is on no network")
    if defaults and networks and defaults[0] not in networks:
        problems.append(f"the edge dials apps on {defaults[0]!r} but is on {networks}")
    internal = internal_networks(text)
    for net in networks:
        if defaults and net == defaults[0]:
            if net in internal:
                problems.append(f"the edge dials apps on {net!r}, an internal network")
            continue
        if net not in internal:
            problems.append(f"the edge is also on {net!r}, which is not internal: the default no longer says "
                            f"which of an app's addresses the edge can reach")
        elif routed_on(text, net):
            problems.append(f"{net!r} is internal, but routed services sit on it: {routed_on(text, net)}")
    return problems


def selftest():
    good = COMPOSE.read_text(encoding="utf-8")
    assert check(good) == [], check(good)
    # the file as it was before DGO-1592: no default — the bug this exists for
    before = good.replace("    - --providers.docker.network=traefik-network\n", "")
    assert any("0 times" in p for p in check(before)), check(before)
    # a default naming a network the edge is not on
    wrong = good.replace("--providers.docker.network=traefik-network", "--providers.docker.network=meet-net")
    assert any("dials apps on 'meet-net'" in p for p in check(wrong)), check(wrong)
    # the edge put on an app's network too: the default no longer says which address it can reach. This
    # case said «exactly one» before DGO-1652 narrowed the rule, and it fails just the same
    two = re.sub(r"(\n    networks:\n    - traefik-network\n)", r"\1    - meet-net\n", good, count=1)
    assert two != good and any("'meet-net', which is not internal" in p for p in check(two)), check(two)
    # the door's network (DGO-1652) is allowed only while it is internal…
    open_door = good.replace("  docker-api:\n    internal: true\n", "  docker-api:\n")
    assert open_door != good and any("'docker-api', which is not internal" in p for p in check(open_door)), check(open_door)
    # …and while no routed service sits on it
    routed = re.sub(r"(\n  docker-socket-proxy:\n(?:.*\n)*?    networks:\n      - docker-api\n)",
                    r"\1    labels:\n      - traefik.enable=true\n", good, count=1)
    assert routed != good and any("routed services sit on it" in p for p in check(routed)), check(routed)


if __name__ == "__main__":
    selftest()
    problems = check(COMPOSE.read_text(encoding="utf-8"))
    for p in problems:
        print("FAIL:", p)
    if problems:
        sys.exit(1)
    print("ok: the edge dials every app on traefik-network, and its only other network is its door's, internal "
          "and with no routed service (6 cases)")

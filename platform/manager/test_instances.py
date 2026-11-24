"""An app's further copies — instances («מופעים», DGO-1920) — on synthetic trees only.

    python3 platform/manager/test_instances.py          (or: python -m pytest platform/manager/test_instances.py -q)

What this holds:
  * `add` declares the row in platform.state.yaml (every comment of the file kept), enables the instance and
    generates instances/<id>/: a manifest whose every name is derived, and a compose file that is a full copy
    of the template's services — plain YAML, no compose tags (the compiler reads it) — with the app's own
    volumes renamed, the shared ones left shared, and every relative path pointed back at the template;
  * the next free key is 2, then 3; a key or title that is not one is refused before anything is written;
  * an app that cannot have instances is refused with its reason (layer 2, multi_instance: false, an
    instance of an instance, no compose, its own traefik labels);
  * the compiler's catalog reads the instance as an app (layer 3, id = folder), so the collisions it
    refuses (hosts, tiles, slugs) are its own;
  * `sync` writes again what was edited by hand, removes a folder whose row is gone, and never touches a
    folder it did not generate; `--check` writes nothing;
  * `remove` drops the row, the disposition and the folder;
  * where `docker compose` is installed, the include of template + instance compiles, with the instance's
    ports published on a port the engine picks and its depends_on renamed.
"""
import importlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import instances as inst   # noqa: E402

rc = inst.reconcile

STATE_TEXT = """# platform.state.yaml — a comment that must survive every write
schema_version: 1

apps:
  tpl:              { state: enabled, by: cli }   # the template
  chassis:          { enabled: true }

bindings: {}
"""

TPL_COMPOSE = """services:
  tpl:
    image: alpine:3.20
    build: { context: ., dockerfile: Dockerfile }
    container_name: tpl-${DEPLOYMENT_NAME:-bina-deployment}
    hostname: tpl
    environment:
      - SELF=http://tpl:3091/x
      - OTHER=http://postgres:5432
    volumes:
      - tpl_home:/data
      - ${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock
      - shared_vault:/vault
      - ./entry.sh:/entry.sh:ro
      - type: bind
        source: ${BBOX_REPO_HOST:-../../}
        target: /repo
    ports:
      - "${TPL_BIND:-127.0.0.1}:${TPL_PORT:-3091}:3091"
  tpl-desktop:
    image: alpine:3.20
    container_name: tpl-desktop-${DEPLOYMENT_NAME:-bina-deployment}
    hostname: ${DGO_BRANCH:-tpl-desktop}
    volumes:
      - type: volume
        source: tpl_home
        target: /config
        volume: { subpath: desktop }
    depends_on:
      tpl: { condition: service_started }
volumes:
  tpl_home:
  shared_vault:
"""


def _manifest(aid, layer=3, **kw):
    # the template is a hand on the office (the engine's socket, the checkout), as Claude Desktop is, so it says it
    # knows copies; test_a_copy_must_be_self_contained_or_say_so takes that word away
    m = {"id": aid, "title": {"he": "תבנית", "en": "Template"}, "layer": layer, "kind": "service",
         "version": "0.1.0", "compose": "docker-compose.yml", "multi_instance": True,
         "capabilities": [{"name": f"{aid}-agent", "type": "protocol", "interface": "agent.v1",
                           "endpoint": f"http://{aid}:3091"}],
         "contributes": {"env": {"console": {"X": "1"}}},
         "agent": {"context": "AGENT.md", "order": 4},
         "cli": {"alias": "t"},
         "routing": [{"host": "tp", "port": 3000, "auth": "sso", "service": f"{aid}-desktop",
                      "module": {"id": aid, "alias": aid, "name": "תבנית", "url": f"http://{aid}-desktop:3000/",
                                 "url_env": "TPL_URL"},
                      "sso": {"slug": aid, "display_name": "Template", "default_host": "tp.localhost",
                              "base_url_env": "TPL_BASE_URL"}}],
         "health": {"probe": {"http": f"http://{aid}:3091/v1/health"}},
         "data": {"volumes": [f"{aid}_home"], "on_uninstall": "keep"}}
    m.update(kw)
    return m


def _repo():
    d = pathlib.Path(tempfile.mkdtemp(prefix="dgo1920-"))
    (d / "apps" / "tpl").mkdir(parents=True)
    (d / "apps" / "tpl" / "app.json").write_text(json.dumps(_manifest("tpl")), encoding="utf-8")
    (d / "apps" / "tpl" / "docker-compose.yml").write_text(TPL_COMPOSE, encoding="utf-8")
    (d / "platform-base" / "chassis").mkdir(parents=True)
    (d / "platform-base" / "chassis" / "app.json").write_text(
        json.dumps(_manifest("chassis", layer=2, multi_instance=None)), encoding="utf-8")   # says nothing
    (d / "platform-base" / "chassis" / "docker-compose.yml").write_text(
        "services:\n  chassis:\n    image: alpine:3.20\n", encoding="utf-8")
    state = d / "platform.state.yaml"
    state.write_text(STATE_TEXT, encoding="utf-8")
    rc.REPO, rc.STATE, rc.GEN = d, state, d / ".generated"
    rc.BASE, rc.APPS, rc.INSTANCES = d / "platform-base", d / "apps", d / "instances"
    rc.CATALOG_ROOTS = {rc.BASE: (1, 2), rc.APPS: (3,), rc.INSTANCES: (1, 2, 3)}
    inst.REPO, inst.ROOT, inst.STATE = d, d / "instances", state
    return d


def _refused(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except inst.Refused as e:
        return str(e)
    raise AssertionError(f"{fn.__name__}{a} was not refused")


def test_add_generates_and_declares():
    d = _repo()
    iid = inst.add("tpl", title_he="תבנית שנייה", title_en="Template two", by="test")
    assert iid == "tpl-2"
    text = (d / "platform.state.yaml").read_text(encoding="utf-8")
    assert "a comment that must survive every write" in text
    assert "tpl-2:" in text and "state: enabled" in text.split("tpl-2:")[1].splitlines()[0]
    st = inst._state()
    assert st["app_instances"]["tpl-2"]["of"] == "tpl" and st["app_instances"]["tpl-2"]["key"] == "2"
    m = json.loads((d / "instances" / "tpl-2" / "app.json").read_text(encoding="utf-8"))
    assert m["id"] == "tpl-2" and m["instance_of"] == "tpl" and m["instance_key"] == "2"
    assert m["title"] == {"he": "תבנית שנייה", "en": "Template two"}
    assert "contributes" not in m and "agent" not in m
    assert m["capabilities"][0]["endpoint"] == "http://tpl-2:3091"
    r = m["routing"][0]
    assert r["host"] == "tp-2" and r["service"] == "tpl-2-desktop"
    assert r["module"]["id"] == "tpl-2" and r["module"]["alias"] == "tpl-2" and r["module"]["name"] == "תבנית שנייה"
    assert r["module"]["url"] == "http://tpl-2-desktop:3000/" and r["module"]["url_env"] == "TPL_URL_2"
    assert r["sso"] == {"slug": "tpl-2", "display_name": "Template two", "default_host": "tp-2.localhost",
                        "base_url_env": "TPL_BASE_URL_2"}
    assert m["health"]["probe"]["http"] == "http://tpl-2:3091/v1/health"
    assert m["data"]["volumes"] == ["tpl_home_2"] and m["cli"]["alias"] == "t-2"
    c = (d / "instances" / "tpl-2" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "!" not in c.split("\n", 3)[3]                                 # no compose tag: plain YAML for every reader
    doc = inst.yaml.safe_load(c)
    s, sd = doc["services"]["tpl-2"], doc["services"]["tpl-2-desktop"]
    assert set(doc["services"]) == {"tpl-2", "tpl-2-desktop"}
    assert s["image"] == "alpine:3.20" and s["build"]["context"] == "../../apps/tpl"
    assert s["container_name"] == "tpl-2-${DEPLOYMENT_NAME:-bina-deployment}"
    assert sd["container_name"] == "tpl-2-desktop-${DEPLOYMENT_NAME:-bina-deployment}"
    assert s["hostname"] == "tpl-2" and sd["hostname"] == "${DGO_BRANCH:-tpl-desktop}-2"
    assert s["environment"]["SELF"] == "http://tpl-2:3091/x"             # its own service's address, renamed
    assert s["environment"]["OTHER"] == "http://postgres:5432"           # a neighbour's address is not ours
    assert s["environment"]["DGO_INSTANCE_ID"] == "tpl-2" and s["environment"]["DGO_INSTANCE_KEY"] == "2"
    assert s["volumes"][:4] == ["tpl_home_2:/data", "${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock",
                                "shared_vault:/vault", "../../apps/tpl/entry.sh:/entry.sh:ro"]
    assert s["volumes"][4]["source"] == "${BBOX_REPO_HOST:-../..}"       # the same folder, from the instance's
    assert sd["volumes"][0]["source"] == "tpl_home_2" and sd["volumes"][0]["volume"] == {"subpath": "desktop"}
    assert s["ports"] == ["${TPL_BIND:-127.0.0.1}::3091"]                # the engine picks the host port
    assert sd["depends_on"] == {"tpl-2": {"condition": "service_started"}}
    assert set(doc["volumes"]) == {"tpl_home_2", "shared_vault"}         # the shared one declared, not renamed


def test_next_key_and_refusals():
    d = _repo()
    assert inst.add("tpl") == "tpl-2"
    assert inst.add("tpl") == "tpl-3"
    assert inst.add("tpl", key="work") == "tpl-work"
    before = (d / "platform.state.yaml").read_text(encoding="utf-8")
    assert "already exists" in _refused(inst.add, "tpl", key="work")
    assert "not a key" in _refused(inst.add, "tpl", key="Bad_Key")
    assert "not a key" in _refused(inst.add, "tpl", key="-x")
    assert "not a key" in _refused(inst.add, "tpl", key="a" * 17)
    assert "plain text" in _refused(inst.add, "tpl", title_en='bad "quote"')
    assert "layer 2" in _refused(inst.add, "chassis")
    assert "itself an instance" in _refused(inst.add, "tpl-2")
    assert "no app" in _refused(inst.add, "nothing")
    assert (d / "platform.state.yaml").read_text(encoding="utf-8") == before   # a refusal writes nothing


def test_manifest_says_no():
    d = _repo()
    p = d / "apps" / "tpl" / "app.json"
    p.write_text(json.dumps(_manifest("tpl", multi_instance=False)), encoding="utf-8")
    assert "multi_instance: false" in _refused(inst.add, "tpl")
    p.write_text(json.dumps({**_manifest("tpl"), "compose": None}), encoding="utf-8")
    assert "owns no container" in _refused(inst.add, "tpl")
    p.write_text(json.dumps(_manifest("tpl", data={"volumes": ["tpl_home"], "sql": [{"database": "tpl"}]})),
                 encoding="utf-8")
    assert "data.sql" in _refused(inst.add, "tpl")                      # a database a copy would share
    p.write_text(json.dumps(_manifest("tpl")), encoding="utf-8")
    c = d / "apps" / "tpl" / "docker-compose.yml"
    c.write_text(TPL_COMPOSE.replace("    hostname: tpl\n", "    hostname: tpl\n    labels:\n"
                                     "      - traefik.http.routers.tpl.rule=Host(`x`)\n"), encoding="utf-8")
    assert "traefik routers" in _refused(inst.add, "tpl")
    c.write_text(TPL_COMPOSE, encoding="utf-8")
    # a host folder in data.volumes (dashboard's ../../data/lan): a copy would share it, and its name is no volume
    p.write_text(json.dumps(_manifest("tpl", data={"volumes": ["tpl_home", "../../data/lan"]})), encoding="utf-8")
    assert "host folder" in _refused(inst.add, "tpl")


def test_a_copy_must_be_self_contained_or_say_so():
    """An app whose code does not know copies acts on the first one from a copy — refused, unless it says
    `multi_instance: true` (its author's word that it reads DGO_INSTANCE_ID)."""
    d = _repo()
    p, c = d / "apps" / "tpl" / "app.json", d / "apps" / "tpl" / "docker-compose.yml"
    plain = {k: v for k, v in _manifest("tpl").items() if k != "multi_instance"}
    p.write_text(json.dumps(plain), encoding="utf-8")
    assert "mounts the office itself" in _refused(inst.add, "tpl")         # the engine's socket: a second hand
    office_mounts = ("      - ${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock\n",
                     "      - type: bind\n        source: ${BBOX_REPO_HOST:-../../}\n        target: /repo\n")
    TPL = TPL_COMPOSE
    for m in office_mounts:
        TPL = TPL.replace(m, "")
    c.write_text(TPL, encoding="utf-8")
    hooks = d / "apps" / "tpl" / "hooks"
    hooks.mkdir()
    (hooks / "uninstall").write_text("#!/bin/sh\n", encoding="utf-8")       # would clear the FIRST copy's data
    assert "lifecycle hooks (hooks/uninstall)" in _refused(inst.add, "tpl")
    (hooks / "uninstall").unlink()
    (hooks / "status").write_text("#!/bin/sh\n", encoding="utf-8")          # a verb run by hand is not one
    c.write_text(TPL.replace("- shared_vault:/vault", "- ${TPL_DATA_DIR:-tpl_home}:/more"), encoding="utf-8")
    assert "${TPL_DATA_DIR}" in _refused(inst.add, "tpl")                 # .env chooses it: both copies share it
    c.write_text(TPL, encoding="utf-8")
    c.write_text(TPL.replace("- shared_vault:/vault", "- ./state:/state"), encoding="utf-8")
    assert "writes a host folder (./state)" in _refused(inst.add, "tpl")  # both copies would write it
    c.write_text(TPL.replace("- shared_vault:/vault", "- ./conf.toml:/etc/conf.toml:ro"), encoding="utf-8")
    inst._FILE_WHY.clear()
    assert "host folder" not in inst.refusal({**plain, "_dir": d / "apps" / "tpl"})   # read-only config is fine
    c.write_text(TPL.replace("    hostname: tpl\n", "    hostname: tpl\n    network_mode: host\n"), encoding="utf-8")
    assert "host's network" in _refused(inst.add, "tpl")
    c.write_text(TPL, encoding="utf-8")
    (d / "apps" / "tpl" / "Caddyfile").write_text("reverse_proxy tpl-desktop:3000\n", encoding="utf-8")
    assert "Caddyfile addresses its own service tpl-desktop" in _refused(inst.add, "tpl")
    (d / "apps" / "tpl" / "Caddyfile").write_text("PRODID:-//tpl-desktop//calendar//EN\nhttps://tpl.example.com\n",
                                               encoding="utf-8")                        # look like it, address nothing
    (d / "apps" / "tpl" / "Dockerfile").write_text("COPY x /opt/tpl/x\n", encoding="utf-8")   # a path, no address
    inst._FILE_WHY.clear()
    assert "addresses" not in inst.refusal({**plain, "_dir": d / "apps" / "tpl"})
    (d / "apps" / "tpl" / "Caddyfile").unlink()
    inst._FILE_WHY.clear()
    assert inst.add("tpl") == "tpl-2"
    (d / "apps" / "tpl" / "Caddyfile").write_text("reverse_proxy tpl-desktop:3000\n", encoding="utf-8")
    p.write_text(json.dumps(_manifest("tpl", multi_instance=True)), encoding="utf-8")
    c.write_text(TPL.replace("- shared_vault:/vault", "- ${TPL_DATA_DIR:-tpl_home}:/more"), encoding="utf-8")
    assert inst.add("tpl") == "tpl-3"                                     # the app says it knows copies
    more = inst.yaml.safe_load((d / "instances" / "tpl-3" / "docker-compose.yml").read_text(encoding="utf-8"))
    # .env may move the first copy's data; the copy's own variable, and its own volume, never point at it
    assert "${TPL_DATA_DIR_3:-tpl_home_3}:/more" in more["services"]["tpl-3"]["volumes"]


def test_a_copy_has_its_own_data_home():
    """An app that keeps its state in its own data/<app>/ (DGO-2019) is copied without saying multi_instance: the copy
    binds data/<app>-<key>/, its manifest names that home, and the old volume a copy moves from is its own."""
    d = _repo()
    p, c = d / "apps" / "tpl" / "app.json", d / "apps" / "tpl" / "docker-compose.yml"
    plain = {k: v for k, v in _manifest("tpl").items() if k != "multi_instance"}
    plain["data"] = {"volumes": [], "paths": ["data/tpl/home", "data/tpl"],
                     "moved_from": {"data/tpl/home": "tpl_home"}, "on_uninstall": "keep"}
    p.write_text(json.dumps(plain), encoding="utf-8")
    c.write_text("services:\n  tpl:\n    image: alpine:3.20\n    volumes:\n"
                 "      - ../../data/tpl/home:/data\n      - type: bind\n        source: ../../data/tpl\n"
                 "        target: /all\n      - ../../data/other/x:/peek:ro\n", encoding="utf-8")
    assert inst.add("tpl") == "tpl-2"
    m = json.loads((d / "instances" / "tpl-2" / "app.json").read_text(encoding="utf-8"))
    assert m["data"]["paths"] == ["data/tpl-2/home", "data/tpl-2"]
    assert m["data"]["moved_from"] == {"data/tpl-2/home": "tpl_home_2"}
    s = inst.yaml.safe_load((d / "instances" / "tpl-2" / "docker-compose.yml").read_text(encoding="utf-8"))
    v = s["services"]["tpl-2"]["volumes"]
    assert v[0] == "../../data/tpl-2/home:/data" and v[1]["source"] == "../../data/tpl-2"
    assert v[2] == "../../data/other/x:/peek:ro"                          # another app's home is not renamed
    # a host folder of its own that is NOT under data/ is still shared by both copies
    c.write_text("services:\n  tpl:\n    image: alpine:3.20\n    volumes:\n      - ./state:/state\n", encoding="utf-8")
    inst._FILE_WHY.clear()
    assert "writes a host folder (./state)" in _refused(inst.add, "tpl")
    plain["data"]["paths"] = ["data/shared"]
    p.write_text(json.dumps(plain), encoding="utf-8")
    assert "data.paths" in _refused(inst.add, "tpl")                      # a path outside its home: shared


def test_a_key_never_takes_a_name_the_office_has():
    d = _repo()
    # bina-claude --key desktop would be bina-claude-desktop: the FIRST copy's own desktop service and container
    assert "already has" in _refused(inst.add, "tpl", key="desktop")
    assert not (d / "instances").exists() or not any((d / "instances").iterdir())
    assert "tpl-desktop" not in inst._state().get("apps", {})


def test_the_block_keeps_what_comes_after_it():
    d = _repo()
    inst.add("tpl")
    s = d / "platform.state.yaml"
    s.write_text(s.read_text(encoding="utf-8") + "\n# ── this office's own record\noffice:\n  name: hp\n", encoding="utf-8")
    inst.add("tpl")
    text = s.read_text(encoding="utf-8")
    assert "# ── this office's own record\noffice:\n  name: hp\n" in text
    assert set(inst._state()["app_instances"]) == {"tpl-2", "tpl-3"} and inst._state()["office"] == {"name": "hp"}


def test_catalog_reads_the_instance():
    _repo()
    inst.add("tpl")
    cat = rc.load_catalog()
    assert cat["tpl-2"]["layer"] == 3 and cat["tpl-2"]["_dir"].name == "tpl-2"
    assert cat["tpl-2"]["_dir"].parent.name == "instances"
    assert rc.disposition(inst._state()["apps"]["tpl-2"]) == "enabled"


def test_sync_rewrites_removes_and_spares():
    d = _repo()
    inst.add("tpl")
    comp = d / "instances" / "tpl-2" / "docker-compose.yml"
    good = comp.read_text(encoding="utf-8")
    comp.write_text("edited by hand\n", encoding="utf-8")
    changed, errs = inst.sync(check=True, quiet=True)
    assert changed == ["instances/tpl-2/docker-compose.yml"] and not errs
    assert comp.read_text(encoding="utf-8") == "edited by hand\n"        # --check wrote nothing
    inst.sync(quiet=True)
    assert comp.read_text(encoding="utf-8") == good
    keep = d / "instances" / "not-mine"
    keep.mkdir()
    (keep / "notes.txt").write_text("someone's\n", encoding="utf-8")
    text = (d / "platform.state.yaml").read_text(encoding="utf-8")
    inst.write_block({})                                                  # the row is gone (by hand)
    changed, _ = inst.sync(quiet=True)
    assert "instances/tpl-2/ (removed)" in changed and not (d / "instances" / "tpl-2").exists()
    assert keep.exists()                                                  # never a folder it did not make
    assert "a comment that must survive every write" in (d / "platform.state.yaml").read_text(encoding="utf-8")
    assert text != (d / "platform.state.yaml").read_text(encoding="utf-8")
    inst.add("tpl")                                                       # a truncated state file removes nothing
    (d / "platform.state.yaml").write_text("", encoding="utf-8")
    changed, errs = inst.sync(quiet=True)
    assert not changed and "not a state file" in errs[0] and (d / "instances" / "tpl-2").exists()


def test_remove():
    d = _repo()
    inst.add("tpl")
    inst.add("tpl")
    inst.remove("tpl-2")
    st = inst._state()
    assert "tpl-2" not in st["app_instances"] and "tpl-3" in st["app_instances"]
    assert "tpl-2" not in st["apps"] and "tpl-3" in st["apps"]
    assert not (d / "instances" / "tpl-2").exists() and (d / "instances" / "tpl-3").exists()
    inst.remove("tpl-3")
    st = inst._state()
    assert "app_instances" not in st and "tpl-3" not in st["apps"]
    assert "not an instance" in _refused(inst.remove, "tpl-3")
    assert "a comment that must survive every write" in (d / "platform.state.yaml").read_text(encoding="utf-8")


def test_compose_compiles():
    if not shutil.which("docker"):
        print("  skip: no docker here")
        return
    d = _repo()
    inst.add("tpl")
    (d / "compose.yml").write_text("name: dgo1920test\ninclude:\n  - apps/tpl/docker-compose.yml\n"
                                   "  - instances/tpl-2/docker-compose.yml\n", encoding="utf-8")
    r = subprocess.run(["docker", "compose", "-f", str(d / "compose.yml"), "config", "--format", "json"],
                       capture_output=True, text=True, cwd=d, timeout=60)
    if r.returncode != 0 and "is not a docker command" in r.stderr:
        print("  skip: no compose plugin here")
        return
    assert r.returncode == 0, r.stderr
    cfg = json.loads(r.stdout)
    s = cfg["services"]
    assert set(s) == {"tpl", "tpl-desktop", "tpl-2", "tpl-2-desktop"}
    assert s["tpl-2"]["image"] == "alpine:3.20"
    assert s["tpl-2"]["build"]["context"] == s["tpl"]["build"]["context"]   # the template's own folder
    assert [p.get("published") for p in s["tpl-2"]["ports"]] in ([None], [""])
    assert s["tpl"]["ports"][0]["published"] == "3091"
    assert list(s["tpl-2-desktop"]["depends_on"]) == ["tpl-2"]
    srcs = {v["target"]: v.get("source") for v in s["tpl-2"]["volumes"]}
    first = {v["target"]: v.get("source") for v in s["tpl"]["volumes"]}
    assert srcs["/data"] == "tpl_home_2" and srcs["/vault"] == "shared_vault"
    assert srcs["/entry.sh"] == first["/entry.sh"] and srcs["/repo"] == first["/repo"]   # binds resolve the same
    assert s["tpl-2"]["environment"]["SELF"] == "http://tpl-2:3091/x"
    assert s["tpl-2"]["environment"]["OTHER"] == "http://postgres:5432"
    assert {"tpl_home", "tpl_home_2", "shared_vault"} <= set(cfg["volumes"])


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
            print(f"  ok  {name}")
    print(f"{n} passed")

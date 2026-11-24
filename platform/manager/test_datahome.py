"""The data move's decisions (DGO-2019), on synthetic trees and a faked docker.

    python3 platform/manager/test_datahome.py          (or: python -m pytest platform/manager/test_datahome.py -q)

What this holds:
  * a store is what an app's compose binds under its own data/<app>/ — never another app's home, never a tracked
    file — and its old volume is `data.moved_from`'s, named with the office's project (or the compose's `name:`);
  * each store is decided READY / MOVE / SEED / WAIT / CONFLICT, and a rolled-back update (the volume written
    after the move) is moved again — unless the folder was written too, which is never guessed;
  * on a filesystem that does not hold databases every store waits, unless .env admits it;
  * a waiting store gets its mounts back on its volume, one file per app, and an app none waits has no file;
  * `hooks/state`: a number may grow, nothing may vanish or change.
The copy itself — tar, compare, health, the app's own state — is proven against a real engine on a throwaway copy
(the item's notes, DGO-2019), not here.
"""
import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import datahome as dh   # noqa: E402

COMPOSE = """services:
  app:
    image: alpine:3.20
    volumes:
      - ../../data/app:/data
      - ../../data/other/x:/peek:ro
      - ./conf.toml:/etc/conf.toml:ro
      - shared:/shared
  app-worker:
    image: alpine:3.20
    volumes:
      - type: bind
        source: ../../data/app/cache
        target: /cache
      - ../../data/app:/data:ro
volumes:
  shared:
"""


def _tree():
    d = pathlib.Path(tempfile.mkdtemp(prefix="dgo2019-"))
    (d / "apps" / "app").mkdir(parents=True)
    (d / "apps" / "app" / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    m = {"id": "app", "compose": "docker-compose.yml",
         "data": {"paths": ["data/app", "data/app/cache"], "moved_from": {"data/app": "app_data"}}}
    m["_dir"] = d / "apps" / "app"
    dh.REPO, dh.DATA = d, d / "data"
    dh.LEDGER, dh.WAIT = d / "data" / ".moves", d / "data" / ".moves" / "wait"
    return d, {"app": m}


class Engine:
    """A faked docker: which volumes exist and hold data, which folders hold data, their fingerprints."""

    def __init__(self, vols=(), full=(), fp=None):
        self.vols, self.full, self.fp = set(vols), set(full), dict(fp or {})

    def install(self):
        dh.volume_exists = lambda v: v in self.vols
        dh.is_empty = lambda s: s not in self.full
        dh.fingerprint = lambda s: self.fp.get(s, "fp-" + s)


def test_stores_of_reads_only_its_own_home():
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    st = {s["rel"]: s for s in dh.stores_of("app", apps["app"])}
    assert set(st) == {"data/app"}                                    # never data/other, never ./conf.toml
    assert st["data/app"]["volume"] == "office_app_data" and st["data/app"]["service"] == "app"
    # a bind inside the store's folder is the store's, with its subpath (Claude Desktop's /config is home/desktop)
    assert sorted(st["data/app"]["mounts"]) == [("app", "/data", False, ""), ("app-worker", "/cache", False, "cache"),
                                                ("app-worker", "/data", True, "")]
    assert st["data/app"]["abs"] == str(d / "data" / "app")
    # data/app-logs is another app's home (a name that only begins like it), and a store of its own with no old
    # volume waits in one named after it
    (d / "apps" / "app" / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app-logs:/x\n"
        "      - ../../data/app/new:/new\n", encoding="utf-8")
    st = {s["rel"]: s for s in dh.stores_of("app", apps["app"])}
    assert set(st) == {"data/app/new"} and st["data/app/new"]["volume"] == "office_dh_app_new"
    # a compose `name:` is the volume's name
    (d / "apps" / "app" / "docker-compose.yml").write_text(COMPOSE.replace("  shared:\n", "  shared:\n  app_data:\n"
                                                                          "    name: legacy_app\n"), encoding="utf-8")
    st = {s["rel"]: s for s in dh.stores_of("app", apps["app"])}
    assert st["data/app"]["volume"] == "legacy_app"


def test_decide():
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    folder = str(d / "data" / "app")
    st = next(s for s in dh.stores_of("app", apps["app"]) if s["rel"] == "data/app")
    vol = st["volume"]

    def case(engine, ledger=None, refusal=""):
        engine.install()
        p = dh.ledger_path(st)
        if p.exists():
            p.unlink()
        if ledger is not None:
            dh.write_ledger(st, ledger)
        return dh.decide(st, refusal)[0]

    assert case(Engine(vols=[vol], full=[vol])) == "MOVE"
    assert case(Engine(vols=[vol], full=[vol]), refusal="drvfs") == "WAIT"
    assert case(Engine()) == "SEED"
    assert case(Engine(), refusal="drvfs") == "WAIT"
    pathlib.Path(folder).mkdir(parents=True, exist_ok=True)
    assert case(Engine(full=[folder])) == "READY"                     # no volume left: the folder is the truth
    assert case(Engine(vols=[vol], full=[folder, vol])) == "CONFLICT"  # both hold data, nothing recorded
    moved = {"moved_at": "t", "source_fp": "fp-" + vol, "dest_fp": "fp-" + folder}
    assert case(Engine(vols=[vol], full=[folder, vol]), moved) == "READY"
    # a rollback ran on the volume after the move: moved again — the folder is untouched since
    assert case(Engine(vols=[vol], full=[folder, vol], fp={vol: "written"}), moved) == "MOVE"
    assert case(Engine(vols=[vol], full=[folder, vol], fp={vol: "written"}), moved, refusal="drvfs") == "WAIT"
    # …and the folder was written too: both moved on, never guessed
    assert case(Engine(vols=[vol], full=[folder, vol], fp={vol: "w1", folder: "w2"}), moved) == "CONFLICT"
    # a move that failed waits until someone looked (`bbox data retry`), even when the volume changed since: the app
    # writes on it every run, and each retry stops the app and copies again
    failed = {"failed": "differs", "source_fp": "fp-" + vol}
    assert case(Engine(vols=[vol], full=[vol]), failed) == "WAIT"
    assert case(Engine(vols=[vol], full=[vol], fp={vol: "new"}), failed) == "WAIT"
    # the ledger says it moved and the folder is empty now: never filled again from the old volume by itself
    assert case(Engine(vols=[vol], full=[vol]), moved) == "CONFLICT"
    # seeded, still empty, nothing behind it (MinIO's /data, never written): ready, not seeded again every run — but
    # a folder that is gone is a new store again, and an old volume with data behind it still moves
    assert case(Engine(), {"seeded_at": "t"}) == "READY"
    assert case(Engine(), {"seeded_at": "t", "image_absent": True}) == "SEED"   # made before its image: seeded again
    assert case(Engine(), {"seeded_at": "t", "seeded": "created empty (the image x is not here yet)"}) == "SEED"  # …an older record
    assert case(Engine(vols=[vol], full=[vol]), {"seeded_at": "t"}) == "MOVE"
    pathlib.Path(folder).rmdir()
    assert case(Engine(), {"seeded_at": "t"}) == "SEED"
    pathlib.Path(folder).mkdir(parents=True)


def test_fs_refusal():
    _tree()
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "9p"
        dh.os.environ.pop("DGO_DATA_FS_OK", None)
        assert "9p" in dh.fs_refusal() and "DGO-1999" in dh.fs_refusal()
        dh.os.environ["DGO_DATA_FS_OK"] = "9p"
        assert dh.fs_refusal() == ""                                  # admitted after it was proven there
        dh.os.environ.pop("DGO_DATA_FS_OK")
        dh.fs_type = lambda p: "ext4"
        assert dh.fs_refusal() == ""
    finally:
        dh.fs_type = real


def test_fs_type_reads_the_mount_table():
    assert dh.fs_type(pathlib.Path("/proc/self")) == "proc"


def test_override_per_app():
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    Engine(vols=["office_app_data"]).install()
    stores = dh.stores_of("app", apps["app"])
    dh.write_override(stores)
    doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "app.yml").read_text(encoding="utf-8"))
    assert doc["volumes"] == {"app_data": {"name": "office_app_data", "external": True}}
    by = {(s, v["target"]): v for s, spec in doc["services"].items() for v in spec["volumes"]}
    assert by[("app", "/data")] == {"type": "volume", "source": "app_data", "target": "/data"}
    assert by[("app-worker", "/data")]["read_only"] is True
    # the folder inside the store is the same subfolder of the volume it waits in
    assert by[("app-worker", "/cache")] == {"type": "volume", "source": "app_data", "target": "/cache",
                                            "volume": {"subpath": "cache"}}
    # a store with no old volume: compose makes the one it waits in, and a later run moves it like any other
    (d / "apps" / "app" / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app/new:/new\n", encoding="utf-8")
    dh.write_override(dh.stores_of("app", apps["app"]))
    doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "app.yml").read_text(encoding="utf-8"))
    assert doc["volumes"] == {"dh_app_new": {"name": "office_dh_app_new"}}
    (d / "data" / ".moves" / "wait" / "gone.yml").write_text("services: {}\n", encoding="utf-8")
    dh.write_override([])
    assert not list((d / "data" / ".moves" / "wait").glob("*.yml"))   # nothing waits: no file at all


def test_a_volume_compose_never_made_goes_by_its_whole_name():
    """The Telegram group relay ran by hand on `tg_group_relay_state` — no project's prefix, no compose label. Its
    declared store names it `external:<name>`: decided, moved and waited on by that very name; and the backup, which
    finds volumes by compose's labels, is not handed a name it cannot find."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    apps["app"]["data"]["moved_from"] = {"data/app": "external:hand.made-state"}
    Engine(vols=["hand.made-state"], full=["hand.made-state"]).install()
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "ext4"
        st = next(s for s in dh.plan(apps) if s["rel"] == "data/app")
        assert (st["volume"], st["action"]) == ("hand.made-state", "MOVE"), st
        dh.fs_type = lambda p: "9p"
        dh.write_override([s for s in dh.plan(apps) if s["action"] == "WAIT"])
        doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "app.yml").read_text(encoding="utf-8"))
        assert doc["volumes"] == {"hand_made_state": {"name": "hand.made-state", "external": True}}
        assert {"type": "volume", "source": "hand_made_state", "target": "/data"} in doc["services"]["app"]["volumes"]
    finally:
        dh.fs_type = real
    assert dh.datamoves.carried_volumes(d, "app", apps["app"]) == []
    apps["app"]["data"]["moved_from"] = {"data/app": "app_data"}
    assert dh.datamoves.carried_volumes(d, "app", apps["app"]) == ["app_data"]


def test_a_move_says_what_it_stopped_for_it_to_come_back_at_once():
    """The office's sign-in was down from the move to the run's `up`, after every hook and build — and stayed down
    when a run was cut short: ensure says what its moves stopped (the store's services and its readers'), held or
    not, and bbox brings exactly those up at once."""
    import contextlib, io
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "peek").mkdir(parents=True)
    (d / "apps" / "peek" / "docker-compose.yml").write_text(
        "services:\n  peek:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app:/seen:ro\n", encoding="utf-8")
    both = {"app": apps["app"], "peek": {"id": "peek", "compose": "docker-compose.yml", "_dir": d / "apps" / "peek"}}
    Engine(vols=["office_app_data"], full=["office_app_data"]).install()
    real = (dh.fs_type, dh.move, dh.put_aside, dh.services_of, dh.write_ledger)
    asked = []

    def services_of(names):                               # docker's labels, faked: one of ours, one made by hand
        asked.append(list(names))
        return sorted({"office-app-1": "app", "office-peek-1": "peek"}[n] for n in names if n.startswith("office-")), \
            [n for n in names if not n.startswith("office-")]

    def aside_breaks(st):
        raise OSError("no space left on device")          # a full disk fails the setting aside too
    try:
        dh.fs_type = lambda p: "ext4"
        dh.services_of, dh.put_aside = services_of, aside_breaks
        for mode in ("held", "fails", "disk full"):
            def move(st, mode=mode):
                st["_stopped"] = ["office-app-1", "office-peek-1", "relay-by-hand"]
                if mode != "held":
                    raise RuntimeError("the copy differs" if mode == "fails" else "no space left on device")
                return {}

            def full(st, rec):
                raise OSError("no space left on device")  # …and the ledger cannot be written either
            dh.move = move
            dh.write_ledger = full if mode == "disk full" else real[4]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = dh.ensure(apps=both)                 # never raises: the store waits, and what stopped comes back
            lines = out.getvalue().splitlines()
            # only what was STOPPED, by its compose service — never app-worker, which was not running
            assert "REUP app peek" in lines, (mode, out.getvalue())
            assert any("still mounting the old volume: relay-by-hand" in ln for ln in lines), out.getvalue()
            assert rc == (0 if mode == "held" else 1), (mode, rc)
            for p in (d / "data" / ".moves").rglob("*.json"):
                p.unlink()                                # each round decides afresh
        dh.write_ledger = real[4]
        assert asked[-1] == ["office-app-1", "office-peek-1", "relay-by-hand"], asked
        dh.move = lambda st: {}                           # nothing stopped: nothing to bring back
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dh.ensure(apps=both)
        assert not [ln for ln in out.getvalue().splitlines() if ln.startswith("REUP")], out.getvalue()
    finally:
        dh.fs_type, dh.move, dh.put_aside, dh.services_of, dh.write_ledger = real


def test_the_state_is_read_from_the_stores_own_service_or_not_at_all():
    """No container of the store's service running: nothing is said — never the hook's by-hand path, which measures
    the app's MAIN service (the relay's cursor read as telegram's chats, then «gone» after the move)."""
    d, apps = _tree()
    (d / "apps" / "app" / "hooks").mkdir(parents=True)
    (d / "apps" / "app" / "hooks" / "state").write_text('#!/bin/sh\necho "seen ${DGO_STATE_CONTAINER:-by-hand}"\n',
                                                        encoding="utf-8")
    st = dh.stores_of("app", apps["app"])[0]
    real = (dh.containers_of, dh.container_running)
    try:
        dh.containers_of, dh.container_running = (lambda s: []), (lambda n: True)
        assert dh.state_probe(st) == {}
        dh.containers_of = lambda s: ["office-app-1"]
        assert dh.state_probe(st) == {"seen": "office-app-1"}
    finally:
        dh.containers_of, dh.container_running = real


def test_the_no_engine_pass_keeps_what_the_run_said_of_a_volume():
    """The run asked docker and wrote `external` for a volume compose never made; `waits` (no engine, every compose
    command) must not rewrite it without — compose would warn every time, and `down -v` would take a hand-made volume."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    apps["app"]["data"]["moved_from"] = {"data/app": "external:by_hand"}
    Engine(vols=["by_hand"]).install()
    st = dh.stores_of("app", apps["app"])
    dh.write_override(st)
    dh.write_override(st, engine=False)
    doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "app.yml").read_text(encoding="utf-8"))
    assert doc["volumes"] == {"by_hand": {"name": "by_hand", "external": True}}, doc["volumes"]


def test_the_run_of_a_moving_office_holds_every_store():
    """`bbox home move` runs the office from its new folder with DGO_DATA_HOLD: every store stays on its volume — a
    move that goes back loses nothing — and the copy into data/ is the next run's (the second reader, H1)."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    Engine(vols=["office_app_data"], full=["office_app_data"]).install()
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "ext4"
        assert {s["rel"]: s["action"] for s in dh.plan(apps)}["data/app"] == "MOVE"
        dh.os.environ["DGO_DATA_HOLD"] = "1"
        st = next(s for s in dh.plan(apps) if s["rel"] == "data/app")
        assert st["action"] == "WAIT" and "bbox home move" in st["why"], st
    finally:
        dh.os.environ.pop("DGO_DATA_HOLD", None)
        dh.fs_type = real


def test_a_move_that_c_cannot_hold_waits_before_it_stops_anything():
    """Under WSL the distro's disk is a file on C:: its own free space says nothing of C:, and a full C: gives every
    volume I/O errors. The smaller of the two decides — before anything is stopped."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    st = dh.stores_of("app", apps["app"])[0]
    real = (dh.size_of, dh.windows_drive_free, dh.users_of)
    stopped = []
    try:
        dh.size_of = lambda v: 10 << 20
        dh.users_of = lambda v: stopped.append(v) or []
        # C: full, and C: with the copy's room but not the office's 20 GiB floor after it: both wait
        for c_free in (0, (10 << 20) * 2 + (5 << 30)):
            dh.windows_drive_free = lambda c_free=c_free: c_free
            try:
                dh.move(st)
            except dh.Waiting as e:
                assert "no room" in str(e), e
            else:
                raise AssertionError(f"moved with {c_free} bytes free on C:")
        assert stopped == [], stopped                  # nothing was even asked to stop
    finally:
        dh.size_of, dh.windows_drive_free, dh.users_of = real


def test_a_move_never_takes_the_disk_under_the_offices_floor():
    """Off Windows too: the old volume stays, so a move costs its store's size for good. Until DGO-2188 a move asked
    for 1 GiB to spare — vps1, with 7.9 GB free of 99, would have been left with about 1 GB after one take. What is
    left after the copy is the office's own disk floor (BBOX_DISK_MIN_GB, else 5 GiB), decided before anything stops."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    st = dh.stores_of("app", apps["app"])[0]
    real = (dh.size_of, dh.windows_drive_free, dh.users_of, dh.folder_free, dh.os.environ.get("BBOX_DISK_MIN_GB"), dh.sh)
    stopped = []
    GiB = 1 << 30

    class Went(Exception):
        pass

    def went_on(*a, **k):
        raise Went()                                   # the room check passed: the move's next step asks the engine

    try:
        dh.os.environ.pop("BBOX_DISK_MIN_GB", None)
        dh.windows_drive_free = lambda: None           # not WSL
        dh.size_of = lambda v: 1 * GiB
        dh.users_of = lambda v, **k: stopped.append(v) or []
        dh.sh = went_on                                # never the real engine: the first call after the room check ends the test's move
        # vps1's morning: 7.9 GB free. A 1 GiB store fits (1.1 + 5 <= 7.9); with 6 GiB free it would leave 4.9: waits
        for free, moves in ((int(7.9 * GiB), True), (6 * GiB, False), (int(6.2 * GiB), True), (2 * GiB, False)):
            dh.folder_free = lambda free=free: free
            del stopped[:]
            try:
                dh.move(st)
            except dh.Waiting as e:
                assert not moves, f"waited with {free / GiB:.1f} GiB free: {e}"
                assert "no room" in str(e) and "5 GiB floor" in str(e), e
                assert stopped == [], stopped          # nothing was even asked to stop
            except Went:
                assert moves, f"went on with {free / GiB:.1f} GiB free"
            else:
                raise AssertionError("move() returned without stopping anything")
        # the office's own floor decides: 20 GiB declared, and 7.9 free is no room; 0 declared is the old 1 GiB
        dh.folder_free = lambda: int(7.9 * GiB)
        dh.os.environ["BBOX_DISK_MIN_GB"] = "20"
        try:
            dh.move(st)
        except dh.Waiting as e:
            assert "20 GiB floor" in str(e), e
        else:
            raise AssertionError("moved under a declared 20 GiB floor")
        dh.os.environ["BBOX_DISK_MIN_GB"] = "0"
        dh.folder_free = lambda: int(2.2 * GiB)        # 1.1 + 1 <= 2.2
        try:
            dh.move(st)
        except Went:
            pass
        else:
            raise AssertionError("a floor of 0 did not fall back to the 1 GiB spare")
    finally:
        dh.size_of, dh.windows_drive_free, dh.users_of, dh.folder_free = real[:4]
        dh.sh = real[5]
        if real[4] is None:
            dh.os.environ.pop("BBOX_DISK_MIN_GB", None)
        else:
            dh.os.environ["BBOX_DISK_MIN_GB"] = real[4]


def test_the_image_is_named_as_compose_names_it():
    """`ghcr.io/…/forward-auth:${IMAGE_TAG:-latest}` is no image: a new store was never seeded from it, and the folder
    had the umask's mode and the bbox user's owner (the second reader). The office's value, else the default."""
    d, apps = _tree()
    (d / "apps" / "app" / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: ghcr.io/x/app:${IMAGE_TAG:-latest}\n    volumes:\n      - ../../data/app:/data\n",
        encoding="utf-8")
    keep = dh.os.environ.pop("IMAGE_TAG", None)
    try:
        assert dh.stores_of("app", apps["app"])[0]["image"] == "ghcr.io/x/app:latest"
        (d / ".env").write_text("IMAGE_TAG=v7\n", encoding="utf-8")
        assert dh.stores_of("app", apps["app"])[0]["image"] == "ghcr.io/x/app:v7"
        dh.os.environ["IMAGE_TAG"] = "v8"
        assert dh.stores_of("app", apps["app"])[0]["image"] == "ghcr.io/x/app:v8"
        # `${VAR:?message}`, as n8n's: the value alone — left raw, n8n's image was never one
        (d / "apps" / "app" / "docker-compose.yml").write_text(
            "services:\n  app:\n    image: binaos/n8n:${N8N_VERSION:?set N8N_VERSION in .env (see .env.ex)}\n"
            "    volumes:\n      - ../../data/app:/data\n", encoding="utf-8")
        (d / ".env").write_text("N8N_VERSION=2.17.4\n", encoding="utf-8")
        keep_n8n = dh.os.environ.pop("N8N_VERSION", None)          # the environment wins over .env: none here
        try:
            assert dh.stores_of("app", apps["app"])[0]["image"] == "binaos/n8n:2.17.4"
        finally:
            if keep_n8n is not None:
                dh.os.environ["N8N_VERSION"] = keep_n8n
    finally:
        dh.os.environ.pop("IMAGE_TAG", None)
        if keep is not None:
            dh.os.environ["IMAGE_TAG"] = keep


def test_every_moving_store_is_read_before_any_move_stops_its_app():
    """security's data and sensor are both measured in `security`: the first move stopped it, and the second store read
    nothing and waited a whole run. ensure reads every moving store first; move() reads fresh and takes the early read
    only when the fresh one says nothing (a minutes-old read would roll a good move back), and asks a container an
    earlier move stopped to be healthy after its own (batch D's second reader, and the engine's)."""
    import contextlib, io
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "app" / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app/a:/a\n"
        "      - ../../data/app/b:/b\n", encoding="utf-8")
    (d / "apps" / "app" / "hooks").mkdir()
    (d / "apps" / "app" / "hooks" / "state").write_text("#!/bin/sh\n", encoding="utf-8")
    m = {**apps["app"], "data": {"paths": ["data/app/a", "data/app/b"],
                                 "moved_from": {"data/app/a": "a", "data/app/b": "b"}}}
    Engine(vols=["office_a", "office_b"], full=["office_a", "office_b"]).install()
    real = (dh.fs_type, dh.move, dh.state_probe, dh.services_of, dh.size_of, dh.windows_drive_free, dh.users_of,
            dh.helper, dh.manifest, dh.write_ledger, dh.healthy, dh.SPARE, dh.sh, dh.containers_of,
            dh.container_running)
    running, seen, led, runs = [True], [], [], set()

    def move(st):
        seen.append((st["rel"], st.get("_before")))
        runs.add(id(st["_run"]))
        running[0] = False                                # the first move stops the one service both are read in
        return {}

    class Done:
        returncode, stdout = 0, b""
    try:
        dh.fs_type, dh.move = (lambda p: "ext4"), move
        dh.state_probe = lambda st: {"rows": "3"} if running[0] else {}
        dh.services_of = lambda names: ([], [])
        with contextlib.redirect_stdout(io.StringIO()):
            dh.ensure(apps={"app": m})
        assert seen == [("data/app/a", {"rows": "3"}), ("data/app/b", {"rows": "3"})], seen
        assert len(runs) == 1, runs                       # one record for the whole run, shared by every store
        # the real move(), its copy and docker faked: what it records as `before`, as the containers to be healthy
        # after, and in the run's record
        dh.move, dh.SPARE = real[1], 0                    # no room asked: the test never depends on the disk
        dh.size_of, dh.windows_drive_free = (lambda v: 0), (lambda: None)
        dh.helper, dh.sh = (lambda *a, **k: None), (lambda args, **k: Done())
        dh.manifest = lambda s, h=False: "./x|f|644|0|0|1|1|ab"
        dh.write_ledger = lambda st, rec: led.append(rec)
        dh.healthy = lambda names: {n: "healthy" for n in names}
        dh.containers_of = lambda svcs: ["office-app-1"]
        b = dh.stores_of("app", m)[1]
        run = {}
        with contextlib.redirect_stdout(io.StringIO()):
            # the first move of a run: its users are stopped, and the run's record says so
            dh.users_of = lambda v, every=False: ["office-app-1"]
            dh.state_probe, dh.container_running = (lambda st: {"rows": "3"}), (lambda n: True)
            dh.move({**b, "_run": run})
            assert run == {"office-app-1": "healthy"}, run
            # the one service it is read in was stopped by it: the early read, and that container asked after
            dh.users_of = lambda v, every=False: ["office-app-1"] if every else []
            dh.state_probe, dh.container_running = (lambda st: {}), (lambda n: False)
            dh.move({**b, "_before": {"rows": "3"}, "_run": run})
            # it answers: the fresh read, never the minutes-old one
            dh.state_probe, dh.container_running = (lambda st: {"rows": "5"}), (lambda n: True)
            dh.move({**b, "_before": {"rows": "3"}, "_run": {}})
            # it runs and says nothing now: it waits, as before — never moved on an old read
            dh.state_probe = lambda st: {}
            try:
                dh.move({**b, "_before": {"rows": "3"}, "_run": {}})
                raise AssertionError("moved on an early read while its service runs")
            except dh.Waiting:
                pass
        assert [r["before"] for r in led] == [{"rows": "3"}, {"rows": "3"}, {"rows": "5"}], led
        assert led[1]["healthy_before"] == ["office-app-1"], led[1]            # asked to be healthy after this move too
        assert led[2]["healthy_before"] == [], led[2]
    finally:
        (dh.fs_type, dh.move, dh.state_probe, dh.services_of, dh.size_of, dh.windows_drive_free, dh.users_of,
         dh.helper, dh.manifest, dh.write_ledger, dh.healthy, dh.SPARE, dh.sh, dh.containers_of,
         dh.container_running) = real


def test_a_folder_with_nothing_from_the_image_is_an_empty_volume():
    """Nothing at the target in the image: a store that was a volume is root:root 755, as docker's empty volume — never
    the unprivileged bbox user's, which security's root without capabilities cannot write. No image yet (a `build:`
    one is built at the run's `up`): a store that was a volume WAITS on it, which docker fills from the image at its
    first mount — owner included, n8n's `node` — and no folder is made. A store that was always a host folder (no
    moved_from: browser42's, written by its host hooks) is made empty, as before, and its owner is not touched."""
    d, apps = _tree()
    st = dh.stores_of("app", apps["app"])[0]
    folder = dh.stores_of("app", {**apps["app"], "data": {"paths": ["data/app"]}})[0]   # no moved_from
    real = dh.sh, dh.helper
    ran = []

    class Done:
        def __init__(self, rc, out=b""):
            self.returncode, self.stdout = rc, out

    try:
        dh.helper = lambda mounts, script, *a, **k: ran.append((mounts, script))
        dh.sh = lambda args, **k: Done(1)                        # no image, and none to pull
        plain = {**st, "mounts": [m for m in st["mounts"] if not m[3]]}            # the fixture's nested bind left out
        try:
            dh.seed({**plain, "image": "x:latest", "build": True})
            raise AssertionError("a store that was a volume was seeded with no image to seed it from")
        except dh.Waiting as e:
            assert "not here yet" in str(e), e
        assert ran == [] and not dh.pathlib.Path(st["abs"]).exists(), (ran, st["abs"])   # no folder, nothing chowned
        # …but a mount by a subpath (the fixture's app-worker /cache) needs the folder now: docker neither makes a
        # volume's subpath nor fills it from the image — made, root:root 755, as before
        assert dh.seed({**st, "image": "x:latest", "build": True}).startswith("created empty")
        assert ran == [([(st["abs"], "/dst", False)], "chown 0:0 /dst && chmod 755 /dst")], ran
        dh.pathlib.Path(st["abs"]).rmdir()
        ran.clear()
        assert dh.seed({**folder, "image": "x:latest", "build": True}).startswith("created empty")
        assert ran == [] and dh.pathlib.Path(folder["abs"]).is_dir(), ran                 # a host folder, as before
        dh.pathlib.Path(folder["abs"]).rmdir()
        ran.clear()
        dh.sh = lambda args, **k: Done(1 if args[:2] == ["docker", "cp"] else 0, b"cid")   # nothing at the target
        assert "has nothing at" in dh.seed({**st, "image": "x:latest"})
        assert ran == [([(st["abs"], "/dst", False)], "chown 0:0 /dst && chmod 755 /dst")], ran
        ran.clear()
        assert "has nothing at" in dh.seed({**folder, "image": "x:latest"})
        assert ran == [], ran                                    # always a host folder: its owner is not ours to set
    finally:
        dh.sh, dh.helper = real


def test_a_seed_with_no_image_yet_waits_on_its_volume():
    """A new office, its app's image built at this run's `up`: ensure keeps the store on its volume (the wait file) —
    no failure, no ledger, no folder — and the next run, the volume filled by docker from the image, moves it."""
    import contextlib, io
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    Engine().install()                                    # no volume, no folder: SEED
    real = (dh.fs_type, dh.seed)
    try:
        dh.fs_type = lambda p: "ext4"

        def seed(st):
            raise dh.Waiting("its image x is not here yet: it starts on its volume")
        dh.seed = seed
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = dh.ensure(apps=apps)
        assert rc == 0, out.getvalue()                    # a wait, not a failure
        doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "app.yml").read_text(encoding="utf-8"))
        assert doc["volumes"]["app_data"]["name"] == "office_app_data", doc
        assert not dh.read_ledger(dh.stores_of("app", apps["app"])[0]), "a wait writes no ledger"
        assert "waits: its image x is not here yet" in out.getvalue(), out.getvalue()
    finally:
        dh.fs_type, dh.seed = real


def test_a_store_that_was_a_host_folder_moves_like_a_volume():
    """`moved_from: path:<folder>` (a source-tree `./storage`): the old folder stands where a volume does — its absolute
    path; decided MOVE while it holds data, SEED when it is gone, CONFLICT when the two hold one another (copied into
    itself) or the old place is a file; a store that waits is bound back to the old folder, no volume made, and to
    nothing when that folder is gone; it waits while another app binds the old folder; it is made empty, never filled
    from the image; and it is never a volume the backup carries or a restore writes."""
    d, apps = _tree()
    (d / "apps" / "app" / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app/power:/power\n", encoding="utf-8")
    m = {**apps["app"], "data": {"paths": ["data/app/power"], "moved_from": {"data/app/power": "path:data/power"}}}
    st = dh.stores_of("app", m)[0]
    old = str(d / "data" / "power")
    assert st["volume"] == old and st["volume_key"] is None and st["_from_path"], st
    (d / "data" / "power").mkdir(parents=True)
    Engine(full=[old]).install()                          # the old folder holds data; the store's is empty
    assert dh.decide(st, "")[0] == "MOVE", dh.decide(st, "")
    (d / "data" / "power").rmdir()
    assert dh.decide(st, "")[0] == "SEED", dh.decide(st, "")                 # the old folder is gone: a new store
    inside = {**st, "volume": str(d / "data" / "app")}                     # data/app → data/app/power: itself
    assert dh.decide(inside, "")[0] == "CONFLICT", dh.decide(inside, "")
    (d / "data" / "power").mkdir(parents=True)                             # waiting, it is bound back to it
    dh.write_override([{**st, "_targets": {"app": ["/power"]}}])
    (d / "data" / "power").rmdir()
    doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "app.yml").read_text(encoding="utf-8"))
    assert doc["services"]["app"]["volumes"] == [{"type": "bind", "source": old, "target": "/power"}], doc
    assert not doc.get("volumes"), doc                    # no volume: the old folder itself
    assert dh.datamoves.old_volumes(m) == [] and dh.datamoves.carried_volumes(d, "app", m) == [], "a folder is no volume"
    # a new office, its image not here yet: never waits for docker to fill it (no bind is filled from an image, and the
    # wait would make the old folder, root's, in the source tree) — made at once, its owner a host folder's
    assert st["_was_volume"] is False, st
    real = dh.sh, dh.helper
    ran = []

    class Done:
        def __init__(self, rc, out=b""):
            self.returncode, self.stdout = rc, out

    try:
        dh.helper = lambda mounts, script, *a, **k: ran.append((mounts, script))
        dh.sh = lambda args, **k: Done(1)                     # no image, and none to pull
        assert dh.seed({**st, "image": "x:latest", "build": True}).startswith("created empty")
        assert ran == [] and dh.pathlib.Path(st["abs"]).is_dir(), ran
        assert not (d / "data" / "power").exists(), "the old folder was made"
        # …and with its image here: still made empty — a bind showed the app the folder alone, never the image's files
        dh.pathlib.Path(st["abs"]).rmdir()
        calls = []
        dh.sh = lambda args, **k: calls.append(args) or Done(0, b"cid")
        assert dh.seed({**st, "image": "x:latest"}).startswith("created empty"), "seeded from the image"
        assert calls == [] and ran == [], (calls, ran)
    finally:
        dh.sh, dh.helper = real
    # a store waiting while its old folder is gone: nothing to hold — no bind of a missing path in the wait file
    dh.write_override([{**st, "_targets": {"app": ["/power"]}}])
    assert not (d / "data" / ".moves" / "wait" / "app.yml").exists(), "a missing old folder was bound"
    # the old place is a FILE: never read as missing (seeded empty, the file dropped)
    (d / "data" / "power").write_text("a password file", encoding="utf-8")
    assert dh.decide(st, "")[0] == "CONFLICT", dh.decide(st, "")
    (d / "data" / "power").unlink()
    # …or outside the DGO folder (`path:../x`, which G118 refuses): never bound read-write by a wait file
    outside = dh.stores_of("app", {**m, "data": {**m["data"], "moved_from": {"data/app/power": "path:../elsewhere"}}})[0]
    assert dh.decide(outside, "")[0] == "CONFLICT", dh.decide(outside, "")
    # a store that waits (a refused filesystem) while its old folder is gone: nothing to wait with — made and recorded
    # as a seed, so an old folder appearing later never takes the app away from the folder it writes
    import contextlib, io
    real_fs = dh.fs_type
    try:
        dh.fs_type = lambda p: "9p"
        if dh.pathlib.Path(st["abs"]).exists():
            dh.pathlib.Path(st["abs"]).rmdir()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert dh.ensure(apps={"app": {**m, "_dir": d / "apps" / "app"}}) == 0, out.getvalue()
        assert dh.pathlib.Path(st["abs"]).is_dir() and dh.read_ledger(st).get("seeded_at"), out.getvalue()
        assert not (d / "data" / ".moves" / "wait" / "app.yml").exists(), out.getvalue()
        dh.ledger_path(st).unlink()
        dh.pathlib.Path(st["abs"]).rmdir()
    finally:
        dh.fs_type = real_fs
    # another app still binds the old folder (dashboard's read of data/power): it waits until none does
    (d / "data" / "power").mkdir()
    (d / "apps" / "reader").mkdir()
    (d / "apps" / "reader" / "docker-compose.yml").write_text(
        "services:\n  r:\n    image: alpine:3.20\n    volumes:\n      - ../../data/power/sub:/p:ro\n", encoding="utf-8")
    real_fs = dh.fs_type
    try:
        dh.fs_type = lambda p: "ext4"
        Engine(full=[old]).install()
        both = {"app": {**m, "_dir": d / "apps" / "app"}, "reader": {"id": "reader", "_dir": d / "apps" / "reader"}}
        got = next(s for s in dh.plan(both) if s["rel"] == "data/app/power")
        assert got["action"] == "WAIT" and "reader/r still bind" in got["why"], (got["action"], got["why"])
        got = next(s for s in dh.plan({"app": both["app"]}) if s["rel"] == "data/app/power")
        assert got["action"] == "MOVE", (got["action"], got["why"])                     # nobody else binds it
    finally:
        dh.fs_type = real_fs


def test_waits_before_any_run_decides():
    """No engine: what compose reads between a change landing and the next `bbox run`."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "app" / "app.json").write_text(json.dumps({k: v for k, v in apps["app"].items() if k != "_dir"}),
                                                 encoding="utf-8")
    (d / ".generated").mkdir()
    (d / ".generated" / "compose.yml").write_text("include:\n  - apps/app/docker-compose.yml\n", encoding="utf-8")
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "ext4"
        dh.waits()
        doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "app.yml").read_text(encoding="utf-8"))
        assert doc["volumes"] == {"app_data": {"name": "office_app_data"}}      # undecided: on its volume
        st = dh.stores_of("app", apps["app"])[0]
        dh.write_ledger(st, {"seeded_at": "t"})
        (d / "data" / ".moves" / "wait" / "app.yml").unlink()
        dh.waits()
        assert not (d / "data" / ".moves" / "wait" / "app.yml").exists()      # decided: the folder
        dh.write_ledger(st, {"failed": "differs"})
        dh.waits()
        assert (d / "data" / ".moves" / "wait" / "app.yml").exists()          # a failed move keeps waiting
        # what a run wrote is never taken off by `waits`
        (d / "data" / ".moves" / "wait" / "other.yml").write_text("services: {}\n", encoding="utf-8")
        dh.waits()
        assert (d / "data" / ".moves" / "wait" / "other.yml").exists()
    finally:
        dh.fs_type = real


def test_a_reader_waits_with_the_store_it_reads():
    """lan-console reads forward-auth's users file: on an office that waits, it must read it where it still is — on the
    owner's volume, through the READER's own wait file (read only while the reader is compiled) — never an empty
    folder. A store nobody reads gives no reader file."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "peek").mkdir(parents=True)
    (d / "apps" / "peek" / "docker-compose.yml").write_text(
        "services:\n  peek:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app/sub:/seen:ro\n"
        "      - ../../data/peek/own:/own\n", encoding="utf-8")
    peek = {"id": "peek", "compose": "docker-compose.yml", "_dir": d / "apps" / "peek", "data": {"paths": ["data/peek/own"]}}
    Engine(vols=["office_app_data"]).install()
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "9p"
        stores = dh.plan({"app": apps["app"], "peek": peek})
        app_store = next(s for s in stores if s["rel"] == "data/app")
        assert app_store["readers"][0]["app"] == "peek"
        assert app_store["readers"][0]["mount"] == ("peek", "/seen", True, "sub")
        dh.write_override([s for s in stores if s["action"] == "WAIT"])
        w = d / "data" / ".moves" / "wait"
        doc = dh.yaml.safe_load((w / "peek.yml").read_text(encoding="utf-8"))
        seen = next(v for v in doc["services"]["peek"]["volumes"] if v["target"] == "/seen")
        assert seen == {"type": "volume", "source": "app_data", "target": "/seen", "read_only": True,
                        "volume": {"subpath": "sub"}}
        assert doc["volumes"]["app_data"]["name"] == "office_app_data"
        assert "peek" not in (dh.yaml.safe_load((w / "app.yml").read_text(encoding="utf-8"))["services"])
    finally:
        dh.fs_type = real


def test_a_targeted_run_never_moves_what_it_only_reads():
    """`bbox run lan-console` must not move forward-auth's store: it would stop the sign-in and only bring up the
    reader. And `bbox run forward-auth` moves it only when every service that uses it comes up with it."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "peek").mkdir(parents=True)
    (d / "apps" / "peek" / "docker-compose.yml").write_text(
        "services:\n  peek:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app:/seen:ro\n", encoding="utf-8")
    peek = {"id": "peek", "compose": "docker-compose.yml", "_dir": d / "apps" / "peek"}
    Engine(vols=["office_app_data"], full=["office_app_data"]).install()
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "ext4"
        both = {"app": apps["app"], "peek": peek}
        whole = {s["rel"]: s["action"] for s in dh.plan(both)}
        assert whole["data/app"] == "MOVE"                                    # a whole run moves it
        reader = {s["rel"]: s["action"] for s in dh.plan(both, {"peek"})}
        assert reader["data/app"] == "WAIT"                                   # its reader alone: never
        owner = {s["rel"]: s for s in dh.plan(both, {"app", "app-worker"})}
        assert owner["data/app"]["action"] == "WAIT" and "peek" in owner["data/app"]["why"]
        assert {s["rel"]: s["action"] for s in dh.plan(both, {"app", "app-worker", "peek"})}["data/app"] == "MOVE"
    finally:
        dh.fs_type = real


def test_a_store_waits_while_another_app_mounts_its_old_volume_by_name():
    """any-concurrency mounts n8n_storage, and the agents mount obsidian_vault, by NAME: moving the store would stop them
    with nothing to start them again, or leave them writing a copy nobody reads. It waits until they bind the folder —
    whatever the short syntax's default or the volume's own `name:` says."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "peek").mkdir(parents=True)
    peek = {"id": "peek", "compose": "docker-compose.yml", "_dir": d / "apps" / "peek"}
    Engine(vols=["office_app_data"], full=["office_app_data"]).install()
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "ext4"
        for compose in ("services:\n  peek:\n    image: alpine:3.20\n    volumes:\n"
                        "      - ${PEEK_VOL:-app_data}:/seen:ro\nvolumes:\n  app_data:\n",
                        "services:\n  peek:\n    image: alpine:3.20\n    volumes:\n"
                        "      - {type: volume, source: theirs, target: /seen}\nvolumes:\n"
                        "  theirs: {external: true, name: office_app_data}\n"):
            (d / "apps" / "peek" / "docker-compose.yml").write_text(compose, encoding="utf-8")
            st = next(s for s in dh.plan({"app": apps["app"], "peek": peek}) if s["rel"] == "data/app")
            assert st["action"] == "WAIT" and "peek/peek" in st["why"], st
        (d / "apps" / "peek" / "docker-compose.yml").write_text(
            "services:\n  peek:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app:/seen:ro\n", encoding="utf-8")
        assert {s["rel"]: s["action"] for s in dh.plan({"app": apps["app"], "peek": peek})}["data/app"] == "MOVE"
    finally:
        dh.fs_type = real


def test_a_reader_of_an_app_that_is_off():
    """any-concurrency runs and n8n is off: the reader reads n8n's store on its volume, never an empty folder, and the
    store is never moved by a run that does not run its app."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "app" / "app.json").write_text(json.dumps({k: v for k, v in apps["app"].items() if k != "_dir"}),
                                                 encoding="utf-8")
    (d / "apps" / "peek").mkdir(parents=True)
    (d / "apps" / "peek" / "docker-compose.yml").write_text(
        "services:\n  peek:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app:/seen:ro\n", encoding="utf-8")
    peek = {"id": "peek", "compose": "docker-compose.yml", "_dir": d / "apps" / "peek"}
    Engine(vols=["office_app_data"], full=["office_app_data"]).install()
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "ext4"
        st = next(s for s in dh.plan({"peek": peek}) if s["rel"] == "data/app")
        assert st["action"] == "WAIT" and "off" in st["why"] and st["readers"][0]["app"] == "peek"
        dh.write_override([st])
        doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "peek.yml").read_text(encoding="utf-8"))
        assert doc["services"]["peek"]["volumes"][0]["source"] == "app_data"
    finally:
        dh.fs_type = real


def test_plan_json_has_no_internal_fields():
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    Engine(vols=["office_app_data"], full=["office_app_data"]).install()
    real_apps = dh.enabled_apps
    try:
        dh.enabled_apps = lambda: dict(apps)
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dh.main(["plan", "--json"])
        rows = json.loads(out.getvalue())
        assert rows and "readers" in rows[0] and not any(k.startswith("_") for k in rows[0])
    finally:
        dh.enabled_apps = real_apps


def test_a_stale_wait_file_is_pruned():
    """A pull renamed a reader's service between two runs: its wait file keeps nothing compose no longer has."""
    d, apps = _tree()
    w = d / "data" / ".moves" / "wait"
    w.mkdir(parents=True)
    (w / "app.yml").write_text(dh.yaml.safe_dump({
        "services": {"gone": {"volumes": [{"type": "volume", "source": "old", "target": "/x"}]},
                     "app": {"volumes": [{"type": "volume", "source": "app_data", "target": "/data"},
                                         {"type": "volume", "source": "old", "target": "/nomore"}]}},
        "volumes": {"old": {"name": "o"}, "app_data": {"name": "a"}}}), encoding="utf-8")
    (w / "lost.yml").write_text(dh.yaml.safe_dump({"services": {"lost": {"volumes": [
        {"type": "volume", "source": "v", "target": "/v"}]}}, "volumes": {"v": {"name": "v"}}}), encoding="utf-8")
    dh.prune_wait_files({"app": apps["app"], "lost": {"id": "lost", "_dir": d / "apps" / "lost"}})
    doc = dh.yaml.safe_load((w / "app.yml").read_text(encoding="utf-8"))
    assert doc == {"services": {"app": {"volumes": [{"type": "volume", "source": "app_data", "target": "/data"}]}},
                   "volumes": {"app_data": {"name": "a"}}}
    assert not (w / "lost.yml").exists()                                  # an app with no compose left: no service


def test_a_default_in_the_short_syntax_is_read():
    d, apps = _tree()
    (d / "apps" / "app" / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: alpine:3.20\n    volumes:\n      - ${X:-../../data/app/x}:/x\n", encoding="utf-8")
    assert [b[0] for b in dh.binds_of(apps["app"])[1]] == ["data/app/x"]


def test_waits_carries_the_readers_too():
    """No engine: between two runs, a reader of an undecided store is held on the owner's volume as well."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "app" / "app.json").write_text(json.dumps({k: v for k, v in apps["app"].items() if k != "_dir"}),
                                                 encoding="utf-8")
    (d / "apps" / "peek").mkdir(parents=True)
    (d / "apps" / "peek" / "docker-compose.yml").write_text(
        "services:\n  peek:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app:/seen:ro\n", encoding="utf-8")
    (d / "apps" / "peek" / "app.json").write_text(json.dumps({"id": "peek", "compose": "docker-compose.yml"}),
                                                  encoding="utf-8")
    (d / ".generated").mkdir()
    (d / ".generated" / "compose.yml").write_text(
        "include:\n  - apps/app/docker-compose.yml\n  - apps/peek/docker-compose.yml\n", encoding="utf-8")
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "ext4"
        assert dh.waits() == 0
        doc = dh.yaml.safe_load((d / "data" / ".moves" / "wait" / "peek.yml").read_text(encoding="utf-8"))
        assert doc["services"]["peek"]["volumes"] == [{"type": "volume", "source": "app_data", "target": "/seen",
                                                       "read_only": True}]
        assert doc["volumes"] == {"app_data": {"name": "office_app_data"}}
    finally:
        dh.fs_type = real


def test_same_state():
    assert dh.same_state({"rows.a": "10", "vapid": "ab"}, {"rows.a": "12", "vapid": "ab", "new": "1"}) == []
    assert dh.same_state({"rows.a": "10"}, {"rows.a": "9"}) == []           # the app ran on and deleted a row
    assert dh.same_state({"rows.a": "10"}, {"rows.a": "0"}) == ["rows.a 10 → 0"]   # it came up on an empty store
    assert dh.same_state({"rows.a": "0"}, {"rows.a": "0"}) == []
    assert dh.same_state({"vapid": "ab"}, {"vapid": "cd"}) == ["vapid 'ab' → 'cd'"]
    assert dh.same_state({"signed-in": "yes"}, {}) == ["signed-in gone (was yes)"]


def test_project_is_the_offices_without_the_variable():
    """The HP and vps1 pin no COMPOSE_PROJECT_NAME: the project is the folder's name, as lib.sh office_project says."""
    d, _ = _tree()
    saved = dh.os.environ.pop("COMPOSE_PROJECT_NAME", None)
    try:
        p = d / "MyDGO"                                                       # inside this test's own tree
        p.mkdir()
        dh.REPO = p
        assert dh.project() == "mydgo"
        (p / ".env").write_text("COMPOSE_PROJECT_NAME=pinned\n", encoding="utf-8")
        assert dh.project() == "pinned"
        q = d / "הלשכה"
        q.mkdir()
        dh.REPO = q
        assert dh.project() == "digital-office"                               # a name compose cannot derive
    finally:
        if saved is not None:
            dh.os.environ["COMPOSE_PROJECT_NAME"] = saved


def test_a_filled_folder_never_waits():
    """On drvfs a store with no record waits — unless its folder already holds its data (browser42's data/browser42)."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    m = {k: v for k, v in apps["app"].items() if k != "_dir"}
    m["data"] = {"paths": ["data/app"]}                                       # no old volume: a bind it always had
    (d / "apps" / "app" / "app.json").write_text(json.dumps(m), encoding="utf-8")
    (d / ".generated").mkdir()
    (d / ".generated" / "compose.yml").write_text("include:\n  - apps/app/docker-compose.yml\n", encoding="utf-8")
    real = dh.fs_type
    try:
        dh.fs_type = lambda p: "9p"
        (d / "data" / "app").mkdir(parents=True)
        (d / "data" / "app" / "db").write_text("state", encoding="utf-8")
        dh.waits()
        assert not (d / "data" / ".moves" / "wait" / "app.yml").exists()
        (d / "data" / "app" / "db").unlink()                                  # an empty one does wait there
        dh.waits()
        assert (d / "data" / ".moves" / "wait" / "app.yml").exists()
    finally:
        dh.fs_type = real


def test_a_wait_file_keeps_no_service_the_compose_lost():
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    w = d / "data" / ".moves" / "wait"
    w.mkdir(parents=True)
    (w / "app.yml").write_text(dh.yaml.safe_dump({
        "services": {"gone": {"volumes": [{"type": "volume", "source": "old", "target": "/x"}]},
                     "app": {"volumes": [{"type": "volume", "source": "app_data", "target": "/data"}]}},
        "volumes": {"old": {"name": "office_old"}, "app_data": {"name": "office_app_data"}}}), encoding="utf-8")
    Engine().install()
    dh.write_override(dh.stores_of("app", apps["app"]), engine=False)
    doc = dh.yaml.safe_load((w / "app.yml").read_text(encoding="utf-8"))
    assert "gone" not in doc["services"] and "old" not in doc["volumes"]     # a service with no image fails compose


def test_the_backup_carries_a_volume_until_its_move_is_proven():
    import datamoves
    d, apps = _tree()
    m = apps["app"]
    assert datamoves.carried_volumes(d, "app", m) == ["app_data"]
    st = {"app": "app", "rel": "data/app"}
    dh.write_ledger(st, {"moved_at": "t", "verified": False})
    assert datamoves.carried_volumes(d, "app", m) == ["app_data"]            # moved, not checked yet
    dh.write_ledger(st, {"moved_at": "t", "verified": True})
    assert datamoves.carried_volumes(d, "app", m) == []
    # …and a store that was a FOLDER: its old folder is the app's own, and carried until its move is proven (an
    # app-scoped backup of an office that waits would otherwise leave apitools' signer out without a word)
    f = {**m, "data": {"paths": ["data/app/storage"], "moved_from": {"data/app/storage": "path:apps/app/storage/"}}}
    assert datamoves.old_folders(f) == ["apps/app/storage"] and datamoves.old_volumes(f) == []
    assert datamoves.carried_folders(d, "app", f) == ["apps/app/storage"] and datamoves.carried_volumes(d, "app", f) == []
    dh.write_ledger({"app": "app", "rel": "data/app/storage"}, {"moved_at": "t", "verified": True})
    assert datamoves.carried_folders(d, "app", f) == []


def test_verify_gives_a_slow_app_its_own_deadline():
    """Plane boots in 21 minutes (its reader): a moved store is given its app's `progress_deadline_seconds` to come up
    healthy when that is longer than verify's own wait — never sent back to its volume over a boot still running."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    Engine(vols=["office_app_data"], full=[str(d / "data" / "app"), "office_app_data"]).install()
    st = next(s for s in dh.stores_of("app", apps["app"]) if s["rel"] == "data/app")
    real = dh.containers_of, dh.health, dh.state_probe, dh.fs_type
    waited = []
    try:
        dh.fs_type = lambda p: "ext4"
        dh.containers_of = lambda services: ["app-1"]
        dh.state_probe = lambda s: {}
        dh.health = lambda names, deadline: waited.append(round(deadline - dh.time.time())) or []
        for deadline, want in ((None, 600), (1800, 1800), (60, 600)):
            dh.write_ledger(st, {"moved_at": "t", "healthy_before": ["app-1"]})
            m = {**apps["app"], **({"progress_deadline_seconds": deadline} if deadline else {})}
            waited.clear()
            assert dh.verify(timeout=600, apps={"app": m}) == 0
            assert waited and waited[0] in (want, want - 1), (deadline, waited)
    finally:
        dh.containers_of, dh.health, dh.state_probe, dh.fs_type = real


def test_verify_never_waits_on_what_it_stopped_itself():
    """Two stores of one app: the first fails its check, and its containers are stopped for it. The second is not
    judged now — still moved and unverified, for the next run — never waited on for a container verify itself
    stopped (the folder reader: Plane's state and logs, an hour of `bbox run`)."""
    d, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    (d / "apps" / "app" / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: alpine:3.20\n    volumes:\n      - ../../data/app/state:/state\n"
        "      - ../../data/app/logs:/logs\n", encoding="utf-8")
    apps["app"]["data"] = {"paths": ["data/app/state", "data/app/logs"],
                           "moved_from": {"data/app/state": "app_state", "data/app/logs": "app_logs"}}
    Engine(vols=["office_app_state", "office_app_logs"],
           full=[str(d / "data" / "app" / "state"), str(d / "data" / "app" / "logs"), "office_app_state",
                 "office_app_logs"]).install()
    stores = dh.stores_of("app", apps["app"])
    assert len(stores) == 2, stores
    real = dh.containers_of, dh.health, dh.state_probe, dh.fs_type, dh.sh, dh.helper
    waited = []

    class Done:
        def __init__(self, rc=0, out=b""):
            self.returncode, self.stdout = rc, out

    try:
        dh.fs_type = lambda p: "ext4"
        dh.containers_of = lambda services: ["app-1"]
        dh.state_probe = lambda s: {}                                # what it held is gone
        dh.health = lambda names, deadline: waited.append(names) or []
        dh.sh = lambda args, **k: Done()
        dh.helper = lambda *a, **k: Done()
        for s in stores:
            dh.write_ledger(s, {"moved_at": "t", "healthy_before": ["app-1"], "before": {"rows": "5"}})
        assert dh.verify(timeout=600, apps=apps) == 1
        leds = [dh.read_ledger(s) for s in stores]
        assert sum(1 for x in leds if x.get("failed")) == 1, leds                  # the first, sent back
        rest = [x for x in leds if not x.get("failed")]
        assert len(rest) == 1 and rest[0].get("moved_at") and not rest[0].get("verified"), rest   # not judged now
        assert len(waited) == 1, waited                                           # never waited on the stopped one
    finally:
        dh.containers_of, dh.health, dh.state_probe, dh.fs_type, dh.sh, dh.helper = real


def test_a_move_keeps_and_compares_the_extended_attributes():
    """storage-api keeps each Drive object's content-type as a `user.supabase.*` attribute, which busybox tar drops
    while every count and hash agrees (the reader of Drive's bytes). The helper's script copies them and lists them;
    a move whose copy differs in them fails — the store stays on its volume."""
    import os, subprocess
    d = pathlib.Path(tempfile.mkdtemp(prefix="dgo2019-xa-"))
    src, dst = d / "src", d / "dst"
    (src / "obj").mkdir(parents=True)
    (src / "obj" / "v1").write_text("bytes", encoding="utf-8")
    (dst / "obj").mkdir(parents=True)
    (dst / "obj" / "v1").write_text("bytes", encoding="utf-8")
    try:
        os.setxattr(src / "obj" / "v1", "user.supabase.content-type", b"application/pdf")
    except OSError:
        print("  (this filesystem keeps no user attributes: the script's own run is skipped)")
    else:
        run = lambda *a: subprocess.run([sys.executable, "-c", dh.XATTRS, *a], capture_output=True, text=True, check=True).stdout
        assert run("list", str(src)).endswith("obj/v1|user.supabase.content-type|"
                                              + __import__("hashlib").sha256(b"application/pdf").hexdigest() + "\n")
        assert run("list", str(dst)) == ""
        run("copy", str(src), str(dst))
        assert run("list", str(dst)) == run("list", str(src))
    # the move: its lists differ after the copy → it fails, never records a move
    d2, apps = _tree()
    dh.os.environ["COMPOSE_PROJECT_NAME"] = "office"
    st = dh.stores_of("app", apps["app"])[0]
    real = (dh.size_of, dh.windows_drive_free, dh.users_of, dh.helper, dh.pyhelper, dh.xattrs_of, dh.manifest,
            dh.state_probe, dh.write_ledger, dh.SPARE)
    copied, led = [], []
    try:
        dh.size_of, dh.windows_drive_free, dh.users_of, dh.SPARE = (lambda v: 0), (lambda: None), (lambda v, **k: []), 0
        dh.helper = lambda *a, **k: None
        dh.manifest = lambda s, h=False: "./x|f|644|0|0|1|1|ab"
        dh.state_probe = lambda s: {}
        dh.write_ledger = lambda s, rec: led.append(rec)
        dh.pyhelper = lambda mounts, code, *a, **k: copied.append(a)
        lists = {st["volume"]: "./x|user.a|h1\n", st["abs"]: ""}                  # the copy came out without them
        dh.xattrs_of = lambda s: lists[s]
        try:
            dh.move(st)
            raise AssertionError("a copy that lost its attributes was recorded as a move")
        except RuntimeError as e:
            assert "extended attributes" in str(e), e
        assert copied and copied[0][0] == "copy" and not led, (copied, led)
        lists[st["abs"]] = lists[st["volume"]]                                       # …and with them: moved
        copied.clear()
        dh.move(st)
        assert led and led[0]["xattrs"] == 1, led
        # the helper image neither here nor to be pulled: the store waits, and nothing was asked to stop
        real_sh, asked = dh.sh, []

        class Done:
            def __init__(self, rc):
                self.returncode, self.stdout = rc, b""
        dh.sh = lambda args, **k: Done(1 if args[:2] in (["docker", "image"], ["docker", "pull"]) else 0)
        dh.users_of = lambda v, **k: asked.append(v) or []
        try:
            dh.move(st)
            raise AssertionError("moved with no helper image to keep the attributes")
        except dh.Waiting as e:
            assert "could not be pulled" in str(e) and not asked, (e, asked)
        finally:
            dh.sh = real_sh
    finally:
        (dh.size_of, dh.windows_drive_free, dh.users_of, dh.helper, dh.pyhelper, dh.xattrs_of, dh.manifest,
         dh.state_probe, dh.write_ledger, dh.SPARE) = real


def test_ledger_names():
    st = {"app": "notifications", "rel": "data/notifications"}
    assert dh.ledger_path(st).name == "_.json"
    st = {"app": "project-pln", "rel": "data/project-pln/db"}
    assert dh.ledger_path(st).as_posix().endswith("project-pln/db.json")


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
            print(f"  ok  {name}")
    print(f"{n} passed")

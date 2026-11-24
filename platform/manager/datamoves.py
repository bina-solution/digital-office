"""datamoves — the ledger of the data move (DGO-2019), read without the engine and without YAML.

platform/manager/datahome.py moves each store of an app from its old volume into `data/<app>/<store>` and writes
one record per store in `data/.moves/<app>/<store>.json`. Three readers need that record and nothing else:
the move itself, the office's backup (scripts/deployment-archive.py) and data-management's inventory. A store whose
move is not proven yet still RUNS from its old volume, so that volume is still the app's to carry and to declare —
or a backup taken on an office that waits (the HP until DGO-1999, the Mac) would carry the empty folder and miss the
data (the second reader of DGO-2019).
"""
from __future__ import annotations

import json
import os
import pathlib

#: A `data.moved_from` value naming a volume compose never made — a hand-made container's — by its whole name.
EXTERNAL = "external:"
#: A `data.moved_from` value naming a host FOLDER of the checkout the store was in before (a source-tree
#: `path:apps/apitools/storage`): moved into data/<app>/<store> the same way, and never a volume to carry or restore.
PATH = "path:"


def is_volume(old) -> bool:
    """Whether a `data.moved_from` value is a volume compose made — neither `external:` nor `path:`."""
    return isinstance(old, str) and bool(old) and not old.startswith((EXTERNAL, PATH))


def ledger_name(rel: str) -> str:
    """`data/<app>/<store>` → `<store>.json` (`a/b` → `a__b.json`); `data/<app>` itself → `_.json`."""
    sub = rel.split("/", 2)[2] if rel.count("/") >= 2 else "_"
    return sub.replace("/", "__") + ".json"


def read(repo: pathlib.Path, app: str, rel: str) -> dict:
    """The store's record, or {} when no run has decided it."""
    try:
        return json.loads((pathlib.Path(repo) / "data" / ".moves" / app / ledger_name(rel)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def old_volumes(manifest: dict) -> list[str]:
    """Every old volume `data.moved_from` names (unprefixed; never an `external:` one): what a RESTORE may write for
    the app. A backup taken where a store still ran from its volume carries that volume (carried_volumes), and a
    restore that refused it — because `data.volumes` no longer names it — would bring the app up empty (the second
    reader of the forward-auth move: every account gone). Restored, it is moved into the folder by the next `bbox run`,
    as any old volume is."""
    moved = ((manifest.get("data") or {}).get("moved_from") or {}) if isinstance(manifest, dict) else {}
    return sorted({v for v in moved.values() if is_volume(v)})


def claimed_folders(manifests: dict, handled) -> dict:
    """{data/<app>/<store>: app} for each store whose old volume the app's own hooks/backup claims (`SKIPVOL
    <volume>`): a database it dumps itself, a queue it leaves out on purpose. The folder the volume moved to is the same
    data, live — tarred beside the dump it is an inconsistent copy that a restore would lay over the dump's. The
    archive leaves it to the hook, as it leaves the volume; the hook backs the store up wherever it now is."""
    out = {}
    for aid, m in (manifests or {}).items():
        moved = ((m.get("data") or {}).get("moved_from") or {}) if isinstance(m, dict) else {}
        for rel, vol in moved.items():
            if isinstance(vol, str) and vol in handled:
                out[rel] = aid
    return out


def old_folders(manifest: dict) -> list[str]:
    """The folders of the checkout (repo-relative) the app's stores came from (`path:` of data.moved_from) — its own,
    as its old volumes are: a backup of an office that still ran from one carries it, and an import puts it back there
    for the next `bbox run` to move."""
    moved = ((manifest.get("data") or {}).get("moved_from") or {}) if isinstance(manifest, dict) else {}
    return sorted({os.path.normpath(str(v)[len(PATH):]) for v in moved.values() if str(v).startswith(PATH)})


def carried_folders(repo: pathlib.Path, app: str, manifest: dict) -> list[str]:
    """`carried_volumes` for the stores that were folders: each `path:` folder whose store has no proven move — moved,
    compared and verified — so an app-scoped backup of an office that waits still carries it (the reader of apitools')."""
    moved = ((manifest.get("data") or {}).get("moved_from") or {}) if isinstance(manifest, dict) else {}
    out = []
    for rel, old in sorted(moved.items()):
        rec = read(repo, app, rel)
        if str(old).startswith(PATH) and not (rec.get("moved_at") and rec.get("verified")):
            out.append(os.path.normpath(str(old)[len(PATH):]))
    return out


def carried_volumes(repo: pathlib.Path, app: str, manifest: dict) -> list[str]:
    """The old volumes (unprefixed, as `data.volumes` names them) that the app's stores may still run from: each
    `data.moved_from` volume whose store has no proven move — moved, compared and verified. Files only. A volume
    compose never made (`external:<name>`) is not one of them: the backup finds volumes by compose's labels, which it
    has none of — it was outside the backup before its move too, and its folder is inside it after."""
    moved = ((manifest.get("data") or {}).get("moved_from") or {}) if isinstance(manifest, dict) else {}
    out = []
    for rel, vol in sorted(moved.items()):
        rec = read(repo, app, rel)
        if not (rec.get("moved_at") and rec.get("verified")) and is_volume(vol):
            out.append(vol)
    return out

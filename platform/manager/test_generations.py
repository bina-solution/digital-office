"""`reconcile.py rollback` restores a generation IN PLACE (FPG-497).

A running container bind-mounts folders of .generated/ (connections, the console, security, dgo-extend and computers
mount .generated/registry), and a bind mount follows the folder it was given. The old rollback deleted every folder of
.generated/ and copied the generation back — new folders, so each of those containers went on reading a deleted one,
empty, while it reported healthy; the credential broker then refused every lease (2026-10-29, 08:45Z). These cases
pin the folders: same inode before and after, contents exactly the generation's.

Run: python -m pytest platform/manager/test_generations.py -q
"""
import importlib.util
import os
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_gen_mod", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_gen_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


@pytest.fixture()
def gen(tmp_path, monkeypatch):
    g = tmp_path / ".generated"
    (g / "registry").mkdir(parents=True)
    (g / "registry" / "office.apps.json").write_text('{"apps": ["a"]}\n')
    (g / "registry" / "console.modules.yaml").write_text("- id: recorder\n  icon: mic\n")
    (g / "compose.yml").write_text("include:\n- compose.yml\n")
    monkeypatch.setattr(rc, "REPO", tmp_path)
    monkeypatch.setattr(rc, "GEN", g)
    monkeypatch.setattr(rc, "GENS", g / "generations")
    return g


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and "generations" not in p.relative_to(root).parts}


def test_rollback_keeps_the_mounted_folder(gen):
    before = snapshot(gen)
    gid = rc.archive_generation()
    reg_inode = os.stat(gen / "registry").st_ino
    # what a render does next: a file changes, one appears, one goes, a new folder appears
    (gen / "registry" / "office.apps.json").write_text('{"apps": ["a", "b"]}\n')
    (gen / "registry" / "new.json").write_text("{}\n")
    (gen / "registry" / "console.modules.yaml").unlink()
    (gen / "overlays").mkdir()
    (gen / "overlays" / "x.yml").write_text("x: 1\n")
    rc.restore_generation(gid)
    assert os.stat(gen / "registry").st_ino == reg_inode, "the registry folder was replaced: mounts would go blind"
    assert snapshot(gen) == before, "the restore is not exactly the generation"
    assert not (gen / "overlays").exists()


def test_rollback_writes_files_in_place(gen):
    gid = rc.archive_generation()
    f = gen / "registry" / "office.apps.json"
    ino = os.stat(f).st_ino
    f.write_text('{"apps": []}\n')
    rc.restore_generation(gid)
    assert os.stat(f).st_ino == ino and f.read_text() == '{"apps": ["a"]}\n'


def test_rollback_leaves_an_unchanged_file_alone(gen):
    gid = rc.archive_generation()
    f = gen / "compose.yml"
    os.utime(f, (1_000_000_000, 1_000_000_000))
    rc.restore_generation(gid)
    assert os.stat(f).st_mtime == 1_000_000_000, "an identical file was rewritten (watchers would fire)"


def test_rollback_keeps_the_generations_and_archives_the_state_it_leaves(gen):
    gid = rc.archive_generation()
    (gen / "registry" / "office.apps.json").write_text('{"apps": ["z"]}\n')
    rc.restore_generation(gid)
    gens = sorted(p.name for p in (gen / "generations").iterdir())
    assert gens == [gid, f"{int(gid) + 1:04d}"], gens
    assert (gen / "generations" / gens[-1] / "registry" / "office.apps.json").read_text() == '{"apps": ["z"]}\n'


def test_a_file_and_a_folder_may_swap(gen):
    gid = rc.archive_generation()
    (gen / "compose.yml").unlink()
    (gen / "compose.yml").mkdir()
    (gen / "registry" / "office.apps.json").unlink()
    (gen / "registry" / "office.apps.json").mkdir()
    rc.restore_generation(gid)
    assert (gen / "compose.yml").is_file() and (gen / "registry" / "office.apps.json").is_file()

"""FPG-621: each FreeCAD model at its own address — the list, one model, its files — and nothing a model's folder does
not hold is served, whatever the folder holds (a stray file, a broken params.json or bom.csv, hidden files, links)."""
from __future__ import annotations

import json
import os

import pytest
from fastapi import HTTPException

import app as cad


@pytest.fixture()
def models(tmp_path, monkeypatch):
    root = tmp_path / "caps-pro"
    good = root / "FPG Standard 30x24 galvanized"
    good.mkdir(parents=True)
    (good / "params.json").write_text(json.dumps({"label": "FPG Standard 30x24 galvanized", "style": "fpg-standard",
                                                  "material": "Galvanized steel G90", "steps": [["Hood", "Cut it."]]}))
    (good / "bom.csv").write_text("item,part_no,qty\n1,FPG-S-101,2\n")
    for f in ("model.glb", "1-assembled.png", "build-sheet.pdf", "P-500_lid.flat.svg", "build.log", ".secret.json"):
        (good / f).write_bytes(b"x")
    bad = root / "broken"
    bad.mkdir()
    (bad / "params.json").write_text("[]")                     # JSON, not the job's object
    (bad / "bom.csv").write_bytes(b"\xff\xfe\x00bad")           # not UTF-8
    (root / "a stray file.json").write_text("{}")               # a file, not a model's folder
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"x")
    os.symlink(outside, root / "link out")                      # a folder that is a link out of MODELS
    os.symlink(outside / "secret.pdf", good / "leak.pdf")       # a file that is a link out of its model
    os.symlink(tmp_path / "gone", good / "dead.png")            # a broken link
    monkeypatch.setattr(cad, "MODELS", str(root))
    return root


def test_the_list_holds_the_models_and_nothing_else(models):
    names = [m["name"] for m in cad.list_models()["models"]]
    assert sorted(names) == ["FPG Standard 30x24 galvanized", "broken"]


def test_one_model_with_its_parts_and_steps(models):
    m = cad.get_model("FPG Standard 30x24 galvanized")
    assert m["label"] == "FPG Standard 30x24 galvanized" and m["style"] == "fpg-standard"
    assert m["bom"] == [{"item": "1", "part_no": "FPG-S-101", "qty": "2"}] and m["steps"] == [["Hood", "Cut it."]]
    assert "model.glb" in m["files"] and "build.log" not in m["files"] and ".secret.json" not in m["files"]
    assert "leak.pdf" not in m["files"] and "dead.png" not in m["files"]
    assert m["freecad_path"] == "/config/projects/caps-pro/FPG Standard 30x24 galvanized"


def test_a_broken_model_reads_as_empty_not_a_500(models):
    m = cad.get_model("broken")
    assert m["label"] == "broken" and m["bom"] == [] and m["steps"] == []


@pytest.mark.parametrize("name", ["a stray file.json", "link out", "nope", "..", ".", "../outside"])
def test_what_is_not_a_model_is_404(models, name):
    with pytest.raises(HTTPException) as e:
        cad.get_model(name)
    assert e.value.status_code == 404


@pytest.mark.parametrize("file", ["build.log", ".secret.json", "leak.pdf", "dead.png", "../params.json", "params.json/.."])
def test_only_the_models_own_files_are_served(models, file):
    with pytest.raises(HTTPException) as e:
        cad.model_file("FPG Standard 30x24 galvanized", file)
    assert e.value.status_code == 404


def test_a_file_is_served_and_an_svg_only_as_a_download(models):
    pdf = cad.model_file("FPG Standard 30x24 galvanized", "build-sheet.pdf")
    assert pdf.media_type == "application/pdf" and "attachment" not in pdf.headers.get("content-disposition", "")
    svg = cad.model_file("FPG Standard 30x24 galvanized", "P-500_lid.flat.svg")
    assert "attachment" in svg.headers.get("content-disposition", "")

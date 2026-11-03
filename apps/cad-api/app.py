"""cad-api — the office's parametric models, their takeoff and their files (DGO-1076).

    GET  /healthz                                   up, and whether the CAD kernel loads
    GET  /api/families                              every family: its parameters and who said its rules
    GET  /api/families/{id}
    POST /api/families/{id}/takeoff                 {params, sheet: {w, h, material}, qty, kerf, svg}
                                                    -> pieces, sheets (placed), bom, notes — no money
    POST /api/families/{id}/model?format=step|glb   {params} -> the 3D file (build123d, inches)

    GET  /api/caps                                  the gallery's caps: parameters, sources
    POST /api/caps/{style}/quote                    a job ({cap_spec} as the services app stores it, or {params},
                                                    material, gauge, price_list) -> parts, sheets, BOM, cost, price
    POST /api/caps/{style}/model?format=step|glb    the same job -> the folded 3D replica

    GET  /                                          the caps for a person: one card each (static/index.html)
    GET  /caps/{style}                              one cap: its 3D, pieces, sheets, BOM, cost and the rules it
                                                    took for granted, with the sizes in the address (static/cap.html)

    GET  /models, /models/{name}                    the office's FreeCAD models, one address each (FPG-621): the 3D,
    GET  /api/models, /api/models/{name}            renders, parts list, steps, build sheet and files to download
    GET  /models/{name}/files/{file}                one of its files (only the kinds MODEL_FILES names)

The takeoff answers without the CAD kernel, so a quote never waits for a model. A bad parameter is a
400 whose `detail` is the sentence to show.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import families
import caps
import caps.cost as costing
import takeoff as tk

app = FastAPI(title="cad-api", version="0.1.0")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
#: the stock sheet when a takeoff names none — Alan: «48 inches by 120 inches» (MEET-41 [13:24])
DEFAULT_SHEET = (float(os.environ.get("CAD_SHEET_W", "48")), float(os.environ.get("CAD_SHEET_H", "120")))


def _family(fid: str):
    try:
        return families.get(fid)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


def _params(fam, raw):
    try:
        return families.check(fam, raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@app.get("/healthz")
def healthz():
    try:
        import build123d
        kernel = build123d.__version__
    except Exception as e:  # the takeoff still works; say why the models would not
        kernel = f"unavailable: {type(e).__name__}: {e}"
    return {"ok": True, "families": sorted(families.FAMILIES), "build123d": kernel}


@app.get("/api/families")
def list_families():
    return {"families": [families.describe(f) for f in families.FAMILIES.values()]}


@app.get("/api/families/{fid}")
def one_family(fid: str):
    return families.describe(_family(fid))


@app.post("/api/families/{fid}/takeoff")
def run_takeoff(fid: str, body: dict = Body(default={})):
    fam = _family(fid)
    p = _params(fam, body.get("params"))
    sheet = body.get("sheet") or {}
    try:
        sw, sh = float(sheet.get("w", DEFAULT_SHEET[0])), float(sheet.get("h", DEFAULT_SHEET[1]))
        kerf = float(body.get("kerf", 0))
        qty = int(body.get("qty") or 1)
    except (AttributeError, TypeError, ValueError):
        raise HTTPException(400, "sheet {w, h} and kerf are inches, qty a whole number") from None
    if not (0 < sw <= 240 and 0 < sh <= 240 and 0 <= kerf <= 1):
        raise HTTPException(400, "a sheet is 1–240″ each way and the kerf 0–1″")
    t0 = time.monotonic()
    try:
        out = tk.takeoff(fam, p, sw, sh, str(sheet.get("material") or "galvanized"), qty, kerf)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    if body.get("svg"):
        out["svg"] = [tk.sheet_svg(s) for s in out["sheets"]]
    out["ms"] = round((time.monotonic() - t0) * 1000, 1)
    return out


@app.post("/api/families/{fid}/model")
def model(fid: str, format: str = "glb", body: dict = Body(default={})):
    fam = _family(fid)
    p = _params(fam, body.get("params"))
    if format not in ("step", "glb"):
        raise HTTPException(400, "format is step or glb")
    try:
        from build123d import Unit, export_gltf, export_step
    except Exception as e:
        raise HTTPException(503, f"the CAD kernel does not load here: {type(e).__name__}: {e}") from None
    try:
        shape = fam.solid(p)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    # One file per family and size, overwritten by the next call for the same: the shared projects folder
    # holds the models, not a temp file per request. Owned by FreeCAD's user, so it opens there too.
    name = f"{fam.ID}-{'x'.join(f'{p[k]:g}' for k in ('L', 'W') if k in p)}.{format}"
    path = os.path.join(_out_dir(), name)
    part = path + ".part"
    if format == "step":
        export_step(shape, part, unit=Unit.IN)
        media = "model/step"
    else:
        export_gltf(shape, part, unit=Unit.IN, binary=True)
        media = "model/gltf-binary"
    os.replace(part, path)
    _share(path, 0o664)
    return FileResponse(path, media_type=media, filename=name)


#: FreeCAD's user in the `cad` container (linuxserver PUID/PGID): the files this api writes are theirs too
SHARE_UID, SHARE_GID = int(os.environ.get("CAD_PUID", "1000")), int(os.environ.get("CAD_PGID", "1000"))


def _share(path: str, mode: int) -> None:
    os.chmod(path, mode)
    try:
        os.chown(path, SHARE_UID, SHARE_GID)
    except PermissionError:  # not root (a test run): the mode alone still lets FreeCAD read it
        pass


def _out_dir() -> str:
    """CAD_OUT, made on first use (a fresh volume has nothing in it) and FreeCAD's to write as well."""
    out = os.environ.get("CAD_OUT") or tempfile.gettempdir()
    os.makedirs(out, exist_ok=True)
    root = os.path.dirname(out.rstrip("/"))
    for d in ([root] if root not in ("", "/") else []) + [out]:
        _share(d, 0o2775)
    return out


@app.get("/api/caps")
def list_caps():
    prices = costing.load(costing.DEFAULT)
    return {"caps": [{"id": s.id, "title": s.title, "group": s.group, "source": s.source, "params": s.params}
                     for s in caps.STYLES.values()],
            "price_lists": sorted(p[:-5] for p in os.listdir(costing.HERE) if p.endswith(".json")),
            # the default list's shop and sheets, so a page offers the metals it can price and says which are assumed
            "shop": prices.get("shop", ""),
            "materials": [{"key": k, "w": v.get("w"), "h": v.get("h"), "cents": v.get("cents"), "source": v.get("source", "")}
                          for k, v in prices.get("sheets", {}).items()]}


@app.get("/", include_in_schema=False)
def gallery_page():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/caps/{style}", include_in_schema=False)
def cap_page(style: str):
    try:
        caps.get(style)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    return FileResponse(os.path.join(STATIC, "cap.html"))


# --- the office's FreeCAD models (FPG-604, FPG-621): each one's own address, like an item's -----------------------
#: where the FreeCAD jobs publish (job.sh → the cad app's /config/projects/caps-pro = this volume's caps-pro)
MODELS = os.environ.get("CAD_MODELS", "/projects/caps-pro")
#: what a model page offers to download, by extension (anything else in its folder is not served)
MODEL_FILES = {".pdf": "application/pdf", ".png": "image/png", ".step": "model/step", ".glb": "model/gltf-binary",
               ".fcstd": "application/zip", ".dxf": "application/dxf", ".svg": "image/svg+xml", ".csv": "text/csv",
               ".json": "application/json"}


def _inside(path: str, root: str) -> bool:
    """`path` is really under `root` — a symlink pointing elsewhere is not."""
    r = os.path.realpath(root)
    return os.path.realpath(path).startswith(r + os.sep)


def _model_dir(name: str) -> str:
    """A model's folder by its name — one of MODELS' own folders (a real folder, not hidden, not a link out), never a
    path."""
    try:
        names = set(os.listdir(MODELS))
    except OSError:
        names = set()
    d = os.path.join(MODELS, name)
    if name not in names or "/" in name or name.startswith(".") or not os.path.isdir(d) or not _inside(d, MODELS):
        raise HTTPException(404, f"no model {name!r}")
    return d


def _model_files(d: str) -> list[str]:
    """The files of a model's folder a page may offer: the kinds MODEL_FILES names, not hidden, really inside it."""
    return sorted(f for f in os.listdir(d) if os.path.splitext(f)[1].lower() in MODEL_FILES and not f.startswith(".")
                  and os.path.isfile(os.path.join(d, f)) and _inside(os.path.join(d, f), d))


def _model(name: str, full: bool = False) -> dict:
    d = _model_dir(name)
    files = _model_files(d)
    meta = {}
    try:
        with open(os.path.join(d, "params.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        pass
    if not isinstance(meta, dict):        # a params.json that is JSON but not the job's object: as if there were none
        meta = {}
    out = {"name": name, "label": meta.get("label", name), "style": meta.get("style", "standard"),
           "material": meta.get("material", ""), "files": files,
           "updated": int(max((os.path.getmtime(os.path.join(d, f)) for f in files), default=0)),
           "fcstd": next((f for f in files if f.lower().endswith(".fcstd")), None),
           "freecad_path": f"/config/projects/caps-pro/{name}"}
    if full:
        import csv
        out["params"], out["steps"], out["counts"] = meta.get("params", {}), meta.get("steps", []), meta.get("counts", {})
        try:
            with open(os.path.join(d, "bom.csv"), encoding="utf-8", newline="") as f:
                out["bom"] = list(csv.DictReader(f))
        except (OSError, ValueError, csv.Error):       # unreadable, not UTF-8, not CSV: the page shows no parts list
            out["bom"] = []
    return out


@app.get("/api/models")
def list_models():
    try:
        names = sorted(n for n in os.listdir(MODELS) if os.path.isdir(os.path.join(MODELS, n)) and not n.startswith("."))
    except OSError:
        names = []
    out = []
    for n in names:
        try:
            out.append(_model(n))
        except HTTPException:                    # a folder that is not a model's (a link out, hidden): not listed
            continue
    return {"models": sorted(out, key=lambda m: -m["updated"])}


@app.get("/api/models/{name}")
def get_model(name: str):
    return _model(name, full=True)


@app.get("/models/{name}/files/{file}", include_in_schema=False)
def model_file(name: str, file: str):
    d = _model_dir(name)
    ext = os.path.splitext(file)[1].lower()
    if file not in _model_files(d):
        raise HTTPException(404, f"no file {file!r} in {name!r}")
    inline = ext in (".pdf", ".png", ".glb")          # an SVG is downloaded, never opened here (it could carry script)
    return FileResponse(os.path.join(d, file), media_type=MODEL_FILES[ext], filename=None if inline else file)


@app.get("/models", include_in_schema=False)
def models_page():
    return FileResponse(os.path.join(STATIC, "models.html"))


@app.get("/models/{name}", include_in_schema=False)
def model_page(name: str):
    _model_dir(name)
    return FileResponse(os.path.join(STATIC, "model.html"))


def _cap_job(style: str, body: dict) -> dict:
    try:
        caps.get(style)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    if not isinstance(body, dict):
        raise HTTPException(400, "the body is a job object: {cap_spec} or {params}")
    return body


@app.post("/api/caps/{style}/quote")
def cap_quote(style: str, body: dict = Body(default={})):
    job = _cap_job(style, body)
    t0 = time.monotonic()
    try:
        out = caps.quote(style, job, costing.load(str(job.get("price_list") or costing.DEFAULT)))
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(400, str(e)) from None
    out["ms"] = round((time.monotonic() - t0) * 1000, 1)
    return out


@app.post("/api/caps/{style}/model")
def cap_model(style: str, format: str = "glb", body: dict = Body(default={})):
    job = _cap_job(style, body)
    if format not in ("step", "glb"):
        raise HTTPException(400, "format is step or glb")
    try:
        from build123d import Unit, export_gltf, export_step
    except Exception as e:
        raise HTTPException(503, f"the CAD kernel does not load here: {type(e).__name__}: {e}") from None
    try:
        shape = caps.model(style, job)
        p = caps.params_from(caps.get(style), job)
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(400, str(e)) from None
    name = f"cap-{style}-{p['L']:g}x{p['W']:g}.{format}"
    # the file on disk is keyed by the whole job (every option and the metal, not L × W alone) and each request
    # writes its own temporary file: two people opening one shared link, or one size in two metals, never meet
    key = hashlib.sha1(json.dumps({"style": style, "job": job}, sort_keys=True, default=str).encode()).hexdigest()[:12]
    out = _out_dir()
    path = os.path.join(out, f"cap-{style}-{p['L']:g}x{p['W']:g}-{key}.{format}")
    fd, part = tempfile.mkstemp(dir=out, suffix=".part")
    os.close(fd)
    try:
        if format == "step":
            export_step(shape, part, unit=Unit.IN)
        else:
            export_gltf(shape, part, unit=Unit.IN, binary=True)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    _share(path, 0o664)
    return FileResponse(path, media_type="model/step" if format == "step" else "model/gltf-binary", filename=name)

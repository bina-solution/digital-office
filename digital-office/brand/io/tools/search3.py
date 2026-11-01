"""Sweep v3: square anchors only (the "0": o 4x6, gap 1 -> anchors 0 2 4 6 both ways), radii that can repeat
across parts, scored with beautiful logo mode including the curve-repetition factor. -> results3.jsonl"""
import json, math, os, sys, time, random
from multiprocessing import Pool
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from iomark import Design  # noqa: E402

O_PAIRS = [(0, 0), (0.5, 0), (0.5, 0.5), (1, 0), (1, 1), (1.5, 0.5), (1.5, 1), (2, 1)]
BOX = [0, 0.25, 0.5, 1, 1.5, 2, 3, -1]            # container corner radius in modules; -1 = disc


def space():
    for rho in (0.0, 0.25, 0.5):
        for ro, ri in O_PAIRS:
            for rc in BOX:
                for pol in ("pos", "neg"):
                    for k in (1.0, 2.0):
                        for centre in ("median", "bbox"):
                            yield dict(rho=rho, ro=ro, ri=ri, rc=rc, pol=pol, k=k, centre=centre)


def design(a):
    return Design(4, 1, a["rho"], a["ro"], 0.0, a["pol"], a["k"], a["centre"], ri=a["ri"], rc=math.inf if a["rc"] < 0 else a["rc"])


def _lean():
    import beautiful.core as C
    from beautiful import experimental as X
    C.X.all_measurements = lambda rgb: {"edge_contact": X.edge_contact(rgb)}
    return C.beauty


def run(a):
    beauty = _lean()
    d = design(a)
    rec = dict(a, key=d.key(), L=round(d.L, 4), a=round(d.a, 4), margin=round(d.margin, 4))
    if d.margin < 0.25:
        rec["score"] = None
        return rec
    img = d.raster(1024)
    ink = 1 - img
    h = ink.shape[0] // 2
    L, R, T, B = ink[:, :h].sum(), ink[:, h:].sum(), ink[:h].sum(), ink[h:].sum()
    r = beauty(Image.fromarray((img * 255).round().astype(np.uint8)).convert("RGB"), "logo")
    s = r["raw"]["symmetry"]
    rec.update(white=round(float(img.mean()), 5), lr=round(float(min(L, R) / max(L, R)), 4), tb=round(float(min(T, B) / max(T, B)), 4),
               score=r["score"], ws=r["weighted_sum"], factors=r["factors"], penalties=r["penalties"],
               distinct=r["raw"]["experimental"]["curve_repetition"]["distinct"],
               radii=[c["radius_px"] for c in r["raw"]["experimental"]["curve_repetition"]["classes"]],
               v=s["vertical_mirror"], bal=s["balance"])
    return rec


if __name__ == "__main__":
    out = os.path.join(HERE, "results3.jsonl")
    done = {json.loads(l)["key"] for l in open(out)} if os.path.exists(out) else set()
    todo = [a for a in space() if design.__name__ and True]
    todo = [a for a in todo if a not in []]
    random.Random(3).shuffle(todo)
    t0 = time.time()
    print(len(todo), "candidates", flush=True)
    with open(out, "a") as fh, Pool(6) as pool:
        for i, rec in enumerate(pool.imap_unordered(run, todo, chunksize=4), 1):
            if rec["key"] in done:
                continue
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            if i % 200 == 0:
                print(f"{i}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)
    print("done", time.time() - t0, flush=True)

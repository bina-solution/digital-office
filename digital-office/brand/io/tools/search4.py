"""Sweep v4: halves-centred only (ink 1:1 both ways), clearance 2 / 2.5 / 3, and the all-quarter family.
Reuses search3.run / design; skips keys already in results3.jsonl. -> results4.jsonl"""
import json, os, sys, time, random
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from search3 import run, design  # noqa: E402

O_PAIRS = [(0, 0), (0.25, 0), (0.25, 0.25), (0.5, 0), (0.5, 0.5), (1, 0), (1, 1), (1.5, 0.5), (2, 1)]
BOX = [0, 0.25, 0.5, 1, 1.5, 2, 3, -1]


def space():
    for rho in (0.0, 0.25, 0.5):
        for ro, ri in O_PAIRS:
            for rc in BOX:
                for pol in ("pos", "neg"):
                    for k in (2.0, 2.5, 3.0):
                        yield dict(rho=rho, ro=ro, ri=ri, rc=rc, pol=pol, k=k, centre="median")


if __name__ == "__main__":
    out = os.path.join(HERE, "results4.jsonl")
    done = set()
    for f in ("results3.jsonl", "results4.jsonl"):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            done |= {json.loads(l)["key"] for l in open(p)}
    todo = [a for a in space() if design(a).key() not in done]
    random.Random(4).shuffle(todo)
    t0 = time.time()
    print(len(todo), "new candidates", flush=True)
    with open(out, "a") as fh, Pool(6) as pool:
        for i, rec in enumerate(pool.imap_unordered(run, todo, chunksize=4), 1):
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            if i % 200 == 0:
                print(f"{i}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)
    print("SWEEP4_DONE", time.time() - t0, flush=True)

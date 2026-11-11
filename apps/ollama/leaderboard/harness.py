#!/usr/bin/env python3
"""leaderboard harness — measure the models of THIS machine's Ollama, the way the office runs them (DGO-1351).

    python3 harness.py fetch  <dir>                          # the public sets: pinned, sampled once
    python3 harness.py run    <dir> <model>… [--url U] [--limit N]   # the answers → <dir>/runs/<model>.jsonl
    python3 harness.py speed  <dir> <model>… [--url U]       # the speed, on a quiet machine → the same file
    python3 harness.py score  <dir>                          # every run → <dir>/results.json
    python3 harness.py status <dir>

What it measures and why (the public page: bina-solutions.co.il/ai-leaderboard/methodology/):
* THE OFFICE'S CONFIGURATION, NOT A LAB'S. The server's own defaults — context length, KV-cache type,
  threads, GPU offload — are what is measured, and they are recorded with the run, because the question a
  visitor asks is "what will this model do on a machine like mine". Nothing is tuned per model.
* THE SAME QUESTIONS IN TWO LANGUAGES. Belebele and Global-MMLU are parallel sets: the Hebrew item and the
  English item are one question translated, so a model's two scores differ by the language only. The
  items are sampled once (seed 20261105, one stream per set) and written to <dir>/sets/, and every later
  run asks exactly them.
* A PRIVATE OFFICE SET. <dir>/private/office.jsonl — Hebrew office work (invoice fields, VAT, routing a
  customer's message, dates, a policy question, a strict format) — is never published, so a model that
  was trained on the public sets gains nothing on it. The file is optional; without it the score is
  computed from the public sets alone and says so.
* AN INTERVAL, NOT A POINT. Every score carries a 95% bootstrap interval over its questions. A model ranks below
  another only when the other's whole interval lies above its own (rank = 1 + the number of such models), so two
  models whose difference is inside the noise share a rank. Ranks are taken among complete runs only.
* RESUMABLE. Every answer is appended the moment it arrives; a stopped run picks up where it stopped.
* A SCORE IS NOT A SPEED. Answers do not depend on timing, so they are collected whatever else the machine
  is doing; the speed is its own pass (`speed`), run when the machine is quiet, and each speed run records
  the load average it ran under. An answer that came after another caller swapped the model in (this
  server holds one model at a time) keeps its answer and loses its timing.

Stdlib only, so it runs on any office machine that has python3.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

SEED = 20261105
N_MCQ = 100          # per set and language
N_MT = 50            # per translation direction
#: Room for a short preamble before the answer's number: Hebrew takes more tokens per word, and a cap of 8
#: cut «התשובה היא 2» before the 2 (measured on the first run, 2026-11-05) — a cap that taxed Hebrew only.
MCQ_TOKENS = 24
ROWS_API = "https://datasets-server.huggingface.co/rows"
FLORES_TAR = "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz"
SETS = {
    "belebele": {"dataset": "facebook/belebele", "he": "heb_Hebr", "en": "eng_Latn", "split": "test",
                 "licence": "CC BY-SA 4.0"},
    "gmmlu": {"dataset": "CohereLabs/Global-MMLU", "he": "he", "en": "en", "split": "test",
              "licence": "Apache-2.0"},
    "flores": {"dataset": "FLORES-200 devtest", "url": FLORES_TAR, "licence": "CC BY-SA 4.0"},
}
#: The composite scores, weights published on the methodology page.
HEBREW_WEIGHTS = {"belebele_he": 0.25, "gmmlu_he": 0.25, "flores_en_he": 0.20, "office_he": 0.30}
ENGLISH_WEIGHTS = {"belebele_en": 0.5, "gmmlu_en": 0.5}
SPEED_RUNS = 3
#: A speed run started above this 1-minute load average is kept only when no quieter one exists.
QUIET_LOAD = 1.5


# ── fetching ─────────────────────────────────────────────────────────────────────────────────────
def _get(url: str, timeout: int = 60, tries: int = 6) -> bytes:
    """One GET, retried. The rows API answers 429 after ~45 quick requests (measured 2026-11-05), so a 429
    waits half a minute and more, and every request is paced."""
    last = None
    for i in range(tries):
        time.sleep(1.2)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bina-leaderboard/1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:  # the server's words travel with the failure (G66)
            last = f"HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}"
            time.sleep(30 * (i + 1) if e.code == 429 else 2 + 3 * i)
        except Exception as e:  # noqa: BLE001 — a flaky network is retried, then said
            last = e
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"fetch failed: {url}: {last}")


def _write_lines(path: Path, rows: list) -> None:
    """A set file appears whole or not at all: a fetch that dies half-way must not leave a short set
    that every later run would then treat as THE set."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _rows(dataset: str, config: str, split: str, offset: int, length: int) -> list:
    q = urllib.parse.urlencode({"dataset": dataset, "config": config, "split": split,
                                "offset": offset, "length": length})
    return [r["row"] for r in json.loads(_get(f"{ROWS_API}?{q}"))["rows"]]


def _num_rows(dataset: str, config: str, split: str) -> int:
    q = urllib.parse.urlencode({"dataset": dataset, "config": config, "split": split, "offset": 0, "length": 1})
    return int(json.loads(_get(f"{ROWS_API}?{q}"))["num_rows_total"])


def _revision(dataset: str) -> str:
    try:
        return json.loads(_get(f"https://huggingface.co/api/datasets/{dataset}", tries=2)).get("sha") or ""
    except Exception:  # noqa: BLE001
        return ""


def fetch(d: Path) -> None:
    """Sample the public sets once. An existing set file is kept: re-sampling would change the questions."""
    out = d / "sets"
    out.mkdir(parents=True, exist_ok=True)
    # A set's provenance (revision, time) is written when that set is SAMPLED and kept afterwards: a later fetch that
    # samples nothing must not stamp today's revision on questions taken from an older one.
    old_meta = json.loads((out / "meta.json").read_text(encoding="utf-8")) if (out / "meta.json").exists() else {}
    meta = {"seed": SEED, "sets": dict(old_meta.get("sets") or {})}
    now_ = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Belebele: 900 parallel questions; pair the two languages by (link, question_number).
    if not (out / "belebele.jsonl").exists():
        s = SETS["belebele"]
        both = {}
        for lang in ("he", "en"):
            rows = []
            for off in range(0, 900, 100):
                rows += _rows(s["dataset"], s[lang], s["split"], off, 100)
            both[lang] = {(r["link"], r["question_number"]): r for r in rows}
        keys = sorted(set(both["he"]) & set(both["en"]))
        pick = random.Random(f"{SEED}-belebele").sample(keys, N_MCQ)
        _write_lines(out / "belebele.jsonl", [
            {"id": f"{k[0]}#{k[1]}", "answer": str(both["he"][k]["correct_answer_num"]),
             "he": [both["he"][k]["flores_passage"], both["he"][k]["question"]] + [both["he"][k][f"mc_answer{i}"] for i in range(1, 5)],
             "en": [both["en"][k]["flores_passage"], both["en"][k]["question"]] + [both["en"][k][f"mc_answer{i}"] for i in range(1, 5)]}
            for k in pick])
        meta["sets"]["belebele"] = {**SETS["belebele"], "revision": _revision(SETS["belebele"]["dataset"]), "n": N_MCQ, "sampled_at": now_}

    # Global-MMLU: 14k questions per language, sorted by subject and aligned by sample_id. Two questions from
    # each of 50 random pages of 100: 50 subjects' worth of spread for 100 requests, inside the rows API's pace.
    if not (out / "gmmlu.jsonl").exists():
        s = SETS["gmmlu"]
        total = _num_rows(s["dataset"], s["he"], s["split"])
        rnd = random.Random(f"{SEED}-gmmlu")
        pages = sorted(rnd.sample(range(0, total - 100, 100), N_MCQ // 2))
        rows = []
        for off in pages:
            he_page = _rows(s["dataset"], s["he"], s["split"], off, 100)
            en_page = {r["sample_id"]: r for r in _rows(s["dataset"], s["en"], s["split"], off, 100)}
            for he in rnd.sample(he_page, 2):
                en = en_page.get(he["sample_id"])
                if en is None:
                    raise RuntimeError(f"Global-MMLU {he['sample_id']}: no English twin on page {off}")
                rows.append({"id": he["sample_id"], "answer": he["answer"].strip().upper(),
                             "label": he.get("cultural_sensitivity_label"),
                             "he": [he["question"], he["option_a"], he["option_b"], he["option_c"], he["option_d"]],
                             "en": [en["question"], en["option_a"], en["option_b"], en["option_c"], en["option_d"]]})
        _write_lines(out / "gmmlu.jsonl", rows)
        meta["sets"]["gmmlu"] = {**SETS["gmmlu"], "revision": _revision(SETS["gmmlu"]["dataset"]), "n": N_MCQ, "sampled_at": now_}

    # FLORES-200 devtest: 1012 parallel sentences; one sample serves both directions.
    if not (out / "flores.jsonl").exists():
        tgz = d / "flores200_dataset.tar.gz"
        if not tgz.exists():
            tgz.write_bytes(_get(FLORES_TAR, timeout=300))
        lines = {}
        with tarfile.open(tgz) as tf:
            for lang in ("heb_Hebr", "eng_Latn"):
                m = next(m for m in tf.getmembers() if m.name.endswith(f"devtest/{lang}.devtest"))
                lines[lang] = tf.extractfile(m).read().decode("utf-8").splitlines()
        idx = sorted(random.Random(f"{SEED}-flores").sample(range(len(lines["eng_Latn"])), N_MT))
        _write_lines(out / "flores.jsonl", [{"id": f"devtest#{i}", "he": lines["heb_Hebr"][i], "en": lines["eng_Latn"][i]}
                                            for i in idx])
        meta["sets"]["flores"] = {**SETS["flores"], "n": N_MT, "sampled_at": now_}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


# ── the questions ────────────────────────────────────────────────────────────────────────────────
def _load(p: Path) -> list:
    """Every record of a JSONL file. A line that does not parse — a run killed mid-write, a full disk — is skipped,
    so one cut-off line never stops a run from resuming or a score from being read."""
    out = []
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def tasks(d: Path) -> list:
    """Every (task, item id, prompt, max tokens, expected) this harness asks, in a fixed order."""
    out = []
    for it in _load(d / "sets" / "belebele.jsonl"):
        p, q, a1, a2, a3, a4 = it["he"]
        out.append(("belebele_he", it["id"], MCQ_TOKENS, it["answer"],
                    "קרא את הקטע וענה על השאלה. השב רק במספר התשובה הנכונה (1, 2, 3 או 4).\n\n"
                    f"קטע: {p}\n\nשאלה: {q}\n1. {a1}\n2. {a2}\n3. {a3}\n4. {a4}\n\nתשובה:"))
        p, q, a1, a2, a3, a4 = it["en"]
        out.append(("belebele_en", it["id"], MCQ_TOKENS, it["answer"],
                    "Read the passage and answer the question. Reply with the number of the correct answer only (1, 2, 3 or 4).\n\n"
                    f"Passage: {p}\n\nQuestion: {q}\n1. {a1}\n2. {a2}\n3. {a3}\n4. {a4}\n\nAnswer:"))
    for it in _load(d / "sets" / "gmmlu.jsonl"):
        q, a, b, c, dd = it["he"]
        out.append(("gmmlu_he", it["id"], MCQ_TOKENS, it["answer"],
                    "ענה על שאלת הבחירה. השב רק באות של התשובה הנכונה (A, B, C או D).\n\n"
                    f"שאלה: {q}\nA. {a}\nB. {b}\nC. {c}\nD. {dd}\n\nתשובה:"))
        q, a, b, c, dd = it["en"]
        out.append(("gmmlu_en", it["id"], MCQ_TOKENS, it["answer"],
                    "Answer the multiple-choice question. Reply with the letter of the correct answer only (A, B, C or D).\n\n"
                    f"Question: {q}\nA. {a}\nB. {b}\nC. {c}\nD. {dd}\n\nAnswer:"))
    for it in _load(d / "sets" / "flores.jsonl"):
        out.append(("flores_en_he", it["id"], 256, it["he"],
                    "Translate the following sentence from English to Hebrew. Reply with the Hebrew translation only.\n\n" + it["en"]))
        out.append(("flores_he_en", it["id"], 256, it["en"],
                    "תרגם את המשפט הבא מעברית לאנגלית. השב בתרגום לאנגלית בלבד.\n\n" + it["he"]))
    for it in _load(d / "private" / "office.jsonl"):
        out.append(("office_he", it["id"], int(it.get("max_tokens", 300)), it["check"], it["prompt"]))
    return out


# ── talking to Ollama ────────────────────────────────────────────────────────────────────────────
def _post(url: str, path: str, body: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(url.rstrip("/") + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _json_get(url: str, path: str) -> dict:
    with urllib.request.urlopen(url.rstrip("/") + path, timeout=30) as r:
        return json.loads(r.read())


def ask(url: str, model: str, prompt: str, max_tokens: int, think_off: bool) -> dict:
    body = {"model": model, "stream": False, "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0, "seed": 0, "num_predict": max_tokens}}
    if think_off:
        body["think"] = False
    t0 = time.monotonic()
    r = _post(url, "/api/chat", body)
    r["_wall"] = time.monotonic() - t0
    return r


def environment(url: str, model: str) -> dict:
    """What a reader needs to reproduce the number: the model's identity, the runtime, the machine."""
    env = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        env["ollama_version"] = _json_get(url, "/api/version").get("version")
    except Exception:  # noqa: BLE001
        env["ollama_version"] = None
    show = _post(url, "/api/show", {"model": model}, timeout=60)
    det = show.get("details") or {}
    env["model"] = {"name": model, "family": det.get("family"), "parameter_size": det.get("parameter_size"),
                    "quantization": det.get("quantization_level"), "format": det.get("format"),
                    "capabilities": show.get("capabilities") or [], "licence_head": (show.get("license") or "")[:200]}
    for m in (_json_get(url, "/api/tags").get("models") or []):
        if m.get("name") == model:
            env["model"]["digest"] = m.get("digest")
            env["model"]["file_bytes"] = m.get("size")
    try:
        cpu = [l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")]
        mem = next(int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemTotal"))
        env["machine"] = {"cpu": cpu[0] if cpu else None, "threads": len(cpu), "ram_gb": round(mem / 1048576, 1),
                          "host": os.uname().nodename}
    except Exception:  # noqa: BLE001
        env["machine"] = {}
    return env


def loaded(url: str) -> list:
    try:
        return _json_get(url, "/api/ps").get("models") or []
    except Exception:  # noqa: BLE001
        return []


SPEED_PROMPT = ("כתוב פסקה קצרה, בעברית פשוטה, שמסבירה לבעל עסק קטן מה ההבדל בין חשבונית מס לבין חשבונית מס/קבלה, "
                "ומתי צריך מספר הקצאה. אחר כך תן שלוש המלצות מעשיות לסידור הניירת בסוף החודש. "
                "הנה רקע שאפשר להיעזר בו: עסק מורשה מוציא חשבונית מס על כל עסקה; כשהתשלום מתקבל באותו רגע, "
                "אפשר להוציא מסמך אחד שמשמש גם כקבלה. רשות המסים הנהיגה מודל של חשבוניות ישראל, ובו חשבונית "
                "מעל סכום מסוים צריכה מספר הקצאה כדי שהלקוח יוכל לקזז את המע״מ. ")


def run(d: Path, model: str, url: str, limit: int | None) -> None:
    runs = d / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / (re.sub(r"[^A-Za-z0-9._-]+", "_", model) + ".jsonl")
    # only real answers are done: a question that failed (the server was being recreated, the model would not load)
    # is asked again by the next run instead of standing as a zero forever
    done = {(r["task"], r["id"]) for r in _load(path) if r.get("kind") == "answer" and not r.get("error")}
    env = environment(url, model)
    think_off = "thinking" in env["model"]["capabilities"]
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "env", **env}, ensure_ascii=False) + "\n")
        f.flush()
        todo = [t for t in tasks(d) if (t[0], t[1]) not in done]
        if limit is not None:
            todo = todo[:limit]
        print(f"{model}: {len(done)} done, {len(todo)} to ask", flush=True)
        first_fails = 0
        for i, (task, iid, max_tokens, expected, prompt) in enumerate(todo, 1):
            try:
                r = ask(url, model, prompt, max_tokens, think_off)
                msg = (r.get("message") or {}).get("content") or ""
                rec = {"kind": "answer", "task": task, "id": iid, "answer": msg,
                       "prompt_tokens": r.get("prompt_eval_count"), "gen_tokens": r.get("eval_count"),
                       "prompt_s": (r.get("prompt_eval_duration") or 0) / 1e9, "gen_s": (r.get("eval_duration") or 0) / 1e9,
                       "load_s": (r.get("load_duration") or 0) / 1e9, "wall_s": round(r["_wall"], 3),
                       "swapped": (r.get("load_duration") or 0) > 2e9 and i > 1}
            except Exception as e:  # noqa: BLE001 — one failed question is recorded, the run goes on
                rec = {"kind": "answer", "task": task, "id": iid, "answer": "", "error": f"{type(e).__name__}: {e}"[:300]}
            first_fails = first_fails + 1 if ("error" in rec and first_fails == i - 1) else first_fails
            if first_fails == 3:
                # three failures from the very first question: the model does not load here (memory, a
                # missing file). Said once rather than 540 times; this model stops and the next one starts.
                print(f"{model}: does not answer here — {rec['error']}", flush=True)
                f.write(json.dumps({"kind": "abort", "reason": rec["error"]}) + "\n")
                return
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if i % 25 == 0:
                print(f"{model}: {i}/{len(todo)}", flush=True)
    print(f"{model}: finished", flush=True)


def speed(d: Path, model: str, url: str) -> None:
    """A fixed Hebrew prompt, 128 tokens out, SPEED_RUNS times — a different first line each time, so no run
    reuses another's prompt cache — with the load average each run started under, so a reader can see the
    machine was quiet (or was not)."""
    path = d / "runs" / (re.sub(r"[^A-Za-z0-9._-]+", "_", model) + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    think_off = "thinking" in environment(url, model)["model"]["capabilities"]
    ask(url, model, "שלום", 4, think_off)                     # load it first: the load is not a speed
    with open(path, "a", encoding="utf-8") as f:
        for k in range(SPEED_RUNS):
            load1 = os.getloadavg()[0]
            try:
                r = ask(url, model, f"({k + 1}/{SPEED_RUNS}, {time.time():.0f})\n" + SPEED_PROMPT, 128, think_off)
                ps = [m for m in loaded(url) if m.get("name") == model]
                f.write(json.dumps({"kind": "speed", "run": k + 1, "load1": round(load1, 2),
                                    "prompt_tokens": r.get("prompt_eval_count"),
                                    "prompt_s": (r.get("prompt_eval_duration") or 0) / 1e9,
                                    "gen_tokens": r.get("eval_count"), "gen_s": (r.get("eval_duration") or 0) / 1e9,
                                    "load_s": (r.get("load_duration") or 0) / 1e9, "wall_s": round(r["_wall"], 3),
                                    "size_bytes": ps[0].get("size") if ps else None,
                                    "vram_bytes": ps[0].get("size_vram") if ps else None,
                                    "context": ps[0].get("context_length") if ps else None,
                                    "processor": f"{ps[0].get('size_vram', 0) * 100 // max(1, ps[0].get('size') or 1)}% GPU" if ps else None,
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
            except Exception as e:  # noqa: BLE001
                f.write(json.dumps({"kind": "speed", "run": k + 1, "error": f"{type(e).__name__}: {e}"[:300]}) + "\n")
            f.flush()
    print(f"{model}: speed done", flush=True)


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    s = re.sub(r"[\"'״׳“”‘’`.,:;!?()\[\]{}]", " ", str(s or "")).replace("\u200f", "").replace("\u200e", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _num(s: str):
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(s or "").replace("\u200f", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _first_json(s: str):
    s = str(s or "")
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip())
    i = s.find("{")
    while i >= 0:
        depth = 0
        for j in range(i, len(s)):
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            if depth == 0:
                try:
                    return json.loads(s[i:j + 1])
                except ValueError:
                    break
        i = s.find("{", i + 1)
    return None


def _same(got, want) -> bool:
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        g = got if isinstance(got, (int, float)) else _num(got)
        return g is not None and abs(float(g) - float(want)) <= 0.011
    return _norm(got) == _norm(want)


def check_office(answer: str, check: dict) -> bool:
    kind = check.get("kind")
    if kind == "number":
        # «1,000 × 1.18 = 1,180» means 1,180; «1,475 ₪ (כולל מע״מ 18%)» means 1,475: the result after the last «=»,
        # else the first number
        txt = str(answer or "")
        g = _num(txt.rsplit("=", 1)[1]) if "=" in txt else _num(txt)
        return g is not None and abs(g - float(check["value"])) <= float(check.get("tol", 0.011))
    if kind == "label":
        found = [l for l in check["labels"] if _norm(l) in _norm(answer)]
        return found == [check["value"]] or (len(found) > 1 and _norm(answer).startswith(_norm(check["value"])))
    if kind == "exact":
        return _norm(answer) in [_norm(v) for v in ([check["value"]] + check.get("also", []))]
    if kind == "date":
        found = set(re.findall(r"\d{4}-\d{2}-\d{2}", str(answer)))
        return found == {check["value"]}                # one date, the right one — not a list that contains it
    if kind == "contains_all":
        a = _norm(answer)
        return all(any(_norm(alt) in a for alt in (k if isinstance(k, list) else [k])) for k in check["value"])
    if kind == "json_fields":
        obj = _first_json(answer)
        if not isinstance(obj, dict):
            return False
        if check.get("exact_keys") and set(obj) != set(check["value"]):
            return False
        return all(k in obj and _same(obj[k], v) for k, v in check["value"].items())
    raise ValueError(f"unknown check kind {kind!r}")


#: «the answer is C», «Answer: 3», «התשובה היא 2», «תשובה: ב»: the answer named after these words wins over a
#: number or letter that only happens to appear earlier («According to paragraph 1, the answer is 3»).
_ANSWER_WORD = re.compile(r"(?:answer|תשובה|התשובה)\W{0,12}(?:is\W{0,3}|היא\W{0,3})?", re.I)


def _pick(reply: str, alphabet: str) -> str | None:
    """The option a reply chose: the reply that IS an option, else the option named after «answer»/«תשובה», else
    the first option that stands alone. Letters are matched upper-case only — the English article «a» is not
    option A, and a Hebrew lead-in cannot contain one, so lower-case would tax English alone (second reader,
    2026-11-05) — except when the whole reply is one letter."""
    r = reply.strip().strip(".:)(*[] \n\t\"'")
    if len(r) == 1 and r.upper() in alphabet:
        return r.upper()
    m = _ANSWER_WORD.search(reply)
    if m:
        tail = re.match(r"\W*\(?([" + alphabet + "])(?![\\w])", reply[m.end():])
        if tail:
            return tail.group(1)
    m = re.search(r"(?<![\w.,])([" + alphabet + r"])(?![\w])", reply)
    return m.group(1) if m else None


def correct(task: str, answer: str, expected) -> bool:
    a = str(answer or "").strip()
    if task.startswith("belebele"):
        return _pick(a, "1234") == str(expected)
    if task.startswith("gmmlu"):
        return _pick(a, "ABCD") == str(expected)
    if task == "office_he":
        return check_office(a, expected)
    raise ValueError(task)


def chrf_stats(hyp: str, ref: str, order: int = 6) -> list:
    """Per-sentence character n-gram statistics (whitespace removed), as sacrebleu's chrF collects them."""
    h, r = re.sub(r"\s+", "", hyp or ""), re.sub(r"\s+", "", ref or "")
    out = []
    for n in range(1, order + 1):
        hc = Counter(h[i:i + n] for i in range(len(h) - n + 1))
        rc = Counter(r[i:i + n] for i in range(len(r) - n + 1))
        out += [sum(hc.values()), sum(rc.values()), sum((hc & rc).values())]
    return out


def chrf(stats: list, beta: float = 2.0) -> float:
    """Corpus chrF from summed statistics: the F-beta of each n-gram order, averaged over the orders seen."""
    f2, score, eff = beta * beta, 0.0, 0
    for i in range(0, len(stats), 3):
        nh, nr, nm = stats[i:i + 3]
        if nh > 0 and nr > 0:
            eff += 1
            p, r = nm / nh, nm / nr
            score += (1 + f2) * p * r / (f2 * p + r) if (p + r) > 0 else 0.0
    return 100.0 * score / eff if eff else 0.0


def _boot(values: list, stat, reps: int = 1000, seed: int = 1) -> tuple:
    if not values:
        return (None, None)
    rnd, n, xs = random.Random(seed), len(values), []
    for _ in range(reps):
        xs.append(stat([values[rnd.randrange(n)] for _ in range(n)]))
    xs.sort()
    return (xs[int(0.025 * reps)], xs[int(0.975 * reps) - 1])


def _acc(v: list) -> float:
    return 100.0 * sum(v) / len(v) if v else 0.0


def _chrf_of(v: list) -> float:
    return chrf([sum(c) for c in zip(*v)]) if v else 0.0


def score(d: Path) -> dict:
    expected = {(t[0], t[1]): t[3] for t in tasks(d)}
    models = []
    for path in sorted((d / "runs").glob("*.jsonl")):
        recs = _load(path)
        envs = [r for r in recs if r.get("kind") == "env"]
        last = {}
        for r in recs:
            if r.get("kind") == "answer" and (r["task"], r["id"]) in expected:
                key = (r["task"], r["id"])
                if not r.get("error") or key not in last or last[key].get("error"):
                    last[key] = r                       # a real answer is never replaced by a later failure
        per = {}
        for (task, iid), r in last.items():
            if (task, iid) not in expected or r.get("error"):
                continue                                # a failed question is not an answer: it is asked again
            if task.startswith("flores"):
                per.setdefault(task, []).append(chrf_stats(r.get("answer", ""), expected[(task, iid)]))
            else:
                per.setdefault(task, []).append(1 if correct(task, r.get("answer", ""), expected[(task, iid)]) else 0)
        scores = {}
        for task, v in per.items():
            f = _chrf_of if task.startswith("flores") else _acc
            lo, hi = _boot(v, f)
            scores[task] = {"value": round(f(v), 1), "lo": round(lo, 1), "hi": round(hi, 1), "n": len(v),
                            "metric": "chrF" if task.startswith("flores") else "accuracy %"}
        unparsed = sum(1 for (t, _), r in last.items() if t.startswith(("belebele", "gmmlu"))
                       and not re.search(r"[1-4ABCDabcd]", r.get("answer", "")))
        errors = sum(1 for r in last.values() if r.get("error"))

        def composite(weights: dict) -> dict | None:
            have = {k: w for k, w in weights.items() if k in per}
            if not have:
                return None
            tot = sum(have.values())
            val = sum(scores[k]["value"] * w for k, w in have.items()) / tot
            rnd, xs = random.Random(7), []
            for _ in range(1000):
                acc = 0.0
                for k, w in have.items():
                    v = per[k]
                    sample = [v[rnd.randrange(len(v))] for _ in range(len(v))]
                    acc += (_chrf_of(sample) if k.startswith("flores") else _acc(sample)) * w
                xs.append(acc / tot)
            xs.sort()
            return {"value": round(val, 1), "lo": round(xs[25], 1), "hi": round(xs[974], 1),
                    "parts": sorted(have), "complete": len(have) == len(weights)}

        speeds = [r for r in recs if r.get("kind") == "speed" and not r.get("error") and r.get("gen_s")]
        quiet = [r for r in speeds if (r.get("load1") or 0) < QUIET_LOAD]
        speeds = quiet or speeds
        timed = [r for r in last.values() if r.get("prompt_s") and not r.get("swapped") and not r.get("error")]

        def med(xs: list):
            xs = sorted(x for x in xs if x is not None)
            return round(xs[len(xs) // 2], 2) if xs else None

        speed = {
            "gen_tps": med([r["gen_tokens"] / r["gen_s"] for r in speeds]),
            "prompt_tps": med([r["prompt_tokens"] / r["prompt_s"] for r in speeds if r.get("prompt_s")]),
            "ttft_s": med([r["prompt_s"] + r.get("load_s", 0) for r in speeds]),
            "mem_gb": med([(r.get("size_bytes") or 0) / 1e9 for r in speeds if r.get("size_bytes")]),
            "vram_gb": med([(r.get("vram_bytes") or 0) / 1e9 for r in speeds if r.get("size_bytes")]),
            "context": med([r.get("context") for r in speeds]),
            "answer_s_median": med([r["wall_s"] for r in timed]),
            "load1_max": max([r.get("load1") or 0 for r in speeds], default=None),
            "runs": len(speeds),
        }
        models.append({"model": envs[-1]["model"]["name"] if envs else path.stem, "env": envs[-1] if envs else {},
                       "scores": scores, "hebrew": composite(HEBREW_WEIGHTS), "english": composite(ENGLISH_WEIGHTS),
                       "speed": speed, "answered": sum(1 for r in last.values() if not r.get("error")),
                       "expected": len(expected), "unparsed_mcq": unparsed, "errors": errors,
                       "aborted": _aborted(recs)})
    # Ranks among COMPLETE runs only: a model half-way through its questions has an interval nobody can compare.
    # A model ranks below another only when the other's whole interval lies above its own (rank = 1 + how many such
    # models there are), so models whose difference is inside the noise share a rank.
    whole = [m for m in models if m["answered"] >= m["expected"] and not m["errors"]]
    for key in ("hebrew", "english"):
        for m in models:
            if m[key]:
                m[key]["rank"] = (1 + sum(1 for o in whole if o is not m and o[key] and o[key]["lo"] > m[key]["hi"])
                                  if m in whole else None)
    meta = json.loads((d / "sets" / "meta.json").read_text(encoding="utf-8")) if (d / "sets" / "meta.json").exists() else {}
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sets": meta,
           "weights": {"hebrew": HEBREW_WEIGHTS, "english": ENGLISH_WEIGHTS},
           "private_office_set": (d / "private" / "office.jsonl").exists(),
           "models": sorted(models, key=lambda m: -(m["hebrew"] or {"value": -1})["value"])}
    (d / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def _aborted(recs: list):
    """Why a run stopped, when it stopped and no answer came after: a later resume that answered clears it."""
    reason = None
    for r in recs:
        if r.get("kind") == "abort":
            reason = r.get("reason") or "aborted"
        elif r.get("kind") == "answer" and not r.get("error"):
            reason = None
    return reason


def status(d: Path) -> None:
    exp = len(tasks(d))
    for path in sorted((d / "runs").glob("*.jsonl")):
        recs = _load(path)
        ans = {(r["task"], r["id"]) for r in recs if r.get("kind") == "answer"}
        sp = sum(1 for r in recs if r.get("kind") == "speed")
        err = sum(1 for r in recs if r.get("error"))
        print(f"{path.stem}: {len(ans)}/{exp} answered, {sp} speed runs, {err} errors")


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="harness.py")
    ap.add_argument("verb", choices=["fetch", "run", "speed", "score", "status"])
    ap.add_argument("dir")
    ap.add_argument("models", nargs="*")
    ap.add_argument("--url", default=os.environ.get("OLLAMA_URL", "http://ollama:11434"))
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)
    d = Path(a.dir)
    if a.verb == "fetch":
        fetch(d)
    elif a.verb == "run":
        for m in a.models:
            run(d, m, a.url, a.limit)
    elif a.verb == "speed":
        for m in a.models:
            speed(d, m, a.url)
    elif a.verb == "score":
        res = score(d)
        for m in res["models"]:
            h, e = m["hebrew"] or {}, m["english"] or {}
            print(f"{m['model']:34} he {h.get('value')} [{h.get('lo')}–{h.get('hi')}]  en {e.get('value')}  "
                  f"gen {m['speed']['gen_tps']} tok/s  {m['answered']}/{m['expected']}")
    else:
        status(d)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

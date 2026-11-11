"""One speaker per transcription segment (DGO-1627).

A meeting reaches this service as ONE mixed recording: Jibri composites every participant into a
single mp4, so "who spoke" cannot be read off a track — it has to be inferred from the voices.
The owner's report that every line of a meeting came out as «שלמה» is this gap, not a typo: with no
speaker field at all, the page has one name to give.

THE METHOD is the one ivrit-py's `engine="ivrit"` uses (MIT, ivrit-ai/ivrit-py, its
`ivrit/diarization.py` -> `IvritDiarizationEngine`): one SpeechBrain ECAPA-TDNN embedding per
transcription segment (`speechbrain/spkrec-ecapa-voxceleb`, Apache-2.0), then agglomerative
clustering of those embeddings — the number of voices fixed by the caller when it is known, found by
the clustering otherwise.

WHY SEGMENT-LEVEL AND NOT FRAME-LEVEL. What this service returns is a list of segments, and the
meeting page draws one line per segment (apps/meet/tools/flow/build_flow.py: `turns`). A label per
segment is therefore exactly the answer to "who said this line". Frame-level diarization (pyannote's
shape, the fallback in ai/context/research/dgo-1627-diarization.md) buys boundaries *inside* a
segment, at a CPU cost an order of magnitude larger — and this page cannot show them.

NOTHING IS DOWNLOADED AT RUN TIME and nothing is asked of a person: the model is baked into the
image at build time (`DEFAULT_MODEL`, see Dockerfile.asr) and loaded from that directory. The repo is
public and ungated (verified 2026-11-09: huggingface.co/api/models/speechbrain/spkrec-ecapa-voxceleb
-> gated=false, apache-2.0), so no account and no token are involved. No outside service: the audio
never leaves the office and no text is sent anywhere (DGO-1407).

The labels are STABLE and impersonal: «דובר 1» is whoever spoke first, «דובר 2» the next voice to
appear, and so on. Naming them is a person's job and happens on the meeting page
(`apps/meet/tools/flow/build_flow.py` maps a label to a name when the analysis gives one); an
algorithm must not invent somebody's name.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Iterator

import numpy as np

LOG = logging.getLogger("asr.diarize")

# Baked into the image (Dockerfile.asr: huggingface_hub.snapshot_download at a pinned revision).
DEFAULT_MODEL = os.environ.get("SPEECH_DIARIZE_MODEL", "/opt/diarize")
MODEL_REPO = "speechbrain/spkrec-ecapa-voxceleb"
MODEL_REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
RATE = 16000

# Cosine distance above which two segments are different voices. ECAPA on 1-3 s of the same speaker
# sits well under this and different speakers well over it; the value comes from the fixture run
# recorded in the item (see ai/context/research/dgo-1627-diarization.md), and it is a setting so a
# meeting can be re-run without a build.
THRESHOLD = float(os.environ.get("SPEECH_DIARIZE_THRESHOLD", "0.62"))
MIN_SECONDS = float(os.environ.get("SPEECH_DIARIZE_MIN_SECONDS", "1.0"))
MAX_SPEAKERS = int(os.environ.get("SPEECH_DIARIZE_MAX_SPEAKERS", "8"))
MIN_SEGMENTS = int(os.environ.get("SPEECH_DIARIZE_MIN_SEGMENTS", "3"))
LABEL = "דובר"

_encoder: Any = None
_encoder_lock = threading.Lock()


def release() -> None:
    """Drop the encoder and its memory. The ASR model is released on an idle timer for the same
    reason: this box has 2.5 GiB for the whole container and the ASR model's peak sits close to it
    (measured in docker-compose.yml's comment), so a diarizer that stays resident eats the margin.
    The next job pays one load (about ten seconds) — the same trade the ASR already makes."""
    global _encoder
    with _encoder_lock:
        if _encoder is None:
            return
        _encoder = None
        try:
            import gc

            gc.collect()
        except Exception:  # never let housekeeping fail a job
            pass


# ── audio, streamed ────────────────────────────────────────────────────────────────────
#
# A 72-minute meeting is 69 M samples at 16 kHz; holding it whole is 276 MB of float32 on a box that
# is also holding the ASR model. So the file is decoded once, in order, and a rolling window of about
# a second of slack is kept in front of the segment being read.

def _blocks(path: str, rate: int = RATE) -> Iterator[tuple[float, np.ndarray]]:
    """(t, samples) at `rate`, mono float32, decoded in one forward pass."""
    import av

    with av.open(path) as container:
        if not container.streams.audio:
            raise ValueError(f"{path}: no audio stream")
        stream = container.streams.audio[0]
        stream.thread_type = "AUTO"
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        t = 0.0
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                data = np.asarray(out.to_ndarray(), dtype=np.float32).reshape(-1)
                if data.size:
                    yield t, data
                    t += data.size / rate
        for out in resampler.resample(None):
            data = np.asarray(out.to_ndarray(), dtype=np.float32).reshape(-1)
            if data.size:
                yield t, data
                t += data.size / rate


class _Audio:
    """Random access to [start, end) windows of one file, in one streaming pass."""

    def __init__(self, path: str, rate: int = RATE) -> None:
        self.path = path
        self.rate = rate
        self._it = _blocks(path, rate)
        self._buf = np.zeros(0, dtype=np.float32)
        self._t0 = 0.0
        self._eof = False

    def _fill(self, until: float) -> None:
        while not self._eof and self._t0 + self._buf.size / self.rate < until:
            try:
                t, data = next(self._it)
            except StopIteration:
                self._eof = True
                return
            if not self._buf.size:
                self._t0 = t
            self._buf = np.concatenate([self._buf, data]) if self._buf.size else data

    def slice(self, start: float, end: float) -> np.ndarray | None:
        """Samples of [start, end); None when that window has (almost) no audio."""
        start = max(0.0, start)
        end = max(start, end)
        if start < self._t0 - 1e-6:            # asked for a window already dropped: cannot happen
            start = self._t0                   # in time order, but never crash over it
            end = max(start, end)
        self._fill(end)
        a = int(round((start - self._t0) * self.rate))
        b = int(round((end - self._t0) * self.rate))
        a, b = max(0, a), min(self._buf.size, b)
        if b - a < int(0.2 * self.rate):
            return None
        chunk = self._buf[a:b].copy()
        drop = max(0, a - int(1.0 * self.rate))   # keep one second of slack before `start`
        if drop:
            self._buf = self._buf[drop:]
            self._t0 += drop / self.rate
        return chunk


# ── embeddings ─────────────────────────────────────────────────────────────────────────

def _load_encoder(model_dir: str = DEFAULT_MODEL) -> Any:
    """The ECAPA classifier, from the image's own directory. One per process, once."""
    global _encoder
    with _encoder_lock:
        if _encoder is not None:
            return _encoder
        import torch
        from speechbrain.inference.speaker import EncoderClassifier

        # One thread: this is a 2-core office box that must keep a core (the ASR is pinned the same
        # way). `torch.set_num_threads` is the knob that bites — speechbrain's RunOptions has no
        # thread setting (measured 2026-11-09: `num_threads` there is a TypeError).
        torch.set_num_threads(int(os.environ.get("SPEECH_DIARIZE_THREADS", "1")))
        src = model_dir if os.path.isdir(model_dir) else _fetch()
        _encoder = EncoderClassifier.from_hparams(source=src, savedir=src, run_opts={"device": "cpu"})
        LOG.info("diarize: ECAPA loaded from %s", src)
        return _encoder


def _fetch() -> str:
    """Only when the image was built without the model (a developer's container)."""
    from huggingface_hub import snapshot_download

    target = os.path.join(os.environ.get("SPEECH_MODEL_DIR", "/data/models"), "ecapa")
    LOG.warning("diarize: %s is not in the image; fetching %s (no account needed)", DEFAULT_MODEL, MODEL_REPO)
    snapshot_download(MODEL_REPO, revision=MODEL_REVISION, local_dir=target)
    return target


def embed(encoder: Any, audio: np.ndarray) -> np.ndarray:
    """One L2-normalised ECAPA embedding for one window of mono float32 at 16 kHz."""
    import torch

    with torch.inference_mode():
        vec = encoder.encode_batch(torch.from_numpy(audio).unsqueeze(0)).detach().cpu().numpy()
    vec = np.asarray(vec, dtype=np.float64).reshape(-1)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


# ── clustering ─────────────────────────────────────────────────────────────────────────

def _distances(embs: np.ndarray) -> np.ndarray:
    """Cosine distance matrix of L2-normalised embeddings."""
    sim = np.clip(embs @ embs.T, -1.0, 1.0)
    d = 1.0 - sim
    np.fill_diagonal(d, 0.0)
    return np.maximum(d, 0.0)


def agglomerate(dist: np.ndarray, *, threshold: float, n_clusters: int | None = None,
                max_clusters: int = MAX_SPEAKERS) -> list[int]:
    """Average-linkage on cosine distance: merge the two closest clusters until the closest pair is
    further apart than `threshold` (or `n_clusters` is reached, or `max_clusters` is left).

    Lance–Williams average update, so each merge is one vectorised row update (O(N^2) per merge)."""
    n = int(dist.shape[0])
    if n == 0:
        return []
    if n == 1:
        return [0]
    d = dist.astype(np.float64).copy()
    np.fill_diagonal(d, np.inf)
    sizes = np.ones(n, dtype=np.float64)
    members = {i: [i] for i in range(n)}
    alive = list(range(n))
    target = n_clusters if n_clusters else 0
    while len(alive) > 1:
        sub = d[np.ix_(alive, alive)]
        flat = int(np.argmin(sub))
        i, j = divmod(flat, len(alive))
        best = float(sub[i, j])
        if n_clusters is None:
            if best > threshold:
                break
        elif len(alive) <= max(1, target):
            break
        a, b = alive[i], alive[j]
        # average linkage: the merged distance is the size-weighted mean of the two rows
        new = (sizes[a] * d[a, :] + sizes[b] * d[b, :]) / (sizes[a] + sizes[b])
        new[a] = np.inf
        new[b] = np.inf
        d[a, :] = new
        d[:, a] = new
        d[a, a] = np.inf
        d[b, :] = np.inf
        d[:, b] = np.inf
        sizes[a] = sizes[a] + sizes[b]
        members[a] = members[a] + members.pop(b)
        alive.remove(b)
    labels = np.full(n, -1, dtype=int)
    for cluster_id, root in enumerate(sorted(alive)):
        for member in members[root]:
            labels[member] = cluster_id
    # a cap on voices: too many clusters means the threshold is looser than the recording; keep
    # merging the closest pairs until the cap holds
    if len(alive) > max_clusters:
        return _merge_to(labels, dist, max_clusters)
    return labels.tolist()


def _merge_to(labels: list[int], dist: np.ndarray, target: int) -> list[int]:
    lab = np.asarray(labels)
    while len(set(lab.tolist())) > target:
        ids = sorted(set(lab.tolist()))
        best, pair = np.inf, (ids[0], ids[1])
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                da, db = lab == a, lab == b
                value = float(dist[np.ix_(da, db)].mean())
                if value < best:
                    best, pair = value, (a, b)
        lab[lab == pair[1]] = pair[0]
    # renumber by first appearance so the ids read 0,1,2…
    order: dict[int, int] = {}
    out = []
    for value in lab.tolist():
        if value not in order:
            order[value] = len(order)
        out.append(order[value])
    return out


def _relabel_by_first_appearance(labels: list[int], starts: list[float]) -> list[int]:
    first: dict[int, float] = {}
    for label, start in zip(labels, starts):
        if label not in first or start < first[label]:
            first[label] = start
    order = {label: i for i, label in enumerate(sorted(first, key=lambda k: first[k]))}
    return [order[label] for label in labels]


# ── the public door ────────────────────────────────────────────────────────────────────

def attach(segments: list[dict[str, Any]], path: str, *, num_speakers: int | None = None,
           model_dir: str = DEFAULT_MODEL, threshold: float = THRESHOLD,
           min_seconds: float = MIN_SECONDS,
           should_stop: Any = None) -> dict[str, Any]:
    """Give every segment a `speaker` label; return the segments and the voices found."""
    if not segments:
        return {"segments": segments, "speakers": [], "method": {"engine": "none", "reason": "no segments"}}
    work = [s for s in segments if (float(s.get("end") or 0) - float(s.get("start") or 0)) >= min_seconds]
    if len(work) < MIN_SEGMENTS:
        return {"segments": segments, "speakers": [],
                "method": {"engine": "none", "reason": f"{len(work)} usable segments"}}

    encoder = _load_encoder(model_dir)
    audio = _Audio(path)
    embs: list[np.ndarray] = []
    used: list[dict[str, Any]] = []
    for seg in sorted(work, key=lambda s: float(s.get("start") or 0)):
        # a cancelled or over-time job must stop HERE too: this pass runs after the words are in and
        # can take minutes on a long meeting
        if should_stop is not None and should_stop():
            return {"segments": segments, "speakers": [],
                    "method": {"engine": "none", "reason": "stopped"}}
        window = audio.slice(float(seg.get("start") or 0), float(seg.get("end") or 0))
        if window is None:
            continue
        embs.append(embed(encoder, window))
        used.append(seg)
    if len(used) < MIN_SEGMENTS:
        return {"segments": segments, "speakers": [],
                "method": {"engine": "none", "reason": "audio missing for the segments"}}

    matrix = _distances(np.vstack(embs))
    labels = agglomerate(matrix, threshold=threshold,
                         n_clusters=int(num_speakers) if num_speakers else None)
    labels = _relabel_by_first_appearance(labels, [float(s.get("start") or 0) for s in used])

    # every segment gets a label: one too short to embed takes the label of its nearest neighbour in
    # time (a cough, a "כן" in the gap, a two-word interruption)
    by_start = {id(s): label for s, label in zip(used, labels)}
    assigned = [(seg, f"{LABEL} {by_start[id(seg)] + 1}") for seg in used]
    for seg in segments:                        # every segment gets a label: one too short to embed
        if id(seg) in by_start:                 # takes its nearest neighbour's (a cough, a "כן")
            continue
        start = float(seg.get("start") or 0)
        nearest = min(used, key=lambda s: abs(float(s.get("start") or 0) - start), default=None)
        if nearest is not None:
            assigned.append((seg, f"{LABEL} {by_start[id(nearest)] + 1}"))
    speakers_summary = group_segments([dict(seg, speaker=label) for seg, label in assigned])
    for seg, label in assigned:
        seg["speaker"] = label

    return {"segments": segments, "speakers": speakers_summary,
            "method": {"engine": "ecapa-agglomerative", "model": MODEL_REPO,
                       "revision": MODEL_REVISION, "threshold": threshold,
                       "labels": len(set(labels)), "segments": len(used)}}


def group_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-label totals, in the order the voices first appear: what the page lists as «מי דיבר»."""
    out: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for seg in segments:
        label = seg.get("speaker")
        if not label:
            continue
        entry = seen.get(label)
        if entry is None:
            entry = {"id": f"S{len(seen) + 1}", "label": label, "segments": 0, "seconds": 0.0,
                     "first": round(float(seg.get("start") or 0), 2)}
            seen[label] = entry
            out.append(entry)
        entry["segments"] += 1
        entry["seconds"] = round(entry["seconds"] + max(0.0, float(seg.get("end") or 0) - float(seg.get("start") or 0)), 1)
    for entry in out:                       # a voice with one short line is noise, not a person
        entry["thin"] = entry["segments"] < 2 or entry["seconds"] < 3.0
    out.sort(key=lambda e: e["first"])      # the order of speech, whatever order the list came in
    for i, entry in enumerate(out):
        entry["id"] = f"S{i + 1}"
    return out

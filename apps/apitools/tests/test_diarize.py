"""Speaker labels on a transcript (DGO-1627) — the assignment half of the pipeline.

The fixtures are two 12-second WAVs (16 kHz mono) cut from an office meeting (the office's own
audio, used only as a voice fixture), and the segment lists below are GIVEN, not transcribed: what
is under test here is the assignment — which line belongs to which voice — while the ASR that
produces the lines is the other half of the pipeline and is not re-run by the suite.

  two_voices.wav   one person speaks (0.0–5.0), a pause, a DIFFERENT person answers (6.0–12.0)
  one_voice.wav    the same person in two stretches (0.0–5.0, 6.0–12.0), same pause

The truth of "different person" is by construction of the fixture (the two stretches are different
voices, checked against the recording's own speaker highlight when the fixture was cut — see the
item's comment trail) and it is checked in BOTH directions: a diarizer that answers "2 speakers" to
everything fails `one_voice`, and one that answers "1 speaker" to everything fails `two_voices`.

Run where the image's dependencies are present (the ASR image: torch + speechbrain + the ECAPA model
at /opt/diarize), otherwise the module skips:

    docker run --rm -v "$PWD/apps/apitools:/w" -w /w dgo-apitools-asr:diarize \
        python -m pytest tests/test_diarize.py -q
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("speechbrain")

from asr import diarize  # noqa: E402  (after the skip: importing it loads nothing by itself)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TWO = os.path.join(FIXTURES, "diarize-two-voices.wav")
ONE = os.path.join(FIXTURES, "diarize-one-voice.wav")


def segments(*spans: tuple[float, float]) -> list[dict]:
    return [{"id": i + 1, "start": a, "end": b, "text": f"line {i + 1}"} for i, (a, b) in enumerate(spans)]


# two people: four short turns each, in the shape the ASR returns them
TWO_SPANS = [(0.2, 2.4), (2.5, 4.9), (6.1, 8.4), (8.5, 11.8)]
ONE_SPANS = [(0.2, 2.4), (2.5, 4.9), (6.1, 8.4), (8.5, 11.8)]


@pytest.mark.skipif(not os.path.exists(TWO), reason="fixture missing")
def test_two_voices_are_two_speakers() -> None:
    got = diarize.attach(segments(*TWO_SPANS), TWO)
    labels = [s.get("speaker") for s in got["segments"]]
    assert len(got["speakers"]) == 2, f"a two-voice clip gave {len(got['speakers'])} speaker(s): {labels}"
    # the change falls where the second person starts talking, not somewhere else
    assert labels[0] == labels[1] != labels[2] == labels[3], labels
    assert all(labels), "every segment must carry a label"


@pytest.mark.skipif(not os.path.exists(ONE), reason="fixture missing")
def test_one_voice_is_one_speaker() -> None:
    got = diarize.attach(segments(*ONE_SPANS), ONE)
    labels = [s.get("speaker") for s in got["segments"]]
    assert len(got["speakers"]) == 1, f"a one-voice clip gave {len(got['speakers'])} speakers: {labels}"
    assert len(set(labels)) == 1, labels


@pytest.mark.skipif(not os.path.exists(TWO), reason="fixture missing")
def test_labels_are_numbered_by_first_appearance() -> None:
    got = diarize.attach(segments(*TWO_SPANS), TWO)
    first = got["segments"][0]["speaker"]
    assert first == f"{diarize.LABEL} 1", f"the first voice must be «{diarize.LABEL} 1», got {first}"
    # a second meeting must not depend on clustering internals: the ids follow the order of speech
    assert got["speakers"][0]["label"] == first
    assert [s["label"] for s in got["speakers"]] == [f"{diarize.LABEL} {i + 1}" for i in range(len(got["speakers"]))]


@pytest.mark.skipif(not os.path.exists(TWO), reason="fixture missing")
def test_the_number_of_voices_can_be_told() -> None:
    """The meeting knows its roster; «the two of us» must be honoured, not second-guessed.

    Told «2» about a clip that holds two voices, the clustering must not answer three — that is
    the case the option exists for, and it is the case that can fail (a fixture with one voice is
    answered «1» even without the option)."""
    told = diarize.attach(segments(*TWO_SPANS), TWO, num_speakers=2)
    assert len({s["speaker"] for s in told["segments"]}) == 2, [s.get("speaker") for s in told["segments"]]
    got = diarize.attach(segments(*ONE_SPANS), ONE, num_speakers=1)
    assert len({s["speaker"] for s in got["segments"]}) == 1


@pytest.mark.skipif(not os.path.exists(TWO), reason="fixture missing")
def test_a_too_short_line_borrows_its_neighbour() -> None:
    spans = [(0.2, 2.4), (2.5, 4.9), (5.0, 5.3), (6.1, 11.8)]   # the third is 0.3 s of "כן"
    got = diarize.attach(segments(*spans), TWO)
    labels = [s.get("speaker") for s in got["segments"]]
    assert labels[2], "a short line must still be labelled"
    assert labels[2] in (labels[1], labels[3])


@pytest.mark.skipif(not os.path.exists(TWO), reason="fixture missing")
def test_speakers_summary_counts_the_lines() -> None:
    got = diarize.attach(segments(*TWO_SPANS), TWO)
    total = sum(s["segments"] for s in got["speakers"])
    assert total == len(got["segments"])
    assert all(s["seconds"] > 0 for s in got["speakers"])

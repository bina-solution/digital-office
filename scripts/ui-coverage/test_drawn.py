#!/usr/bin/env python3
"""The rule every photograph waits for (drawn.py), held to its word — run by gate G72.

What a screen has to be before it may be photographed or measured, how long it may take, and when
the camera stops waiting are decisions: three tools read them (the live map, the simulation's map,
its flow suites), and a change that made a skeleton count as a screen would turn every one of their
pictures into a picture of placeholders without a single test going red. The cases are drawn.py's
own (`--self-test`): screens that are scripted look by look — there at once, behind a skeleton for
three seconds, for six, for ever; a list that grows; a page that navigates; an animation's time
that must be kept without becoming the screen's.

Run: python3 scripts/ui-coverage/test_drawn.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import drawn  # noqa: E402

if __name__ == "__main__":
    sys.exit(drawn._self_test())

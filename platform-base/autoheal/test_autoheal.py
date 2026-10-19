"""autoheal's own replay of the incidents it was written for.

`autoheal.py --selftest` was run by nothing — no gate, no workflow, no hook — so the claim "this
restarts worker-1 and not worker-2" rested on nobody having broken it since. The tests gate (G72)
runs every `test_*` file; this one is that self-test, as written, and exits with its verdict.
"""
import pathlib
import runpy
import sys

sys.argv = ["autoheal.py", "--selftest"]
runpy.run_path(str(pathlib.Path(__file__).with_name("autoheal.py")), run_name="__main__")

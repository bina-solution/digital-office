"""The door's rule, run by the gate that runs every plane's tests (G72).

`platform-base/traefik/socket-proxy/proxy.py --selftest` decides request lines: the paths a docker
provider reads (versioned and not) are allowed; writes, image/volume reads, dot segments, encoded
separators and a malformed line are refused. It decides request heads: exactly one request with no
body goes to the engine byte for byte, or nothing does (DGO-991). And on a fake engine it proves that
a later request on the same connection never reaches it. This runs it, so "the edge's door refuses
more than it serves" is a claim a gate makes rather than one a session remembers making.

THE CASE THAT IS WHY THIS TEST EXISTS AT ALL: the door's first version matched paths literally and
refused `/v1.24/version` — the docker client versions every path and traefik hardcodes API 1.24. The
edge came up with zero routers and answered 404 for every host while traefik reported healthy. That
request line is one of the cases below, on the ALLOW side.
"""
import pathlib
import runpy
import sys

sys.argv = ["proxy.py", "--selftest"]
runpy.run_path(str(pathlib.Path(__file__).with_name("socket-proxy") / "proxy.py"), run_name="__main__")

#!/usr/bin/env python3
"""bbox agent — launcher. The CLI lives in scripts/bbox_agent/ (cli.py has the verbs, client.py the
contract client + token cache, render.py the live terminal view). Python 3.9, standard library only,
so it runs natively on the Mac host as well as on every Linux docker host."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bbox_agent.cli import main  # noqa: E402

sys.exit(main())

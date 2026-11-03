#!/usr/bin/env python3
"""CLI compatibility client for the internal Browser42 task runner."""

import json
import os
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


endpoint = os.environ.get("BROWSER42_TASK_RUNNER", "http://127.0.0.1:8766/v1/task")
# Client timeout must exceed runner budget (300s) + queue wait (30s) with margin.
timeout = int(os.environ.get("BROWSER42_TASK_CLIENT_SECONDS", "340"))
request_id = os.environ.get("BROWSER42_REQUEST_ID") or uuid.uuid4().hex
headers = {"Content-Type": "application/json"}
# The runner's own token (DGO-1152): this client runs inside the runner's container (`docker exec`, from
# `bbox b42 task`), where the runner minted it into AGENT_TOKEN_FILE.
try:
    with open(os.environ.get("AGENT_TOKEN_FILE") or "/nonexistent", encoding="utf-8") as fh:
        token = fh.read().strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
except OSError:
    pass
request = Request(endpoint, data=json.dumps({"argv": sys.argv[1:], "requestId": request_id}).encode("utf-8"), headers=headers, method="POST")
try:
    with urlopen(request, timeout=timeout) as response:
        sys.stdout.write(response.read().decode("utf-8"))
except HTTPError as error:
    sys.stdout.write(error.read().decode("utf-8"))
    sys.exit(2)
except URLError as error:
    print(json.dumps({"ok": False, "error": {"code": "runner_unavailable", "message": str(error.reason)}}))
    sys.exit(2)
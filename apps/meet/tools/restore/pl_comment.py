#!/usr/bin/env python3
"""Post one comment on a Plane MEET item, from inside project-pln-fireplace.
usage: pl_comment.py ISSUE_ID HTML_FILE   (the key comes from plan.api_key(); it is never printed)"""
import sys
sys.path.insert(0, "/tmp")
import plan  # noqa: E402

iid, path = sys.argv[1], sys.argv[2]
body = open(path, encoding="utf-8").read()
k = plan.api_key()
H = {"X-API-Key": k}
pid = "65aebff2-e6e0-4257-974f-0ff7942267cc"      # project MEET (checked: identifier MEET)
url = f"{plan.BASE}/api/v1/workspaces/bina/projects/{pid}/issues/{iid}/comments/"
out, code = plan.http("POST", url, body={"comment_html": body}, headers=H)
print("comment:", code, (out or {}).get("id"), (out or {}).get("error", "")[:200])

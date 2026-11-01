#!/usr/bin/env python3
"""Create N8N webhook test workflows for integration validation.

Uses the N8N REST API to create and activate simple webhook workflows
that test each integration (Google Sheets, Drive, Gmail, Gemini, Redis, Postgres).
"""

import json
import os
import sys

import requests

N8N_URL = os.getenv("N8N_URL", "http://localhost:5678")
N8N_API_KEY = os.getenv("N8N_API_KEY", "")

HEADERS = {
    "X-N8N-API-KEY": N8N_API_KEY,
    "Content-Type": "application/json",
}

# Credential IDs (from the database)
CREDS = {
    "googleSheetsOAuth2Api": {"id": "e2knIZpw8YF0QBAB", "name": "Google Sheets person17@example.com"},
    "googleDriveOAuth2Api": {"id": "KirWFwoFdEFmnN0R", "name": "Google Drive person17@example.com"},
    "gmailOAuth2": {"id": "jft0CdgvgPNvaLNn", "name": "Gmail person17@example.com"},
    "googlePalmApi": {"id": "6mfcsdRaqQ4IdQ8Y", "name": "ai-studio-bs-extraction"},
    "redis": {"id": "BoJE1odVZ6MBcpax", "name": "Redis Local Account"},
    "postgres": {"id": "tJ195ajNq1kQveRG", "name": "N8N DB"},
}


def _webhook_node(path: str):
    return {
        "parameters": {
            "path": path,
            "httpMethod": "POST",
            "responseMode": "responseNode",
            "options": {},
        },
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [200, 300],
        "id": "webhook-1",
        "name": "Webhook",
        "webhookId": path.replace("/", "-"),
    }


def _respond_node():
    return {
        "parameters": {
            "respondWith": "allIncomingItems",
            "options": {},
        },
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": [600, 300],
        "id": "respond-1",
        "name": "Respond",
    }


def _conn(src: str, dst: str):
    return {src: {"main": [[{"node": dst, "type": "main", "index": 0}]]}}


# ---------------------------------------------------------------------------
# Workflow definitions
# ---------------------------------------------------------------------------


def gsheet_workflow():
    return {
        "name": "[FV] Test Integration - Google Sheets",
        "nodes": [
            _webhook_node("test-integration/gsheet"),
            {
                "parameters": {
                    "authentication": "oAuth2",
                    "documentId": {
                        "__rl": True,
                        "value": "1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo",
                        "mode": "list",
                        "cachedResultName": "AutomationValues",
                        "cachedResultUrl": "https://docs.google.com/spreadsheets/d/1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo/edit?usp=drivesdk",
                    },
                    "sheetName": {
                        "__rl": True,
                        "value": 1467881049,
                        "mode": "list",
                        "cachedResultName": "הגדרות",
                    },
                    "options": {},
                },
                "type": "n8n-nodes-base.googleSheets",
                "typeVersion": 4.5,
                "position": [400, 300],
                "id": "gsheet-1",
                "name": "Google Sheets",
                "credentials": {"googleSheetsOAuth2Api": CREDS["googleSheetsOAuth2Api"]},
            },
            _respond_node(),
        ],
        "connections": {
            **_conn("Webhook", "Google Sheets"),
            **_conn("Google Sheets", "Respond"),
        },
        "settings": {"executionOrder": "v1"},
    }


def gdrive_workflow():
    return {
        "name": "[FV] Test Integration - Google Drive",
        "nodes": [
            _webhook_node("test-integration/gdrive"),
            {
                "parameters": {
                    "resource": "fileFolder",
                    "returnAll": False,
                    "limit": 3,
                    "filter": {
                        "folderId": {
                            "__rl": True,
                            "value": "root",
                            "mode": "list",
                            "cachedResultName": "/ (Root folder)",
                        },
                        "whatToSearch": "files",
                    },
                    "options": {},
                },
                "type": "n8n-nodes-base.googleDrive",
                "typeVersion": 3,
                "position": [400, 300],
                "id": "gdrive-1",
                "name": "Google Drive",
                "credentials": {"googleDriveOAuth2Api": CREDS["googleDriveOAuth2Api"]},
            },
            _respond_node(),
        ],
        "connections": {
            **_conn("Webhook", "Google Drive"),
            **_conn("Google Drive", "Respond"),
        },
        "settings": {"executionOrder": "v1"},
    }


def gmail_workflow():
    return {
        "name": "[FV] Test Integration - Gmail",
        "nodes": [
            _webhook_node("test-integration/gmail"),
            {
                "parameters": {
                    "operation": "getAll",
                    "returnAll": False,
                    "limit": 3,
                    "options": {},
                },
                "type": "n8n-nodes-base.gmail",
                "typeVersion": 2.1,
                "position": [400, 300],
                "id": "gmail-1",
                "name": "Gmail",
                "credentials": {"gmailOAuth2": CREDS["gmailOAuth2"]},
            },
            _respond_node(),
        ],
        "connections": {
            **_conn("Webhook", "Gmail"),
            **_conn("Gmail", "Respond"),
        },
        "settings": {"executionOrder": "v1"},
    }


def gemini_workflow():
    return {
        "name": "[FV] Test Integration - Gemini",
        "nodes": [
            _webhook_node("test-integration/gemini"),
            {
                "parameters": {
                    "modelId": {
                        "__rl": True,
                        "mode": "list",
                        "value": "models/gemini-2.5-pro",
                        "cachedResultName": "models/gemini-2.5-pro",
                    },
                    "messages": {
                        "values": [
                            {"content": "={{ $json.body.prompt || 'Reply with the single word OK' }}"}
                        ]
                    },
                    "options": {},
                },
                "type": "@n8n/n8n-nodes-langchain.googleGemini",
                "typeVersion": 1,
                "position": [400, 300],
                "id": "gemini-1",
                "name": "Gemini",
                "credentials": {"googlePalmApi": CREDS["googlePalmApi"]},
            },
            _respond_node(),
        ],
        "connections": {
            **_conn("Webhook", "Gemini"),
            **_conn("Gemini", "Respond"),
        },
        "settings": {"executionOrder": "v1"},
    }


WORKFLOWS = {
    "gsheet": gsheet_workflow,
    "gdrive": gdrive_workflow,
    "gmail": gmail_workflow,
    "gemini": gemini_workflow,
}


def create_and_activate(name: str, wf_def: dict) -> dict:
    """Create a workflow and activate it. Returns API response."""
    # Check if exists already
    resp = requests.get(
        f"{N8N_URL}/api/v1/workflows",
        headers=HEADERS,
        params={"limit": 250},
        timeout=30,
    )
    resp.raise_for_status()
    existing = resp.json().get("data", [])
    for w in existing:
        if w["name"] == wf_def["name"]:
            print(f"  ✓ Already exists: {w['name']} (id={w['id']}, active={w['active']})")
            if not w["active"]:
                act = requests.post(
                    f"{N8N_URL}/api/v1/workflows/{w['id']}/activate",
                    headers=HEADERS,
                    timeout=30,
                )
                if act.ok:
                    print(f"    → Activated")
                else:
                    print(f"    → Activation failed: {act.text[:200]}")
            return w

    resp = requests.post(
        f"{N8N_URL}/api/v1/workflows",
        headers=HEADERS,
        json=wf_def,
        timeout=30,
    )
    resp.raise_for_status()
    created = resp.json()
    wf_id = created["id"]
    print(f"  + Created: {wf_def['name']} (id={wf_id})")

    act = requests.post(
        f"{N8N_URL}/api/v1/workflows/{wf_id}/activate",
        headers=HEADERS,
        timeout=30,
    )
    if act.ok:
        print(f"    → Activated")
    else:
        print(f"    → Activation failed: {act.text[:200]}")

    return created


def main():
    if not N8N_API_KEY:
        print("N8N_API_KEY not set. Cannot create workflows.", file=sys.stderr)
        return 1

    print(f"Creating N8N test workflows at {N8N_URL}…\n")

    targets = sys.argv[1:] if len(sys.argv) > 1 else list(WORKFLOWS.keys())
    for name in targets:
        factory = WORKFLOWS.get(name)
        if not factory:
            print(f"  ? Unknown workflow: {name}")
            continue
        try:
            create_and_activate(name, factory())
        except Exception as exc:
            print(f"  ✗ {name} failed: {exc}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

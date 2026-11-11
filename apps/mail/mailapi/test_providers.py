# -*- coding: utf-8 -*-
"""Mail's connect list (/providers): a consent way names the consent it opens (EXU-19).

The console's connect wizard opens a consent through the app's own relayed start when the app's tile is served on
that office, and otherwise through connections' own start, which knows a consent only by its catalog id
(platform-base/connections/providers/30-google.yaml: google-workspace-grant). The way's protocol (mail_gmail_oauth)
is no catalog id: asked by it, connections answers 404 «not an oauth connection», measured four times in one day on
Exampleu's Files. So the way says which grant it opens:

    python3 -m pytest apps/mail/mailapi/test_providers.py -q
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


@pytest.fixture
def client():
    import profiles
    profiles._started = True            # no background reconciler in a unit test
    import service
    service.app.testing = True
    return service.app.test_client()


def test_a_consent_way_names_the_grant_it_opens(client):
    provs = client.get("/providers").get_json()["providers"]
    consent = [m for p in provs for m in p["auth_methods"] if m.get("start_url") and not m.get("needs")]
    assert [m["protocol"] for m in consent] == ["mail_gmail_oauth"]
    # the grant mailview's own start asks connections for (mailview/app.py, /oauth/google/start)
    assert consent[0].get("grant") == "google-workspace-grant"


def test_a_way_with_no_consent_window_names_no_grant(client):
    provs = client.get("/providers").get_json()["providers"]
    assert [m["protocol"] for p in provs for m in p["auth_methods"] if m.get("grant")] == ["mail_gmail_oauth"]

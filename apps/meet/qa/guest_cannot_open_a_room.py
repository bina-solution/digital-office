#!/usr/bin/env python3
"""A meeting link gives a guest that meeting and nothing else (DGO-1633): from OUTSIDE the office, as an anonymous
guest, ask the office's meet to open a room nobody opened. It must refuse.

    python3 apps/meet/qa/guest_cannot_open_a_room.py meet.<office domain>

Meet runs Jitsi's secure domain (docker-compose.yml: ENABLE_AUTH, AUTH_TYPE=jwt, ENABLE_GUESTS): a signed-in host
opens a room with the console's token, and a guest only joins a room that is already open. A guest who could
open rooms of their own would have the office's video bridge, its recorder and its TURN server for anything.

The guest's way in is the page's own: BOSH at https://<meet>/http-bind, SASL ANONYMOUS on the guest domain,
then the conference request to the focus (jicofo) — what the meeting page sends before it shows a room. Standard
library only; GET/POST to the meet host and nothing else. Exit 0 when the office refuses (the escape fails),
1 when it opens the room, 2 when the probe could not get as far as asking.
"""
import random
import re
import secrets
import ssl
import sys
import urllib.request

NS = "http://jabber.org/protocol/httpbind"


class Bosh:
    def __init__(self, url, to):
        self.url, self.to, self.rid, self.sid = url, to, random.randint(10**9, 2 * 10**9), None
        self.ctx = ssl.create_default_context()

    def post(self, inner="", **attrs):
        self.rid += 1
        a = {"rid": str(self.rid), "xmlns": NS}
        if self.sid:
            a["sid"] = self.sid
        a.update(attrs)
        body = "<body " + " ".join(f"{k}='{v}'" for k, v in a.items()) + (f">{inner}</body>" if inner else "/>")
        req = urllib.request.Request(self.url, body.encode(), {"Content-Type": "text/xml; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=30, context=self.ctx) as r:
            return r.read().decode("utf-8", "replace")

    def open(self):
        got = self.post(to=self.to, ver="1.6", wait="10", hold="1", content="text/xml; charset=utf-8",
                        **{"xml:lang": "en", "xmpp:version": "1.0", "xmlns:xmpp": "urn:xmpp:xbosh"})
        m = re.search(r"sid=['\"]([^'\"]+)", got)
        if not m:
            raise RuntimeError("no BOSH session: " + got[:200])
        self.sid = m.group(1)
        return got

    def wait_for(self, pattern, inner="", tries=4, **attrs):
        got = self.post(inner, **attrs)
        for _ in range(tries):
            if re.search(pattern, got):
                return got
            got = self.post()
        return got


def main(meet):
    room = "dgo1633-probe-" + secrets.token_hex(6)
    b = Bosh(f"https://{meet}/http-bind?room={room}", "guest.meet.jitsi")
    feats = b.open()
    if "ANONYMOUS" not in feats:
        feats = b.post()
    if "ANONYMOUS" not in feats:
        print(f"meet {meet}: the guest domain offers no anonymous sign-in — guests cannot join at all")
        return 2
    got = b.wait_for(r"<success|<failure", "<auth xmlns='urn:ietf:params:xml:ns:xmpp-sasl' mechanism='ANONYMOUS'/>")
    if "<success" not in got:
        print(f"meet {meet}: anonymous sign-in refused: {got[:160]}")
        return 2
    b.post(to="guest.meet.jitsi", **{"xml:lang": "en", "xmpp:restart": "true", "xmlns:xmpp": "urn:xmpp:xbosh"})
    got = b.wait_for(r"<jid>", "<iq type='set' id='bind_1' xmlns='jabber:client'>"
                               "<bind xmlns='urn:ietf:params:xml:ns:xmpp-bind'/></iq>")
    jid = re.search(r"<jid>([^<]+)</jid>", got)
    if not jid:
        print(f"meet {meet}: no resource bound: {got[:160]}")
        return 2
    ask = (f"<iq type='set' to='focus.meet.jitsi' id='conf_1' xmlns='jabber:client'>"
           f"<conference xmlns='http://jitsi.org/protocol/focus' room='{room}@muc.meet.jitsi' "
           f"machine-uid='{secrets.token_hex(16)}'/></iq>")
    got = b.wait_for(r"id=['\"]conf_1['\"]", ask, tries=6)
    iq = re.search(r"<iq[^>]*id=['\"]conf_1['\"].*?(?:</iq>|/>)", got, re.S)
    answer = iq.group(0) if iq else got
    b.post(type="terminate")
    if re.search(r"type=['\"]error['\"]", answer) and "not-authorized" in answer:
        print(f"ok: meet {meet} refused the guest {jid.group(1).split('@')[0][:6]}… a room nobody opened "
              f"({room}): not-authorized — a guest joins only a host's meeting")
        return 0
    if re.search(r"ready=['\"]true['\"]", answer):
        print(f"FAIL: meet {meet} OPENED {room} for an anonymous guest — anyone can hold meetings on this office")
        return 1
    print(f"meet {meet}: unexpected answer to the conference request: {answer[:240]}")
    return 2


if __name__ == "__main__":
    if len(sys.argv) != 2 or "/" in sys.argv[1]:
        sys.exit(__doc__.split("\n\n")[1])
    sys.exit(main(sys.argv[1]))

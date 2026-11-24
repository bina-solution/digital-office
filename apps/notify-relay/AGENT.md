# notify-relay — «ממסר ההתראות»

**What it is for.** An office that runs no notice board of its own (the MacBook and the Dell; the board is
`platform-base/notifications`) still has posters: dgo-extend, the machine app, autoheal, Azaria, the n8n workflows,
esign. All of them post to `http://notifications:8977`, and on such an office that name answered nothing. This app
takes the name and carries every `POST /api/notifications` to the herd's board on the hub (`NOTIFY_RELAY_HUB`,
default `hp-laptop`) over the link. The hub's board shows the notice as «<office> · …», keeps this office's episodes
apart from its own, and drops what would act on the hub (answers, relative links, `meta.to`). DGO-2111, root 2.

**How.**
- The hub's address is the compiled record `.generated/registry/remote.<hub>.alerts.json` (`door.base`), never a
  constant. No record (this office is not given the hub's `alerts`) means every notice is kept.
- A notice the hub does not take now (the link is down, a 5xx) is kept in the volume (`/data/spool.jsonl`), in order,
  and sent every 30 s. A newer notice never overtakes a kept one: a «back» after its «down». The cap (10,000) drops the
  oldest, said in the log.
- A 4xx is the hub's refusal of that notice: it is said back to the poster and not kept.
- `GET /health` says the hub, its address and how many are kept.

**Never** enable it on an office that runs its own board: the name `notifications` would answer twice. The relay
refuses to serve when `notifications-<deployment>` exists, and says so in its log.

**Test:** `python3 apps/notify-relay/test_relay.py` (stdlib only).

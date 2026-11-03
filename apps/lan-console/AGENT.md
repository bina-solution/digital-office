# Operating «הקונסול ברשת המקומית» (the `lan-console` app)

This office's console on its local network, for a phone on the same Wi-Fi (DGO-1125, DGO-1126):
http://console.<LAN_DOMAIN>:<LAN_PORT>. The bare http://<LAN_ADDRESS>:<LAN_PORT> (and /dgo) leads there. It uses the
same accounts and the same passwords as the office, and every app another office shares opens inside it.

How it fits together:

- **The door** is on the host, not in the office: `packaging/macos/lan-door.py --policy data/lan/policy.json`.
  - engine.sh starts it next to the link's door, as `console_door_start`.
  - It listens on the LAN address only while the policy says `{"on": true, "address": …, "port": …, "until": …}`.
  - It admits private sources only: 12 connections at a time and 60 new ones a minute from any one address.
  - It hands each connection to traefik's `lan` entry (guest :8081, published on 127.0.0.1 only).
- **The name**: LAN_DOMAIN, the address as a name (`192-168-16-100.sslip.io`; public DNS answers it with that same
  private address, measured through the home router). `hooks/prepare` writes it when .env has none, and the compiler takes
  the same default (`reconcile.py lan_name`). A host can be nested under a name and not under an address: that is what lets
  a shared app that keeps a host of its own (Bina, Plane, meetings, recordings, Obsidian…) open here.
- **The routes** on `lan`, every one naming its host:
  - `console.<LAN_DOMAIN>`: the console, behind `lan-auth`; `/dgo` → `/`;
  - `auth.<LAN_DOMAIN>`: the sign-in page, `/login` and `/logout` only, rate-capped (lan-signin);
  - the address itself: a redirect to the name;
  - `<alias>.<office>.console.<LAN_DOMAIN>`: each shared app, compiled by `platform/manager/serve.py` (the `…-console-lan`
    form, behind `lan-auth@docker`).
  web and websecure are traefik's default entries (platform-base/traefik), so no other route lands on `lan`.
- **The sign-in** is the office's own forward-auth: the same page and accounts as console.<domain> (r030-002; authentik
  leaves every office).
  - `lan-signin` is the forward-auth image signing in at `auth.<LAN_DOMAIN>`; its hand-off gives the console and every
    app nested under the name a cookie of its own.
  - The office's forward-auth cannot serve this: it sends every browser to signin.<domain>, which a phone cannot resolve.
  - It reads forward-auth's users file read-only from forward-auth's own volume (`forward_auth_data`): one set of
    accounts, never a copy of the hashes. While an office migrates it takes the same legacy pair, so a phone signed in
    to authentik on this name is not asked again.
  - `hooks/prepare` removes the authentik proxy outpost this entry had before (`lan-outpost`); nothing is provisioned.

```bash
./bbox lan-console prepare && ./bbox run lan-signin   # after LAN_ADDRESS, LAN_DOMAIN or LAN_PORT changes
cat data/lan/policy.json                       # open or closed, on which address, until when
tail ~/.bbox/macos/console-door.log            # the door's open/closed lines
```

Rules:
- Off by default; plain HTTP, so the screen says the password crosses the Wi-Fi as it is.
- Never 0.0.0.0, and never the engine's own 127.0.0.1:8080.
- The address follows the Mac by itself (the router gives it another one after a reboot): the door rewrites the
  policy's address only behind the same router it was opened behind, then LAN_ADDRESS in .env (when the one there
  is no longer the Mac's), and re-makes the LAN routes (prepare's derived name, a render, lan-signin). Carried to
  another network, it stays shut until the console is switched on again. A name that does not depend on DHCP at
  all is hos-104/hos-502.
- The name needs a DNS that lets a public name answer with a private address. The home router does NOT (measured
  2026-11-03 through 192.168.16.1: google.com and 1-1-1-1.sslip.io answer, 192-168-16-104.sslip.io and
  10-0-0-1.sslip.io come back NOERROR and empty — rebind protection, like dnsmasq's stop-dns-rebind, FritzBox and
  pfSense), while 1.1.1.1 and 8.8.8.8 answer them. So a device on the router's DNS cannot reach the console by its
  name: the bare address only redirects to the name, and the sign-in lives on the name. A device with its own DNS
  (Android's Private DNS, iOS with a DNS profile) does. A name that is not a public answer for a private address is
  hos-104/hos-502.
- A write (POST/PUT/PATCH/DELETE) whose `Origin` is not under the name is refused at the entry (`lan-console-foreign-write`):
  `sslip.io` is not a public suffix, so every `*.sslip.io` page is the same site as this console to a browser.
- Not yet: an app of THIS office that the console frames on a host of its own (on the MacBook, git) has no route under
  the name, so its tile shows traefik's 404 there; the apps other offices share are routed (`serve.py`).
- `.env` holds LAN_ADDRESS, LAN_DOMAIN and LAN_PORT; the signing key is forward-auth's FORWARD_AUTH_SECRET (never printed).

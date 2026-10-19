# A colour and an animal per office — the decision, and where each half lives

The owner, 2026-10-09: every DGO gets **a colour and an animal**, chosen in the install wizard and
kept in the office's identity, so that when offices are linked a person reads *which* office an app
belongs to without opening it. His own words on the three he has: this HP laptop is the heavy one
("elephantish … the heavy laptop I have at home"), the Mac is "a MacBook Neo … I would want to give
it a deer … maybe yellow", and the VPS is "an eagle because it's in the clouds … I'll let you pick
the colour for that".

## The three he named, and what is still his

| office | animal | colour | who decides |
|---|---|---|---|
| hp (this one — the heavy laptop) | elephant | **grey** | said |
| macbook (MacBook Neo) | deer | **yellow** | said |
| vps (srv908573, staging) | eagle | *open* | **the owner** — he kept the colour for himself |
| a fourth office, a fifth… | the registry's next icon | a legal hue | whoever installs it, in the wizard |

## Where each half lives (one source per fact)

* **The colour is a TOKEN, never a hex on a screen** (`flt-002`): `platform-base/bina-ui/theme-tokens.css`
  is the only place a colour is written (G27/G82), so a per-office hue is added there as its own
  token family — one name per office, read by the tile, the rail, the window chrome and the badge.
  A per-office hex pasted into `console/static/**` is the defect those gates exist to catch.
* **The animal is an ICON, never an emoji** (`flt-003`): `platform-base/bina-ui/bina-icons.js`, the
  same file every other platform icon comes from, stamped into the G27 carriers by the gate's own
  `--fix`. An emoji is a font's opinion, not ours, and it renders differently on every OS.
* **The choice is IDENTITY, not configuration** (`flt-001`): it is made once, in the install wizard,
  stored with the office's identity (the same record `bbox dgo identity` prints and the backup
  carries), and it survives the office being re-installed, re-paired or moved.
* **Every surface that names another office carries both** (`flt-004`): a remote tile, a linked
  office's row, the link screen, the console's office switcher. The simulator demonstrates it
  (`flt-005`) and keeps online/offline **distinct from** the colour — a colour is an identity, not a
  health state, and the two must never be read interchangeably (an offline office keeps its colour,
  and the quiet mark stays the one that says "not answering").

## Why this is written down before it is built

Adding a hue to the one palette is a change every screen inherits, and stamping a new icon re-writes
every carrier file — so the *decision* (which office, which animal, which hue) is separated from the
*edit* (tokens + icons + the wizard field). The owner's three answers above are the decision; the vps
colour is the only piece still owed, and it is his.

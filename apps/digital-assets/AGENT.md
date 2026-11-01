# Operating `digital-assets`

The business's digital front — everything it shows the world — as **slots**. A slot is one named,
typed place (`identity.logo.square`, `identity.description.short`, `content.app-store.listing`,
`media.launch-day.launch-film`); it holds **versions** (assets), and one version is **active**: that
one IS the business now. Making a version active produces a **plan** (per channel: push / manual /
live / skip, with the reason), and **publishing** delivers it: social accounts through `social-list`
(the office browser on every network), websites through `sites`, the office's own products read
`GET /api/brand` live.
**Blueprints** (`business-basic`, `startup-tail`, `basic-restaurant`) create the slots; a
**media unit** is a slot of kind `set` from a blueprint's timeline (`plan.due`, `plan.assets` = what it
needs, `plan.channels` = where it goes).

## What you can do from here

```bash
# where things belong: the media units, what each needs, and when
curl -s 'http://digital-assets:8985/api/slots?section=media'
curl -s http://digital-assets:8985/api/slots/media.teaser.teaser-drip

# put media you MADE into its unit's gallery (a draft, marked as yours). svg | data_base64+mime | text | url
curl -s -X POST http://digital-assets:8985/api/media -H 'content-type: application/json' -H 'x-actor: agent:azaria' \
  -d '{"slot":"media.teaser.teaser-drip","title":"טיזר יום 1","data_base64":"iVBOR…","mime":"image/png","author":"עזריה"}'
# no slot → it lands in `media.inbox` ("מדיה שטרם שובצה") for the owner to place

# post media to channels (channel ids: facebook instagram x youtube github discord whatsapp …)
curl -s -X POST http://digital-assets:8985/api/posts -H 'content-type: application/json' -H 'x-actor: agent:azaria' \
  -d '{"slot":"media.teaser.teaser-drip","asset_ids":["a-…"],"text":"…","channels":["facebook","x"]}'

# an identity change, when the OWNER asked for it: add a version and make it active → the plan
curl -s -X POST http://digital-assets:8985/api/slots/identity.description.short/assets \
  -H 'content-type: application/json' -d '{"text":"…","activate":true}'
curl -s -X POST http://digital-assets:8985/api/slots/identity.description.short/publish -d '{}' -H 'content-type: application/json'
curl -s http://digital-assets:8985/api/brand        # the identity as products read it
```

Canonical ops: `POST /<op>` for listSlots, getSlot, addAsset, addMedia, setActive, plan, publish,
listMedia, createPost, getBrand, getBundle, listBlueprints, applyBlueprint, listChannels, bindChannel.

## Traps

- **Activating and publishing change the business everywhere** (every connected account, the
  website, the products). Create drafts freely; activate or publish an identity slot only when the
  owner asked for that change. Showing the owner the plan (`GET /api/slots/<key>/plan`) first is the
  polite path.
- **`needs_owner` is not a failure.** It is either a manual channel the owner ticked (a listing, a
  printed surface) or a browser run that stopped for a human — a login in the office browser's live
  view (`/a/browser42/`), or a script's first watched run. Do not retry it; say what it waits for.
- **Never pass `watch: true`.** It means "the owner is watching the office browser" and unlocks a
  browser script that was never verified. It is the owner's consent, not yours to give.
- Social platforms do not accept SVG. The app renders SVG to PNG for avatars and posts; when it
  cannot, the plan and the post say "upload a PNG". Prefer PNG/JPEG for media you create.
- A manual channel (Google Business Profile, Wolt, print…) is tracked only when the owner ticks it in
  the plan; publishing without a choice sends what the office can do itself.
- `applyBlueprint` is additive: it adds and refreshes slot definitions, never deletes an asset or
  changes an active choice. `launch_date` (D0) re-dates the startup-tail timeline.
- A channel with no account bound is `skip` with `needs: bind` — binding is the owner's (screen
  "ערוצים"); accounts themselves are connected in `social-list`.

---
title: Digital assets
description: "Everything the business shows the world — logo, name, descriptions, content and media — in slots, and from there to every channel: networks, website and products. What changes the business everywhere, and what waits for the owner."
---

## What it is

«Digital assets» (`digital-assets`) holds everything the business shows the world: logo, name, descriptions, content and media. It is for administrators only, off in a new install, and is in the «Digital assets» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable digital-assets
./bbox run
```

## Slots and versions

- **A slot** is one place with a name and a kind: the square logo, the short description, the app's page in the store, the launch video.
- **A version** is one asset in a slot. Each slot can have several versions, and **one active**: it is the business now.
- **A template** creates slots: for example `business-basic`, `startup-tail` or `basic-restaurant`. Applying a template only adds and updates slots. It does not delete an asset and does not replace an active choice.

## From the slot to every channel

When a version becomes active, the app prepares a **plan**: for each channel, whether it will get the change by itself, by hand, or not at all, and why. **Publishing** carries out the plan:

| Channel | How the change arrives |
|---|---|
| Social networks | Through the [Social networks](/en/apps/social-list) app, in the office's browser |
| Websites | Through [Sites](/en/apps/sites) |
| The office's products | They read the identity in real time |

**Activating and publishing change the business everywhere:** on every connected account, on the website and in the products. Drafts are created freely. An identity slot is activated or published only when the owner asked for the change.

## What waits for the owner

- **«Waiting for the owner» is not a failure.** It is a manual channel the owner marked (for example a Google business page, Wolt or print), or a browser run that stopped because a person is needed, for example a sign-in to an account.
- **A channel with no connected account** is skipped. Accounts are connected in the «Social networks» app, and that is up to the owner.

## What does not work yet today

- **Writing to social networks has not been verified on any network yet.** On every network the owner signs in once in the office's browser, and every first write runs while they watch. See [Social networks](/en/apps/social-list).
- **Social networks do not accept SVG.** The app converts SVG to PNG for profile pictures and posts. When that does not succeed, the plan asks for a PNG of the logo.
- **A website in another office does not always get the change.** When the app cannot be reached from the office that serves the website, the website is served as it is. See [Sites](/en/apps/sites).

## Going further

- [Sites](/en/apps/sites)
- [Connections](/en/apps/connections)
- [The apps](/en/apps)

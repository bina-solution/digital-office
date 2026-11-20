---
title: Social networks
description: "Every social network the business is on, from one place: profile, posts and comments, through the office's browser or through the network's API — and what has been proven so far."
---

## What it is

«Social networks» (`social-list`) holds all the business's social networks behind one interface: profile (name, description, picture, banner, links), posts, comments, likes and data. It is for administrators only, off in a new install, and is in the «Social networks» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable social-list
./bbox run
```

The browser way also needs the office's browser, `browser42`, which is off in a new install. Turn it on the same way.

## Two ways to speak in the business's name

| Way | What it is |
|---|---|
| Browser (the default, on every network) | The owner signs in to the network once in the office's browser, and a script acts inside that session, at a person's pace |
| API | On a network that has one, with a key in the vault. For example a Facebook page, Instagram, X, YouTube or GitHub |

Connecting and disconnecting an account are up to the owner, on the app's screen.

## What «succeeded» means here

- **Success is reading back.** A write ends in success only when the network shows the new value. Otherwise it fails, with the proof.
- **A sign-in, two-step verification or a CAPTCHA stops everything.** The owner signs in once on the live screen of the office's browser. Nobody types a password for them.
- **A script nobody has seen succeed yet** waits for the owner. They open it while they watch the first run.
- **Every network says something about automation on its site.** The screen shows it to the owner. Writes through the browser stay few, and at the owner's initiative.

## From the command line

| Command | What it does |
|---|---|
| `./bbox social-list accounts` | The accounts: for each the network and how the office speaks in its name |
| `./bbox social-list activity` | Everything done in the owner's name |

Neither command calls any network.

## What does not work yet today

- **No real network has been verified yet.** On Facebook, in one office, reading the profile, a text or picture post and editing a post were observed. On every network, Facebook included, the owner signs in once in the office's browser, and every first write runs while they watch. On Facebook there is no script yet for the page's description, the links, the list of posts, deleting, comments and likes, and the picture and the banner are still a draft.
- **Instagram's API** cannot edit a profile, and publishes only from a picture at a public address. Through the browser the description and the picture can be updated after a first run the owner watched, but it cannot publish posts yet.
- **X's API** is paid by usage, and a post with a link costs about 13 times as much.

## Going further

- [Identity](/en/apps/digital-assets)
- [Connections](/en/apps/connections)
- [Chat](/en/apps/chat)

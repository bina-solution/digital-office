---
title: Sites
description: "The business's websites: a site the office builds and a site that existed before the office, a public address, uptime, visits and scans — and what does not reach the live site yet."
---

## What it is

«Sites» (`sites`) holds the business's websites: their uptime, the visits, and security, SEO and appearance scans. It is for administrators only, off in a new install, and is in the «Sites» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable sites
./bbox run
```

It needs [Computers](/en/apps/computers): a site runs on a computer from its list, and «Sites» holds no key or address of a computer itself.

## Two kinds of site

| Kind | What it is |
|---|---|
| Managed | The office produces the site's files on the computer and brings it up |
| Adopted | A site that existed before the office. The office checks and scans it, and does not touch its installation until you click «Move to the standard pattern» |

On a managed site, the site's record is the contract: a new deploy writes the files again. A change by hand on the computer stays only until the next deploy. Change the record, then deploy.

## The public address

Every site can get an address the world sees: a domain and a path, in one of two modes:

| Mode | Who serves the site |
|---|---|
| `container` | The site's own container |
| `office` | «Sites» itself, from a kept copy. The site's container is stopped |

A public address is open to the whole world, with no sign-in. Check the addresses before you save.

## What it checks

- **Uptime:** a regular check. When the state changes, a notification is sent.
- **Visits:** from the site's own log. On an adopted site the count starts on the day of adoption.
- **Scans:** security, SEO and appearance. A finding disappears by itself when a later scan no longer finds it.

## From the command line

| Command | What it does |
|---|---|
| `./bbox sites ls` | Every site: state, address and the latest check |
| `./bbox sites show <id>` | One site, in full |
| `./bbox sites probe <id>` | One uptime check now, and the last 24 hours |
| `./bbox sites uptime <id>` | The uptime checks. You can give a number of hours |
| `./bbox sites findings <id>` | What the latest scan found |
| `./bbox sites logs <id>` | The log of the site's container |
| `./bbox sites flow` | The events: a site created, deployed, started, stopped or deleted |

Deleting a site leaves its files on the computer. Only an explicit request, with the site's id, deletes them too.

## What does not work yet today

- **A site the office serves does not pass on its headers.** In `office` mode, a header the site sets for itself, like Permissions-Policy, does not reach visitors. Only the edge router's headers arrive.
- **Edited texts and pictures do not always reach the live site.** They come from the «Identity» app. When it is in another office and cannot be reached, the site is served as it is, and the asset addresses answer 503. This was found on a live server office on 2 November 2026, and the fault is still open.
- **The appearance scan needs the rendering service.** When it is not healthy, the scan writes «The rendering service is not available». That is not a finding about the site.

## What it reaches outside

The SEO scan reads the whole sitemap, and checks every link that leaves the site once. The pace is limited, the answer is kept per server, and it does not call a private address.

## Going further

- [Computers](/en/apps/computers)
- [Notifications](/en/apps/notifications)
- [Security](/en/apps/security)

---
title: Edge router
description: "traefik, the office's door: which ports are open and to whom, TLS certificates, how an app gets an address, and what is not locked yet."
---

## What it is

«Edge router» (`traefik`) is the office's door: almost every request from outside passes through it. The exception is the door of a [link](/en/concepts/link) between offices, which passes a request straight to the app. It routes every address to its app, holds the TLS certificates, and sends a request for an app behind the sign-in to [Identity and sign-in](/en/apps/forward-auth) before it reaches the app. It is part of the base of every office (layer 1), for administrators only, and has no tile.

## The ports

80 and 443 are the door. Where they open depends on the computer:

| Computer | 80 and 443 |
|---|---|
| A Linux server | On every interface, to the whole world |
| macOS | On the Mac itself only: `localhost:8080` and `localhost:8443`. A phone on the same Wi-Fi network reaches the centre through the Mac's address on port 8080 |
| Windows | On Windows itself through `localhost`. On the network only in WSL's mirrored network mode, after `bbox.cmd dialable` |

Three more ports are bound to the local address only: 8081, to which the Mac's door hands a phone's connection (the phone itself dials the Mac's address on port 8080); and 5432 and 6379, which pass to the database of [Automations](/en/apps/n8n) and to [Redis](/en/apps/redis), only over an encrypted connection, by name, and from addresses in the `DBS_ALLOWED_IPS` list. A port published on every interface bypasses the computer's firewall, which is why they are bound to the local address.

## Certificates

- **An office with a public domain** (a name with a dot in `DEPLOYMENT_DOMAIN`): the certificates come from Let's Encrypt, verified through port 80. A request over HTTP is redirected to HTTPS only when [HTTPS redirect](/en/apps/https-redirect) is on. `./bbox onboarding` turns it on on a server with a public address. Without onboarding, or behind NAT, it is off, and every app also answers over HTTP, without encryption. The contact address is `TRAEFIK_ACME_EMAIL`, by default `admin@` at the domain. When the office moves to another domain, this address moves too.
- **A local office** (`localhost`): there are no certificates, because no authority issues a certificate for such a name. The office answers over HTTP.

## How an app gets an address

The router publishes no container by itself: only what was marked for routing gets an address. Most routes are built from `routing` in the app's `app.json`. A few apps define routes of their own, and some routes are written in the router's own files.

An app with `auth: "sso"`, the default, stands behind the office's sign-in. A public address, with no sign-in, is a decision written in the app's settings. In a development office with `BBOX_SSO=off` there is no sign-in at all: every request comes in as an administrator.

A container that has a health check gets requests only when it is healthy. Such a container that is still starting gets no requests.

## What it does not do

- **It does not hold the engine's socket.** It reads the list of containers through a door that only answers reads. If someone breaks into the router, they do not control the computer.
- **It does not report out.** traefik's check for a new version and its usage reporting are off.
- **It writes an access log,** and [Security](/en/apps/security) reads it to know who came in. On a laptop (macOS or Windows), the router sees the address of the virtual machine, not of whoever made the request.

## What does not work yet today

- **A visitor over IPv6 looks like the office itself.** On a server with a public IPv6 address, they arrive from an internal address, and any rule that depends on the address does not apply to them. Until this is fixed, close IPv6 for ports 80 and 443 in the server's firewall.
- **A run that brings most of the office up again at once** on a small computer delays the health checks, and the router does not route to what is not healthy yet. Since 11 November 2026 the centre has a fallback route: its names reach it even when its check is delayed. The other apps have no such route yet.
- **An engine that does not answer an API 1.24 client** leaves the router with no route at all, with no error. See [Requirements](/en/start/requirements).

## Going further

- [Identity and sign-in](/en/apps/forward-auth)
- [Security](/en/apps/security)
- [Sites](/en/apps/sites)

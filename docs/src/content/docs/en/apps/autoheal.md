---
title: Self-healing
description: "The service that restarts a stuck service, starts a service that did not come up, stops forgotten manual work, and tells about each of them in Notifications."
---

## What it is

«Self-healing» (`autoheal`) is a service in the base of every office (layer 1). It has no screen and no commands. It checks the health of the office's services every 30 seconds. Every restart, every refusal and every trip of the breaker is written to [Notifications](/en/apps/notifications).

It exists because the container engine marks a service «unhealthy» and does nothing about it: a service whose process is alive but whose work stopped stays stuck. «Self-healing» does what a person would do: restarts it.

## What it does

| Case | What it does |
|---|---|
| A service the engine marked «unhealthy», and that asked for healing | Restarts it, after 3 consecutive checks of its own |
| An office service that has been unhealthy for 20 minutes | Notifies once, with the check's latest output. A service that did not ask for healing is not restarted |
| A service that fell, and the engine tried to start it and failed | Starts it, with a wait that grows longer between attempts |
| A container someone started by hand that has run for more than six hours | Stops it if it belongs to the office. If not, only notifies |
| An app that runs only while it is used, whose network is quiet | Stops it. Opening it starts it again |
| The computer's temporary-files folder, when it is in memory and takes more than 512 MiB | Notifies once, with the names and sizes of the large files. Deletes nothing |

## The brakes

The «unhealthy» mark can be wrong, so four brakes stand between the mark and a restart:

1. **Only who asked.** A service is restarted only if it carries the label `binaos.autoheal=true`, in its app's definition, and only if it belongs to this office.
2. **Databases and the edge router never.** postgres, redis and the other databases, and the edge router, are not restarted even with the label. Restarting a database once cost about two minutes in which the whole office was unavailable, and restarting the edge router cuts every open request and every open sign-in.
3. **Consecutive failure.** One healthy check resets the count.
4. **A breaker.** At least 15 minutes between one restart and the next, and no more than three restarts in six hours. After that it stops and notifies that a person is needed.

Starting a service that fell also has a ceiling: four attempts in six hours, then a person. A service that was stopped on purpose is not started: it is started only when the engine recorded an error on start.

## What it does not do today

- **Few services asked for healing.** Today only five n8n services (the two workers and the three runners services) and Plane's main service carry the label. Another service that gets stuck gets a notice after 20 minutes, but is not restarted.
- **Only what has a health check.** A service with no health check defined is never marked «unhealthy», so this service does not see when it gets stuck.
- **An app stopped because it was not used** is written only to its own log, not to Notifications.
- **It does not repair.** It does not build, delete or change settings. If a restart did not help, it stops and waits for a person.

## How to check it works

- `./bbox logs autoheal` shows its latest look: what it checked, what it started and what it refused.
- Every restart and every refusal appear in [Notifications](/en/apps/notifications).

## Going further

- [Notifications](/en/apps/notifications)
- [The office's health](/en/admin/health)
- [Machine](/en/apps/machine)

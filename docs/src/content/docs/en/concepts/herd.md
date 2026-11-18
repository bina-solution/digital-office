---
title: Herd
description: "Several offices, each on a different computer, linked and working as one business — and each computer has a role: the desk, the office, the workshop, and the window and door."
---

## The problem

A business does not run on one computer. The laptop gets closed, the server is far away, and the strong computer has no screen anyone sits in front of. If each of them is a separate office, every app lives somewhere else, and nobody knows where.

## The idea

### Several offices, one business

A herd is several offices of the same business, each on a different computer, linked to each other with a [link](/en/concepts/link). From each one you open the apps of the others, as if they ran in it.

### Each computer has a role

| Role | What runs on it |
|---|---|
| **The desk** | The interface: the centre, the links and the agents. No business data |
| **«The office»** | Always on: every business app, every automation and all the data |
| **The workshop** | Heavy work that runs at times: models, transcription, text recognition, tests, and the backup store |
| **The window and door** | What faces the public: websites, meetings, mail, and the sign-in for the whole herd |

The roles are written in one file, `apps/computers/herd.yaml`. This command compares it to what really runs: what runs where, what should move, what is left over, and what runs twice.

```bash
./bbox computers herd
```

### A limit

An office on a laptop is not available while it sleeps or is off. The other offices in the herd keep working. That is why what must always run lives on the computer in the «office» role.

## What this makes possible

- Every job runs on the computer that suits it: heavy work in the workshop, public-facing work at the window, the data in «the office», which never turns off.
- You work from anywhere, from the centre of any office, on the apps of all of them.
- When a computer goes down, you see what was on it and where it should move.

## Going further

- [Link](/en/concepts/link)
- [Office](/en/concepts/office)
- [Several computers — one office](/en/idea)

---
title: Supabase
description: "Supabase on top of the office's database: file storage and a data API that other apps need, and Studio — which acts as an administrator over all the data."
---

## What it is

«Supabase» (`supabase`) is Supabase on top of the office's [database](/en/apps/postgres). It has no database of its own. It gives two things other apps need:

| What | Who needs it |
|---|---|
| File storage (`object-storage`) | «Office storage», the engine of [Files](/en/apps/drive) |
| A data API (`data-api`) | [INDOX](/en/apps/indox) |

In the default file it is off, but «Files» (through «Office storage») and «INDOX» are on in a new install and need it, so the office starts it for them. It is for administrators only.

## Studio

Studio is the screen of the tables and the storage (the «Supabase Studio» tile in the «Infrastructure» group), behind the office's sign-in.

**Studio acts as an administrator over the office's database.** A change in it changes the data of every app. Change in it only a table the owner named, in their own words.

## What not to do

- **Do not replace `SUPABASE_JWT_SECRET` on your own.** The keys of n8n, «Office storage» and «INDOX» are created from it. Replacing it cancels all of them, and a restart does not bring them back: the keys have to be created again.
- **Do not hand out the service key.** With it you can run SQL on the office's database.
- **Do not publish the API "to test it".** Its public address exists only over https, and only when the office gives it a name. It is behind the office's sign-in, and after that the API's keys are checked.

## What does not work yet today

- **`/auth`, `/realtime` and `/functions`** are routed to services that do not run in the office, so they fail.
- **The dashboard password (`SUPABASE_DASHBOARD_PASSWORD`) guards no path.** The sign-in to Studio is the office's sign-in.

## Going further

- [Database](/en/apps/postgres)
- [Files](/en/apps/drive)
- [INDOX](/en/apps/indox)

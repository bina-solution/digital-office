---
title: Files
description: Keep, find and take out files in the «Files» app, from the screen or from the terminal.
---

## Why

«Files» (`drive`) is the office's place for files: documents, pictures, recordings and videos. Other apps keep files in it too. You work by **path**, for example `/Documents/Contracts`.

## Before you start

- «Files» is on. On a new install it is on. If not: [Turn an app on](/en/use/add-app).

## From the screen

1. Open the «Files» tile in the centre.
2. Open a folder, and drag a file from the computer into the screen.

![«Files» with a folder open and a list of files](TODO-shot: drive, the folder /Documents with three demo files, demo office, desktop 1440x900, light theme)

## From the terminal

1. **Put a file in:**

   ```bash
   ./bbox drive put ./doc.pdf /Documents/
   ```

   A path that ends in `/` keeps the file's name. Missing folders on the path are created automatically. If the name is taken, the new file is called «name (2)». With `--replace`, the old file goes to the bin.

2. **See what is in a folder:**

   ```bash
   ./bbox drive ls /Documents
   ```

3. **Find by name:**

   ```bash
   ./bbox drive find invoice
   ```

   Returns files and folders whose name contains the text, with their path.

4. **Take a file out to the computer:**

   ```bash
   ./bbox drive get "/Documents/doc.pdf" ./
   ```

5. **Create a folder:**

   ```bash
   ./bbox drive mkdir "/Meetings/2026-10-28"
   ```

Every command: `./bbox drive help`.

## Drives

Every drive is a connection: a profile of the office's storage, or a Google account. Without `-p`, the commands work on the default drive.

```bash
./bbox drive profile list
```

The drive marked with `*` is the default. To work on another drive:

```bash
./bbox drive -p <drive> ls /
```

## System folders

A folder an app writes to is marked `system`. It cannot be renamed, moved or deleted.

## How to check it worked

```bash
./bbox drive find doc
```

What you will see: a line with the path of the file you put in.

## See also

- [The first hour](/en/start/first-hour)
- [Ask Bina](/en/use/ask-bina)

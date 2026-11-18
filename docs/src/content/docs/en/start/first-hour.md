---
title: The first hour
description: A first tutorial — sign in to the office, get to know the centre, check that «Files» is on, put a file in it, and ask the agent «Bina» to find it.
---

## What you will have at the end

An office where the «Files» app is on, with a file of yours in it.
The office's agent, «Bina», found the file when you asked.

## Before you start

- An installed, running office: [Start — choose a computer](/en/start), then [After the install](/en/start/after-install).
- The first administrator already created, through the one-time link `./bbox run` printed ([After the install](/en/start/after-install), step 2). You need the name and password you chose there.
- A small file to upload, for example the PDF of an invoice.
- For «Bina»: a key for a language-model service. The agent knows three connections: DeepSeek, OpenAI and Anthropic. The key is yours, and it is an outside service.

## The steps

1. **Sign in.** Open the centre's address: the value of `CONSOLE_BASE_URL` in `.env`, and on macOS `http://console.localhost:8080`. Type the name and password.

   What you will see: the centre, «Console» in the header, and a tile for each app that is on.

   ![The centre right after the first sign-in](TODO-shot: first-hour-1-console — a demo office's centre right after the first sign-in; desktop 1440x900, light and dark theme)

2. **Get to know the centre.** Each tile is an app. Clicking a tile opens it inside the centre. You can share the address of an open screen: it leads exactly there.

3. **Check that «Files» is on.** On a new office «Files» is on from the start, and it has a tile in the centre.
   If someone turned it off: open «App Management», find «Files» and turn it on. The screen does the whole switch-on.

   From the terminal, the same in two commands. The first records the decision, the second brings the app up:

   ```bash
   ./bbox apps enable drive
   ./bbox run
   ```

   What you will see: a «Files» tile in the centre.

   ![«App Management» with the «Files» row and its switch](TODO-shot: first-hour-2-app-management — «App Management», the «Files» row with its switch; desktop 1440x900, light and dark theme)

4. **Put a file in «Files».** Open the tile and upload the file to a folder.

   From the terminal:

   ```bash
   ./bbox drive put ./doc.pdf /Documents/
   ```

   What you will see: the file in the folder's list.

   ![«Files» with the uploaded file](TODO-shot: first-hour-3-drive-file — «Files» with the uploaded file; desktop 1440x900, light and dark theme)

5. **Connect «Bina» to a language model.** Open «Connections» and save your key there, in one of the agent's three connections.

   ![«Connections» with a language-model key connection for «Bina»](TODO-shot: first-hour-4-connections — «Connections», a language-model key connection; desktop 1440x900, light theme)

6. **Ask «Bina» to find the file.** Open the «Azaria» tile and write, for example: «Find me the file doc.pdf in Files».

   «Bina» learns every app that is on from its brief. When «Files» is on, the agent gets its brief too.

   What you will see: an answer with the file's path.

   ![«Bina» answers with the file's path](TODO-shot: first-hour-5-bina-answer — a conversation in «Azaria», the answer with the path; desktop 1440x900, light and dark theme)

   From the terminal you can check the same answer without the agent:

   ```bash
   ./bbox drive find doc
   ```

## Cleaning up

Want to turn «Files» off? `./bbox apps disable drive`, then `./bbox run`. The files are kept.

## What you have now

An office with one sign-in, an app that is on, a file in it, and an agent working in it.

## What next

- [The concepts](/en/concepts)
- [Glossary](/en/glossary)
- [Several computers — one office](/en/idea)

# Chat service — Full QA Verification Guide

> **There is no longer a separate admin dashboard.** `GET /admin` and `ui/index.ejs` were removed
> once every section they held had a home in the chat app itself: #connect became the connection
> switcher and the connect flow, #settings became the per-connection bot panel, #actions became the
> abstract broadcast plus WhatsApp send-document, and #users became the subscriber table. Any older
> instruction to "open the dashboard" means the chat app at `/`.

## Prerequisites

- Access to the chat app: `https://chat.hacohen.bina-solutions.co.il`
  - Credentials: configured in `.env` (`AUTH_USERNAME` / `AUTH_PASSWORD`, fed from the `chat-auth`
    connection as `CHAT_AUTH_USER` / `CHAT_AUTH_PASS`)
- A WhatsApp account that is **not** the bot number (050-000-0013)
- The tester's phone number should be listed as an admin in settings (via n8n webhook or `ADMIN_PHONE_*` env vars) to test admin-only features (options 10, 11)

## Part 1: The chat app

### 1.1 Login
1. Open `https://chat.hacohen.bina-solutions.co.il/login`
2. Enter credentials → should redirect to the chat app at `/`
3. Verify: conversation list on the right, the connection switcher at the foot of the sidebar

### 1.2 Connections
- The switcher lists every connection; the active one carries a readiness dot fed by `/api/readyz`
- `שיחה חדשה` opens the people picker where the connection supports it, and is **disabled with a
  reason** where it does not — WhatsApp and Telegram cannot enumerate an address book
- Adding a connection: `חיבורים` offers only protocols the adapter layer can actually build

### 1.3 Bots
- `בוטים וחיבורים` shows every connection against its attached bot
- Selecting a row shows that bot's settings **for that connection** — the same bot can hold
  different policy on WhatsApp and on local chat
- Settings persist across a container recreate (they are written to `CHAT_STATE_DIR`)

### 1.4 Broadcast (use with caution — sends to ALL conversations)
```bash
# abstract: goes through whichever connection is active
curl -X POST -H "Content-Type: application/json" -u <user>:<pass> \
  -d '{"to":"all","text":"Test broadcast"}' \
  https://chat.hacohen.bina-solutions.co.il/api/broadcast
```
- Verify: `to:"all"` must be typed explicitly; a partial fan-out returns **207** with per-recipient results

### 1.5 Send Document
- `כלים` → send-document. **WhatsApp-only and labelled as such**: the abstract contract addresses
  conversations, not phone numbers, so there is no canonical equivalent
- Verify: recipient receives the document with thumbnail preview

## Part 2: Bot Conversation Flows (Agent Testing via Browser > WhatsApp Web)

Open WhatsApp (phone app or web.whatsapp.com) and message the bot number.

### 2.1 Welcome Flow (New User)
1. If this is your first message to the bot, send any text (e.g., "hi")
2. **Expected**: Welcome message "ברוכים הבאים לבוט הכהנים..." followed by the menu

### 2.2 Menu Display
After welcome, the menu should show:
```
🌟 איך אוכל לעזור לך היום?

בקש מהבוט להגיד שלום 1️⃣
אודות הבוט 2️⃣

(Admin-only section, if you are an admin:)
אפשרויות מנהל:
קליטת דוח גיול 1️⃣0️⃣
קליטת חשבונית / ת. משלוח 1️⃣1️⃣
קליטת מסמך מקישור 1️⃣2️⃣
רענון הגדרות 1️⃣3️⃣
```

### 2.3 Option 1 — Hello Back
1. Send: `1`
2. **Expected**: "הי {YourName}!" + menu

### 2.4 Option 2 — About
1. Send: `2`
2. **Expected**: About text mentioning bina-solutions.co.il + menu

### 2.5 Invalid Input
1. Send: any text that isn't a menu option (e.g., "hello", "xyz", "99")
2. **Expected**: "לא הצלחתי להבין את הבחירה שלך אנא נסה/י שנית." + menu

### 2.6 Option 10 — Balance Sheet Upload (Admin Only)
1. Send: `10`
2. **Expected**: Prompt to upload a balance sheet PDF/image
3. **Test cancel**: Send `cancel` or `ביטול`
4. **Expected**: "בוטל." + menu
5. Re-enter with `10`, then send an actual PDF or image file
6. **Expected**: Processing acknowledgement, then result with company name and Google Drive link (or company guess prompt if company unknown)

### 2.7 Option 10 — Company Guess Fallback
1. Enter option 10 and upload a file where the company cannot be auto-detected
2. **Expected**: Bot asks you to type the company name
3. Type a valid company name from the system
4. **Expected**: Balance sheet processed with that company + Drive link + menu
5. **Alternative**: Send `cancel` instead of company name → "בוטל." + menu

### 2.8 Option 11 — Generic Document Upload (Admin Only)
1. Send: `11`
2. **Expected**: Prompt to upload a document (invoice / delivery note)
3. **Test cancel**: Send `cancel` or `ביטול`
4. **Expected**: "בוטל." + menu
5. Re-enter with `11`, then send a PDF or image of an invoice
6. **Expected**: Processing acknowledgement, then result with company name, document ID/type, and Drive link + menu

### 2.9 Option 12 — Link/URL Document Intake (Admin Only)
1. Send: `12`
2. **Expected**: Prompt to send a link to a document
3. **Test cancel**: Send `cancel` or `ביטול`
4. **Expected**: "בוטל." + menu
5. Re-enter with `12`, then send a URL (e.g., `https://mrng.to/nrOjnbuZSL`)
6. **Expected**: Processing acknowledgement, then result with document type, ID, company name, and Google Drive link + menu

### 2.10 Option 13 — Reload Settings (Admin Only)
1. Send: `13`
2. **Expected**: "✅ הגדרות רועננו בהצלחה" + menu
3. Verify in container logs: "Loaded settings. Admins: N" and "Loaded N companies"

### 2.11 Auto-Intake — Document Outside Menu (Admin Only)
1. While in menu state (not awaiting anything), send a PDF or image file directly
2. **Expected**: Bot auto-detects the document, processes it, returns document type/ID/company/Drive link + menu

### 2.12 Auto-Intake — Link Outside Menu (Admin Only)
1. While in menu state, send a URL (e.g., `https://mrng.to/nrOjnbuZSL`)
2. **Expected**: Bot extracts the URL, downloads the document, processes it, returns result + menu
3. Also test mixed text with link: `check this https://mrng.to/nrOjnbuZSL thanks`
4. **Expected**: Bot extracts URL from mixed text, processes document, returns result + menu

### 2.13 State Timeout (24h Auto-Reset)
1. Enter option 10 or 11 (so state is `await_*`)
2. Wait 24+ hours (or manually set `stateChangedAt` to an old timestamp in the DB)
3. Send any message
4. **Expected**: State resets, bot shows menu instead of expecting a file

### 2.14 Daily Message Limit
1. Send more than 100 messages in a single day
2. **Expected**: After reaching the limit, bot sends "הגעת למגבלת ההודעות היומית" and stops responding until the next day

### 2.15 Hebrew Cancellation
1. Enter any awaiting state (10 or 11)
2. Send: `ביטול`
3. **Expected**: "בוטל." + menu (Hebrew cancel word works)

## Part 3: Group Message Handling

### 3.1 Group Admin Commands
1. Add the bot to a WhatsApp group
2. Send a menu option (e.g., `1`) from an admin phone
3. **Expected**: Bot responds with the same flow as private chat (hello, about, etc.)

### 3.2 Group Document/Link Auto-Intake (Admin)
1. Send a document or link in the group from an admin phone
2. **Expected**: Bot auto-intakes the document/link, processes it, returns result

### 3.3 Group Non-Admin Messages
1. Send a message in the group from a non-admin phone
2. **Expected**: Bot replies with "הבוט פעיל רק עבור מנהלים בקבוצות" (bot active only for admins in groups)

### 3.4 Group Text Messages (Non-Command)
1. Send regular text (not a menu option) in the group from an admin phone
2. **Expected**: Bot shows "לא הצלחתי להבין" + menu

## Part 4: Edge Cases

### 4.1 Non-Text Message in Menu State (Admin)
1. Send an image or document while in menu state (not in awaiting file state)
2. **Expected**: Bot auto-intakes the document → processes it → returns document type/ID/company/Drive link + menu

### 4.1b Non-Text Message in Menu State (Non-Admin)
1. From a non-admin phone, send an image or document in menu state
2. **Expected**: Bot treats it as invalid input → shows "לא הצלחתי להבין" + menu

### 4.2 Text During File Awaiting State
1. Enter option 10 or 11
2. Send a regular text message (not "cancel")
3. **Expected**: Bot reminds you to send a file (e.g., "העלה קובץ PDF...")

### 4.3 Rapid Messages
1. Send multiple messages very quickly (within 1 second)
2. **Expected**: All messages are processed sequentially (per-user lock ensures no state race)

### 4.4 Bot Reconnection
1. Restart the bot container: `docker compose restart chat`
2. Wait 10–15 seconds for reconnection
3. Send a message to the bot
4. **Expected**: Bot responds normally (no re-scan needed, auth persisted)

## Part 5a: The abstract API

Every op below resolves the backend from the **selected** connection and accepts a per-call
`connection_id` override, so the same request can be aimed at any connection without switching.
`GET /api/manifest` lists the ops the active backend actually implements — an op that is absent
answers **501 with a reason** rather than pretending, which is what lets the UI disable a control
instead of offering one that can only fail.

| Endpoint | Method | Notes |
|---|---|---|
| `/api/manifest` | GET | `{connection_id, ops[], protocols[]}` — the truth about what this connection can do |
| `/api/readyz` | GET | 200 ready / 503 unhealthy; probes the ACTIVE connection only |
| `/api/accounts` · `/api/account/select` | GET · POST | the switcher |
| `/api/chat-providers` · `/api/account/add` · `/api/account/:id` · `/api/account/:id/probe` | GET · POST · DELETE · GET | connect flow; probe answers **200 with `ok:false`** when unhealthy — a failing probe is a successful answer |
| `/api/bots` · `/api/account/bot` | GET · POST | roster and attachment |
| `/api/bots/:id/settings` | GET · PUT · DELETE | per-(connection, bot); PUT is partial, DELETE resets to the declared defaults |
| `/api/users` | GET | address book — **optional op**, 501 on WhatsApp/Telegram |
| `/api/conversations` | GET · POST | POST takes `user_id` (direct) or `title` (group). Direct is **idempotent** — an existing 1:1 is returned, `created:false` |
| `/api/conversation/:id` · `/send` · `/read` | GET · POST · POST | thread, send, read watermark |
| `/api/export/conversations?format=json\|csv` | GET | canonical ops only, so it works on every backend |
| `/api/events` | GET | SSE live updates — **optional op**; 501 where the backend cannot push, and the client falls back to polling |
| `/connections` · `/connections/select` · `/connections/:id` · `/readyz` · `/manifest` · `/providers` | — | root-level aliases in the console's dialect (contract `platform-service.v1`), so the shell's account chip works. Same handlers, different field names |

Quick end-to-end check of the live-update path, from inside the container:

```bash
curl -N -u <user>:<pass> http://localhost:3000/api/events
# then, in another shell, send a message into any conversation — an `event: change` frame
# carrying only ids should arrive within a second
```

## Part 5b: Legacy WhatsApp endpoint checklist

These predate the abstract API and are **kept deliberately**: two live n8n workflows POST to them
with the `Chat Auth` credential, and send-to-a-phone-number has no canonical equivalent.

| # | Endpoint | Method | Auth | Test Command | Expected |
|---|----------|--------|------|-------------|----------|
| 1 | `/api/bot/state` | GET | Yes | `curl -u user:pass .../api/bot/state` | JSON with `is_connected`, `users`, `botNumber` |
| 2 | `/api/subscribers` | GET | Yes | `curl -u user:pass .../api/subscribers` | JSON array of subscribers |
| 3 | `/api/subscribers` | DELETE | Yes | `curl -X DELETE -u user:pass .../api/subscribers` | `{success: true}` (⚠️ deletes all!) |
| 4 | `/api/subscribers/backup` | GET | Yes | `curl -u user:pass -o backup.json .../api/subscribers/backup` | JSON file download |
| 5 | `/api/subscribers/restore` | POST | Yes | Upload JSON backup file | Redirects to `/` |
| 6 | `/api/bot/qr` | GET | Yes | Open in browser | PNG QR image (only when disconnected) |
| 7 | `/api/bot/disconnect` | POST | Yes | `curl -X POST -u user:pass .../api/bot/disconnect` | `{success: true}` (⚠️ disconnects bot!) |
| 8 | `/api/bot/broadcast` | POST | Yes | See §1.4 | `{success: true}` |
| 9 | `/api/bot/send-document` | POST | Yes | Multipart form with `document` file + `phoneNumber` + `caption` | `{success: true}` |
| 10 | `/login` | POST | Rate limited | Form POST with `username` + `password` | Redirect to `/` |
| 11 | Any invalid path | GET | — | `curl .../nonexistent` | 404 page |



## Part 6: Verification Summary Checklist

- [x] Admin panel login works
- [x] Bot shows connected on dashboard
- [x] Subscribers list loads correctly
- [x] Backup download produces valid JSON
- [ ] Welcome message for new user *(not testable — already subscribed)*
- [x] Option 1 (hello) responds with name
- [x] Option 2 (about) shows info text
- [x] Option 10 (balance sheet) enters file upload state
- [x] Option 11 (generic doc) enters file upload state
- [x] Cancel (English) exits awaiting state
- [x] Cancel (Hebrew ביטול) exits awaiting state
- [x] Invalid input shows error + menu
- [ ] File upload in option 10 processes correctly *(VNC file picker limitation)*
- [ ] File upload in option 11 processes correctly *(VNC file picker limitation)*
- [ ] Company guess fallback works for option 10 *(depends on file upload)*
- [x] Group messages do not trigger bot responses *(replaced by group admin command support in v0.6)*
- [x] Group media from admin is saved *(auto-intake link processed in group)*
- [x] Bot reconnects after container restart
- [ ] Rate limiting blocks excessive login attempts *(not tested)*
- [ ] Unauthenticated API requests are rejected *(not tested)*
- [ ] Broadcast sends to all subscribers *(not tested — affects real users)*
- [ ] Document send via admin works with thumbnail *(not tested)*
- [x] Option 12 (link intake) processes URL document correctly
- [x] Option 12 cancel works
- [x] Option 13 (reload settings) reloads admins and companies
- [ ] Auto-intake document outside menu works *(VNC file picker limitation)*
- [x] Auto-intake link outside menu works
- [x] Auto-intake mixed text+link extracts URL correctly
- [x] Settings loaded at startup (admins + companies in logs) *(9 admins, 1203 companies)*
- [x] Group chat: bot responds to admin commands
- [ ] Group chat: bot ignores non-admin messages *(no second phone available)*

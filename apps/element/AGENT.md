# Operating «אלמנט» (the `element` app)

Element Desktop, the official Matrix client, inside the office (ai/context/wrapped-official-app.md, DGO-1264):
- its screen is the console's tile (Element Desktop under Selkies, behind the front door);
- its headless side is the adapter at `http://element:3093` (`chat.v1`: probe, listConversations,
  getConversation, sendMessage, markRead), over the Matrix client-server API;
- both live in the volume `element_home`: the screen's sign-in in `desktop/`, the adapter's in `adapter/`
  (the only folder the adapter mounts).

The adapter is a device of its own on the owner's account. Element keeps its session encrypted in its own
store, and the office never reads a vendor's files, so the owner signs the adapter in once.

## What you can do from here

```bash
./bbox element status [--json]
./bbox element login https://matrix.example.org owner --password-stdin   # the password on stdin
./bbox element login https://matrix.example.org --token-stdin            # or a token copied from Element
./bbox element rooms [N]                       # id · name · encrypted|plain · unread
./bbox element read '<room id>' [N]
./bbox element send '<room id>' <text…>
./bbox element mark-read '<room id>' '<event id>'
./bbox element logout
```

## Rules

- `send` is a message to people, as the owner: it runs only on the owner's word.
- The sign-in is the owner's. Never sign out the screen, never change the account. `logout` signs out only
  a device the adapter signed in with a password. A token copied from Element belongs to his other device,
  and is only forgotten.
- Act through the adapter (`chat.v1`), never through Element's files.

## Traps

- The screen signs in by PASSWORD. A homeserver that signs in through a browser (SSO, or the Matrix
  Authentication Service, which matrix.org uses) needs a browser in the desktop image. It has none yet, and
  that is DGO-1264's next slice (bina-claude's sign-in browser, DGO-1506, is the pattern). For the adapter,
  a token copied from Element works on any server, but such a token may expire, and then `status` says
  «not signed in».
- Encrypted rooms: the adapter does not decrypt. Their messages read as «encrypted», and `send` into one is
  refused (409). Read and write them on the screen.
- Every call but `/v1/health` needs the app's bearer token (`/data/adapter/api-token`); the hooks read it
  inside the container.
- No flow yet: the adapter has no sync loop, so nothing is published on `dgo:flow:element` (G108 KNOWN).

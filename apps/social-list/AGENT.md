# Operating `social-list`

Every social network the business is on, behind ONE abstract API (`social.v1`): profile
(name, bio, avatar, banner, links), posts (create/list/update/delete), comments, reactions, insights.
An **account** is an instance in the credential plane; its **kind** is how the office speaks for it:

- `browser` — **the default, on every network** (Facebook, Instagram, X, YouTube, GitHub, Discord,
  WhatsApp Web): the owner logged in ONCE in the office browser (browser42) and a portal script
  (`scripts/<network>.yaml`) acts in that session, at a person's pace;
- `api` — the alternative where a network has one, with a token in the vault (GitHub, Discord bot,
  Facebook Page, Instagram Graph, X, YouTube, WhatsApp Cloud).

There is no "prepare and let the owner click" kind. An op without a script yet answers `no` with the
reason; it opens when its script is written and one watched run verified it.

The caller never picks the implementation: the account's protocol does. `fixture` is the office's
own test network (served at `/fixture/`), used to prove the whole chain without a real account.

## What you can do from here

```bash
curl -s http://social-list:8986/api/accounts                        # every account, its network and kind
curl -s -X POST http://social-list:8986/capabilities -H 'content-type: application/json' \
     -d '{"account":"facebook"}'                                     # what this account can do, op by op
curl -s -X POST http://social-list:8986/getProfile -H 'content-type: application/json' -d '{"account":"x"}'
# a post (account = an account id, or a network id meaning its primary account); a write is a JOB:
curl -s -X POST http://social-list:8986/createPost -H 'content-type: application/json' \
     -d '{"account":"facebook","post":{"text":"…","media":[{"kind":"image","url":"http://digital-assets:8985/files/<sha>.png"}]},"wait":25}'
curl -s http://social-list:8986/api/jobs/<id>                       # queued | running | ok | error
curl -s -X POST http://social-list:8986/api/selftest -d '{"kind":"api"}' -H 'content-type: application/json'
```

Canonical ops: `POST /<op>` for listAccounts, getProfile, updateProfile, listPosts, createPost,
updatePost, deletePost (needs `confirm` = the post id), listComments, createComment, deleteComment,
react, insights, capabilities. `GET /api/activity` is the log of everything done on the owner's behalf.

## Traps

- **An ok is a READ-BACK, not a click.** A write ends `ok` only when the network shows the new value;
  otherwise `assert_failed` with the evidence. Report exactly that.
- **`needs_human_login` / `needs_2fa` / `captcha` stop everything.** Tell the owner to log in once in
  the office browser's live view (`/a/browser42/`). Never retry, never type a password anywhere.
- **`needs_verification`** = a browser script that no human has watched succeed yet. Only the owner
  may unlock it (`watch: true` while watching the live view). Never pass `watch` yourself.
- **`tos`** (ban / risk / low) is what the network's terms say about automating its site — shown to
  the owner, never a switch. Keep browser writes few and owner-initiated on every network.
- X's API is paid per use and a post that carries a URL costs ~13× more (`cost_hint` in the result).
- Instagram's API cannot edit a profile at all, and publishes only from a PUBLIC image URL
  (`SOCIAL_LIST_PUBLIC_URL`); the browser account does both without either limit.
- Connecting or disconnecting an account is the owner's act in the UI (`/a/social-list/`), not yours.

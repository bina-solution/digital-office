# Operating «אחסון הלשכה» (the `drive-local` engine)

The office's own storage — an ENGINE of «קבצים» (the generic `drive` app; apps/drive/ENGINES.md). It holds
the files of every profile of the office's storage (`admin`, `user2`…): the index in postgres
(`drive_files`, `drive_folders`, `drive_profiles`, `drive_media`), the bytes in supabase storage (bucket
`drive`). It has no screen of its own: you never call it directly — work through «קבצים».

## The four channels

- **ui** — inside «קבצים»: each profile is a drive under «כוננים»; «ניהול פרופילים» makes, renames,
  suspends and removes profiles (its `/engine/*` routes, handed over by «קבצים»).
- **cli** — `./bbox drive …` (every verb takes `-p <profile>`); `./bbox drive-local status` says whether
  the engine answers and lists its accounts.
- **api** — `drive-engine.v1` at `http://drive-local:8988` (`GET /ops`, `POST /v1/accounts|describe|call/<m>`,
  `GET /v1/content|download`, `PUT /v1/store|op_upload`): «קבצים»'s, not yours. Agents and apps use
  «קבצים»'s own routes (`http://drive:8975/api/fs…`, the §3 ops), which name a drive by `connection_id` or
  `profile_id` and reach this engine by themselves.
- **flow** — none of its own: what happened is «קבצים»'s and the office's log.

## Rules

- **Never delete.** A profile removed in «ניהול פרופילים» removes ACCESS only; its files stay (rows keep
  their `profile`), and making the profile again under the same id brings them back.
- A profile's key is shown ONCE when it is made or rotated; only its hash is kept. Never print one.
- The share link `https://drive.<office>/file/d/<id>/view` opens a file for anyone who has it — give one
  only when asked. A file in the trash is not served.
- The declared profiles are in this app's `app.json` (`engine.profiles`); the reconciler makes them at
  start and never re-mints a key of a profile that has its vault instance.

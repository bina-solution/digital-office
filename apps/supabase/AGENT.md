# Operating «סופאבייס» (the `supabase` app)

Supabase over the office's own Postgres (`platform-base/postgres`; this app runs no database of its
own). It provides two capabilities other apps require, drive and indox among them:

- `object-storage`: `http://supabase-kong:8000/storage/v1` (put, get, list, delete);
- `data-api`: `http://supabase-kong:8000` (REST).

Studio, the screen for tables and storage, is `supabase-studio`, behind the office's SSO. It ships
off, and in the herd it belongs on the HP.

## Rules

- Read through the REST API with the key the calling app already holds. Never hand out the service
  key: with it, the gateway's `/pg/` route reaches postgres-meta as `supabase_admin`, which is SQL on
  the platform database.
- **Studio and its meta service act as `supabase_admin` on the platform database.** An edit there
  changes every app's data. Only on the owner's words, for the table he named.
- **Never rotate `SUPABASE_JWT_SECRET` on your own.** The anon and service keys are JWTs minted from
  it (`platform-base/postgres/hooks/keygen.py`), and n8n, drive, indox and apitools hold them. A rotation
  invalidates all of them, and a restart does not bring the apps back: the keys must be minted again.
- `hooks/backup` and `hooks/restore` are called by the deployment archive, never by hand.

## Traps

- **The gateway is published.** kong is routed by the edge at `SUPABASE_BASE_URL` (and
  `supabase.localhost`) on plain HTTP, with no SSO in front. Its own key checks are the only gate,
  so never add a route to `kong.yml`.
- The storage route has no key check at the gateway: the storage service verifies each request
  itself (a JWT or an S3 signature).
- `kong.yml` routes `/auth`, `/realtime` and `/functions` to services this compose does not run, so
  those paths fail.
- The dashboard password (`SUPABASE_DASHBOARD_PASSWORD`) guards no route. Studio's sign-in is the
  office's SSO.

Gates: G23 (a gallery app ships disabled).

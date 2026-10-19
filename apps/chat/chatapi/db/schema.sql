-- The private chat engine's IDENTITY table, on the Postgres the platform already runs.
--
-- ONE table, and that is the whole point of this file now. Conversations, members, messages,
-- attachments, mentions and read state used to live here too; they live on the buzz relay
-- (`chat-relay`) since 2026-09-02, because read state, pin lists, typing, presence, threads,
-- reactions, edits, group roles and full-text search were each going to be another table and
-- another hand-written query here. See ai/context/chat-buzz-engine-plan.md for the argument and
-- the measured evidence; chat-service-plan.md §3 is the decision it reverses, and only that.
--
-- What did NOT move, and why it is still here: a PROFILE is an authorisation fact about THIS
-- deployment — which identities exist, which of them is an admin, and the hash of the api key this
-- service verifies inbound calls against. The relay knows nothing about any of that; it knows
-- pubkeys. So the identity plane stays local and the conversation plane is the engine's.
--
-- Every statement is IF NOT EXISTS, because this file runs on EVERY start of the app rather than
-- once from a migration runner. There is no migration state to get out of step with the tables, and
-- a container that comes up against an empty database provisions itself instead of erroring.
--
-- The retired tables are NOT dropped here. This file runs unattended on every boot, and a DROP in
-- it would destroy a live deployment's chat history the moment it deployed — silently, and with no
-- backup taken. Retiring them is a deliberate, operator-run step: apps/chat/hooks/drop-legacy-chat.
--
-- `__SCHEMA__` is substituted by db/index.js (default `public`) so a deployment can isolate chat in
-- its own schema without a second copy of this DDL.

-- IDENTITIES ON THIS ENGINE — the private engine's profiles.
--
-- One row per identity this deployment can ACT AS. The credential is what makes a profile an
-- ordinary instance rather than a special case: the key itself lives in the connections vault (so a
-- client can fetch it), and only its HASH lives here (so this service can verify an inbound call).
-- Never both in one place.
--
-- `id` is a slug: it lands in a WHERE clause, a vault account_hint and a URL path segment, so it is
-- kept inert. It used to carry a FOREIGN KEY to chat_users — a profile was also a person row — and
-- that reference is gone with the table: on the relay a person IS a pubkey, and the profile's own
-- `pubkey` column below is the link. `instance_id` is the vault instance minted for it — NULLABLE,
-- because connections may be unreachable at bootstrap and a profile that exists locally with its
-- instance still pending is a retry, not a failure.
CREATE TABLE IF NOT EXISTS __SCHEMA__.chat_profiles (
  id            text PRIMARY KEY,
  display_name  text        NOT NULL DEFAULT '',
  is_admin      boolean     NOT NULL DEFAULT false,
  -- sha256 of the minted API key, hex. Never the key.
  key_hash      text        NOT NULL,
  status        text        NOT NULL DEFAULT 'active',   -- 'active' | 'suspended'
  instance_id   text,                                    -- the connections-vault instance, once made
  -- The profile's identity ON THE RELAY: the 64-hex Nostr pubkey whose nsec lives in the vault
  -- beside the api key. Stored here (and only the PUBLIC half) so this service can answer the one
  -- question the projection asks constantly and cannot ask the vault on a hot path: "the author of
  -- this event — is that one of our profiles, and which?". That is what turns a relay pubkey back
  -- into `sender.id = <profile slug>`, which is what keeps every bot's per-user state — admin
  -- lists, daily limits, per-user locks — valid across the engine swap.
  pubkey        text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Added after chat_profiles already existed on live deployments, so it is a separate ALTER rather
-- than part of the CREATE above (which IF NOT EXISTS would skip entirely).
ALTER TABLE __SCHEMA__.chat_profiles ADD COLUMN IF NOT EXISTS pubkey text;

-- …and for the same reason, the FK to the retired chat_users has to be dropped from tables that
-- already exist. Removing it from the CREATE above is enough for a fresh database and does NOTHING
-- to a live one: `IF NOT EXISTS` skips the whole statement, constraint and all. Measured — with the
-- constraint still in place, declaring a new profile failed with `insert or update on table
-- "chat_profiles" violates foreign key constraint "chat_profiles_id_fkey"`, because there was no
-- longer a person row to point at.
--
-- Dropping a constraint LOOSENS the schema: no row is touched and nothing is lost, which is why
-- this one belongs in the boot path while the DROP TABLEs deliberately do not (they are
-- apps/chat/hooks/drop-legacy-chat, with a backup and a human).
ALTER TABLE __SCHEMA__.chat_profiles DROP CONSTRAINT IF EXISTS chat_profiles_id_fkey;

-- Credential resolution is on the hot path of every authenticated request: hash → profile.
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_profiles_key_hash
  ON __SCHEMA__.chat_profiles (key_hash);

-- Resolution the other way: an instance id off the connection bar → the profile it addresses.
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_profiles_instance
  ON __SCHEMA__.chat_profiles (instance_id) WHERE instance_id IS NOT NULL;

-- And the third direction, which the relay projection walks on every conversation list: a Nostr
-- pubkey → the profile it belongs to. UNIQUE because two profiles sharing an identity would make
-- "who sent this" ambiguous, and the answer decides which bot is allowed to reply.
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_profiles_pubkey
  ON __SCHEMA__.chat_profiles (pubkey) WHERE pubkey IS NOT NULL;

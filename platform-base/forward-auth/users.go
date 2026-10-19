package main

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// The user store is a FILE read once at boot and then held in memory. It is deliberately not a
// database and not an API: v1 has one owner, and the office already has exactly one place that
// holds a person's secret — the credential plane (`connections`). When the credential plane can
// write this file, the store is empty of policy and this program never learns a new fact.

// user is one person, in the vocabulary the whole estate already reads: the fields below are the
// five headers every gated app trusts.
type user struct {
	Name    string // X-authentik-username — the identity. `console`, `my-docs` and `indox` key on it.
	Email   string // X-authentik-email
	Display string // X-authentik-name
	UID     string // X-authentik-uid — for a migrated office, authentik's OWN uid (see loadUsers)
	Groups  []string
	hash    string // pbkdf2-sha256$… (ours) or pbkdf2_sha256$… (authentik's), never logged or rendered
	// unusable marks Django's `!<40 chars>` value: the account exists and has NO password. It is not
	// a hash and can never match; keeping the row is what lets a migrated office carry its service
	// accounts without the file being refused.
	unusable bool
	// legacy records that `hash` is authentik's family, so the window can watch the count fall.
	legacy bool
}

// GroupHeader renders Groups the way the estate parses it. `|` is not a guess: console/app.py:83
// and indox …/api/__init__.py:6983 both `.split("|")` this exact header.
func (u *user) GroupHeader() string { return strings.Join(u.Groups, "|") }

type userStore struct {
	byName map[string]*user
	// burn is a real hash of a password nobody knows, verified against when the NAME is unknown.
	// WHY: without it, "no such user" returns in microseconds and "wrong password" takes 210k
	// iterations — a free username oracle for an unauthenticated caller, one request at a time.
	burn string
	// legacy is how many loaded entries are still written in authentik's family. Reported at boot;
	// never used to decide anything (see the family comment above).
	legacy int
}

// loadUsers reads the users file. Format, one user per line, `#` comments and blank lines ignored:
//
//	<name> <email> <display> <uid> <groups> <hash>
//
// `<groups>` is comma-separated and `-` means none. The hash is the LAST field because it is the
// only one that cannot contain a space, so a line is self-describing without a quoting rule.
// A malformed line is FATAL rather than skipped: silently dropping the owner's line is a login
// page that refuses the owner, and it would look like a wrong password.
//
// A MIGRATED OFFICE writes the owner's line from authentik, and two of the six fields then carry a
// value this program does not choose:
//
//   - `<uid>` must be authentik's OWN uid, not a number this program invents. authentik's outpost
//     sends `X-authentik-uid` and it is `sha256("<user.id>-<install_id>")` in hex (64 chars) —
//     `User.uid` in authentik/core/models.py, which the API confirms for akadmin in the live office.
//     Anything an app stores keyed on that header would otherwise name a different person after the
//     swap. It is read, once, from authentik's own database before the window; §"Migration" of the
//     design note carries the query.
//   - `<groups>` cannot carry a group name containing a space (the file is whitespace-separated),
//     and authentik's one group here is literally `authentik Admins`. `-` is the honest value: the
//     group is dropped LOUDLY (the boot line names it) rather than silently arriving truncated,
//     and a name with a space is a format limit to fix in the credential plane, not a password
//     to reset.
func loadUsers(path string) (*userStore, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	st := &userStore{byName: map[string]*user{}}
	for i, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		f := strings.Fields(line)
		if len(f) != 6 {
			return nil, fmt.Errorf("%s:%d: want 6 fields (name email display uid groups hash), got %d", path, i+1, len(f))
		}
		if _, dup := st.byName[f[0]]; dup {
			return nil, fmt.Errorf("%s:%d: duplicate user %q", path, i+1, f[0])
		}
		u := &user{Name: f[0], Email: f[1], Display: f[2], UID: f[3], hash: f[5]}
		if strings.HasPrefix(u.hash, unusablePrefix) {
			u.unusable = true
		} else {
			scheme, err := hashFamily(u.hash)
			if err != nil {
				return nil, fmt.Errorf("%s:%d: %w", path, i+1, err)
			}
			u.legacy = scheme == legacyScheme
		}
		if f[4] != "-" {
			u.Groups = strings.Split(f[4], ",")
		}
		if u.legacy {
			st.legacy++
		}
		st.byName[u.Name] = u
	}
	if len(st.byName) == 0 {
		return nil, fmt.Errorf("%s: no users — a store with nobody in it can only refuse", path)
	}
	if st.burn, err = hashPassword(randomToken(24)); err != nil {
		return nil, err
	}
	return st, nil
}

// verify answers "is this the person, and only if so, who". It is the ONLY way a session is ever
// minted, so both halves of it are constant-time or deliberately equal-length:
//   - the name lookup is a map hit (Go maps are not constant-time, and hiding WHICH name exists
//     would mean walking the store — the burn above equalises the cost that actually leaks);
//   - the password comparison is subtle.ConstantTimeCompare, never `==`.
//   - an account whose stored value is unusable (`!…`) burns exactly like an unknown name: Django
//     does the same, and returning early here would turn "this account has no password" into the
//     same cheap answer as "no such account" only for the accounts that DO exist.
func (s *userStore) verify(name, password string) (*user, bool) {
	u, ok := s.byName[name]
	if !ok || u.unusable {
		_, _ = checkPassword(s.burn, password)
		return nil, false
	}
	good, err := checkPassword(u.hash, password)
	if err != nil || !good {
		return nil, false
	}
	return u, true
}

// ── password hashing ─────────────────────────────────────────────────────────────────────────────
//
// WHY a KDF at all, in a service whose whole point is "small, stdlib, no cgo": the standard library
// has no KDF, and a plain sha256(password) is a password hash in name only — one GPU walks a
// human-chosen password in seconds. Twenty lines of a published construction (RFC 8018 §5.2) is
// strictly the smaller risk, and it keeps the no-dependency, cross-compile-anywhere property that
// the owner asked for (x/crypto/bcrypt or argon2 would spend it).

const (
	hashScheme = "pbkdf2-sha256"
	// iterations is written INTO every hash, so raising it later does not invalidate the entries
	// already written by the credential plane — old lines keep working, new ones are stronger.
	iterations = 210_000
	saltLen    = 16
	keyLen     = 32
)

// pbkdf2SHA256 is PBKDF2 with HMAC-SHA256 as the PRF (RFC 8018 §5.2).
func pbkdf2SHA256(password, salt []byte, iter, dkLen int) []byte {
	prf := hmac.New(sha256.New, password)
	hLen := prf.Size()
	blocks := (dkLen + hLen - 1) / hLen
	out := make([]byte, 0, blocks*hLen)
	u := make([]byte, hLen)
	t := make([]byte, hLen)
	counter := make([]byte, 4)
	for b := 1; b <= blocks; b++ {
		counter[0], counter[1], counter[2], counter[3] = byte(b>>24), byte(b>>16), byte(b>>8), byte(b)
		prf.Reset()
		prf.Write(salt)
		prf.Write(counter)
		u = prf.Sum(u[:0])
		copy(t, u)
		for n := 2; n <= iter; n++ {
			prf.Reset()
			prf.Write(u)
			u = prf.Sum(u[:0])
			for k := range t {
				t[k] ^= u[k]
			}
		}
		out = append(out, t...)
	}
	return out[:dkLen]
}

// hashPassword mints a storable entry. Used by `-hash` and by the burn value; never on the request
// path, where the cost would be a way to drown the office in CPU.
func hashPassword(password string) (string, error) {
	salt := make([]byte, saltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	enc := base64.RawStdEncoding
	sum := pbkdf2SHA256([]byte(password), salt, iterations, keyLen)
	return fmt.Sprintf("%s$%d$%s$%s", hashScheme, iterations, enc.EncodeToString(salt), enc.EncodeToString(sum)), nil
}

// ── the TWO stored families, and why both must be read ───────────────────────────────────────────
//
// `pbkdf2-sha256` is OURS. `pbkdf2_sha256` — one character apart, so it is spelled out everywhere —
// is AUTHENTIK'S, i.e. Django's `PBKDF2PasswordHasher` (django/contrib/auth/hashers.py, Django
// 5.0.10 in the live image). Reading it is the whole of requirement 2 of `core-006`: the owner's
// password database is carried over AS IT IS, so a migrated office authenticates with no password
// reset and nothing to re-enter.
//
// They are not the same construction, and the three differences are each a silent failure if you
// get them wrong:
//
//	                    ours                              Django's
//	scheme              pbkdf2-sha256                     pbkdf2_sha256      (hyphen vs underscore)
//	salt                base64url-free std, UNPADDED     PLAIN ASCII, 22 chars from [A-Za-z0-9]
//	digest suffix       base64 std, UNPADDED (43 chars)  base64 std, PADDED (44 chars, ends "=")
//	comparison          raw digest, constant time        the WHOLE re-encoded entry, constant time
//
// The salt one is the trap. Django's salt is high-entropy ASCII (`get_random_string(22,
// RANDOM_STRING_CHARS)` — 128 bits, `salt_entropy`) and it is fed to PBKDF2 as those 22 BYTES;
// base64-decoding it like ours produces a different key and refuses a correct password. Measured
// against the live office 2026-10-09: `authentik_core_user.password` for akadmin is four fields,
// 13/6/22/44 characters, iteration count 720000 — Django 5.0's own default, and 3.4× our 210k, so
// the imported hash is the STRONGER of the two.
//
// REHASH ON FIRST SUCCESSFUL LOGIN is the clean upgrade path, and this program deliberately does
// not do it: the users file is read ONCE at boot and mounted read-only, because a second writer for
// "who may sign in" is exactly what §2.7 of the design note refuses (the credential plane is the
// one writer). Nothing is lost by waiting: the imported hash is already stronger than a fresh one
// from here. The migration note (`ai/context/core-go-forward-auth.md`, "Migration") states the
// upgrade as it is actually done — the credential plane re-writes the line the next time it writes
// the file — and this program only REPORTS how many entries still carry the old family, so the
// window can watch that number reach zero.
const (
	// legacyScheme is Django's/authentik's spelling. Never written by this program; only read.
	legacyScheme = "pbkdf2_sha256"
	// unusablePrefix is Django's "this account has no usable password" marker
	// (`UNUSABLE_PASSWORD_PREFIX` + 40 random characters). The live office has two such rows, both
	// authentik service accounts; a migration that copies every row must not be refused because of
	// them, and no password may ever match one.
	unusablePrefix = "!"
)

// parseHash splits a stored entry into the family it belongs to and its parameters, refusing
// anything neither this program nor authentik could have written. `salt` is returned as the CALLER
// must use it: for the legacy family that is the ASCII bytes Django fed to PBKDF2, and for ours it
// is the decoded 16 random bytes.
func parseHash(encoded string) (scheme string, iter int, salt, want []byte, err error) {
	parts := strings.SplitN(encoded, "$", 4)
	if len(parts) != 4 || (parts[0] != hashScheme && parts[0] != legacyScheme) {
		return "", 0, nil, nil, fmt.Errorf(
			"password hash %q is not %s$<iters>$<salt>$<hash> (this service) or %s$<iters>$<salt>$<hash> (authentik)",
			encoded, hashScheme, legacyScheme)
	}
	if iter, err = strconv.Atoi(parts[1]); err != nil || iter < 1 {
		return "", 0, nil, nil, fmt.Errorf("password hash iteration count %q is not a positive integer", parts[1])
	}
	switch parts[0] {
	case legacyScheme:
		if parts[2] == "" {
			return "", 0, nil, nil, errors.New("password hash salt is empty")
		}
		if want, err = base64.StdEncoding.DecodeString(parts[3]); err != nil {
			return "", 0, nil, nil, fmt.Errorf("password hash digest: %w", err)
		}
		return parts[0], iter, []byte(parts[2]), want, nil
	default:
		if salt, err = base64.RawStdEncoding.DecodeString(parts[2]); err != nil {
			return "", 0, nil, nil, fmt.Errorf("password hash salt: %w", err)
		}
		if want, err = base64.RawStdEncoding.DecodeString(parts[3]); err != nil {
			return "", 0, nil, nil, fmt.Errorf("password hash digest: %w", err)
		}
		return parts[0], iter, salt, want, nil
	}
}

// checkPassword is the constant-time comparison itself. It re-derives with the parameters STORED
// beside the hash, so entries written at a lower iteration count stay checkable.
func checkPassword(encoded, password string) (bool, error) {
	scheme, iter, salt, want, err := parseHash(encoded)
	if err != nil {
		return false, err
	}
	got := pbkdf2SHA256([]byte(password), salt, iter, len(want))
	if scheme == legacyScheme {
		// Django verifies by RE-ENCODING and comparing the whole entry
		// (`constant_time_compare(encoded, self.encode(password, salt, iterations))`), not by
		// comparing digests. Reproducing that is what makes a mismatch in padding, iteration
		// spelling or salt encoding a refusal here instead of an acceptance there.
		re := fmt.Sprintf("%s$%d$%s$%s", legacyScheme, iter, string(salt), base64.StdEncoding.EncodeToString(got))
		return subtle.ConstantTimeCompare([]byte(re), []byte(encoded)) == 1, nil
	}
	return subtle.ConstantTimeCompare(got, want) == 1, nil
}

// hashFamily names the family an entry is written in, without deriving anything: `loadUsers` uses it
// to refuse a file it cannot verify, and to count what will need re-writing once the credential
// plane next writes the file.
func hashFamily(encoded string) (string, error) {
	scheme, _, _, _, err := parseHash(encoded)
	return scheme, err
}

func randomToken(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic("forward-auth: no entropy: " + err.Error()) // a session without entropy is not a session
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

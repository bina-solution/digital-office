// forward-auth — the office's identity service, as one Go binary.
//
// It replaces authentik in layers 1–2: 1132 MB and 4 containers become one static binary that does
// the one job the estate actually uses (forward-auth) and nothing else. DESIGN AND MIGRATION:
// ai/context/core-go-forward-auth.md, which also states what authentik does here that this does NOT.
//
// Build (release):  go build -trimpath -ldflags "-s -w" . && go test ./...
// Cross-compile for every OS from one host: GOOS=windows|darwin|linux GOARCH=amd64|arm64 go build .
// That property is not free — it is why the module is stdlib-only and the build is CGO_ENABLED=0.
package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

func main() {
	hashOnly := flag.Bool("hash", false, "read a password on stdin and print the users-file entry, then exit")
	healthAt := flag.String("health", "", "GET this URL and exit 0 iff it answers 2xx, then exit (for a HEALTHCHECK on a scratch image)")
	flag.Parse()

	if *hashOnly {
		line, err := bufio.NewReader(os.Stdin).ReadString('\n')
		if err != nil && line == "" {
			log.Fatalf("forward-auth: -hash: nothing on stdin: %v", err)
		}
		h, err := hashPassword(strings.TrimRight(line, "\r\n"))
		if err != nil {
			log.Fatalf("forward-auth: -hash: %v", err)
		}
		fmt.Println(h)
		return
	}

	if *healthAt != "" {
		c := &http.Client{Timeout: 5 * time.Second}
		resp, err := c.Get(*healthAt)
		if err != nil {
			log.Fatalf("forward-auth: -health: %v", err)
		}
		_ = resp.Body.Close()
		if resp.StatusCode < 200 || resp.StatusCode > 299 {
			log.Fatalf("forward-auth: -health: %s answered %d", *healthAt, resp.StatusCode)
		}
		return
	}

	cfg, err := configFromEnv()
	if err != nil {
		// Refuse to start, loudly. WHY this is fatal rather than a warning with defaults: the one
		// value it complains about is the cookie signing key. A service that starts without one
		// signs every session with an empty key, and then anybody on the office network can mint a
		// cookie naming the owner. There is no safe default for a secret.
		log.Fatalf("forward-auth: %v", err)
	}
	users, err := loadUsers(cfg.usersFile)
	if err != nil {
		log.Fatalf("forward-auth: %v", err)
	}

	s := &server{
		users:        users,
		sign:         &signer{key: []byte(cfg.secret), ttl: cfg.sessionTTL},
		external:     cfg.external,
		secureCookie: strings.HasPrefix(cfg.external, "https://"),
		cookieDomain: cfg.cookieDomain,
		suffixes:     cfg.suffixes,
		legacy:       cfg.legacySessions,
		legacyKey:    legacySigningKey(cfg.legacySecretKey),
	}
	legacyNote := "authentik cookies NOT accepted"
	if s.legacy != nil {
		legacyNote = fmt.Sprintf("accepting %d live authentik session(s) until %s",
			len(s.legacy.bySID), s.legacy.latest.UTC().Format(time.RFC3339))
	}
	log.Printf("forward-auth: listening on %s · %d user(s) · %s · cookies %s · return-to bounded to %s · %s",
		cfg.listen, len(users.byName), cfg.external,
		map[bool]string{true: "Secure", false: "plain (http edge)"}[s.secureCookie],
		strings.Join(cfg.suffixes, " "), legacyNote)
	// One line, at boot, about the password family — the number the window watches fall to zero.
	// It names no user and no hash: `users.legacy` is a count and nothing else.
	if users.legacy > 0 {
		log.Printf("forward-auth: %d of %d user(s) authenticate from an authentik %s hash, verified as-is; "+
			"the credential plane re-writes them in this service's own family when it next writes the file",
			users.legacy, len(users.byName), legacyScheme)
	}

	srv := &http.Server{
		Addr:              cfg.listen,
		Handler:           s.routes(),
		ReadHeaderTimeout: 10 * time.Second, // a slow-loris header is the cheapest way to hold a worker
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       90 * time.Second,
	}
	log.Fatal(srv.ListenAndServe())
}

// ── configuration ────────────────────────────────────────────────────────────────────────────────
//
// Everything comes from the environment, because that is how this platform passes a fact to a
// container (`app.json` → `.generated/`). Nothing is read from a file that a running process could
// have changed underneath us — the one file there is, the users file, is read once, at boot.

type config struct {
	listen       string
	external     string
	cookieDomain string
	secret       string
	usersFile    string
	sessionTTL   time.Duration
	suffixes     []string
	// The migration pair. BOTH or NEITHER: a snapshot with no key cannot verify a cookie (and would
	// only be a place to relax the signature later), and a key with no snapshot would accept a
	// signature over a session authentik may already have retired. Off is the default and is a
	// complete, working service — it simply challenges a browser holding authentik's cookie, and the
	// person signs in again with the password that still verifies.
	legacySecretKey  string
	legacySessions   *legacySessions
	legacySessionsAt string
}

const (
	defaultListen    = ":9000"
	defaultUsersFile = "/etc/forward-auth/users"
	defaultSession   = 12 * time.Hour
	// A signing key shorter than the hash it feeds is the weak link in an otherwise sound cookie.
	minSecretLen = 32
)

func configFromEnv() (*config, error) {
	c := &config{
		listen:       env("FORWARD_AUTH_LISTEN", defaultListen),
		external:     strings.TrimRight(env("FORWARD_AUTH_EXTERNAL_URL", ""), "/"),
		cookieDomain: env("FORWARD_AUTH_COOKIE_DOMAIN", ""),
		secret:       env("FORWARD_AUTH_SECRET", ""),
		usersFile:    env("FORWARD_AUTH_USERS_FILE", defaultUsersFile),
		sessionTTL:   defaultSession,
	}

	var missing []string
	if c.external == "" {
		missing = append(missing, "FORWARD_AUTH_EXTERNAL_URL")
	}
	if c.secret == "" {
		missing = append(missing, "FORWARD_AUTH_SECRET")
	}
	// A return-to that is not bounded is an open redirect, and the bound is a deployment fact (which
	// hosts this office serves), not something this program can infer from a request it is trying to
	// authenticate. So it is required, and there is no default.
	hosts := env("FORWARD_AUTH_ALLOWED_HOSTS", "")
	if strings.TrimSpace(hosts) == "" {
		missing = append(missing, "FORWARD_AUTH_ALLOWED_HOSTS")
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("refusing to start without %s", strings.Join(missing, ", "))
	}
	if len(c.secret) < minSecretLen {
		return nil, fmt.Errorf("FORWARD_AUTH_SECRET is %d bytes; a cookie signing key needs at least %d", len(c.secret), minSecretLen)
	}
	if !strings.HasPrefix(c.external, "http://") && !strings.HasPrefix(c.external, "https://") {
		return nil, errors.New("FORWARD_AUTH_EXTERNAL_URL must be an absolute http(s) URL, e.g. http://auth.localhost")
	}
	for _, h := range strings.Split(hosts, ",") {
		if h = strings.TrimSpace(h); h != "" {
			c.suffixes = append(c.suffixes, h)
		}
	}
	if ttl := env("FORWARD_AUTH_SESSION_TTL", ""); ttl != "" {
		d, err := time.ParseDuration(ttl)
		if err != nil || d <= 0 {
			return nil, fmt.Errorf("FORWARD_AUTH_SESSION_TTL %q is not a positive duration", ttl)
		}
		c.sessionTTL = d
	}

	// The migration pair, both-or-neither, and the file must LOAD: a snapshot configured but
	// unreadable is a service that silently refuses every pre-swap session, which is the one failure
	// this whole file exists to prevent.
	c.legacySecretKey = env("FORWARD_AUTH_LEGACY_SECRET", "")
	c.legacySessionsAt = env("FORWARD_AUTH_LEGACY_SESSIONS", "")
	switch {
	case c.legacySecretKey == "" && c.legacySessionsAt == "":
		// Off. Nothing to do: this is the steady state after step 7.
	case c.legacySecretKey == "" || c.legacySessionsAt == "":
		return nil, errors.New("FORWARD_AUTH_LEGACY_SECRET and FORWARD_AUTH_LEGACY_SESSIONS must be set together " +
			"(the first verifies authentik's cookie, the second says which of its sessions are still live)")
	default:
		ls, err := loadLegacySessions(c.legacySessionsAt)
		if err != nil {
			return nil, fmt.Errorf("FORWARD_AUTH_LEGACY_SESSIONS: %w", err)
		}
		c.legacySessions = ls
	}
	return c, nil
}

func env(name, fallback string) string {
	if v, ok := os.LookupEnv(name); ok {
		return v
	}
	return fallback
}

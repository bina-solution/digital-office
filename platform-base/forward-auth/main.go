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
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

func main() {
	hashOnly := flag.Bool("hash", false, "read a password on stdin and print the users-file entry, then exit")
	healthAt := flag.String("health", "", "GET this URL and exit 0 iff it answers 2xx, then exit (for a HEALTHCHECK on a scratch image)")
	firstRunOnly := flag.Bool("first-run", false, "read a first-run code on stdin; while there is no users file, keep its sha256 as the setup file (setup.go), then exit")
	importOnly := flag.Bool("import-users", false, "read a users file on stdin and keep it as the users file where there is none yet (setup.go), then exit")
	flag.Parse()

	if *firstRunOnly {
		os.Exit(writeFirstRun(env("FORWARD_AUTH_USERS_FILE", defaultUsersFile), env("FORWARD_AUTH_SETUP_FILE", defaultSetupFile),
			os.Stdin, os.Stdout))
	}
	if *importOnly {
		os.Exit(importUsers(env("FORWARD_AUTH_USERS_FILE", defaultUsersFile), os.Stdin, os.Stdout))
	}

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
	// A fresh office has no users file yet, only a first-run code (setup.go); every other office has
	// its file, and a missing one is still fatal — the message says which of the two is absent.
	firstRun, err := loadSetup(cfg.usersFile, cfg.setupFile)
	if err != nil {
		log.Fatalf("forward-auth: %v", err)
	}
	live, err := newLiveUsers(cfg.usersFile, firstRun.pending())
	if err != nil {
		log.Fatalf("forward-auth: %v", err)
	}
	users := live.cur
	if firstRun.pending() {
		log.Printf("forward-auth: no owner yet — first-run setup is open at %s/setup with the code the office printed", cfg.external)
	}

	s := &server{
		users:        users,
		live:         live,
		firstRun:     firstRun,
		handoff:      newHandoff([]byte(cfg.secret)),
		limit:        newLimiter(),
		sign:         &signer{key: []byte(cfg.secret), ttl: cfg.sessionTTL},
		external:     cfg.external,
		secureCookie: strings.HasPrefix(cfg.external, "https://"),
		cookieDomain: cfg.cookieDomain,
		suffixes:     cfg.suffixes,
		legacy:       cfg.legacySessions,
		legacyKey:    legacySigningKey(cfg.legacySecretKey),
		edgeToken:    []byte(cfg.edgeToken),
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
	ln, err := listen(cfg.listen)
	if err != nil {
		log.Fatalf("forward-auth: %v", err)
	}
	log.Fatal(srv.Serve(ln))
}

// listen opens FORWARD_AUTH_LISTEN: a TCP address (":9078", as the container is given it), or
// "unix:<absolute path>" — the phone's native core (DGO-1090), where loopback is shared by every app on
// the phone and a socket in the app's own directory is reached by this app alone. A socket left by a
// process that died — its connect refused — is replaced; one that answers, or fails any other way (a
// full backlog, another owner's), is not, and anything else at that path is never removed; the new
// socket is its owner's alone. One process starts it (the app's service): two starting at the same
// moment could both find the old socket dead.
func listen(addr string) (net.Listener, error) {
	path, isUnix := strings.CutPrefix(addr, "unix:")
	if !isUnix {
		return net.Listen("tcp", addr)
	}
	if !filepath.IsAbs(path) {
		return nil, fmt.Errorf("FORWARD_AUTH_LISTEN=%s: a socket's path is absolute", addr)
	}
	if len(path) > 107 { // sun_path's 108 bytes, its NUL aside: longer fails only as bind's "invalid argument"
		return nil, fmt.Errorf("FORWARD_AUTH_LISTEN=%s: %d bytes, and a socket's path is at most 107", addr, len(path))
	}
	if st, err := os.Lstat(path); err == nil {
		if st.Mode()&os.ModeSocket == 0 {
			return nil, fmt.Errorf("FORWARD_AUTH_LISTEN=%s: %s is there and is not a socket", addr, path)
		}
		c, err := net.DialTimeout("unix", path, time.Second)
		if err == nil {
			c.Close()
			return nil, fmt.Errorf("FORWARD_AUTH_LISTEN=%s: another process answers on it", addr)
		}
		if !errors.Is(err, syscall.ECONNREFUSED) {
			return nil, fmt.Errorf("FORWARD_AUTH_LISTEN=%s: %v — not taken over", addr, err)
		}
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return nil, err
		}
	}
	ln, err := net.Listen("unix", path)
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(path, 0o600); err != nil {
		ln.Close()
		return nil, err
	}
	return ln, nil
}

// ── configuration ────────────────────────────────────────────────────────────────────────────────
//
// Everything comes from the environment, because that is how this platform passes a fact to a
// container (`app.json` → `.generated/`). The one file there is, the users file, must load at boot,
// and is re-read when it changes (live.go).

type config struct {
	listen       string
	external     string
	cookieDomain string
	secret       string
	usersFile    string
	setupFile    string
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
	edgeToken        string // FORWARD_AUTH_EDGE_TOKEN: the phone's native core's (handlers.go fromCore)
}

const (
	defaultListen    = ":9000"
	defaultUsersFile = "/etc/forward-auth/users"
	defaultSetupFile = "/etc/forward-auth/setup"
	// 14 days, authentik's own session length (review finding F3): traefik cannot carry a Set-Cookie
	// on a 2xx, so there is no sliding renewal, and 12 h asked the owner for his password twice a day.
	defaultSession = 14 * 24 * time.Hour
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
		setupFile:    env("FORWARD_AUTH_SETUP_FILE", defaultSetupFile),
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
	// the phone's machine, behind its native core (fromCore): a token as strong as a signing key, or none
	if c.edgeToken = env("FORWARD_AUTH_EDGE_TOKEN", ""); c.edgeToken != "" && len(c.edgeToken) < minSecretLen {
		return nil, fmt.Errorf("FORWARD_AUTH_EDGE_TOKEN is %d bytes; it needs at least %d", len(c.edgeToken), minSecretLen)
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

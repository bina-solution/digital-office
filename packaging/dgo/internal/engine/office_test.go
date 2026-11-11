package engine

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// realTool is the machine's own tool by name, for an oracle whose PATH holds only what it names.
func realTool(name string) string { return "#!/bin/sh\nPATH=/usr/bin:/bin\nexec " + name + " \"$@\"\n" }

// TestTheEnvReadersAndTheOfficesNameMatchLibSh runs scripts/lib.sh's _env_raw, read_env, read_env_value,
// office_unnamed and office_project — their own text — beside envRaw, readEnv, readEnvValue, officeUnnamed and
// officeProject, on the .env and the folder of each case (DGO-1782, DGO-1802).
func TestTheEnvReadersAndTheOfficesNameMatchLibSh(t *testing.T) {
	funcs := shFunc(t, "scripts/lib.sh", "_env_raw", "read_env", "read_env_value", "office_unnamed", "office_project")
	cases := []struct{ name, dotenv, folder, compose string }{
		{"the template unedited: no name, the domain from an empty slug",
			"BUSINESS_NAME=\nCOMPANY_SLUG=\nCOMPANY_BASE_DOMAIN=digital-office.co.il\nDEPLOYMENT_DOMAIN=${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN}\n", "MyDGO", ""},
		{"a name", "BUSINESS_NAME=\"Bina Solutions\"\nDEPLOYMENT_DOMAIN=${COMPANY_SLUG}.x\n", "office", ""},
		{"a name that is a comment", "BUSINESS_NAME=   # your business\nDEPLOYMENT_DOMAIN=${COMPANY_SLUG:-}.x\n", "office", ""},
		{"an empty quoted slug resolves into quotes", "BUSINESS_NAME=\nCOMPANY_SLUG=\"\"\nDEPLOYMENT_DOMAIN=${COMPANY_SLUG}.digital-office.co.il\n", "x", ""},
		{"a literal domain by hand runs on", "BUSINESS_NAME=\nDEPLOYMENT_DOMAIN=office.example.com\n", "x", ""},
		{"defaults, a chain, an unclosed reference", "A=${B}\nB=${C:-deep}\nBUSINESS_NAME=${A}\nDEPLOYMENT_DOMAIN=${OPEN.x\n", "x", ""},
		{"CRLF and an «=» in a value", "BUSINESS_NAME=a=b\r\nDEPLOYMENT_DOMAIN=.x\r\n", "x", ""},
		{"a quoted name keeps « #»", "BUSINESS_NAME='Bina # Solutions' # note\nDEPLOYMENT_DOMAIN=.x\n", "x", ""},
		{"the first line of a key wins", "BUSINESS_NAME=\nBUSINESS_NAME=late\nDEPLOYMENT_DOMAIN=.x\n", "x", ""},
		{"a folder compose normalises", "", "--Weird.Name_9", ""},
		{"a folder named in Hebrew", "", "הלשכה שלי", ""},
		{"COMPOSE_PROJECT_NAME as given", "", "MyDGO", "Given_Name"},
	}
	for _, c := range cases {
		base := t.TempDir()
		root := filepath.Join(base, c.folder)
		if err := os.Mkdir(root, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, ".env"), []byte(c.dotenv), 0o644); err != nil {
			t.Fatal(err)
		}
		setup := "REPO_ROOT=\"$(P " + sq(root) + ")\""
		if c.compose != "" {
			setup += "\nexport COMPOSE_PROJECT_NAME=" + sq(c.compose)
		} else {
			setup += "\nunset COMPOSE_PROJECT_NAME"
		}
		stdout, stderr, code := shell(t, setup, funcs,
			`printf '%s|%s|' "$(read_env_value BUSINESS_NAME)" "$(read_env DEPLOYMENT_DOMAIN)"
if office_unnamed; then printf 'unnamed|'; else printf 'named|'; fi
office_project`,
			map[string]string{"head": realTool("head"), "basename": realTool("basename")})
		if code != 0 {
			t.Fatalf("%s: lib.sh exited %d: %s", c.name, code, stderr)
		}
		physical, err := filepath.EvalSymlinks(root)
		if err != nil {
			t.Fatal(err)
		}
		env := []byte(c.dotenv)
		word := "named"
		if officeUnnamed(env) {
			word = "unnamed"
		}
		got := readEnvValue(env, "BUSINESS_NAME") + "|" + readEnv(env, "DEPLOYMENT_DOMAIN") + "|" + word + "|" +
			officeProject(c.compose, filepath.ToSlash(physical))
		if got != stdout {
			t.Errorf("%s:\n go     %q\n lib.sh %q", c.name, got, stdout)
		}
	}
}

// TestHoldsDataMatchesLibSh runs scripts/lib.sh's office_holds_data — the engine's containers, then its
// volumes, of the checkout's project — beside officeHoldsData, on each answer the engine can give.
func TestHoldsDataMatchesLibSh(t *testing.T) {
	funcs := shFunc(t, "scripts/lib.sh", "office_project", "office_holds_data")
	const pn, dh = "office", "unix:///run/bbox-docker.sock"
	ps, vols := "ps -aq --filter label=com.docker.compose.project="+pn, "volume ls -q --filter label=com.docker.compose.project="+pn
	cases := []struct {
		name    string
		answers map[string]reply
	}{
		{"nothing of it", map[string]reply{ps: ok(""), vols: ok("")}},
		{"answers that are only newlines are nothing ($(…) drops them)", map[string]reply{ps: ok("\n"), vols: ok("\n\n")}},
		{"a stopped container", map[string]reply{ps: ok("3f2a9c\n"), vols: ok("")}},
		{"volumes only (its containers removed)", map[string]reply{ps: ok(""), vols: ok("office_pgdata\noffice_redis\n")}},
		{"the engine refuses the first question", map[string]reply{ps: no("permission denied"), vols: ok("")}},
		{"the engine refuses the second", map[string]reply{ps: ok(""), vols: no("Cannot connect to the Docker daemon")}},
	}
	for _, c := range cases {
		_, stderr, code := shell(t, "export COMPOSE_PROJECT_NAME="+pn, funcs, `office_holds_data || exit $?`,
			map[string]string{"docker": stub("docker", c.answers), "basename": realTool("basename")})
		r := &rec{goos: "linux", cmds: map[string]reply{}, env: map[string]string{}}
		for k, a := range c.answers {
			r.cmds["docker -H "+dh+" "+k] = a
		}
		if got := officeHoldsData(r.system(t), host{env: func(string) string { return "" }}, dh, pn); got != code {
			t.Errorf("%s: go %d, lib.sh %d (%s)", c.name, got, code, strings.TrimSpace(stderr))
		}
	}
}

package compiler

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// The bugs in reconcile.py that porting it to Go found (cyc-227…237, DGO-627…637), on the Go side: each
// case fails on the code before its fix, with no Python needed. platform/manager/test_port_findings.py
// holds the same cases on the Python side, and the oracle tests (render_test.go and the rest) keep the
// two compilers answering alike.

// DGO-631: syncIdentity writes a stale slug back in the file's own line endings.
func TestSyncIdentityKeepsTheFilesLineEndings(t *testing.T) {
	for _, c := range []struct{ name, before, after string }{
		{"a CRLF .env stays CRLF",
			"BUSINESS_NAME=\"Bina Solutions Ltd.\"\r\n#@derived slug\r\nCOMPANY_SLUG=old\r\nX=1\r\n",
			"BUSINESS_NAME=\"Bina Solutions Ltd.\"\r\n#@derived slug\r\nCOMPANY_SLUG=bina-solutions-ltd\r\nX=1\r\n"},
		{"an LF .env stays LF",
			"BUSINESS_NAME=\"Bina Solutions Ltd.\"\n#@derived slug\nCOMPANY_SLUG=old\n",
			"BUSINESS_NAME=\"Bina Solutions Ltd.\"\n#@derived slug\nCOMPANY_SLUG=bina-solutions-ltd\n"},
		{"a lone CR still ends a line, and stays",
			"A=1\rBUSINESS_NAME=\"Bina Solutions Ltd.\"\r\n#@derived slug\r\nCOMPANY_SLUG=old\r\n",
			"A=1\rBUSINESS_NAME=\"Bina Solutions Ltd.\"\r\n#@derived slug\r\nCOMPANY_SLUG=bina-solutions-ltd\r\n"},
		{"one CRLF line in an LF file keeps its own ending only",
			"BUSINESS_NAME=\"Bina Solutions Ltd.\"\n#@derived slug\nCOMPANY_SLUG=old\r\nX=1\n",
			"BUSINESS_NAME=\"Bina Solutions Ltd.\"\n#@derived slug\nCOMPANY_SLUG=bina-solutions-ltd\r\nX=1\n"},
		{"the planted slug takes the ending of BUSINESS_NAME's line",
			"A=1\r\nBUSINESS_NAME=\"Bina Solutions Ltd.\"\r\nB=2\r\n",
			"A=1\r\nBUSINESS_NAME=\"Bina Solutions Ltd.\"\r\n#@derived slug\r\nCOMPANY_SLUG=bina-solutions-ltd\r\nB=2\r\n"},
		{"under a last line with no ending, the file still ends without one",
			"A=1\nBUSINESS_NAME=\"Bina Solutions Ltd.\"",
			"A=1\nBUSINESS_NAME=\"Bina Solutions Ltd.\"\n#@derived slug\nCOMPANY_SLUG=bina-solutions-ltd"},
	} {
		t.Run(c.name, func(t *testing.T) {
			env := filepath.Join(t.TempDir(), ".env")
			if err := os.WriteFile(env, []byte(c.before), 0o666); err != nil {
				t.Fatal(err)
			}
			if err := syncIdentity(filepath.Dir(env), io.Discard); err != nil {
				t.Fatal(err)
			}
			got, err := os.ReadFile(env)
			if err != nil {
				t.Fatal(err)
			}
			if string(got) != c.after {
				t.Errorf(".env after syncIdentity:\n got %q\nwant %q", got, c.after)
			}
		})
	}
}

// DGO-630: a route that writes no `auth` is behind the sign-in (the routers' default) — and gets its
// provider and its host variable, as one that writes `auth: sso` does; `auth: none` stays open.
func TestARouteWithNoAuthGetsItsProvider(t *testing.T) {
	for _, c := range []struct {
		auth string
		want int
	}{{"auth: sso\n", 1}, {"", 1}, {"auth: none\n", 0}} {
		raw := "layer: 3\nrouting:\n- host: notes\n  port: 80\n" + indent(c.auth) +
			"  sso: {slug: notes, display_name: Notes, base_url_env: NOTES_BASE_URL, default_host: notes.localhost}\n"
		v, err := yamlish.Unmarshal([]byte(raw))
		if err != nil {
			t.Fatal(err)
		}
		cat := &Catalog{Order: []string{"notes"}, Apps: map[string]*App{"notes": {ID: "notes", Layer: 3, doc: v.(*yamlish.Map)}}}
		repo := t.TempDir()
		got, err := ssoProviders(repo, cat, cat.Order, &dotenv{})
		if err != nil {
			t.Fatal(err)
		}
		hosts, err := publishedHosts(cat, cat.Order)
		if err != nil {
			t.Fatal(err)
		}
		if len(got) != c.want || hosts.Len() != c.want {
			t.Errorf("%q: %d provider(s) and %d host variable(s), want %d of each", c.auth, len(got), hosts.Len(), c.want)
		}
	}
}

// DGO-629: compose-files' own overlays that are not UTF-8 are written again, as missing ones are —
// instead of stopping compose-files (and with it every compose call), or handing compose a broken file.
func TestOverlaysThatAreNotUTF8AreWrittenAgain(t *testing.T) {
	repo := t.TempDir()
	put(t, repo, ".generated/cpu-budget.yml", "services:\n  traefik: {cpus: 1}\n  gone: {cpus: 1}\n")
	put(t, repo, ".generated/cpu-budget.effective.yml", "old \xff\n")
	put(t, repo, ".generated/authentik-bootstrap.override.yml", "old \xff\n")
	f, err := effectiveCPUBudget(repo, map[string]bool{"traefik": true}, nil)
	if err != nil {
		t.Fatalf("effectiveCPUBudget stopped: %v", err)
	}
	b := bootstrapOverlay(repo, map[string]bool{"authentik-bootstrap": true}, nil)
	for _, c := range []struct{ got, want, holds string }{
		{f, ".generated/cpu-budget.effective.yml", "Dropped — no such service in the compiled set any more: gone"},
		{b, ".generated/authentik-bootstrap.override.yml", "bbox.bootstrap-inputs: "},
	} {
		body, err := os.ReadFile(filepath.Join(repo, c.want))
		if err != nil {
			t.Fatal(err)
		}
		if c.got != c.want || !utf8.Valid(body) || !strings.Contains(string(body), c.holds) {
			t.Errorf("%s: answered %q, holds:\n%s", c.want, c.got, body)
		}
	}
}

// DGO-628: a second render in a row leaves the edge's files alone — traefik's file provider reloads on
// any write — where zz-serve.yaml, zz-https.yaml and remote.override.yml were written on every render.
func TestASecondRenderLeavesTheEdgesFilesAlone(t *testing.T) {
	real, err := os.ReadFile(filepath.Join(repoRoot(t), stateName))
	if err != nil {
		t.Skip("this checkout has no platform.state.yaml")
	}
	dir := generatorTree(t, renderCase{name: "twice", state: withoutRemote(string(real)) + remoteShapes}, string(real))
	render := func() {
		var out, said bytes.Buffer
		if code := RenderCmd(dir, nil, &out, &said); code != 0 {
			t.Fatalf("render: exit %d\n%s%s", code, out.String(), said.String())
		}
	}
	files := []string{"platform-base/traefik/config/zz-serve.yaml", "platform-base/traefik/config/zz-https.yaml",
		".generated/remote.override.yml"}
	render()
	old := time.Unix(1_000_000_000, 0)
	for _, f := range files {
		if err := os.Chtimes(filepath.Join(dir, filepath.FromSlash(f)), old, old); err != nil {
			t.Fatalf("%s after the first render: %v", f, err)
		}
	}
	render()
	for _, f := range files {
		if fi, err := os.Stat(filepath.Join(dir, filepath.FromSlash(f))); err != nil || !fi.ModTime().Equal(old) {
			t.Errorf("%s was written again by a render that changed nothing (%v)", f, err)
		}
	}
}

// DGO-627: a linked office's `order` that is not a number — a null, a word — reads as a missing one
// (900), so the sorts that follow never meet a null beside numbers; a number stays as it is.
func TestALinkedOfficesOrderIsANumber(t *testing.T) {
	v, err := yamlish.Unmarshal([]byte(strings.NewReplacer("order: 2.5", "order: null", "order: 260", "order: soon").Replace(remoteShapes)))
	if err != nil {
		t.Fatal(err)
	}
	block, _ := get(v.(*yamlish.Map), "remote").([]any)
	entries, errs, err := planRemote(t.TempDir(), "remote", block)
	if err != nil || len(errs) != 0 {
		t.Fatalf("planRemote: %v %v", err, errs)
	}
	got := map[string]any{}
	for _, e := range entries {
		for _, a := range e.apps {
			got[a.app] = a.order
		}
	}
	want := map[string]any{"bina-ds": int64(1), "drive": int64(900), "browser42": int64(900), "sites": int64(900)}
	for app, w := range want {
		if !pyEqual(got[app], w) {
			t.Errorf("%s: order %#v, want %#v", app, got[app], w)
		}
	}
}

// indent puts a route's `auth` line under its list item ("" stays "").
func indent(line string) string {
	if line == "" {
		return ""
	}
	return "  " + line
}

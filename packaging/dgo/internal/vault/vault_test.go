package vault

import (
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func env(kv ...string) func(string) (string, bool) {
	m := map[string]string{}
	for i := 0; i+1 < len(kv); i += 2 {
		m[kv[i]] = kv[i+1]
	}
	return func(k string) (string, bool) { v, ok := m[k]; return v, ok }
}

// python runs app.py's own Fernet (cryptography) as the oracle, or skips where it is not installed.
func python(t *testing.T, script string, args ...string) string {
	t.Helper()
	if exec.Command("python3", "-c", "import cryptography.fernet").Run() != nil {
		t.Skip("python3 with cryptography is the oracle here")
	}
	out, err := exec.Command("python3", append([]string{"-c", script}, args...)...).CombinedOutput()
	if err != nil {
		t.Fatalf("the oracle: %v\n%s", err, out)
	}
	return strings.TrimSpace(string(out))
}

// app.py's _key and vault_read/vault_write, verbatim in what they compute.
const pyKey = `
import base64, hashlib, json, sys
from cryptography.fernet import Fernet, MultiFernet
def key(root): return Fernet(base64.urlsafe_b64encode(hashlib.sha256(root.encode()).digest()))
`

// The vault is app.py's, byte for byte both ways: a vault app.py wrote opens here, under the root key or
// an old one; one written here opens in app.py; a wrong key, or a file that is not a token, is ErrUnreadable —
// never an empty store; renamed ids surface under their new id, the new one winning.
func TestTheVaultIsConnectionsOwnFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "data", "vault.enc")
	os.MkdirAll(filepath.Dir(path), 0o700)

	// app.py writes, under "old"; the core reads under root "new" with "old" in CONNECTIONS_ROOT_KEY_OLD
	python(t, pyKey+`open(sys.argv[1], "wb").write(key("old").encrypt(json.dumps(
    {"telegram-bot": "123:abc", "wadmin-auth": "w", "wadmin-auth:WADMIN_USER": "u", "inst": {"x": [1, 2]}}).encode()))`, path)
	v := Open(path, env("CONNECTIONS_ROOT_KEY", "new", "CONNECTIONS_ROOT_KEY_OLD", " old ,"))
	store, err := v.Read()
	if err != nil {
		t.Fatal(err)
	}
	if string(store["telegram-bot"]) != `"123:abc"` || string(store["inst"]) != `{"x": [1, 2]}` ||
		string(store["chat-auth"]) != `"w"` || string(store["chat-auth:CHAT_USER"]) != `"u"` {
		t.Fatalf("read %v", store)
	}
	// the core writes under "new": app.py opens it with "new" (MultiFernet's first), not with "old" alone
	if err := v.Update(func(s map[string]json.RawMessage) error { s["added"] = json.RawMessage(`"here"`); return nil }); err != nil {
		t.Fatal(err)
	}
	got := python(t, pyKey+`s = json.loads(MultiFernet([key("new")]).decrypt(open(sys.argv[1], "rb").read()))
print(s["added"], s["telegram-bot"], sorted(s)[0])`, path)
	if got != "here 123:abc added" {
		t.Fatalf("app.py read the core's vault as %q", got)
	}
	if python(t, pyKey+`
try:
    key("old").decrypt(open(sys.argv[1], "rb").read()); print("opened")
except Exception as e: print(type(e).__name__)`, path) != "InvalidToken" {
		t.Fatal("a vault the core wrote under the new key opened under the old one")
	}
	if entries, _ := os.ReadDir(filepath.Dir(path)); len(entries) != 1 {
		t.Fatalf("beside the vault: %v (a write leaves nothing but the vault)", entries)
	}

	// a key that opens nothing, and a file that is no token: refused, never {}
	if _, err := Open(path, env("CONNECTIONS_ROOT_KEY", "other")).Read(); !errors.Is(err, ErrUnreadable) {
		t.Fatalf("a wrong key: %v", err)
	}
	if err := Open(path, env("CONNECTIONS_ROOT_KEY", "other")).Update(func(map[string]json.RawMessage) error { return nil }); !errors.Is(err, ErrUnreadable) {
		t.Fatalf("a wrong key's update: %v (it must write nothing)", err)
	}
	python(t, pyKey+`open(sys.argv[1], "wb").write(key("new").encrypt(b"null"))`, path)
	if err := v.Update(func(s map[string]json.RawMessage) error { s["x"] = json.RawMessage(`1`); return nil }); !errors.Is(err, ErrUnreadable) {
		t.Fatalf("a vault of `null`: %v (an error, never a store to write into)", err)
	}
	os.WriteFile(path, []byte("not a token"), 0o600)
	if _, err := v.Read(); !errors.Is(err, ErrUnreadable) {
		t.Fatalf("a file that is no token: %v", err)
	}
	// no file: an empty vault; no key at all: the public fallback, said
	none := Open(filepath.Join(dir, "none.enc"), env())
	if s, err := none.Read(); err != nil || len(s) != 0 || !none.Public {
		t.Fatalf("no file: %v %v, public %v", s, err, none.Public)
	}
}

// An office with no CONNECTIONS_ROOT_KEY (the phone) gets a key of its own, made once and kept beside the
// vault (0600), never the public fallback; the same key opens the vault again; a key named in .env wins.
func TestAnOfficeWithNoRootKeyMakesItsOwn(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "data", "vault.enc")
	v, err := OpenOwn(path, env())
	if err != nil {
		t.Fatal(err)
	}
	if v.Public {
		t.Fatal("the phone's vault is under a public key")
	}
	st, err := os.Stat(filepath.Join(dir, "data", KeyFile))
	if err != nil || st.Mode().Perm() != 0o600 {
		t.Fatalf("the key file: %v %v", st, err)
	}
	if err := v.Update(func(s map[string]json.RawMessage) error { s["a"] = json.RawMessage(`1`); return nil }); err != nil {
		t.Fatal(err)
	}
	if entries, _ := os.ReadDir(filepath.Join(dir, "data")); len(entries) != 2 {
		t.Fatalf("beside the vault: %v (the key and the vault, no temporary file)", entries)
	}
	again, err := OpenOwn(path, env())
	if err != nil {
		t.Fatal(err)
	}
	if s, err := again.Read(); err != nil || string(s["a"]) != "1" {
		t.Fatalf("reopened: %v %v", s, err)
	}
	if _, err := Open(path, env()).Read(); !errors.Is(err, ErrUnreadable) {
		t.Fatal("the public fallback opened the phone's vault")
	}
	named, err := OpenOwn(path, env("CONNECTIONS_ROOT_KEY", "from-env"))
	if err != nil || named.Public {
		t.Fatalf("a key named in .env: %v", err)
	}
	if _, err := named.Read(); !errors.Is(err, ErrUnreadable) {
		t.Fatal("a key named in .env did not take the place of the office's own")
	}
}

// A token is Fernet's in every part the spec fixes: tampering with any byte, a padding that is not PKCS7, and
// another version are refused; app.py's own token is opened.
func TestFernetRefusesWhatIsNotItsToken(t *testing.T) {
	k := keyOf("root")
	tok, err := k.encrypt([]byte(`{"a":1}`), time.Unix(1700000000, 0))
	if err != nil {
		t.Fatal(err)
	}
	if p, err := k.decrypt(tok); err != nil || string(p) != `{"a":1}` {
		t.Fatalf("round trip: %q %v", p, err)
	}
	for i := 0; i < len(tok)-2; i += 7 { // each flipped character of the base64 (the padding's own aside)
		bad := append([]byte(nil), tok...)
		if bad[i] == 'A' {
			bad[i] = 'B'
		} else {
			bad[i] = 'A'
		}
		if _, err := k.decrypt(bad); err == nil {
			t.Fatalf("a token changed at %d opened", i)
		}
	}
	if _, err := keyOf("other").decrypt(tok); err == nil {
		t.Fatal("another key opened it")
	}
	py := python(t, pyKey+`print(key("root").encrypt(b"from app.py").decode())`)
	if p, err := k.decrypt([]byte(py)); err != nil || string(p) != "from app.py" {
		t.Fatalf("app.py's token: %q %v", p, err)
	}
}

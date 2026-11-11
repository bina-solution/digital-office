package vault

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// DevRootKey is app.py's DEV_ROOT_KEY: the key a vault falls back to with CONNECTIONS_ROOT_KEY unset. It is in
// the code, so a vault under it is readable by anyone who has the file (S26, hos-002) — said, never hidden.
const DevRootKey = "dev-root-key-not-for-production"

// publicKeys are app.py's PUBLIC_ROOT_KEYS: the code's fallback and .env.ex's placeholder.
var publicKeys = map[string]bool{DevRootKey: true, "CHANGE_ME": true}

// renamed is app.py's RENAMED_CONNECTIONS: {old: new}, applied on every read.
var renamed = map[string]string{"wadmin-auth": "chat-auth"}

// ErrUnreadable is app.py's VaultUnreadable: the file is there and no configured key opens it, or it opens
// to something that is not a vault. Never read as empty: the next write would persist that over every secret.
var ErrUnreadable = errors.New("the vault is unreadable")

// Vault is one vault file and its keys. Its writes are one at a time (app.py's _vault_lock), and each is
// write-then-rename through a temporary file of its own, synced, so a crash leaves the old vault or the new.
// One Vault per path in a process: the lock is the Vault's, so two of them on one file could lose an update.
type Vault struct {
	Path string
	keys []fernetKey // the first encrypts; every one decrypts (MultiFernet)
	// Public is true when the key that encrypts is one anyone has (the code's fallback or the placeholder)
	Public bool
	mu     sync.Mutex
}

// Open is the vault at path under app.py's keys, read through lookup (os.LookupEnv, or the office's .env):
// CONNECTIONS_ROOT_KEY encrypts (DevRootKey when unset or empty), each of CONNECTIONS_ROOT_KEY_OLD
// (comma-separated) still decrypts.
func Open(path string, lookup func(string) (string, bool)) *Vault {
	root, _ := lookup("CONNECTIONS_ROOT_KEY")
	if root == "" {
		root = DevRootKey
	}
	v := &Vault{Path: path, keys: []fernetKey{keyOf(root)}, Public: publicKeys[root]}
	olds, _ := lookup("CONNECTIONS_ROOT_KEY_OLD")
	for _, k := range strings.Split(olds, ",") {
		if k = strings.TrimSpace(k); k != "" && k != root {
			v.keys = append(v.keys, keyOf(k))
		}
	}
	return v
}

// KeyFile is where an office whose .env names no CONNECTIONS_ROOT_KEY keeps the one the core made for it,
// beside the vault: the phone's (DGO-1328), whose first run writes no such key — and a vault under
// DevRootKey is one anyone with the file opens (S26).
const KeyFile = "root.key"

// OpenOwn is Open, except that with CONNECTIONS_ROOT_KEY unset or empty the key is the office's own, made
// once — 32 random bytes, base64url, in KeyFile beside the vault (0600, its directory 0700) — never
// DevRootKey. A key file that cannot be read or made is an error: nothing is written under a public key.
func OpenOwn(path string, lookup func(string) (string, bool)) (*Vault, error) {
	if root, _ := lookup("CONNECTIONS_ROOT_KEY"); root != "" {
		return Open(path, lookup), nil
	}
	dir := filepath.Dir(path)
	kf := filepath.Join(dir, KeyFile)
	key, err := os.ReadFile(kf)
	if errors.Is(err, os.ErrNotExist) {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return nil, err
		}
		b := make([]byte, 32)
		if _, err := rand.Read(b); err != nil {
			return nil, err
		}
		key = []byte(base64.RawURLEncoding.EncodeToString(b))
		// whole or not at all: written and synced under a temporary name, then linked to KeyFile — a link
		// is atomic and refuses a name that is there, so no reader ever sees a key half written, and a
		// crash leaves at most a stray temporary file, never an empty key that stops every start
		if err = linkWhole(dir, kf, key); errors.Is(err, os.ErrExist) {
			key, err = os.ReadFile(kf) // made by another writer between the read and here: that one is the key
		}
	}
	if err != nil {
		return nil, fmt.Errorf("the office's own vault key (%s): %w", kf, err)
	}
	k := strings.TrimSpace(string(key))
	if k == "" {
		return nil, fmt.Errorf("the office's own vault key (%s) is empty", kf)
	}
	return Open(path, func(name string) (string, bool) {
		if name == "CONNECTIONS_ROOT_KEY" {
			return k, true
		}
		return lookup(name)
	}), nil
}

// linkWhole puts data at name only whole: a temporary file in dir (0600), synced, hard-linked to name
// (os.ErrExist when name is there), the temporary name removed either way.
func linkWhole(dir, name string, data []byte) error {
	f, err := os.CreateTemp(dir, ".root-*.tmp")
	if err != nil {
		return err
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	_, err = f.Write(data)
	if err == nil {
		err = f.Sync()
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		return err
	}
	err = os.Link(tmp, name)
	if errors.Is(err, os.ErrPermission) {
		// a system that allows no hard link here (a phone's SELinux may not): a rename, when name is not
		// there — the core is the one process that makes the key, so nothing races it between the two
		if _, serr := os.Lstat(name); serr == nil {
			return os.ErrExist
		}
		return os.Rename(tmp, name)
	}
	return err
}

// Read is app.py's vault_read(): the store, each value as the JSON it is; {} when there is no file.
func (v *Vault) Read() (map[string]json.RawMessage, error) {
	raw, err := os.ReadFile(v.Path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]json.RawMessage{}, nil
	}
	if err != nil {
		return nil, err
	}
	var plain []byte
	for _, k := range v.keys {
		if plain, err = k.decrypt(raw); err == nil {
			break
		}
	}
	if err != nil {
		return nil, fmt.Errorf("%w: %s: no configured key opens it (CONNECTIONS_ROOT_KEY, CONNECTIONS_ROOT_KEY_OLD) — refusing to read it as empty", ErrUnreadable, v.Path)
	}
	store := map[string]json.RawMessage{}
	if err := json.Unmarshal(plain, &store); err != nil || store == nil { // `null` is no vault either
		return nil, fmt.Errorf("%w: %s: decrypted but not a vault (not a JSON object)", ErrUnreadable, v.Path)
	}
	return applyRenames(store), nil
}

// applyRenames is app.py's _apply_renames: old keys surface under their new id, the new one always winning,
// companions ("<id>:KEY") too — their env name renamed with the id (WADMIN_ → CHAT_).
func applyRenames(store map[string]json.RawMessage) map[string]json.RawMessage {
	for old, new := range renamed {
		if val, ok := store[old]; ok {
			if _, has := store[new]; !has {
				store[new] = val
			}
		}
		for k, val := range store {
			if env, ok := strings.CutPrefix(k, old+":"); ok {
				nk := new + ":" + strings.ReplaceAll(env, "WADMIN_", "CHAT_")
				if _, has := store[nk]; !has {
					store[nk] = val
				}
			}
		}
	}
	return store
}

// Update reads the store, lets change edit it, and writes it — one at a time, as app.py does under its lock.
// change's error writes nothing.
func (v *Vault) Update(change func(map[string]json.RawMessage) error) error {
	v.mu.Lock()
	defer v.mu.Unlock()
	store, err := v.Read()
	if err != nil {
		return err
	}
	if err := change(store); err != nil {
		return err
	}
	return v.write(store)
}

// write is app.py's vault_write(): a temporary file of this write's own in the vault's directory, synced,
// renamed over the vault; never a stray fragment left beside it.
func (v *Vault) write(store map[string]json.RawMessage) error {
	plain, err := json.Marshal(store)
	if err != nil {
		return err
	}
	token, err := v.keys[0].encrypt(plain, time.Now())
	if err != nil {
		return err
	}
	dir := filepath.Dir(v.Path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, "vault-*.tmp")
	if err != nil {
		return err
	}
	tmp := f.Name()
	ok := false
	defer func() {
		if !ok {
			os.Remove(tmp)
		}
	}()
	if _, err := f.Write(token); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmp, v.Path); err != nil {
		return err
	}
	ok = true
	return nil
}

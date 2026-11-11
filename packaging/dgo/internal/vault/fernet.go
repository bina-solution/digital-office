// Package vault is the connections vault — platform-base/connections/app.py's vault.enc — read and written in
// the office core's own process, where the office has no connections container: the phone's core
// (DGO-1328). The file is app.py's, byte for byte: one Fernet token over the store's JSON, under
// Fernet(urlsafe_b64(sha256(CONNECTIONS_ROOT_KEY))), any of CONNECTIONS_ROOT_KEY_OLD still opening it — so a
// vault written here opens in the connections container, and the other way round.
package vault

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"time"
)

// errToken is cryptography's InvalidToken: not a token of this key, or not a token at all.
var errToken = errors.New("not a token any configured key opens")

// fernetKey is one Fernet key: the first half signs, the second encrypts (the Fernet spec).
type fernetKey struct{ sign, enc []byte }

// keyOf is app.py's _key(root): Fernet(base64.urlsafe_b64encode(hashlib.sha256(root.encode()).digest())).
func keyOf(root string) fernetKey {
	d := sha256.Sum256([]byte(root))
	return fernetKey{sign: d[:16], enc: d[16:]}
}

// encrypt is Fernet.encrypt: version 0x80, the time in seconds, a random IV, AES-128-CBC with PKCS7, and an
// HMAC-SHA256 over all of it — base64url with its padding, as cryptography writes it.
func (k fernetKey) encrypt(plain []byte, now time.Time) ([]byte, error) {
	iv := make([]byte, aes.BlockSize)
	if _, err := rand.Read(iv); err != nil {
		return nil, err
	}
	pad := aes.BlockSize - len(plain)%aes.BlockSize
	padded := make([]byte, len(plain)+pad)
	copy(padded, plain)
	for i := len(plain); i < len(padded); i++ {
		padded[i] = byte(pad)
	}
	block, err := aes.NewCipher(k.enc)
	if err != nil {
		return nil, err
	}
	msg := make([]byte, 1+8+aes.BlockSize, 1+8+aes.BlockSize+len(padded)+sha256.Size)
	msg[0] = 0x80
	binary.BigEndian.PutUint64(msg[1:9], uint64(now.Unix()))
	copy(msg[9:], iv)
	ct := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(ct, padded)
	msg = append(msg, ct...)
	mac := hmac.New(sha256.New, k.sign)
	mac.Write(msg)
	msg = mac.Sum(msg)
	out := make([]byte, base64.URLEncoding.EncodedLen(len(msg)))
	base64.URLEncoding.Encode(out, msg)
	return out, nil
}

// decrypt is Fernet.decrypt with no ttl: the version, the HMAC (in constant time) before anything is
// decrypted, then the padding.
func (k fernetKey) decrypt(token []byte) ([]byte, error) {
	msg := make([]byte, base64.URLEncoding.DecodedLen(len(token)))
	n, err := base64.URLEncoding.Decode(msg, token)
	if err != nil {
		return nil, errToken
	}
	msg = msg[:n]
	if len(msg) < 1+8+aes.BlockSize+aes.BlockSize+sha256.Size || msg[0] != 0x80 {
		return nil, errToken
	}
	body, sum := msg[:len(msg)-sha256.Size], msg[len(msg)-sha256.Size:]
	mac := hmac.New(sha256.New, k.sign)
	mac.Write(body)
	if subtle.ConstantTimeCompare(mac.Sum(nil), sum) != 1 {
		return nil, errToken
	}
	iv, ct := body[9:9+aes.BlockSize], body[9+aes.BlockSize:]
	if len(ct)%aes.BlockSize != 0 {
		return nil, errToken
	}
	block, err := aes.NewCipher(k.enc)
	if err != nil {
		return nil, err
	}
	plain := make([]byte, len(ct))
	cipher.NewCBCDecrypter(block, iv).CryptBlocks(plain, ct)
	pad := int(plain[len(plain)-1])
	if pad < 1 || pad > aes.BlockSize {
		return nil, errToken
	}
	for _, b := range plain[len(plain)-pad:] {
		if int(b) != pad {
			return nil, errToken
		}
	}
	return plain[:len(plain)-pad], nil
}

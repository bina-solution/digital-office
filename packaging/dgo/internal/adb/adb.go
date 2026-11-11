// Package adb is `dgo be-child adb`: the phone's app granting ITSELF what only the phone's own adbd may grant
// (DGO-1328) — AVF's two virtual-machine permissions, development ones, and the switch that keeps Android
// from killing the emulated machine for its CPU — through Wireless debugging, with no computer and no root.
// The owner opens Wireless debugging, taps «pair with a code», and gives the app the six digits; the app
// pairs (SPAKE2 in TLS 1.3, pairing_auth.cpp), then connects to adbd (STLS, TLS 1.3 with the paired key) and
// runs its shell commands. Once paired, the phone remembers the key: a later connect needs no code.
//
// The wire, from AOSP packages/modules/adb (pairing_connection, pairing_auth, tls, adb.cpp) and BoringSSL's
// spake25519 — written here, nothing of theirs linked.
package adb

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/binary"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net"
	"os"
	"strings"
	"time"
)

// ── the key ─────────────────────────────────────────────────────────────────────────────────────────

// Key is the app's adb identity: an RSA-2048 key, kept, whose public half adbd remembers once paired.
type Key struct {
	priv *rsa.PrivateKey
	cert tls.Certificate
}

// LoadKey reads the key at path, or makes it there (0600) when there is none.
func LoadKey(path string) (*Key, error) {
	var priv *rsa.PrivateKey
	if raw, err := os.ReadFile(path); err == nil {
		b, _ := pem.Decode(raw)
		if b == nil {
			return nil, fmt.Errorf("%s holds no PEM key", path)
		}
		if priv, err = x509.ParsePKCS1PrivateKey(b.Bytes); err != nil {
			return nil, fmt.Errorf("%s: %v", path, err)
		}
	} else if errors.Is(err, os.ErrNotExist) {
		if priv, err = rsa.GenerateKey(rand.Reader, 2048); err != nil {
			return nil, err
		}
		part := path + ".part"
		if err := os.WriteFile(part, pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(priv)}), 0o600); err != nil {
			return nil, err
		}
		if err := os.Rename(part, path); err != nil {
			return nil, err
		}
	} else {
		return nil, err
	}
	// the certificate TLS presents: self-signed over the same key (x509_generator.cpp's shape: CN=Adb, O=Android)
	tmpl := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "Adb", Organization: []string{"Android"}},
		NotBefore: time.Unix(0, 0), NotAfter: time.Now().AddDate(10, 0, 0), BasicConstraintsValid: true, IsCA: true,
		KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &priv.PublicKey, priv)
	if err != nil {
		return nil, err
	}
	return &Key{priv: priv, cert: tls.Certificate{Certificate: [][]byte{der}, PrivateKey: priv}}, nil
}

// Public is the key as adbd keeps it: base64 of Android's RSAPublicKey struct (android_pubkey.cpp — the
// modulus' words, n0inv, n and R² mod n little-endian, the exponent), then " user@host".
func (k *Key) Public() string {
	n := k.priv.N
	b := make([]byte, 0, 524)
	b = binary.LittleEndian.AppendUint32(b, 64)
	two32 := new(big.Int).Lsh(big.NewInt(1), 32)
	n0inv := new(big.Int).Sub(two32, new(big.Int).ModInverse(new(big.Int).Mod(n, two32), two32))
	b = binary.LittleEndian.AppendUint32(b, uint32(n0inv.Uint64()))
	le := func(v *big.Int) []byte {
		out := make([]byte, 256)
		v.FillBytes(out)
		reverse(out)
		return out
	}
	b = append(b, le(n)...)
	rr := new(big.Int).Exp(big.NewInt(2), big.NewInt(4096), n) // R² mod n, R = 2^2048
	b = append(b, le(rr)...)
	b = binary.LittleEndian.AppendUint32(b, uint32(k.priv.E))
	return base64.StdEncoding.EncodeToString(b) + " dgo@phone"
}

// tlsConfig presents the key's certificate whatever the other side asks for (adbd names its keys in its
// CA list, and Go would otherwise send none that does not match), and believes any certificate: the pairing
// proves the other side, and a connect is to this phone's own loopback.
func (k *Key) tlsConfig() *tls.Config {
	return &tls.Config{
		MinVersion: tls.VersionTLS13, MaxVersion: tls.VersionTLS13, InsecureSkipVerify: true,
		GetClientCertificate: func(*tls.CertificateRequestInfo) (*tls.Certificate, error) { return &k.cert, nil },
	}
}

// ── pairing ────────────────────────────────────────────────────────────────────────────────────────

const (
	pairingVersion = 1
	msgSpake2      = 0
	msgPeerInfo    = 1
	peerInfoSize   = 8192
	maxPayload     = 2 * peerInfoSize
	peerRSAKey     = 0
)

var (
	clientName = []byte("adb pair client\x00")
	serverName = []byte("adb pair server\x00")
	exportName = "adb-label\x00"
	keyInfo    = []byte("adb pairing_auth aes-128-gcm key")
)

// Pair pairs with adbd's pairing port at addr with the code the phone shows, as adb's pairing client
// (Alice): what the phone answers is its GUID.
func Pair(addr, code string, key *Key, timeout time.Duration) (string, error) {
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return "", fmt.Errorf("the pairing port does not answer (is «pair with a code» still open?): %w", err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(timeout))
	t := tls.Client(conn, key.tlsConfig())
	if err := t.Handshake(); err != nil {
		return "", fmt.Errorf("the pairing's TLS: %w", err)
	}
	mine := make([]byte, peerInfoSize)
	mine[0] = peerRSAKey
	copy(mine[1:], key.Public())
	theirs, err := exchange(t, code, mine, true)
	if err != nil {
		return "", err
	}
	return strings.TrimRight(string(theirs[1:]), "\x00"), nil
}

// exchange is SPAKE2 over the TLS connection, then each side's PeerInfo (mine: peerInfoSize bytes, its type
// first) under the key it gives (AES-128-GCM); it answers theirs. alice is adb's client; the other side
// (Bob) is adbd — or a test's.
func exchange(t *tls.Conn, code string, mine []byte, alice bool) ([]byte, error) {
	cs := t.ConnectionState() // its exporter has a pointer receiver: kept in a variable to be called
	ekm, err := cs.ExportKeyingMaterial(exportName, nil, 64)
	if err != nil {
		return nil, fmt.Errorf("the pairing's TLS exports no key: %w", err)
	}
	password := append([]byte(code), ekm...)
	me, them := clientName, serverName
	if !alice {
		me, them = serverName, clientName
	}
	s, err := newSpake2(alice, me, them, password, rand.Reader)
	if err != nil {
		return nil, err
	}
	if err := writePacket(t, msgSpake2, s.msg); err != nil {
		return nil, err
	}
	theirMsg, err := readPacket(t, msgSpake2)
	if err != nil {
		return nil, err
	}
	material, err := s.process(theirMsg)
	if err != nil {
		return nil, err
	}
	aead, err := gcm(hkdf16(material, keyInfo))
	if err != nil {
		return nil, err
	}
	nonce := make([]byte, 12) // the counter, little-endian in the first 8 bytes: 0 for each side's first
	if err := writePacket(t, msgPeerInfo, aead.Seal(nil, nonce, mine, nil)); err != nil {
		return nil, err
	}
	sealed, err := readPacket(t, msgPeerInfo)
	if err != nil {
		return nil, err
	}
	theirs, err := aead.Open(nil, nonce, sealed, nil)
	if err != nil || len(theirs) != peerInfoSize {
		return nil, errors.New("the pairing code is not the one the phone shows (its answer does not open)")
	}
	return theirs, nil
}

func writePacket(w io.Writer, kind byte, payload []byte) error {
	h := make([]byte, 6)
	h[0], h[1] = pairingVersion, kind
	binary.BigEndian.PutUint32(h[2:], uint32(len(payload)))
	_, err := w.Write(append(h, payload...))
	return err
}

func readPacket(r io.Reader, kind byte) ([]byte, error) {
	h := make([]byte, 6)
	if _, err := io.ReadFull(r, h); err != nil {
		return nil, fmt.Errorf("the pairing ended (a wrong code ends it): %w", err)
	}
	n := binary.BigEndian.Uint32(h[2:])
	if h[0] != pairingVersion || h[1] != kind || n == 0 || n > maxPayload {
		return nil, fmt.Errorf("the pairing answered a packet of version %d, type %d, %d bytes", h[0], h[1], n)
	}
	b := make([]byte, n)
	_, err := io.ReadFull(r, b)
	return b, err
}

// hkdf16 is HKDF-SHA256 with no salt, 16 bytes of output (RFC 5869: one block).
func hkdf16(ikm, info []byte) []byte {
	ext := hmac.New(sha256.New, make([]byte, sha256.Size))
	ext.Write(ikm)
	prk := ext.Sum(nil)
	exp := hmac.New(sha256.New, prk)
	exp.Write(info)
	exp.Write([]byte{1})
	return exp.Sum(nil)[:16]
}

func gcm(key []byte) (cipher.AEAD, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}

// ── a connection, and a shell command over it ──────────────────────────────────────────────────────

const (
	cmdCNXN = 0x4e584e43
	cmdSTLS = 0x534c5453
	cmdOPEN = 0x4e45504f
	cmdOKAY = 0x59414b4f
	cmdWRTE = 0x45545257
	cmdCLSE = 0x45534c43
	cmdAUTH = 0x48545541

	adbVersion  = 0x01000001 // skips the checksum
	stlsVersion = 0x01000000
	adbMax      = 1 << 20
)

type message struct {
	cmd, arg0, arg1 uint32
	data            []byte
}

func writeMessage(w io.Writer, m message) error {
	h := make([]byte, 24)
	binary.LittleEndian.PutUint32(h[0:], m.cmd)
	binary.LittleEndian.PutUint32(h[4:], m.arg0)
	binary.LittleEndian.PutUint32(h[8:], m.arg1)
	binary.LittleEndian.PutUint32(h[12:], uint32(len(m.data)))
	binary.LittleEndian.PutUint32(h[16:], 0)
	binary.LittleEndian.PutUint32(h[20:], m.cmd^0xffffffff)
	_, err := w.Write(append(h, m.data...))
	return err
}

func readMessage(r io.Reader) (message, error) {
	h := make([]byte, 24)
	if _, err := io.ReadFull(r, h); err != nil {
		return message{}, err
	}
	m := message{cmd: binary.LittleEndian.Uint32(h[0:]), arg0: binary.LittleEndian.Uint32(h[4:]), arg1: binary.LittleEndian.Uint32(h[8:])}
	n := binary.LittleEndian.Uint32(h[12:])
	if binary.LittleEndian.Uint32(h[20:]) != m.cmd^0xffffffff || n > adbMax {
		return message{}, fmt.Errorf("adbd answered a message that is not one (command %08x, %d bytes)", m.cmd, n)
	}
	m.data = make([]byte, n)
	_, err := io.ReadFull(r, m.data)
	return m, err
}

// Shell connects to adbd's TLS port at addr with the paired key and runs command in its shell, answering
// what it printed. A key the phone does not know is refused there: pair first.
func Shell(addr, command string, key *Key, timeout time.Duration) (string, error) {
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return "", fmt.Errorf("adbd's port does not answer (is Wireless debugging on?): %w", err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(timeout))
	if err := writeMessage(conn, message{cmd: cmdCNXN, arg0: adbVersion, arg1: adbMax, data: []byte("host::")}); err != nil {
		return "", err
	}
	m, err := readMessage(conn)
	if err != nil {
		return "", fmt.Errorf("adbd said nothing to the connect: %w", err)
	}
	if m.cmd == cmdAUTH {
		return "", errors.New("adbd asks for the old key exchange, not TLS: this is not Wireless debugging's port")
	}
	if m.cmd != cmdSTLS {
		return "", fmt.Errorf("adbd answered %08x, not STLS", m.cmd)
	}
	if err := writeMessage(conn, message{cmd: cmdSTLS, arg0: stlsVersion}); err != nil {
		return "", err
	}
	t := tls.Client(conn, key.tlsConfig())
	if err := t.Handshake(); err != nil {
		return "", fmt.Errorf("adbd refused this app's key (pair it first): %w", err)
	}
	if m, err = readMessage(t); err != nil || m.cmd != cmdCNXN {
		return "", fmt.Errorf("adbd did not take the connection after TLS (%v)", err)
	}
	const local = 1
	if err := writeMessage(t, message{cmd: cmdOPEN, arg0: local, data: append([]byte("shell:"+command), 0)}); err != nil {
		return "", err
	}
	var out strings.Builder
	var remote uint32
	for {
		m, err := readMessage(t)
		if err != nil {
			return out.String(), fmt.Errorf("the shell ended before it said it had: %w", err)
		}
		switch m.cmd {
		case cmdOKAY:
			remote = m.arg0
		case cmdWRTE:
			remote = m.arg0
			out.Write(m.data)
			if err := writeMessage(t, message{cmd: cmdOKAY, arg0: local, arg1: remote}); err != nil {
				return out.String(), err
			}
		case cmdCLSE:
			_ = writeMessage(t, message{cmd: cmdCLSE, arg0: local, arg1: m.arg0})
			return out.String(), nil
		}
	}
}

// Main is `dgo be-child adb pair <host:port> <code>` and `dgo be-child adb shell <host:port> <command…>`,
// the key at $DGO_ADB_KEY (made there the first time). What it did on stdout; 0 done, 1 refused or failed
// (the reason on stderr), 2 usage.
func Main(_ string, args []string, stderr io.Writer) int {
	return run(args, os.Stdout, stderr)
}

func run(args []string, stdout, stderr io.Writer) int {
	usage := "usage: dgo be-child adb pair <host:port> <code> | shell <host:port> <command…>  (the key at $DGO_ADB_KEY)"
	path := os.Getenv("DGO_ADB_KEY")
	if len(args) < 3 || path == "" || (args[0] != "pair" && args[0] != "shell") {
		fmt.Fprintln(stderr, usage)
		return 2
	}
	key, err := LoadKey(path)
	if err != nil {
		fmt.Fprintln(stderr, "dgo adb: the key:", err)
		return 1
	}
	if args[0] == "pair" {
		guid, err := Pair(args[1], strings.TrimSpace(args[2]), key, 30*time.Second)
		if err != nil {
			fmt.Fprintln(stderr, "dgo adb: pair:", err)
			return 1
		}
		fmt.Fprintln(stdout, "paired with", guid)
		return 0
	}
	said, err := Shell(args[1], strings.Join(args[2:], " "), key, 60*time.Second)
	fmt.Fprint(stdout, said)
	if err != nil {
		fmt.Fprintln(stderr, "dgo adb: shell:", err)
		return 1
	}
	return 0
}

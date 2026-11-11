package adb

import (
	"bytes"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha512"
	"crypto/tls"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"math/big"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The curve is edwards25519: d as RFC 8032 gives it, the base point's encoding, l·G the identity, and RFC
// 8032's first test key — its public key is the clamped secret times G, encoded.
func TestTheCurveIsEdwards25519(t *testing.T) {
	if want := mustInt("37095705934669439343138083508754565189542113879843219016388785533085940283555"); curveD.Cmp(want) != 0 {
		t.Fatalf("d = %v", curveD)
	}
	if got := hex.EncodeToString(encode(baseG)); got != "5866666666666666666666666666666666666666666666666666666666666666" {
		t.Fatalf("the base point encodes as %s", got)
	}
	if id := mul(orderL, baseG); id.x.Sign() != 0 || id.y.Cmp(big.NewInt(1)) != 0 {
		t.Fatal("l·G is not the identity")
	}
	sk, _ := hex.DecodeString("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
	h := sha512.Sum512(sk)
	h[0] &= 248
	h[31] &= 127
	h[31] |= 64
	if got := hex.EncodeToString(encode(mul(littleEndian(h[:32]), baseG))); got != "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a" {
		t.Fatalf("RFC 8032 test 1's public key = %s", got)
	}
	for name, p := range map[string]point{"M": pointM, "N": pointN} {
		back, err := decode(encode(p))
		if err != nil || back.x.Cmp(p.x) != 0 || back.y.Cmp(p.y) != 0 {
			t.Fatalf("%s does not round-trip: %v", name, err)
		}
	}
}

// Alice and Bob agree on the key with one password, and not with two.
func TestSpake2Agrees(t *testing.T) {
	run := func(pa, pb string) (bool, error) {
		a, err := newSpake2(true, clientName, serverName, []byte(pa), rand.Reader)
		if err != nil {
			return false, err
		}
		b, err := newSpake2(false, serverName, clientName, []byte(pb), rand.Reader)
		if err != nil {
			return false, err
		}
		ka, err := a.process(b.msg)
		if err != nil {
			return false, err
		}
		kb, err := b.process(a.msg)
		if err != nil {
			return false, err
		}
		return bytes.Equal(ka, kb), nil
	}
	if same, err := run("123456", "123456"); err != nil || !same {
		t.Fatalf("one password: agree=%v %v", same, err)
	}
	if same, err := run("123456", "654321"); err != nil || same {
		t.Fatalf("two passwords: agree=%v %v", same, err)
	}
	if p := new(big.Int).And(mustSpake(t).password, big.NewInt(7)); p.Sign() != 0 {
		t.Fatal("the password scalar is not a multiple of 8")
	}
}

func mustSpake(t *testing.T) *spake2 {
	s, err := newSpake2(true, clientName, serverName, []byte("x"), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func key(t *testing.T) *Key {
	k, err := LoadKey(filepath.Join(t.TempDir(), "adbkey"))
	if err != nil {
		t.Fatal(err)
	}
	return k
}

// device is adbd's pairing server, as this package can be it: TLS 1.3 asking for any certificate, SPAKE2 as
// Bob with the code it shows, its GUID as its PeerInfo. It reports the client's public key text.
func device(t *testing.T, code string) (string, chan string) {
	t.Helper()
	k := key(t)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	got := make(chan string, 1)
	go func() {
		c, err := ln.Accept()
		if err != nil {
			got <- "accept: " + err.Error()
			return
		}
		defer c.Close()
		s := tls.Server(c, &tls.Config{Certificates: []tls.Certificate{k.cert}, ClientAuth: tls.RequireAnyClientCert,
			MinVersion: tls.VersionTLS13, MaxVersion: tls.VersionTLS13})
		if err := s.Handshake(); err != nil {
			got <- "handshake: " + err.Error()
			return
		}
		mine := make([]byte, peerInfoSize)
		mine[0] = 1 // ADB_DEVICE_GUID
		copy(mine[1:], "adb-TEST0001")
		theirs, err := exchange(s, code, mine, false)
		if err != nil {
			got <- "exchange: " + err.Error()
			return
		}
		got <- strings.TrimRight(string(theirs[1:]), "\x00")
	}()
	return ln.Addr().String(), got
}

// Pairing with the code the phone shows: each side has the other's identity; with another code, the app
// says the code is not the phone's.
func TestPairWithTheCode(t *testing.T) {
	k := key(t)
	addr, got := device(t, "482913")
	guid, err := Pair(addr, "482913", k, 10*time.Second)
	if err != nil || guid != "adb-TEST0001" {
		t.Fatalf("pair = %q %v", guid, err)
	}
	if said := <-got; said != k.Public() {
		t.Fatalf("the device was given %.60q, want the app's key", said)
	}
	addr, _ = device(t, "482913")
	if _, err := Pair(addr, "111111", k, 10*time.Second); err == nil || !strings.Contains(err.Error(), "not the one the phone shows") {
		t.Fatalf("a wrong code: %v", err)
	}
}

// adb's public key text: base64 of the 524-byte struct, n0inv the negated inverse of n mod 2^32, R² mod n.
func TestThePublicKeyIsAndroids(t *testing.T) {
	k := key(t)
	text := k.Public()
	b64, user, ok := strings.Cut(text, " ")
	if !ok || user != "dgo@phone" {
		t.Fatalf("%q", text)
	}
	dec, err := base64.StdEncoding.DecodeString(b64)
	if err != nil || len(dec) != 524 {
		t.Fatalf("the struct: %d bytes, %v", len(dec), err)
	}
	n := littleEndian(dec[8:264])
	if n.Cmp(k.priv.N) != 0 {
		t.Fatal("the modulus is not the key's")
	}
	n0inv := binary.LittleEndian.Uint32(dec[4:8])
	low := new(big.Int).And(n, big.NewInt(0xffffffff)).Uint64()
	if (uint64(n0inv)*low)&0xffffffff != 0xffffffff {
		t.Fatalf("n0inv·n ≠ -1 mod 2^32")
	}
	rr := littleEndian(dec[264:520])
	if want := new(big.Int).Exp(big.NewInt(2), big.NewInt(4096), n); rr.Cmp(want) != 0 {
		t.Fatal("rr is not R² mod n")
	}
	if binary.LittleEndian.Uint32(dec[0:4]) != 64 || binary.LittleEndian.Uint32(dec[520:524]) != 65537 {
		t.Fatal("the struct's word count or exponent")
	}
}

// A shell command over adbd's TLS port, as a device answers it: CNXN, STLS, TLS with the paired key, the
// device's CNXN, OPEN shell:, OKAY, WRTE, CLSE.
func TestShellOverTLS(t *testing.T) {
	k := key(t)
	dev := key(t)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	done := make(chan error, 1)
	go func() {
		done <- func() error {
			c, err := ln.Accept()
			if err != nil {
				return err
			}
			defer c.Close()
			if m, err := readMessage(c); err != nil || m.cmd != cmdCNXN || string(m.data) != "host::" {
				return fmt.Errorf("CNXN: %v %q", err, m.data)
			}
			if err := writeMessage(c, message{cmd: cmdSTLS, arg0: stlsVersion}); err != nil {
				return err
			}
			if m, err := readMessage(c); err != nil || m.cmd != cmdSTLS {
				return fmt.Errorf("STLS: %v", err)
			}
			s := tls.Server(c, &tls.Config{Certificates: []tls.Certificate{dev.cert}, ClientAuth: tls.RequireAnyClientCert,
				MinVersion: tls.VersionTLS13, MaxVersion: tls.VersionTLS13})
			if err := s.Handshake(); err != nil {
				return err
			}
			pub, ok := s.ConnectionState().PeerCertificates[0].PublicKey.(*rsa.PublicKey)
			if !ok || pub.N.Cmp(k.priv.N) != 0 {
				return fmt.Errorf("the app presented another key")
			}
			if err := writeMessage(s, message{cmd: cmdCNXN, arg0: adbVersion, arg1: adbMax, data: []byte("device::")}); err != nil {
				return err
			}
			m, err := readMessage(s)
			if err != nil || m.cmd != cmdOPEN || string(m.data) != "shell:pm grant x y\x00" {
				return fmt.Errorf("OPEN: %v %q", err, m.data)
			}
			if err := writeMessage(s, message{cmd: cmdOKAY, arg0: 7, arg1: m.arg0}); err != nil {
				return err
			}
			if err := writeMessage(s, message{cmd: cmdWRTE, arg0: 7, arg1: m.arg0, data: []byte("granted\n")}); err != nil {
				return err
			}
			if m, err := readMessage(s); err != nil || m.cmd != cmdOKAY {
				return fmt.Errorf("the WRTE's OKAY: %v", err)
			}
			if err := writeMessage(s, message{cmd: cmdCLSE, arg0: 7, arg1: 1}); err != nil {
				return err
			}
			_, err = readMessage(s)
			return err
		}()
	}()
	said, err := Shell(ln.Addr().String(), "pm grant x y", k, 10*time.Second)
	if err != nil || said != "granted\n" {
		t.Fatalf("shell = %q %v", said, err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

// Google's own adb pairs with this package's pairing server — the proof that SPAKE2, the TLS exporter, the
// framing and the PeerInfo are adbd's: both sides are one exchange here. Where the runner has adb (the
// Android SDK's platform-tools); skipped elsewhere, and said.
func TestGooglesAdbPairsWithThisPairing(t *testing.T) {
	bin, err := exec.LookPath("adb")
	if err != nil {
		for _, env := range []string{"ANDROID_HOME", "ANDROID_SDK_ROOT"} {
			if d := os.Getenv(env); d != "" {
				if p := filepath.Join(d, "platform-tools", "adb"); fileExists(p) {
					bin = p
				}
			}
		}
	}
	if bin == "" {
		t.Skip("no adb on this machine (the Android SDK's platform-tools): the interop is proved where there is")
	}
	addr, got := device(t, "927461")
	home := t.TempDir()
	port := freePort(t)
	env := append(os.Environ(), "HOME="+home, "ANDROID_USER_HOME="+filepath.Join(home, ".android"),
		fmt.Sprintf("ANDROID_ADB_SERVER_PORT=%d", port))
	defer func() {
		k := exec.Command(bin, "kill-server")
		k.Env = env
		_ = k.Run()
	}()
	cmd := exec.Command(bin, "pair", addr, "927461")
	cmd.Env = env
	out, err := cmd.CombinedOutput()
	if err != nil || !strings.Contains(string(out), "Successfully paired") {
		t.Fatalf("adb pair: %v\n%s\nthe device: %s", err, out, <-got)
	}
	if said := <-got; !strings.Contains(said, " ") {
		t.Fatalf("adb gave the device %q, not its public key", said)
	}
}

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

func freePort(t *testing.T) int {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	return ln.Addr().(*net.TCPAddr).Port
}

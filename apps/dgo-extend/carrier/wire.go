package main

// wire.go — what crosses the TCP connection: a three-message handshake, then framed datagrams.
//
// THE HANDSHAKE proves, in both directions, that each end holds the private half of the WireGuard
// key its peer has on record for this pair — and nothing else. It never sends a key:
//
//	dialer   → acceptor   "DGOCARR1" | tag | nonce_d                  tag = SHA-256(label | dialer key | acceptor key)
//	acceptor → dialer     "DGOCARR1" | nonce_a | HMAC(k, "acceptor" | nonce_d | nonce_a)
//	dialer   → acceptor   HMAC(k, "dialer" | nonce_d | nonce_a)
//
// k is derived from the static X25519 agreement of the two WireGuard keys (both ends compute it from
// their own private key and the other's public key), bound to the tag, with a label of its own so it
// can never equal a key WireGuard derives. The TAG is what lets an acceptor holding several pairs
// find the right one, and it names the pair without naming either key: a dialer that is SEARCHING
// a LAN sends it to every address that answers, and a stranger learns nothing it could use. An
// acceptor that does not recognise the tag closes the connection without a byte — a port scanner
// sees a port that accepts and says nothing.
//
// A FRAME is `type | length (2 bytes, big-endian) | payload`. DATA carries one WireGuard datagram,
// PING/PONG carry the sender's clock so a round trip can be measured. Nothing else is defined, and a
// frame of any other type ends the session: a peer that speaks a newer protocol than this one must
// be noticed, not half-understood.

import (
	"bufio"
	"crypto/ecdh"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"time"
)

const (
	magic        = "DGOCARR1"
	nonceLen     = 32
	tagLen       = 32
	proofLen     = 32
	helloLen     = len(magic) + tagLen + nonceLen
	replyLen     = len(magic) + nonceLen + proofLen
	frameData    = 1
	framePing    = 2
	framePong    = 3
	frameHeadLen = 3
	// A WireGuard datagram is at most the interface MTU plus its 32-byte header (1420 + 32 by
	// default); a UDP datagram can never exceed 65535, which is what the 2-byte length can say.
	maxDatagram = 65535
)

// handshakeTimeout bounds the dialer's whole exchange. A peer on a LAN answers in milliseconds and one
// across a relay in well under a second; a connection that has said nothing for this long is not a peer.
var handshakeTimeout = 10 * time.Second

// acceptTimeout bounds the ACCEPTING side's exchange, and is shorter: a real dialer sends its hello the
// moment it connects, while anything that connects and says nothing holds one of the few slots an
// office keeps for unfinished handshakes — so it is let go quickly.
var acceptTimeout = 5 * time.Second

var errHandshake = errors.New("handshake refused")

// Keys is this office's WireGuard identity: the private key (from the tunnel volume) and its public half.
type Keys struct {
	priv *ecdh.PrivateKey
	pub  []byte
}

// NewKeys reads a raw 32-byte WireGuard private key.
func NewKeys(raw []byte) (*Keys, error) {
	priv, err := ecdh.X25519().NewPrivateKey(raw)
	if err != nil {
		return nil, fmt.Errorf("the WireGuard private key is not an X25519 key: %w", err)
	}
	return &Keys{priv: priv, pub: priv.PublicKey().Bytes()}, nil
}

// Public is the key the peer has on record for this office.
func (k *Keys) Public() []byte { return k.pub }

func pairTag(dialerPub, acceptorPub []byte) [tagLen]byte {
	h := sha256.New()
	h.Write([]byte("dgo-carry/1 tag\x00"))
	h.Write(dialerPub)
	h.Write(acceptorPub)
	var t [tagLen]byte
	copy(t[:], h.Sum(nil))
	return t
}

func pairSecret(k *Keys, peerPub []byte, tag [tagLen]byte) ([]byte, error) {
	pk, err := ecdh.X25519().NewPublicKey(peerPub)
	if err != nil {
		return nil, fmt.Errorf("the peer's WireGuard key is not an X25519 key: %w", err)
	}
	shared, err := k.priv.ECDH(pk)
	if err != nil {
		return nil, err // a low-order point: crypto/ecdh refuses the all-zero agreement
	}
	m := hmac.New(sha256.New, shared)
	m.Write([]byte("dgo-carry/1 key\x00"))
	m.Write(tag[:])
	return m.Sum(nil), nil
}

func proofOf(secret []byte, role string, nd, na []byte) []byte {
	m := hmac.New(sha256.New, secret)
	m.Write([]byte(role))
	m.Write([]byte{0})
	m.Write(nd)
	m.Write(na)
	return m.Sum(nil)
}

// DialHandshake runs the dialer's half on a fresh connection to the office holding peerPub, within
// `limit` (0 = handshakeTimeout).
func DialHandshake(c net.Conn, k *Keys, peerPub []byte, limit time.Duration) error {
	tag := pairTag(k.pub, peerPub)
	secret, err := pairSecret(k, peerPub, tag)
	if err != nil {
		return err
	}
	nd := make([]byte, nonceLen)
	if _, err := rand.Read(nd); err != nil {
		return err
	}
	if limit <= 0 {
		limit = handshakeTimeout
	}
	_ = c.SetDeadline(time.Now().Add(limit))
	defer c.SetDeadline(time.Time{})
	hello := make([]byte, 0, helloLen)
	hello = append(hello, magic...)
	hello = append(hello, tag[:]...)
	hello = append(hello, nd...)
	if _, err := c.Write(hello); err != nil {
		return err
	}
	reply := make([]byte, replyLen)
	if _, err := io.ReadFull(c, reply); err != nil {
		return err // closed without a word: whatever answered there does not hold this pair
	}
	if string(reply[:len(magic)]) != magic {
		return errHandshake
	}
	na := reply[len(magic) : len(magic)+nonceLen]
	if !hmac.Equal(reply[len(magic)+nonceLen:], proofOf(secret, "acceptor", nd, na)) {
		return errHandshake
	}
	_, err = c.Write(proofOf(secret, "dialer", nd, na))
	return err
}

// AcceptHandshake runs the acceptor's half. `find` maps a tag to the peer key of the pair it names
// (nil when this office holds no such pair); the returned key says which pair the connection is.
func AcceptHandshake(c net.Conn, k *Keys, find func(tag [tagLen]byte) []byte) ([]byte, error) {
	_ = c.SetDeadline(time.Now().Add(acceptTimeout))
	defer c.SetDeadline(time.Time{})
	hello := make([]byte, helloLen)
	if _, err := io.ReadFull(c, hello); err != nil {
		return nil, err
	}
	if string(hello[:len(magic)]) != magic {
		return nil, errHandshake
	}
	var tag [tagLen]byte
	copy(tag[:], hello[len(magic):len(magic)+tagLen])
	nd := hello[len(magic)+tagLen:]
	peerPub := find(tag)
	if peerPub == nil {
		return nil, errHandshake
	}
	secret, err := pairSecret(k, peerPub, tag)
	if err != nil {
		return nil, err
	}
	na := make([]byte, nonceLen)
	if _, err := rand.Read(na); err != nil {
		return nil, err
	}
	reply := make([]byte, 0, replyLen)
	reply = append(reply, magic...)
	reply = append(reply, na...)
	reply = append(reply, proofOf(secret, "acceptor", nd, na)...)
	if _, err := c.Write(reply); err != nil {
		return nil, err
	}
	pd := make([]byte, proofLen)
	if _, err := io.ReadFull(c, pd); err != nil {
		return nil, err
	}
	if !hmac.Equal(pd, proofOf(secret, "dialer", nd, na)) {
		return nil, errHandshake
	}
	return peerPub, nil
}

func appendFrame(dst []byte, kind byte, payload []byte) []byte {
	var head [frameHeadLen]byte
	head[0] = kind
	binary.BigEndian.PutUint16(head[1:], uint16(len(payload)))
	dst = append(dst, head[:]...)
	return append(dst, payload...)
}

// readFrame reads one frame into buf (which must hold maxDatagram bytes) and returns its payload.
func readFrame(r *bufio.Reader, buf []byte) (byte, []byte, error) {
	var head [frameHeadLen]byte
	if _, err := io.ReadFull(r, head[:]); err != nil {
		return 0, nil, err
	}
	n := int(binary.BigEndian.Uint16(head[1:]))
	if _, err := io.ReadFull(r, buf[:n]); err != nil {
		return 0, nil, err
	}
	switch head[0] {
	case frameData, framePing, framePong:
		return head[0], buf[:n], nil
	}
	return 0, nil, fmt.Errorf("unknown frame type %d", head[0])
}

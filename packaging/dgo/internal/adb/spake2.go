package adb

import (
	"crypto/sha512"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"io"
	"math/big"
)

// SPAKE2 as BoringSSL's crypto/curve25519/spake25519.cc does it (Apache-2.0) — the one adbd's Wireless
// debugging pairing speaks (pairing_auth.cpp) — on edwards25519, in math/big: a pairing is one handshake,
// and the core takes no dependency for it. Not constant-time, and need not be: the code is on the phone's
// screen, the exchange is on its own loopback, once.

// The field's prime 2^255 - 19, the prime-order subgroup's order 2^252 + 27742317777372353535851937790883648493,
// and the base point's coordinates.
const (
	primeP = "57896044618658097711785492504343953926634992332820282019728792003956564819949"
	orderN = "7237005577332262213973186563042994240857116359379907606001950938285454250989"
	baseX  = "15112221349535400772501151409588531511454012693041857206046113283949847762202"
	baseY  = "46316835694926478169428394003475163141307993866256225615783033603165251855960"
)

var (
	fieldP = mustInt(primeP)
	orderL = mustInt(orderN)
	curveD = new(big.Int).Mod(new(big.Int).Mul(big.NewInt(-121665), new(big.Int).ModInverse(big.NewInt(121666), fieldP)), fieldP)
	sqrtM1 = new(big.Int).Exp(big.NewInt(2), new(big.Int).Div(new(big.Int).Sub(fieldP, big.NewInt(1)), big.NewInt(4)), fieldP)
	baseG  = point{mustInt(baseX), mustInt(baseY)}
)

// BoringSSL's M and N, compressed: the first SHA-256 iterate of "edwards25519 point generation seed (M)" and
// "(N)" that decodes to a point.
var (
	pointM = mustPoint("5ada7e4bf6ddd9adb6626d32131c6b5c51a1e347a3478f53cfcf441b88eed12e")
	pointN = mustPoint("10e3df0ae37d8e7a99b5fe74b44672103dbddcbd06af680d71329a11693bc778")
)

// point is an affine point of the twisted Edwards curve -x² + y² = 1 + d·x²·y² over GF(2^255 - 19).
type point struct{ x, y *big.Int }

func mustInt(s string) *big.Int {
	v, ok := new(big.Int).SetString(s, 10)
	if !ok {
		panic("adb: bad constant " + s)
	}
	return v
}

func mustPoint(h string) point {
	b, err := hex.DecodeString(h)
	if err != nil || len(b) != 32 {
		panic("adb: bad point " + h)
	}
	p, err := decode(b)
	if err != nil {
		panic("adb: " + h + ": " + err.Error())
	}
	return p
}

func identity() point { return point{big.NewInt(0), big.NewInt(1)} }

// add is the complete addition law (a = -1, d not a square): it doubles too.
func add(a, b point) point {
	x1y2 := new(big.Int).Mul(a.x, b.y)
	y1x2 := new(big.Int).Mul(a.y, b.x)
	y1y2 := new(big.Int).Mul(a.y, b.y)
	x1x2 := new(big.Int).Mul(a.x, b.x)
	t := new(big.Int).Mul(curveD, x1x2)
	t.Mul(t, y1y2).Mod(t, fieldP)
	one := big.NewInt(1)
	x := new(big.Int).Add(x1y2, y1x2)
	x.Mul(x, new(big.Int).ModInverse(new(big.Int).Mod(new(big.Int).Add(one, t), fieldP), fieldP)).Mod(x, fieldP)
	y := new(big.Int).Add(y1y2, x1x2)
	y.Mul(y, new(big.Int).ModInverse(new(big.Int).Mod(new(big.Int).Sub(one, t), fieldP), fieldP)).Mod(y, fieldP)
	return point{x, y}
}

func neg(a point) point {
	return point{new(big.Int).Mod(new(big.Int).Neg(a.x), fieldP), new(big.Int).Set(a.y)}
}

// mul is k·a for a non-negative integer k of any size — never reduced mod the order: BoringSSL multiplies
// by its scalars' bytes as they are, and a point outside the prime-order subgroup tells the difference.
func mul(k *big.Int, a point) point {
	r := identity()
	for i := k.BitLen() - 1; i >= 0; i-- {
		r = add(r, r)
		if k.Bit(i) == 1 {
			r = add(r, a)
		}
	}
	return r
}

func encode(a point) []byte {
	out := make([]byte, 32)
	a.y.FillBytes(out)
	reverse(out)
	if a.x.Bit(0) == 1 {
		out[31] |= 0x80
	}
	return out
}

func decode(b []byte) (point, error) {
	if len(b) != 32 {
		return point{}, errors.New("a point is 32 bytes")
	}
	le := append([]byte(nil), b...)
	sign := uint(le[31] >> 7)
	le[31] &= 0x7f
	reverse(le)
	y := new(big.Int).SetBytes(le)
	if y.Cmp(fieldP) >= 0 {
		return point{}, errors.New("not a canonical y")
	}
	y2 := new(big.Int).Mul(y, y)
	u := new(big.Int).Sub(y2, big.NewInt(1))
	v := new(big.Int).Add(new(big.Int).Mul(curveD, y2), big.NewInt(1))
	x2 := new(big.Int).Mul(u, new(big.Int).ModInverse(v.Mod(v, fieldP), fieldP))
	x2.Mod(x2, fieldP)
	x := new(big.Int).Exp(x2, new(big.Int).Div(new(big.Int).Add(fieldP, big.NewInt(3)), big.NewInt(8)), fieldP)
	if new(big.Int).Mod(new(big.Int).Mul(x, x), fieldP).Cmp(x2) != 0 {
		x.Mul(x, sqrtM1).Mod(x, fieldP)
	}
	if new(big.Int).Mod(new(big.Int).Mul(x, x), fieldP).Cmp(x2) != 0 {
		return point{}, errors.New("not on the curve")
	}
	if x.Sign() == 0 && sign == 1 {
		return point{}, errors.New("a negative zero")
	}
	if x.Bit(0) != sign {
		x.Sub(fieldP, x)
	}
	return point{x, y}, nil
}

func reverse(b []byte) {
	for i, j := 0, len(b)-1; i < j; i, j = i+1, j-1 {
		b[i], b[j] = b[j], b[i]
	}
}

func littleEndian(b []byte) *big.Int {
	be := append([]byte(nil), b...)
	reverse(be)
	return new(big.Int).SetBytes(be)
}

// spake2 is one side of the exchange: Alice (adb's pairing client) masks with M, Bob with N.
type spake2 struct {
	alice             bool
	myName, theirName []byte
	private           *big.Int // 8·(64 random bytes mod l), as BoringSSL's left_shift_3 leaves it
	password          *big.Int // SHA-512(password) mod l, plus k·l to a multiple of 8 (its "password scalar hack")
	passwordHash      []byte   // SHA-512(password), all 64 bytes, as the transcript takes it
	msg               []byte
}

func newSpake2(alice bool, myName, theirName, password []byte, random io.Reader) (*spake2, error) {
	seed := make([]byte, 64)
	if _, err := io.ReadFull(random, seed); err != nil {
		return nil, err
	}
	s := &spake2{alice: alice, myName: myName, theirName: theirName}
	s.private = new(big.Int).Lsh(new(big.Int).Mod(littleEndian(seed), orderL), 3)
	h := sha512.Sum512(password)
	s.passwordHash = h[:]
	w := new(big.Int).Mod(littleEndian(h[:]), orderL)
	for k := int64(0); k < 8; k++ { // the one k in 0..7 that makes it a multiple of 8 (l is odd)
		c := new(big.Int).Add(w, new(big.Int).Mul(big.NewInt(k), orderL))
		if new(big.Int).And(c, big.NewInt(7)).Sign() == 0 {
			s.password = c
			break
		}
	}
	mask := pointN
	if alice {
		mask = pointM
	}
	s.msg = encode(add(mul(s.private, baseG), mul(s.password, mask)))
	return s, nil
}

// process takes the other side's message and answers the 64-byte key both sides now hold.
func (s *spake2) process(theirs []byte) ([]byte, error) {
	q, err := decode(theirs)
	if err != nil {
		return nil, errors.New("the other side's SPAKE2 message is no point: " + err.Error())
	}
	peerMask := pointM
	if s.alice {
		peerMask = pointN
	}
	dh := encode(mul(s.private, add(q, neg(mul(s.password, peerMask)))))
	h := sha512.New()
	field := func(b []byte) {
		var n [8]byte
		binary.LittleEndian.PutUint64(n[:], uint64(len(b)))
		h.Write(n[:])
		h.Write(b)
	}
	if s.alice {
		field(s.myName)
		field(s.theirName)
		field(s.msg)
		field(theirs)
	} else {
		field(s.theirName)
		field(s.myName)
		field(theirs)
		field(s.msg)
	}
	field(dh)
	field(s.passwordHash)
	return h.Sum(nil), nil
}

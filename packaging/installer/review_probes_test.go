package main

// Second reader's probes for core-stub.patch: attacks on the HTTPS client and the redirect path that the
// stub is expected to withstand. These are EXPECTED TO PASS; each backs a "no finding" in the review.

import (
	"bufio"
	"bytes"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/url"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/solomonBoltin/deployment-hacohen/packaging/trust"
	"github.com/solomonBoltin/deployment-hacohen/packaging/trust/trusttest"
)

func mintCA(t *testing.T) (*x509.Certificate, crypto.Signer, *x509.CertPool) {
	t.Helper()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	tmpl := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "probe CA"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true,
		KeyUsage: x509.KeyUsageCertSign, BasicConstraintsValid: true}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	ca, _ := x509.ParseCertificate(der)
	pool := x509.NewCertPool()
	pool.AddCert(ca)
	return ca, key, pool
}

func mintLeaf(t *testing.T, ca *x509.Certificate, caKey crypto.Signer, name string) tls.Certificate {
	t.Helper()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	tmpl := &x509.Certificate{SerialNumber: big.NewInt(2), Subject: pkix.Name{CommonName: name}, DNSNames: []string{name},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, ca, &key.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key}
}

type readerConn struct {
	net.Conn
	r io.Reader
}

func (c readerConn) Read(p []byte) (int, error) { return c.r.Read(p) }

// A CONNECT proxy that answers 200 and then terminates TLS ITSELF with `leaf` (a man in the middle whose
// certificate chains to a root the getter trusts). The stub must hold the TARGET's name against it.
func TestProbeAProxyCannotPassItsOwnCertificateForTheTarget(t *testing.T) {
	ca, caKey, pool := mintCA(t)
	for _, tc := range []struct {
		name, presents string
		ok             bool
	}{
		{"control: a certificate for the target's own name", "example.com", true},
		{"a trusted certificate for the proxy's name", "proxy.invalid", false},
		{"a trusted certificate for a look-alike", "example.com.proxy.invalid", false},
	} {
		leaf := mintLeaf(t, ca, caKey, tc.presents)
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		defer ln.Close()
		var mu sync.Mutex
		var connectLine string
		go func() {
			for {
				c, err := ln.Accept()
				if err != nil {
					return
				}
				go func() {
					defer c.Close()
					br := bufio.NewReader(c)
					first := true
					for {
						line, err := br.ReadString('\n')
						if err != nil || line == "\r\n" {
							break
						}
						if first {
							mu.Lock()
							connectLine = strings.TrimSpace(line)
							mu.Unlock()
							first = false
						}
					}
					io.WriteString(c, "HTTP/1.1 200 Connection established\r\n\r\n")
					s := tls.Server(readerConn{c, br}, &tls.Config{Certificates: []tls.Certificate{leaf}})
					sr := bufio.NewReader(s)
					for {
						line, err := sr.ReadString('\n')
						if err != nil || line == "\r\n" {
							break
						}
					}
					io.WriteString(s, "HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nmitm")
				}()
			}
		}()
		g := getter{roots: pool, agent: "probe", proxy: func(string, string) (*url.URL, error) {
			return &url.URL{Scheme: "http", Host: ln.Addr().String()}, nil
		}}
		body, err := fetch(g, "https://example.com/dl/keys.json", 1<<10)
		mu.Lock()
		cl := connectLine
		mu.Unlock()
		if tc.ok && (err != nil || body != "mitm") || !tc.ok && err == nil {
			t.Errorf("%s: body %q err %v", tc.name, body, err)
		}
		if cl != "CONNECT example.com:443 HTTP/1.1" {
			t.Errorf("%s: the tunnel asked for %q", tc.name, cl)
		}
		t.Logf("%s: err = %v", tc.name, err)
	}
}

// A redirect can lead anywhere https, but it cannot make one document pass for another: keys.json
// redirected to the manifest fails on type; the manifest redirected to another target's fails on target.
func TestProbeRedirectsCannotChangeTheDocumentOrTheTarget(t *testing.T) {
	s := &site{files: map[string][]byte{}}
	redirects := map[string]string{}
	var mu sync.Mutex
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		to, ok := redirects[r.URL.Path]
		mu.Unlock()
		if ok {
			http.Redirect(w, r, to, http.StatusFound)
			return
		}
		s.mu.Lock()
		b, ok := s.files[r.URL.Path]
		s.mu.Unlock()
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Write(b)
	})
	dl := ts.URL + "/dl"
	r := trusttest.NewRelease(t, dl)
	s.serve("/dl/keys.json", r.KeysJSON())
	s.serve("/dl/linux/amd64/manifest.json", r.ManifestJSON())
	win := r.ManifestDoc()
	win["target"], win["payload_url"] = "windows/amd64", dl+"/windows/amd64/dgo-core.exe"
	s.serve("/dl/windows/amd64/manifest.json", trusttest.Seal(r.Signer, trust.ManifestType, win))
	s.serve("/dl/linux/amd64/dgo-core", r.Payload)
	for _, tc := range []struct{ from, to, want string }{
		{"/dl/keys.json", "/dl/linux/amd64/manifest.json", "payloadType"},
		{"/dl/linux/amd64/manifest.json", "/dl/windows/amd64/manifest.json", "it is for windows/amd64"},
		{"/dl/linux/amd64/manifest.json", "/dl/keys.json", "payloadType"},
	} {
		mu.Lock()
		redirects = map[string]string{tc.from: tc.to}
		mu.Unlock()
		tmp := t.TempDir()
		err := freshInstall(dl, r.RootsB64(), filepath.Join(tmp, "state"), filepath.Join(tmp, "core"), g).run()
		if err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s -> %s: err %v, want %q", tc.from, tc.to, err, tc.want)
		}
	}
}

// Framing edges the patch's TestGetFraming does not list: chunk sizes at and past 2^63, a chunk past the
// cap, Content-Length beside chunked, a close-delimited body past the cap, oversized trailers, a 1xx flood.
func TestProbeFramingEdges(t *testing.T) {
	big := strings.Repeat("x", 2000)
	nineInterim := strings.Repeat("HTTP/1.1 103 Early Hints\r\n\r\n", 9) + "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
	cases := []struct{ name, response, want, err string }{
		{"a chunk size of 2^63", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n8000000000000000\r\nx", "", "malformed chunk size"},
		{"a chunk size of 2^64-1", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nffffffffffffffff\r\nx", "", "malformed chunk size"},
		{"a chunk of 2^63-1 bytes, then the end", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n7fffffffffffffff\r\nabc", "", "unexpected EOF"},
		{"one chunk past the cap", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n7d0\r\n" + big + "\r\n0\r\n\r\n", "", "more than the 1024 bytes"},
		{"Content-Length beside chunked: chunked is read", "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n", "hello", ""},
		{"Content-Length beside chunked, past the cap", "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n7d0\r\n" + big + "\r\n0\r\n\r\n", "", "more than the 1024 bytes"},
		{"close-delimited, past the cap", "HTTP/1.1 200 OK\r\n\r\n" + big, "", "more than the 1024 bytes"},
		{"trailers past 64 KiB", "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nok\r\n0\r\n" + strings.Repeat("X-T: "+strings.Repeat("a", 1000)+"\r\n", 70) + "\r\n", "", "too large"},
		{"nine 1xx before the answer", nineInterim, "", "too many interim"},
		{"Content-Length past int63", "HTTP/1.1 200 OK\r\nContent-Length: 9223372036854775808\r\n\r\nx", "", "Content-Length"},
		{"Content-Length negative", "HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\nx", "", "Content-Length"},
	}
	for _, tc := range cases {
		u, g := rawTLS(t, tc.response)
		body, err := fetch(g, u, 1<<10)
		switch {
		case tc.err == "" && (err != nil || body != tc.want):
			t.Errorf("%s: body %q, err %v, want %q", tc.name, body, err, tc.want)
		case tc.err != "" && (err == nil || !strings.Contains(err.Error(), tc.err)):
			t.Errorf("%s: err %v, want it to contain %q", tc.name, err, tc.want+tc.err)
		}
	}
}

// No URL — the built-in site, a signed payload_url or a server's Location — can add a header line.
func TestProbeNoURLCanInjectARequestHeader(t *testing.T) {
	offline := getter{proxy: func(string, string) (*url.URL, error) {
		t.Fatal("no connection for a URL with a line break")
		return nil, nil
	}}
	for _, u := range []string{"https://digital-office.co.il/dl\r\nX-Evil: 1", "https://digital-office.co.il\r\nX-Evil: 1/dl"} {
		if _, err := fetch(offline, u, 1<<10); err == nil {
			t.Errorf("%q was fetched", u)
		}
	}
	var mu sync.Mutex
	var heads []http.Header
	var uris []string
	ts, g := tlsServer(t, func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		heads, uris = append(heads, r.Header.Clone()), append(uris, r.RequestURI)
		mu.Unlock()
		switch r.URL.Path {
		case "/enc":
			w.Header()["Location"] = []string{"/%0d%0aX-Evil:%201"}
			w.WriteHeader(http.StatusFound)
		default:
			io.WriteString(w, "fine")
		}
	})
	// net/http's server would turn a CR in Location into a space; the raw server sends it as is.
	rawURL, rawG := rawTLS(t, "HTTP/1.1 302 Found\r\nLocation: /ok\rX-Evil: 1\r\nContent-Length: 0\r\n\r\n")
	_, errCR := fetch(rawG, rawURL, 1<<10)
	if errCR == nil || !strings.Contains(errCR.Error(), "Location") {
		t.Errorf("a Location with a bare CR must be refused: %v", errCR)
	}
	_, errEnc := fetch(g, ts.URL+"/enc", 1<<10)
	mu.Lock()
	defer mu.Unlock()
	for i, h := range heads {
		if h.Get("X-Evil") != "" {
			t.Errorf("request %d (%s) carried an injected header", i, uris[i])
		}
	}
	t.Logf("a Location with a bare CR: %v; an encoded CRLF is sent encoded: %q (err %v)", errCR, uris, errEnc)
	var buf bytes.Buffer
	_ = buf
}

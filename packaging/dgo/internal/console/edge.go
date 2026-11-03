package console

import (
	"fmt"
	"net"
	"net/http"
	"net/netip"
	"strings"
)

// The console container is reachable only on the edge's network, so it believes the identity
// headers it is given: X-authentik-* as the forward-auth router wrote them, which app.py reads for
// /api/me and passes on through every app door. This process can listen anywhere — and a bridged edge
// reaches a host process from the bridge's gateway, not from 127.0.0.1 — so here those headers are
// believed only from a peer named by --trusted-proxy, and a listener off loopback without one is
// refused.

// identityHeader reports a request header that says who the caller is or which office it comes
// through: X-authentik-* (forward-auth and authentik), X-DGO-* (the link's From and Office), the
// Remote-*, X-Forwarded-User, X-Auth-Request-* and X-Webauth-* families of other auth proxies, and the
// edge's own Forwarded, X-Forwarded-* and X-Real-IP. Matched with `_` read as `-`: a WSGI server files
// X_Authentik_Username under the same name as X-Authentik-Username.
func identityHeader(name string) bool {
	n := strings.ToLower(strings.ReplaceAll(name, "_", "-"))
	for _, p := range []string{"x-authentik-", "x-dgo-", "remote-", "x-forwarded-", "x-auth-request-", "x-webauth-"} {
		if strings.HasPrefix(n, p) {
			return true
		}
	}
	return n == "forwarded" || n == "x-remote-user" || n == "x-real-ip"
}

// screen removes what a caller may not assert, before anything reads or forwards the request: every
// identity header from a caller that is not a trusted proxy, and from the trusted proxy too any one
// spelled with `_` — no proxy writes that spelling, so it is a client's, smuggled past the edge.
func (s *Server) screen(r *http.Request) {
	trusted := false
	if ap, err := netip.ParseAddrPort(r.RemoteAddr); err == nil {
		for _, p := range s.trusted {
			if p.Contains(ap.Addr().Unmap().WithZone("")) {
				trusted = true
				break
			}
		}
	}
	for name := range r.Header {
		if identityHeader(name) && (!trusted || strings.Contains(name, "_")) {
			delete(r.Header, name)
		}
	}
}

// ParseTrusted reads --trusted-proxy: addresses or CIDR prefixes, comma-separated; "" is none.
func ParseTrusted(v string) ([]netip.Prefix, error) {
	var out []netip.Prefix
	for _, f := range strings.Split(v, ",") {
		if f = strings.TrimSpace(f); f == "" {
			continue
		}
		if a, err := netip.ParseAddr(f); err == nil {
			a = a.Unmap().WithZone("")
			out = append(out, netip.PrefixFrom(a, a.BitLen()))
			continue
		}
		p, err := netip.ParsePrefix(f)
		if err != nil {
			return nil, fmt.Errorf("--trusted-proxy %q is neither an address nor a CIDR prefix", f)
		}
		out = append(out, p.Masked())
	}
	return out, nil
}

// listenAllowed refuses an address other machines can reach unless the proxy allowed to assert
// identity is named: whoever reaches the port could otherwise claim any user.
func listenAllowed(listen string, trusted []netip.Prefix) error {
	host, _, err := net.SplitHostPort(listen)
	if err != nil {
		return fmt.Errorf("--listen %q: %v", listen, err)
	}
	if a, err := netip.ParseAddr(host); host == "localhost" || (err == nil && a.IsLoopback()) {
		return nil
	}
	if len(trusted) == 0 {
		return fmt.Errorf("--listen %s is reachable from other machines: name the edge that may assert identity "+
			"with --trusted-proxy <address|cidr,…> (identity headers from every other caller are removed), or listen on 127.0.0.1", listen)
	}
	return nil
}

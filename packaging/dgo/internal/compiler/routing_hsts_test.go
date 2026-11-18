package compiler

import (
	"strings"
	"testing"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// TestTLSRoutersCarryHstsFirst — the Python twin's test_tls_routers_carry_hsts_and_plain_http_ones_do_not
// (platform/manager/test_https.py), and its order (DGO-1595): on a server office the https router's chain
// OPENS with hsts@file. Measured on vps1 2026-11-17: under `authentik@file,hsts@file` the sign-in's 302 ended
// the chain, and a signed-out visitor got no Strict-Transport-Security. Plain-http routers carry no pin.
func TestTLSRoutersCarryHstsFirst(t *testing.T) {
	raw, err := yamlish.LoadJSON(`{"host": "demo", "port": 80, "auth": "sso",
		"sso": {"slug": "demo", "default_host": "demo.localhost"}}`)
	if err != nil {
		t.Fatal(err)
	}
	r, ok := raw.(*yamlish.Map)
	if !ok {
		t.Fatalf("routing entry is %T, not a map", raw)
	}
	chains := func(env *dotenv) map[string]string {
		t.Helper()
		labels, err := routingLabels("demo", r, "", env, false)
		if err != nil {
			t.Fatal(err)
		}
		out := map[string]string{}
		for _, l := range labels {
			s, _ := l.(string)
			if !strings.HasPrefix(s, "traefik.http.routers.") || !strings.Contains(s, ".middlewares=") {
				continue
			}
			k, v, _ := strings.Cut(strings.TrimPrefix(s, "traefik.http.routers."), ".middlewares=")
			out[k] = v
		}
		return out
	}

	server := chains(&dotenv{vals: map[string]string{"DEPLOYMENT_DOMAIN": "office.example.com"}})
	if got := server["demo-https"]; got != "hsts@file,authentik@file" {
		t.Fatalf("server office demo-https chain = %q, want hsts first: %q", got, "hsts@file,authentik@file")
	}
	for _, name := range []string{"demo-http", "demo-local"} {
		if strings.Contains(server[name], "hsts") {
			t.Fatalf("%s is plain http and carries a pin: %q", name, server[name])
		}
	}
	local := chains(&dotenv{vals: map[string]string{"DEPLOYMENT_DOMAIN": "localhost"}})
	for name, chain := range local {
		if strings.Contains(chain, "hsts") {
			t.Fatalf("a .localhost office pins nothing, but %s = %q", name, chain)
		}
	}
}

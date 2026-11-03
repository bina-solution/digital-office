package console

import (
	"testing"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/edge"
)

// Behind the native edge (`dgo be-child native`, DGO-1090) the console trusts its caller, so the edge's
// strip is the only one: every header the console would refuse from an untrusted caller is one the edge
// removes from every request, and none more.
func TestTheEdgeStripsWhatTheConsoleBelieves(t *testing.T) {
	for _, h := range []string{
		"X-authentik-username", "X-Authentik-Jwt", "x_authentik_meta_app", "X-authentik-entitlements",
		"X-DGO-Office", "X-Dgo-From", "Remote-User", "Remote-Email", "Remote-Groups", "Remote-Name",
		"X-Forwarded-For", "X-Forwarded-User", "X_Forwarded_Host", "Forwarded", "X-Real-IP", "X-Remote-User",
		"X-Auth-Request-Email", "X-Auth-Request-User", "X-Webauth-User",
		"Cookie", "Authorization", "Content-Type", "X-Requested-With", "Remote", "X-Forwardedfor", "X-Authentik",
	} {
		if got, want := edge.Claimed(h), identityHeader(h); got != want {
			t.Errorf("%s: the edge strips it = %v, the console refuses it = %v", h, got, want)
		}
	}
}

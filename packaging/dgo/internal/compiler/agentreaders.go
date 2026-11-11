package compiler

import (
	"path/filepath"
	"sort"
	"strings"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// agentTokenReaders is agent_token_readers(cat, order) (DGO-1152): {agent service: [the compose services that may
// read its action token from the vault]}. An agent service is a service of an enabled app whose environment names
// AGENT_TOKEN_FILE; its readers are the services of an enabled app the provider names (token_readers) for a capability the agent's
// app is the ONE provider of here (an ambiguous capability, or an app using itself, hands out nothing).
func agentTokenReaders(repo string, cat *Catalog, order []string) (*yamlish.Map, error) {
	holders := map[string][]string{}
	for _, aid := range order {
		app := cat.Apps[aid]
		comp := get(app.doc, "compose")
		if !truthy(comp) {
			continue
		}
		rel, err := checkoutPath(repo, app.Dir, comp, aid+": compose")
		if err != nil {
			return nil, err
		}
		doc, err := loadYAML(filepath.Join(repo, filepath.FromSlash(rel)))
		if isGap(err) {
			return nil, err
		}
		if err != nil {
			continue // OSError, UnicodeDecodeError or PyYAML's refusal: nothing declared here
		}
		m, _ := doc.(*yamlish.Map)
		services, _ := get(m, "services").(*yamlish.Map)
		if services == nil {
			continue
		}
		for _, k := range services.Keys() {
			body, _ := get(services, k).(*yamlish.Map)
			if _, isText := services.TypedKey(k).(string); !isText || !namesAgentToken(get(body, "environment")) {
				continue
			}
			holders[aid] = append(holders[aid], k)
		}
	}
	readers := map[string]map[string]bool{}
	for _, aid := range order {
		uses, _ := get(cat.Apps[aid].doc, "use").([]any)
		for _, use := range uses {
			cap := use
			if u, isMap := use.(*yamlish.Map); isMap {
				cap = get(u, "capability")
			}
			var provs []string
			for _, p := range order {
				caps, _ := get(cat.Apps[p].doc, "capabilities").([]any)
				for _, c := range caps {
					if cm, isMap := c.(*yamlish.Map); isMap && pyEqual(get(cm, "name"), cap) {
						provs = append(provs, p)
						break
					}
				}
			}
			if len(provs) != 1 || provs[0] == aid || len(holders[provs[0]]) == 0 {
				continue
			}
			// …and only where the PROVIDER names this app for this capability (token_readers): a consumer's `use`
			// never grants itself the token
			if !providerNames(cat.Apps[provs[0]].doc, cap, aid) {
				continue
			}
			svcs, err := composeServiceMap(repo, cat.Apps[aid])
			if err != nil {
				return nil, err
			}
			for _, agent := range holders[provs[0]] {
				if readers[agent] == nil {
					readers[agent] = map[string]bool{}
				}
				if svcs == nil {
					continue
				}
				for _, s := range svcs.Keys() {
					if _, isText := svcs.TypedKey(s).(string); isText {
						readers[agent][s] = true
					}
				}
			}
		}
	}
	out := yamlish.NewMap()
	agents := make([]string, 0, len(readers))
	for agent := range readers {
		agents = append(agents, agent)
	}
	sort.Strings(agents) // sorted(): code points, which byte order is for valid UTF-8
	for _, agent := range agents {
		if len(readers[agent]) == 0 {
			continue
		}
		names := make([]string, 0, len(readers[agent]))
		for s := range readers[agent] {
			names = append(names, s)
		}
		sort.Strings(names)
		list := []any{}
		for _, s := range names {
			list = append(list, s)
		}
		out.Set(agent, list)
	}
	return out, nil
}

// providerNames is `any(isinstance(n, list) and aid in n for n in named)`: one of the provider's entries for
// capability cap lists aid in its token_readers (each item compared as Python's `in` compares, by ==).
func providerNames(doc *yamlish.Map, cap any, aid string) bool {
	caps, _ := get(doc, "capabilities").([]any)
	for _, c := range caps {
		cm, isMap := c.(*yamlish.Map)
		if !isMap || !pyEqual(get(cm, "name"), cap) {
			continue
		}
		named, _ := get(cm, "token_readers").([]any)
		for _, n := range named {
			if pyEqual(n, aid) {
				return true
			}
		}
	}
	return false
}

// namesAgentToken is `"AGENT_TOKEN_FILE" in names` of a service's environment: a mapping's keys, or a list's
// `NAME=value` items by the name before the first `=`.
func namesAgentToken(env any) bool {
	switch e := env.(type) {
	case *yamlish.Map:
		for _, k := range e.Keys() {
			if name, isText := e.TypedKey(k).(string); isText && name == "AGENT_TOKEN_FILE" {
				return true
			}
		}
	case []any:
		for _, x := range e {
			if s, isText := x.(string); isText {
				if name, _, _ := strings.Cut(s, "="); name == "AGENT_TOKEN_FILE" {
					return true
				}
			}
		}
	}
	return false
}

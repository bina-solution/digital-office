package compiler

import (
	"testing"

	"github.com/bina-solution/digital-office/packaging/dgo/internal/yamlish"
)

// The cases of platform/manager/test_ops.py (DGO-1244), the same lines: checkOps is _check_ops.

const opsCap = `"capabilities":[{"name":"llm","type":"protocol","endpoint":"http://x:1"}]`

func opJSON(extra string) string {
	if extra != "" {
		extra = "," + extra
	}
	return `{"id":"models","method":"GET","path":"/api/tags","access":"read"` + extra + `}`
}

func TestValidateOpsWellFormed(t *testing.T) {
	errs := validation(t, map[string]string{
		"apps/a/app.json": manifest("a", 3, opsCap+`,"ops":[`+opJSON(`"verb":"models"`)+`,{"id":"show","method":"POST","path":"/api/show","access":"read","verb":"show"}]`),
	})
	expectErrs(t, errs)
}

func TestValidateOpsRequiredAndUnknownKeys(t *testing.T) {
	errs := validation(t, map[string]string{
		"apps/a/app.json": manifest("a", 3, opsCap+`,"ops":[{"id":"x","method":"GET","path":"/p","colour":"red","Note":1}]`),
	})
	expectErrs(t, errs,
		"a: ops[0] has no 'access'",
		"a: ops[0] has the key 'Note', which an op does not have",
		"a: ops[0] has the key 'colour', which an op does not have")
}

func TestValidateOpsIdAndPathPatterns(t *testing.T) {
	errs := validation(t, map[string]string{"apps/a/app.json": manifest("a", 3, opsCap+`,"ops":[{"id":"Not An Id","method":"GET","path":"api/x","access":"read"}]`)})
	expectErrs(t, errs,
		"a: ops[0] id 'Not An Id' is not an op's name (a-z, 0-9, -)",
		"a: ops[0] path 'api/x' does not start at the endpoint's root (/)")
}

func TestValidateOpsIdTwice(t *testing.T) {
	errs := validation(t, map[string]string{"apps/a/app.json": manifest("a", 3, opsCap+`,"ops":[`+opJSON("")+`,`+opJSON("")+`]`)})
	expectErrs(t, errs, "a: ops[1] 'models' is declared twice — an op's id is its name in the answer")
}

func TestValidateOpsEndpoint(t *testing.T) {
	two := `"capabilities":[{"name":"llm","type":"protocol","endpoint":"http://x:1"},{"name":"llm2","type":"protocol","endpoint":"http://y:2"}]`
	errs := validation(t, map[string]string{
		"apps/a/app.json": manifest("a", 3, `"ops":[`+opJSON("")+`]`),
		"apps/b/app.json": manifest("b", 3, two+`,"ops":[`+opJSON("")+`]`),
		"apps/c/app.json": manifest("c", 3, two+`,"ops":[`+opJSON(`"capability":"llm2"`)+`]`),
		"apps/d/app.json": manifest("d", 3, `"capabilities":[{"name":"llm","type":"protocol","endpoint":"http://x:1"},{"name":"quiet","type":"protocol"}],"ops":[`+opJSON(`"capability":"quiet"`)+`]`),
	})
	expectErrs(t, errs,
		"a: ops[0] names no capability, and the app has 0 with an endpoint — name the one that serves it",
		"b: ops[0] names no capability, and the app has 2 with an endpoint — name the one that serves it",
		"d: ops[0] capability 'quiet' is not one of this app's capabilities with an endpoint")
}

// a verb is a name; whether its hook exists is DGO-1246's gate (validate reads the manifest only)
func TestValidateOpsVerb(t *testing.T) {
	errs := validation(t, map[string]string{
		"apps/a/app.json": manifest("a", 3, opsCap+`,"ops":[`+opJSON(`"verb":"../models"`)+`]`),
		"apps/b/app.json": manifest("b", 3, opsCap+`,"ops":[`+opJSON(`"verb":"gone"`)+`]`),
	})
	expectErrs(t, errs, "a: ops[0] verb '../models' is not a verb's name (a-z, 0-9, -)")
}

func TestValidateOpsMethodEnum(t *testing.T) {
	errs := validation(t, map[string]string{"apps/a/app.json": manifest("a", 3, opsCap+`,"ops":[`+opJSON(`"method":"FETCH"`)+`]`)})
	// the method key is given twice in this JSON; the last wins, as json.loads keeps it
	expectErrs(t, errs, "a: field 'ops'[0].method must be one of GET|POST|PUT|PATCH|DELETE, got 'FETCH'")
}

// opsRegistryWant is test_ops.py's REGISTRY, as json.dumps(indent=2, ensure_ascii=False) spells it.
const opsRegistryWant = `{
  "a": [
    {
      "id": "models",
      "method": "GET",
      "path": "/api/tags",
      "endpoint": "http://x:1",
      "access": "read",
      "verb": "models",
      "summary": {
        "en": "the models",
        "he": "המודלים"
      }
    },
    {
      "id": "unload",
      "method": "POST",
      "path": "/api/generate",
      "endpoint": "http://x:1",
      "access": "write"
    }
  ],
  "b": [
    {
      "id": "ping",
      "method": "GET",
      "path": "/ping",
      "endpoint": "http://b2:9",
      "access": "read",
      "ui": "the refresh button"
    }
  ]
}`

func TestOpsRegistryMatchesPython(t *testing.T) {
	repo := fixture(t, map[string]string{
		"apps/b/app.json": manifest("b", 3, `"capabilities":[{"name":"one","endpoint":"http://b1:9"},{"name":"two","endpoint":"http://b2:9"}],`+
			`"ops":[{"ui":"the refresh button","access":"read","path":"/ping","method":"GET","id":"ping","capability":"two","verb":null}]`),
		"apps/a/app.json": manifest("a", 3, opsCap+`,"ops":[`+opJSON(`"verb":"models","summary":{"en":"the models","he":"המודלים"}`)+
			`,{"id":"unload","method":"POST","path":"/api/generate","access":"write"}]`),
		"apps/c/app.json": manifest("c", 3, opsCap),
		"apps/d/app.json": manifest("d", 3, opsCap+`,"ops":[`+opJSON("")+`]`),
	}, stateHead)
	cat, err := LoadCatalog(repo)
	if err != nil {
		t.Fatal(err)
	}
	got := yamlish.IndentJSON(opsRegistry(cat, []string{"b", "c", "a"}))
	if got != opsRegistryWant {
		t.Fatalf("ops.json:\n%s\nwant (reconcile.py's):\n%s", got, opsRegistryWant)
	}
}

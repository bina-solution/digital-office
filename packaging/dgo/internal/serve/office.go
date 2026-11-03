package serve

import (
	"bytes"
	"errors"
	"io"
	"mime"
	"net/http"
	"strings"
	"unicode/utf8"

	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/compiler"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/pyval"
	"github.com/solomonBoltin/deployment-hacohen/packaging/dgo/internal/yamlish"
)

// officePut is api_office_put() where this office has no container engine — the phone's core
// (DGO-1090), whose install wizard writes the office's record first: the record as JSON, written by
// the compiler (office-set --by wizard, its twin here, its sentences back as app.py hands them on),
// then read back as office-get reads it. A request from a linked office never reaches here (the route's
// refusal comes first). A body app.py's Flask would read otherwise — not UTF-8 — is the container's.
func (s *server) officePut(w http.ResponseWriter, r *http.Request) bool {
	if !s.engineless {
		return false
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 8<<20))
	r.Body = io.NopCloser(bytes.NewReader(body)) // whole again for the container, should it be its
	// json.loads reads a body's own encoding (a BOM, UTF-16): what is not plain UTF-8 is the container's
	if err != nil || !utf8.Valid(body) || bytes.HasPrefix(body, []byte("\xef\xbb\xbf")) {
		return s.unvouched(r, errOr(err, "a body that is not plain UTF-8"))
	}
	// request.get_json(silent=True): a JSON type and a body that parses, else None
	var record *yamlish.Map
	if isJSON(r.Header.Get("Content-Type")) {
		if v, err := yamlish.LoadJSON(string(body)); err == nil {
			record, _ = v.(*yamlish.Map)
		}
	}
	if record == nil {
		reply(w, http.StatusBadRequest, object("error", "the office record is a JSON object of its fields"))
		return true
	}
	// _office_set: the compiler validates before it writes; what it says comes back line by line
	var out, said bytes.Buffer
	if compiler.OfficeSetCmd(s.repo, []string{"--by", "wizard"}, bytes.NewReader(body), &out, &said) != 0 {
		text := said.String()
		if text == "" {
			text = out.String()
		}
		var errs []any
		for _, ln := range strings.Split(text, "\n") {
			// ln.strip().lstrip("- ").strip()
			if v := pyval.Strip(strings.TrimLeft(pyval.Strip(ln), "- ")); v != "" {
				errs = append(errs, v)
			}
		}
		if len(errs) == 0 {
			errs = []any{"office record refused"}
		}
		joined := make([]string, len(errs))
		for i, e := range errs {
			joined[i] = e.(string)
		}
		reply(w, http.StatusBadRequest, object("error", strings.Join(joined, "; "), "errors", errs))
		return true
	}
	rec, err := compiler.OfficeBlock(s.repo)
	if err != nil {
		return s.unvouched(r, err) // written, and then unreadable here: app.py's 500 is Python's wording
	}
	done, err := installed(s.repo, rec)
	if err != nil {
		return s.unvouched(r, err)
	}
	reply(w, http.StatusOK, object("ok", true, "office", rec, "installed", done))
	return true
}

// errOr is err, or one that says what.
func errOr(err error, what string) error {
	if err != nil {
		return err
	}
	return errors.New(what)
}

// isJSON is Flask's Request.is_json: application/json, or application/*+json.
func isJSON(contentType string) bool {
	mt, _, err := mime.ParseMediaType(contentType)
	if err != nil {
		mt = strings.ToLower(strings.TrimSpace(strings.SplitN(contentType, ";", 2)[0]))
	}
	return mt == "application/json" || strings.HasPrefix(mt, "application/") && strings.HasSuffix(mt, "+json")
}

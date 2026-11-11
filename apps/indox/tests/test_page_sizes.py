#!/usr/bin/env python3
"""test_page_sizes — the action log offers 500 and 1000 rows a page, and no grid pages by a size its API cannot return (DGO-234).

    python3 apps/indox/tests/test_page_sizes.py      (the repo only; no office, no docker)

THE OWNER (2026-08-16, three times): the action log's page sizes of 500 and 1000. The API half landed that
day (`_ACTIONS_LIMIT_MAX = 1000`, «the log page offers 500/1000-row pages»). The page never passed the
options, so the grid kept DataGrid's default and stopped at 200.

THE RULE IT KEEPS, for every server-mode grid: a page size the grid can page by must be one its endpoint
returns. If it is not, the grid asks for N rows, the API returns its cap, the grid pages by N, and the rows
between the cap and N are never shown. The documents grid stays at DataGrid's default (up to 200): its
endpoint is capped at 500, because a 2000-row page of 150-column rows outlived the console proxy
(2026-09-02). Its size also comes from the address (`?size=`), so that path must take only an offered size.

It finds the grids itself: every `<DataGrid` element under webapp/src, read as the element's OWN attributes
(a `{…}` prop is skipped whole, so an element nested in a prop is never mistaken for the grid's end). A
server-mode grid it does not know fails until its endpoint's cap is named in SERVER_GRIDS below; a `mode` or
`pageSizeOptions` it cannot read fails rather than being taken as the default.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "apps/indox/app/webapp/src"
BFF = ROOT / "apps/indox/app/incoming_documents/api/__init__.py"
FAILS = []

#: every server-mode grid → how to read its endpoint's row cap from the BFF
SERVER_GRIDS = {
    "pages/ActionLogPage.tsx": ("/dashboard/actions", r"^_ACTIONS_LIMIT_MAX\s*=\s*(\d+)"),
    "pages/DocumentBrowserPage.tsx": ("the documents query", r'INCOMING_DOCS_QUERY_MAX_LIMIT",\s*"(\d+)"'),
}
_ATTR = re.compile(r"([A-Za-z_][\w-]*)(\s*=\s*)?")


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def _skip_comment(t, i):
    """At a `/*` or `//`: the index just past the comment (its text may hold quotes and braces)."""
    if t.startswith("/*", i):
        j = t.find("*/", i + 2)
        return len(t) if j < 0 else j + 2
    j = t.find("\n", i)
    return len(t) if j < 0 else j


def _skip_string(t, i):
    """At a quote: the index just past the string; a template's `${…}` is skipped as an expression."""
    q, i = t[i], i + 1
    while i < len(t):
        if t[i] == "\\":
            i += 2
        elif q == "`" and t.startswith("${", i):
            i = _skip_braces(t, i + 1)
        elif t[i] == q:
            return i + 1
        else:
            i += 1
    return i


def _skip_braces(t, i):
    """At a `{`: the index just past its matching `}`, with strings, templates and comments skipped."""
    depth = 0
    while i < len(t):
        if t.startswith("/*", i) or t.startswith("//", i):
            i = _skip_comment(t, i)
            continue
        c = t[i]
        if c in "\"'`":
            i = _skip_string(t, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def grids(text):
    """Every `<DataGrid …>` element of one file, as {attribute: its raw value} — the element's OWN
    attributes, up to its own `/>` or `>`. A comment that names the component (`<DataGrid>`) is not one."""
    out = []
    for m in re.finditer(r"<DataGrid\s", text):
        i, attrs = m.end(), {}
        while i < len(text):
            if text.startswith("/*", i) or text.startswith("//", i):
                i = _skip_comment(text, i)
            elif text.startswith("/>", i) or text[i] == ">":
                break
            elif text[i] == "{":                                   # a spread: {...props}
                i = _skip_braces(text, i)
            elif (a := _ATTR.match(text, i)):
                i = a.end()
                value = True
                if a.group(2):
                    j = (_skip_braces(text, i) if text[i:i + 1] == "{"
                         else _skip_string(text, i) if text[i:i + 1] in ("\"", "'") else i)
                    value, i = text[i:j], j
                attrs[a.group(1)] = value
            else:
                i += 1
        out.append(attrs)
    return out


def options_of(value):
    """A `pageSizeOptions` value: its numbers, None when there is none, or "unreadable" (a constant, a
    computed list) — never silently taken as the default."""
    if value is None:
        return None
    m = re.fullmatch(r"\{\s*\[([0-9,\s]+)\]\s*\}", str(value))
    return [int(x) for x in re.findall(r"\d+", m.group(1))] if m else "unreadable"


def mode_of(value):
    """'server' / 'client' from a literal `mode`, 'client' when there is none (DataGrid's default), or
    "unreadable" for any other spelling — never silently taken as client."""
    if value is None:
        return "client"
    v = str(value).strip()
    v = v[2:-2] if re.fullmatch(r"\{\s*['\"].*['\"]\s*\}", v) else v.strip("\"'")
    return v if v in ("server", "client") else "unreadable"


def main():
    bff = BFF.read_text(encoding="utf-8")
    grid_src = (SRC / "components/DataGrid.tsx").read_text(encoding="utf-8")
    m = re.search(r"^export const DEFAULT_PAGE_SIZES\s*=\s*\[([0-9,\s]+)\]", grid_src, re.M)
    default = [int(x) for x in re.findall(r"\d+", m.group(1))] if m else []
    check(bool(default) and "pageSizeOptions = DEFAULT_PAGE_SIZES" in grid_src,
          f"read DataGrid's default page sizes, and it pages by them when a page passes none: {default}")

    files = sorted(SRC.rglob("*.tsx"))
    found = []
    for path in files:
        rel = path.relative_to(SRC).as_posix()
        for attrs in grids(path.read_text(encoding="utf-8")):
            found.append((rel, mode_of(attrs.get("mode")), options_of(attrs.get("pageSizeOptions")), attrs))
    print(f"      scanned {len(files)} .tsx files; grids: " + ", ".join(f"{r} ({md}, {len(a)} attributes)" for r, md, _, a in found))
    check(len(found) >= 3, f"found the grids (at least the log, the documents and the settings tables): {len(found)}")

    sizes = {}
    for rel, md, opts, attrs in found:
        check(md != "unreadable", f"{rel}: its mode is a literal this test can read ({attrs.get('mode')!r})")
        check(opts != "unreadable", f"{rel}: its pageSizeOptions is a literal list this test can read")
        offered = opts if isinstance(opts, list) else default
        if md != "server":
            continue
        if rel not in SERVER_GRIDS:
            check(False, f"{rel}: a server-mode grid this test does not know — name its endpoint's cap in SERVER_GRIDS")
            continue
        endpoint, pattern = SERVER_GRIDS[rel]
        cm = re.search(pattern, bff, re.M)
        cap = int(cm.group(1)) if cm else None
        check(cap is not None and bool(offered) and max(offered) <= cap,
              f"{rel}: every size it offers is one {endpoint} returns (max {max(offered) if offered else '—'} ≤ cap {cap})")
        sizes[rel] = (offered, opts, attrs)

    log = sizes.get("pages/ActionLogPage.tsx", ([], None, {}))[0]
    check(500 in log and 1000 in log, f"the action log offers 500 and 1000 rows a page (offers {log})")

    # the documents page takes `?size=` only from DEFAULT_PAGE_SIZES — right only while its grid offers exactly those
    docs = (SRC / "pages/DocumentBrowserPage.tsx").read_text(encoding="utf-8")
    _, docs_opts, docs_attrs = sizes.get("pages/DocumentBrowserPage.tsx", ([], "missing", {}))
    check(bool(re.search(r"^\s*size:.*DEFAULT_PAGE_SIZES\.includes\(", docs, re.M))
          and docs_attrs.get("initialPageSize") == "{urlInit.size}" and docs_opts is None,
          "the documents grid takes its size from the address only when it is one the grid offers "
          "(it passes no pageSizeOptions, so it offers DEFAULT_PAGE_SIZES)")

    # The readers: a prop, its absence, unreadable forms, a nested element's `/>`, and a comment.
    nested = ('// <DataGrid> the table\n<DataGrid\n  columns={c}\n  toolbarStart={\n    <input\n      type="file"\n'
              '      onChange={(e) => { if (e) go(`a ${b} }`); }}\n    />\n  }\n  /* the owner\'s rows */\n'
              '  mode="server"\n  pageSizeOptions={[25, 5000]}\n/>\n')
    g = grids(nested)
    check(len(g) == 1 and mode_of(g[0].get("mode")) == "server" and options_of(g[0].get("pageSizeOptions")) == [25, 5000]
          and options_of("{ [25, 50, 100, 200, 500, 1000] }") == [25, 50, 100, 200, 500, 1000]
          and options_of(None) is None and options_of("{SIZES}") == "unreadable"
          and mode_of(None) == "client" and mode_of("{'server'}") == "server" and mode_of("{m}") == "unreadable",
          "self-check: reads a grid past a nested element's `/>`, its absence, unreadable forms, and skips a comment")

    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

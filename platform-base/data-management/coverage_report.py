#!/usr/bin/env python3
"""backup coverage report - does a rule actually cover every store on this host?

    docker exec <data-management-container> python3 /app/coverage_report.py

WHY THIS EXISTS. "15 of 21 enabled apps have no backup hook" was raised as evidence that the export
is silently partial. Measured 2026-08-24 it is 16 of 22, and it is NOT a coverage gap: a backup hook
is only needed where the GENERIC rules cannot express an app's data. Ten of those sixteen are fully
covered by sql dumps / volume tars / bind tars, and the other six own no data at all. Zero enabled
apps were at risk.

That is a good answer, but it was an ASSUMPTION until something computed it, and it will rot the
moment an app adds an undeclared store. So this turns it into an assertion that can fail.

WHAT COUNTS AS COVERED is not this script's opinion - inventory.py already stamps every store with a
`coverage` value while attributing it (covered by hook / generic tar / bind tar / sql dump / dormant
tar). A store with NO coverage key is one no rule claims. This only reads that field, so there is
one definition of covered on this host and it lives with the code that does the attributing.

ATTRIBUTION IS NOT COVERAGE, and conflating them is the trap here. `unclaimed` means no app.json
DECLARES the store - it says nothing about whether it is backed up. Measured today, 11 of the 12
unclaimed stores are covered anyway (the whole-database dump catches undeclared tables, including
indox_action_execution_log, which is real client data). Reporting unclaimed as "not backed up" would
have raised eleven false alarms and buried the one real finding.

EXIT 1 if any store on the host has no coverage at all.
"""
import json
import sys
import urllib.error
import urllib.request

URL = 'http://127.0.0.1:8080/api/inventory?wait=true&timeout=300'
SHORT = {'covered (hook)': 'hook', 'covered (generic tar)': 'tar', 'covered (volume tar)': 'tar',
         'covered (bind tar)': 'bind-tar', 'covered (sql dump)': 'sql-dump',
         'covered (dormant tar)': 'dormant', 'covered (secrets)': 'secrets'}


def main():
    try:
        d = json.load(urllib.request.urlopen(URL, timeout=330))
    except urllib.error.HTTPError as e:                          # the service answered: say what
        print('[coverage] FAIL - the inventory answered %s: %s'
              % (e.code, e.read().decode('utf-8', 'replace')[:300]))
        return 1
    except Exception as e:                                       # noqa: BLE001
        print('[coverage] FAIL - cannot read the inventory: %s: %s' % (type(e).__name__, e))
        return 1

    # A partial sweep must never be read as a complete answer - that is the same defect this report
    # is about, one layer up. See the SECTION_STALL guard in app.py.
    ready, sections = d.get('ready') or [], d.get('sections') or []
    if d.get('state') != 'ready' or len(ready) != len(sections):
        print('[coverage] FAIL - inventory is %s with %d/%d sections; refusing to report on a '
              'partial sweep' % (d.get('state'), len(ready), len(sections)))
        return 1
    if d.get('last_wedge'):
        print('[coverage] NOTE - this host recorded a wedged sweep: %s' % d['last_wedge'])

    by_app = d.get('by_app') or []
    print('%-26s %-4s %-5s %-6s %s' % ('APP', 'ENA', 'HOOK', 'STORES', 'COVERAGE'))
    print('-' * 78)
    at_risk, hookless_ok, no_data = [], [], []
    for a in sorted(by_app, key=lambda x: (not x.get('enabled'), x.get('id') or '')):
        stores = a.get('stores') or []
        tally = {}
        for s in stores:
            c = s.get('coverage')
            tally[SHORT.get(c, c or 'UNCOVERED')] = tally.get(SHORT.get(c, c or 'UNCOVERED'), 0) + 1
        bad = tally.get('UNCOVERED', 0)
        print('%s%-24s %-4s %-5s %-6d %s' % (
            '!!' if bad else '  ', a.get('id'), 'yes' if a.get('enabled') else 'no',
            'yes' if a.get('backup_hook') else 'NO', len(stores),
            ', '.join('%s=%d' % kv for kv in sorted(tally.items())) or '(no stores)'))
        if a.get('enabled'):
            if bad:
                at_risk.append(a.get('id'))
            elif not stores:
                no_data.append(a.get('id'))
            elif not a.get('backup_hook'):
                hookless_ok.append(a.get('id'))

    enabled = [a for a in by_app if a.get('enabled')]
    print('')
    print('enabled apps                       : %d of %d' % (len(enabled), len(by_app)))
    print('enabled WITHOUT a backup hook      : %d'
          % len([a for a in enabled if not a.get('backup_hook')]))
    print('  ...of those, covered anyway      : %d  %s' % (len(hookless_ok), hookless_ok))
    print('  ...of those, no data to back up  : %d  %s' % (len(no_data), no_data))
    print('  ...of those, GENUINELY AT RISK   : %d  %s' % (len(at_risk), at_risk))

    # Host-level stores nobody declared. Printed with their coverage, because most ARE covered.
    naked = [u for u in (d.get('unclaimed') or []) if not u.get('coverage')]
    print('')
    print('undeclared stores: %d, of which UNCOVERED: %d'
          % (len(d.get('unclaimed') or []), len(naked)))
    for u in naked:
        print('   !! %-8s %-36s %-8s %s' % (u.get('kind'), u.get('name'), u.get('size') or '',
                                            u.get('why') or ''))

    if at_risk or naked:
        print('')
        print('[coverage] FAIL - %d enabled app(s) with uncovered data, %d uncovered undeclared '
              'store(s). An export taken now would be silently incomplete.' % (len(at_risk), len(naked)))
        return 1
    print('')
    print('[coverage] PASS - every store on this host is covered by a rule')
    return 0


if __name__ == '__main__':
    sys.exit(main())

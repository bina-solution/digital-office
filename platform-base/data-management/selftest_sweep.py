#!/usr/bin/env python3
"""Self-test for the inventory sweep stall guard (platform-base/data-management/app.py).

RUN IT (needs the running service, because it imports the real module and INV):
    docker cp platform-base/data-management/app.py <container>:/tmp/dmtest/app.py
    docker cp platform-base/data-management/selftest_sweep.py <container>:/tmp/
    docker exec -e PYTHONPATH=/tmp/dmtest:/app <container> python3 /tmp/selftest_sweep.py

It drives the REAL _ensure_sweep/_sweep with only INV.inventory_steps replaced, because a
replica of the logic would only ever prove the replica. 26 checks, exit non-zero on any fail:
twelve of the stall guard, six of what a page is given while a sweep runs (`_shown`), eight of what
a restarted process stands on (`_keep` / `_kept` / `_resume`).
"""
import asyncio, json, pathlib, sys, tempfile, time, threading

import app as A  # noqa: E402  (resolved via PYTHONPATH=/tmp/dmtest:/app)

RELEASED = threading.Event()


def hanging_steps(table_limit=40):
    """Completes 'apps', then blocks forever - the shape of a docker/psql shell that never returns."""
    yield 'apps', {'ready': ['apps']}
    RELEASED.wait()
    yield 'volumes', {'ready': ['ZOMBIE']}


def fast_steps(table_limit=40):
    yield 'apps', {'ready': ['apps']}
    yield 'volumes', {'ready': ['REPLACEMENT']}


async def main():
    A.INV.inventory_steps = hanging_steps
    A.SECTION_STALL = 2.0    # keep the test quick; the constant is 600s in production
    # The process under test starts with NOTHING kept, and keeps what it keeps in a directory of its
    # own: this runs beside the service, whose volume holds the real last sweep — never read or
    # written from here.
    A.KEPT_FILE = pathlib.Path(tempfile.mkdtemp(prefix='zz-dm-state-')) / 'last-sweep.json'
    A.SNAP.update(last=None, computed_at=None)

    fails = []

    def check(name, got, want):
        ok = got == want
        if not ok:
            fails.append(name)
        print('  [%s] %s (got %r, want %r)' % ('ok ' if ok else 'FAIL', name, got, want))

    await A._ensure_sweep(force=True)
    await asyncio.sleep(0.5)
    check('a hanging sweep is running', A.SNAP['state'], 'running')
    check('the section it finished is named', A.SNAP['section'], 'apps')
    # the FIRST sweep of a process has nothing to stand on: the page is given it as it fills
    check('a first sweep is shown as it fills', A._shown(), ({'ready': ['apps']}, ['apps']))
    gen1 = A.SNAP['gen']

    # Before the budget expires it must NOT be disturbed - a slow sweep is not a wedged one.
    await A._ensure_sweep(force=True)
    check('within budget the sweep is left alone', A.SNAP['gen'], gen1)

    # The replacement must be able to actually finish, so swap in a generator that returns.
    A.INV.inventory_steps = fast_steps

    # This is the case that was previously unrecoverable: state=="running" forever.
    await asyncio.sleep(2.2)
    await A._ensure_sweep(force=True)
    check('past the budget a NEW sweep is started', A.SNAP['gen'] > gen1, True)
    check('the wedge is surfaced, not swallowed', 'WEDGED' in (A.SNAP['last_wedge'] or ''), True)
    check('the wedge names the last completed section', 'apps' in (A.SNAP['last_wedge'] or ''), True)

    await asyncio.sleep(0.8)
    check('the replacement sweep completes', A.SNAP['state'], 'ready')
    settled = A.SNAP['data']
    check('the replacement owns the snapshot', settled, {'ready': ['REPLACEMENT']})

    # Only NOW release the zombie: it is superseded and must write nothing.
    RELEASED.set()
    time.sleep(0.8)
    check('a superseded zombie writes nothing', A.SNAP['data'], settled)
    check('a superseded zombie cannot flip state', A.SNAP['state'], 'ready')
    # The whole point: recovery must not erase the fact that it happened.
    check('the wedge record SURVIVES a successful recovery',
          'WEDGED' in (A.SNAP['last_wedge'] or ''), True)
    check('current error is cleared by the good sweep', A.SNAP['error'], None)

    # ── what a PAGE is given while a sweep runs: the last COMPLETED sweep's numbers, not the new
    #    sweep's half-built ones (the page stood on placeholders for as long as every sweep took)
    check('a completed sweep is what is shown', A._shown(), (settled, ['REPLACEMENT']))
    START, GO = threading.Event(), threading.Event()

    def next_steps(table_limit=40):
        START.wait()
        yield 'apps', {'ready': ['apps']}
        GO.wait()
        yield 'volumes', {'ready': ['apps', 'volumes']}

    A.INV.inventory_steps = next_steps
    await A._ensure_sweep(force=True)
    await asyncio.sleep(0.3)
    check('a new sweep that has finished nothing: the last numbers, and nothing re-scanned', A._shown(), (settled, []))
    START.set()
    await asyncio.sleep(0.4)
    check('…that has finished a section: STILL the last numbers, and that section told beside them',
          A._shown(), (settled, ['apps']))
    check('…while the restore preflight\'s own reading is the sweep in hand, not what is shown',
          (A.SNAP['state'], A.SNAP['data']), ('running', {'ready': ['apps']}))
    GO.set()
    await asyncio.sleep(0.6)
    check('…and once it completes, its own numbers are what is shown',
          (A.SNAP['state'], A._shown()), ('ready', ({'ready': ['apps', 'volumes']}, ['apps', 'volumes'])))

    # ── across a RESTART: the last completed sweep is kept on the service's own volume, and a new
    #    process stands on it as OLD numbers — never as a sweep of its own (DGO-515: a restarted
    #    service was placeholders for as long as its first sweep took)
    check('nothing kept: a new process has nothing to stand on', A._kept(), None)
    WHOLE = {'ready': list(A.INV.SECTION_ORDER), 'apps': ['kept']}
    mine = A.INV.deployment_name()

    def whole_steps(table_limit=40):
        yield A.INV.SECTION_ORDER[-1], WHOLE

    A.INV.inventory_steps = whole_steps
    await A._ensure_sweep(force=True)
    await asyncio.sleep(0.5)
    check('a sweep that completed every section is kept', (A._kept() or [None])[0], WHOLE)

    def kept_as(deployment, data):
        A.KEPT_FILE.write_text(json.dumps({'deployment': deployment, 'computed_at': 'then', 'data': data}), encoding='utf-8')
        return A._kept()

    check("a file another deployment wrote is not this one's", kept_as('another-office', WHOLE), None)
    check('a sweep that did not complete is not what a page stands on', kept_as(mine, {'ready': ['apps']}), None)
    check('…and this deployment\'s own completed sweep is', kept_as(mine, WHOLE), (WHOLE, 'then'))
    # a new process: nothing in memory, the file on its volume
    A.SNAP.update(state='empty', data=None, last=None, computed_at=None, started_at=None, section=None, section_at=None, error=None)
    A._resume()
    HOLD = threading.Event()

    def first_steps(table_limit=40):
        HOLD.wait()
        yield 'apps', {'ready': ['apps']}

    A.INV.inventory_steps = first_steps
    page = await A.api_inventory(archive=None, refresh=False, wait=False, timeout=600.0, table_limit=40)
    check('a restarted process, its first sweep running: the page is given the kept numbers, with their time',
          (page['state'], page['apps'], page['computed_at'], page['rescanned']), ('running', ['kept'], 'then', []))
    check('…which are not a completed sweep of this process', (page['complete'], A.SNAP['data']), (False, None))
    HOLD.set()
    await asyncio.sleep(0.6)
    check('a sweep that completed only part does not replace what is kept', (A.SNAP['state'], A._kept()), ('ready', (WHOLE, 'then')))

    n = 26
    print('')
    print('sweep-wedge self-test: %d/%d passed' % (n - len(fails), n))
    return 1 if fails else 0


sys.exit(asyncio.run(main()))

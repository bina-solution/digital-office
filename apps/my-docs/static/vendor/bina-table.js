/* ═══════════════════════════════════════════════════════════════════════════
   bina-table (vanilla) — the platform-standard table on RevoGrid, for the
   no-build apps (my-docs, machine, console…). Feature-parity port of the
   React wrapper (incoming-documents/webapp/src/components/BinaTable.tsx):
   sort (+aria-sort), Hebrew filter panel, global search, column resize/reorder
   (+persistence), density toggle (+persistence), row numbers, virtualization,
   inline edit with VALIDATION + ROLLBACK + UNDO, THE RTL STRATEGY (LTR engine
   + reversed columns + RTL text), orchestrated first paint, quick-filter
   chips, column picker, selection + bulk delete, per-row ACTIONS column,
   CSV export/import, client pagination, server mode.

   Usage (no build step):
     <link rel="stylesheet" href="vendor/bina-table.css">
     <script src="vendor/bina-table.js"></script>
     const t = BinaTable.create(el, { columns, data, rowKey, tableId, ... });
     t.setData(rows); t.setLoading(false); t.destroy();
   The RevoGrid dist must sit next to this file: vendor/revo-grid/ (auto-loaded).
   The page carries the office's question-and-notice block (bina-ask.js) as well: what the
   table says («נשמר» with its way back, a refusal) and asks (before deleting rows) goes through
   `binaTell` / `binaAsk` — the table has no toast of its own and no browser dialog.

   ⚠ Ports three hard-won RevoGrid fixes — do not remove:
   (1) afterfocus carries the column key at detail.column.prop (not detail.prop);
   (2) replacing el.source resets scrollLeft → re-anchor by distance-from-
       reading-start across every assignment;
   (3) PHANTOM afteredit: Enter-commit + an immediate outside click re-saves the
       dying editor's EMPTY value against the newly-focused NEXT row — honored
       only for the cell whose editor actually opened (beforeeditstart), and
       clearFocus() (which cancels silently) runs before every source swap.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const ROW_COMFORT = 44;
  const ROW_COMPACT = 34;
  const stop = (e) => e.stopPropagation();

  // ── helpers (same exports as the React wrapper) ────────────────────────────
  const escapeHtml = (v) =>
    String(v == null ? '' : v).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const pillHtml = (text, kind) =>
    text == null || text === ''
      ? ''
      : '<span class="pill ' + (kind || 'muted') + '">' + escapeHtml(text) + '</span>';

  const fmtCurrency = (v) =>
    v == null || v === ''
      ? ''
      : Number(v).toLocaleString('he-IL', { style: 'currency', currency: 'ILS' });

  const fmtDate = (v) => {
    if (!v) return '';
    const d = new Date(String(v));
    return isNaN(d.getTime()) ? String(v) : d.toLocaleDateString('he-IL');
  };

  // Hebrew localization for RevoGrid's filter panel
  const FILTER_CONFIG = {
    localization: {
      captions: {
        title: 'סינון לפי', save: 'החל', reset: 'איפוס', ok: 'אישור', cancel: 'ביטול',
        add: 'הוסף תנאי', placeholder: 'ערך…', and: 'וגם', or: 'או',
        filterCondition: 'תנאי סינון', removeFilter: 'הסר סינון', reorderFilter: 'סדר מחדש',
      },
      filterNames: {
        none: 'ללא', empty: 'ריק', notEmpty: 'לא ריק', eq: 'שווה ל', notEq: 'שונה מ',
        begins: 'מתחיל ב', contains: 'מכיל', notContains: 'לא מכיל',
        eqN: '= (מספר)', neqN: '≠ (מספר)', gt: 'גדול מ', gte: 'גדול/שווה',
        lt: 'קטן מ', lte: 'קטן/שווה',
      },
    },
  };

  // ── per-table UI prefs (localStorage, never critical) ─────────────────────
  function loadPrefs(tableId) {
    if (!tableId) return { sizes: {} };
    try {
      return Object.assign({ sizes: {} }, JSON.parse(localStorage.getItem('bt:' + tableId) || '{}'));
    } catch (e) { return { sizes: {} }; }
  }
  function savePrefs(tableId, patch) {
    if (!tableId) return;
    try {
      localStorage.setItem('bt:' + tableId, JSON.stringify(Object.assign(loadPrefs(tableId), patch)));
    } catch (e) { /* prefs just don't persist */ }
  }

  // ── RevoGrid dist loader (vendored next to this file) ─────────────────────
  let distPromise = null;
  function loadDist(base) {
    if (distPromise) return distPromise;
    if (customElements.get('revo-grid')) return (distPromise = Promise.resolve());
    if (!base) {
      const self = document.querySelector('script[src*="bina-table.js"]');
      base = self ? self.src.replace(/bina-table\.js.*$/, '') : '';
    }
    const s = document.createElement('script');
    s.type = 'module';
    s.src = base + 'revo-grid/revo-grid.esm.js';
    document.head.appendChild(s);
    distPromise = customElements.whenDefined('revo-grid');
    return distPromise;
  }

  // minimal CSV parser (quotes, commas, newlines) for onImportRows
  function parseCsv(text) {
    const rows = []; let row = [], cur = '', inQ = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (inQ) {
        if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
        else cur += ch;
      } else if (ch === '"') inQ = true;
      else if (ch === ',') { row.push(cur); cur = ''; }
      else if (ch === '\n' || ch === '\r') {
        if (ch === '\r' && text[i + 1] === '\n') i++;
        row.push(cur); cur = '';
        if (row.length > 1 || row[0] !== '') rows.push(row);
        row = [];
      } else cur += ch;
    }
    row.push(cur);
    if (row.length > 1 || row[0] !== '') rows.push(row);
    return rows;
  }

  function h_(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }

  // The grid's own controls are DRAWN. A character is whatever the reader's font has for it, and
  // « ‹ › » are punctuation — which is how a reader hears them. One maker: the plus, and the four
  // shapes of the pager, drawn for a page that reads left to right and turned by the stylesheet
  // where it reads right to left (the characters were mirrored by the text direction; a path is not).
  const ICO = { plus: 'M5 12h14M12 5v14', first: 'm11 17-5-5 5-5M18 17l-5-5 5-5', prev: 'm15 18-6-6 6-6',
                next: 'm9 18 6-6-6-6', last: 'm6 17 5-5-5-5M13 17l5-5-5-5' };
  function ico_(name) {
    const ns = 'http://www.w3.org/2000/svg', s = document.createElementNS(ns, 'svg'), d = document.createElementNS(ns, 'path');
    s.setAttribute('class', 'bt-ico'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
    d.setAttribute('d', ICO[name]); s.appendChild(d);
    return s;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  function create(container, props) {
    const p = Object.assign({
      columns: [], data: [], rowKey: 'id', tableId: null, loading: false,
      onEdit: null, onAddRow: null, onDeleteRow: null, onImportRows: null,
      onDeleteRows: null, selectable: undefined, addLabel: 'שורה',
      searchable: true, searchPlaceholder: 'חיפוש בטבלה…', exportable: true,
      pageSize: null, onRowClick: null, quickFilters: null, columnPicker: undefined,
      actions: null, mode: 'client', rowCount: null, onState: null, height: 520,
      theme: 'compact', distBase: null,
      emptyText: 'אין רשומות עדיין.',
      noMatchText: 'לא נמצאו רשומות תואמות — נסו חיפוש אחר או נקו את הסינון.',
    }, props);

    const server = p.mode === 'server';
    const withSelection = p.selectable != null ? p.selectable : !!p.onDeleteRows;
    const prefs0 = loadPrefs(p.tableId);

    // ── state ──
    const st = {
      q: '', page: 1,
      pageSizePref: prefs0.pageSize || null,
      hiddenKeys: prefs0.hidden || p.columns.filter((c) => c.hidden).map((c) => c.key),
      activeQF: null,
      sort: null,          // {key, dir} — the wrapper OWNS sorting (see below)
      rowSize: prefs0.compact ? ROW_COMPACT : ROW_COMFORT,
      sel: new Set(),
      availW: null,
      ready: false,
      destroyed: false,
      focusRow: null,
      editCell: null,          // phantom-afteredit guard
      importing: false,
    };
    let pageView = [];         // pristine rows of the current page (parent data)
    let grid = null;           // the <revo-grid> element
    let searchTimer = 0, anchorRaf = 0, paintRaf = 0;
    let ro = null;

    const colByKey = new Map();
    function reindexCols() {
      colByKey.clear();
      p.columns.forEach((c) => colByKey.set(c.key, c));
    }
    reindexCols();

    // ── skeleton chrome (built once; parts updated in place) ──────────────────
    const card = h_('div', 'bt-card' + (p.onRowClick ? ' bt-rowclick' : ''));
    const chipsRow = h_('div', 'bt-chipsrow'); chipsRow.setAttribute('role', 'tablist');
    const toolbar = h_('div', 'bt-toolbar');
    const search = h_('input', 'bt-search');
    search.placeholder = p.searchPlaceholder;
    search.setAttribute('aria-label', 'חיפוש בטבלה');
    const selCount = h_('span', 'bt-selcount');
    const btnDelSel = h_('button', 'bt-btn sm ghost danger', 'מחק נבחרות');
    const btnClearSel = h_('button', 'bt-btn sm ghost', 'נקה בחירה');
    const btnSelAll = h_('button', 'bt-btn sm ghost', 'בחר הכל');
    // The selection's controls and «בחר הכל» stand in ONE place of one size: both are laid in the same
    // cell (.bt-selzone) and the one that is not said is hidden, not removed. Removed, the three that
    // replace the one took a new line of a toolbar that wraps, and the first tick moved every row down
    // under the finger that had made it.
    const selZone = h_('span', 'bt-selzone'), selOn = h_('span'), selOff = h_('span');
    selOn.append(selCount, btnDelSel, btnClearSel); selOff.append(btnSelAll); selZone.append(selOn, selOff);
    const spacer = h_('span', 'bt-spacer');
    const btnDensity = h_('button', 'bt-btn sm ghost'); btnDensity.title = 'צפיפות שורות';
    const colpick = h_('span', 'bt-colpick');
    const btnPicker = h_('button', 'bt-btn sm ghost');
    const pickerMenu = h_('span', 'bt-colpick-menu'); pickerMenu.style.display = 'none';
    colpick.append(btnPicker, pickerMenu);
    const btnExport = h_('button', 'bt-btn sm ghost', 'ייצוא'); btnExport.title = 'ייצוא CSV (נפתח באקסל)';
    const fileInput = h_('input'); fileInput.type = 'file'; fileInput.accept = '.csv,.xlsx,.xls'; fileInput.style.display = 'none';
    const btnImport = h_('button', 'bt-btn sm ghost', 'ייבוא'); btnImport.title = 'ייבוא שורות מקובץ CSV / Excel';
    const btnDelRow = h_('button', 'bt-btn sm ghost', 'מחק שורה'); btnDelRow.title = 'מחק את השורה שבמיקוד';
    const btnAdd = h_('button', 'bt-btn sm bt-add'), addText = h_('span', null, p.addLabel);
    btnAdd.append(ico_('plus'), addText);
    // The engine tints every cell that cannot be edited. Beside cells that can, that is information;
    // in a table where nothing can be edited it painted the whole body grey — a list that read as
    // switched off (the machine screen's services, 2026-10-07).
    const wrap = h_('div', 'bina-table' + (p.columns.some((c) => c.editable) ? '' : ' bt-readonly'));
    wrap.style.cssText = 'height:' + p.height + 'px;position:relative';
    const gridBox = h_('div'); gridBox.style.cssText = 'visibility:hidden;height:100%';
    const loadingEl = h_('div', 'bt-loading');
    loadingEl.append(h_('span', 'bt-spinner'), document.createTextNode(' טוען נתונים…'));
    const emptyEl = h_('div', 'bt-empty');
    const foot = h_('div', 'bt-foot');
    const countEl = h_('span', 'bt-count num');
    const pagerEl = h_('span', 'bt-pager');
    const footHint = h_('span', 'bt-foot-hint', 'גלילה חופשית — כל הרשומות זמינות');
    foot.append(countEl, pagerEl, footHint);

    // IN A NARROW CARD — a phone, a small window — what is done to ROWS stays in sight (the search, the
    // selection, «הוסף») and what is done to the TABLE goes behind one control. The toolbar wrapped instead:
    // five lines of it, and under them one row of the table on a phone. The card's own measured width decides
    // (`bt-narrow`, at boot); wide, `.bt-tools` is not a box at all and nothing moved.
    const btnMore = h_('button', 'bt-btn sm ghost bt-more', 'עוד');
    btnMore.title = 'כלי הטבלה: צפיפות, עמודות, ייצוא, ייבוא'; btnMore.setAttribute('aria-expanded', 'false');
    const tools = h_('span', 'bt-tools');
    tools.append(btnDensity, colpick, btnExport, fileInput, btnImport, btnDelRow);
    btnMore.addEventListener('click', () => btnMore.setAttribute('aria-expanded', String(tools.classList.toggle('open'))));
    toolbar.append(search, selZone, spacer, btnMore, tools, btnAdd);
    wrap.append(gridBox, loadingEl, emptyEl);
    card.append(chipsRow, toolbar, wrap, foot);
    container.appendChild(card);

    // What the table says and asks, it says and asks through the office's notice and question
    // (`binaTell` / `binaAsk`, bina-ask.js): a page that carries the table carries that block too.
    // The table has no toast and no dialog of its own.
    function pushToast(kind, text, undo) {
      binaTell(text, kind, undo ? { ms: 6000, act: ['ביטול', undo] } : 6000);
    }

    // ── derived data ──
    // numeric-aware, Hebrew-locale-aware value comparator
    function defaultCompare(a, b) {
      const ae = a == null || a === '', be = b == null || b === '';
      if (ae && be) return 0;
      if (ae) return -1;
      if (be) return 1;
      const na = Number(a), nb = Number(b);
      if (!isNaN(na) && !isNaN(nb)) return na - nb;
      return String(a).localeCompare(String(b), 'he', { numeric: true, sensitivity: 'base' });
    }
    function view() {
      if (server) return p.data;
      const qf = (p.quickFilters || []).find((f) => f.key === st.activeQF);
      let rows = qf ? p.data.filter((r) => qf.fn(r)) : p.data;
      const s = st.q.trim().toLowerCase();
      if (s) rows = rows.filter((r) =>
        p.columns.some((c) => String(r[c.key] == null ? '' : r[c.key]).toLowerCase().includes(s)));
      // the wrapper owns client sorting (engine sort is cancelled): it must
      // cover the WHOLE view (engine-sort would only order the current page
      // slice) and survive setData() live refreshes (engine sort state dies
      // with every source replacement — verified on the machine dashboard)
      if (st.sort) {
        const c = colByKey.get(st.sort.key);
        const dir = st.sort.dir === 'desc' ? -1 : 1;
        const key = st.sort.key;
        rows = rows.slice().sort((a, b) =>
          (c && c.compare ? c.compare(a, b) : defaultCompare(a[key], b[key])) * dir);
      }
      return rows;
    }
    function effPageSize() { return st.pageSizePref || p.pageSize || null; }
    function totalCount() { return server ? (p.rowCount != null ? p.rowCount : p.data.length) : view().length; }
    function pageCount() {
      const ps = effPageSize();
      return ps ? Math.max(1, Math.ceil(totalCount() / ps)) : 1;
    }
    function safePage() { return Math.min(st.page, pageCount()); }

    function emitState(debounceMs) {
      if (!server || !p.onState) return;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        p.onState({ page: safePage(), pageSize: effPageSize(), search: st.q, sort: st.sort });
      }, debounceMs || 0);
    }

    // What a column's header needs to show its whole label: the label at the header's weight, the
    // cell's padding (2 × 15, and 2 for the heavier sorted state), and the sort mark (12) and the
    // filter button (24) it carries. Measured on the machine screen, 2026-10-07: 66px of every
    // header cell was not label, so «סטטוס» at its declared 100px read «סט…».
    let headCtx = null;
    function headNeed(c) {
      if (!headCtx) {
        headCtx = document.createElement('canvas').getContext('2d');
        headCtx.font = '700 12px ' + getComputedStyle(container).fontFamily;
      }
      return Math.ceil(headCtx.measureText(c.label || '').width) + 32
        + (c.sortable !== false ? 12 : 0) + (c.filter !== false ? 24 : 0);
    }

    // ── columns for the engine (THE RTL STRATEGY: reverse for the LTR engine) ─
    function buildRevoColumns() {
      const saved = loadPrefs(p.tableId).sizes;
      const manual = !!loadPrefs(p.tableId).manual;
      const visible = p.columns.filter((c) => st.hiddenKeys.indexOf(c.key) < 0);
      // a declared width never cuts its own header; a width a person dragged (`saved`) is theirs
      const base = visible.map((c) => saved[c.key] || Math.max(c.width || 160, headNeed(c)));
      const selW = withSelection ? 44 : 0;
      const actW = p.actions && p.actions.length ? Math.max(44, p.actions.length * 40 + 12) : 0;
      const total = base.reduce((a, b) => a + b, 0);
      const fill = st.availW ? st.availW - selW - actW : 0;
      const factor = !manual && fill > 0 && total > 0 && total < fill ? fill / total : 1;

      const mapped = visible.map((c, i) => {
        const def = {
          prop: c.key, name: c.label, size: Math.floor(base[i] * factor),
          sortable: c.sortable !== false, readonly: !c.editable, filter: c.filter !== false,
          // custom sort order (dates in dd/mm/yyyy, status ranks…) — column
          // option `compare(rowA, rowB)`; RevoGrid calls it with the row models
          ...(c.compare ? { cellCompare: (prop, a, b) => c.compare(a, b) } : {}),
          cellProperties: () => ({
            class: Object.assign(
              c.align && c.align !== 'start' ? { ['bt-align-' + c.align]: true } : {},
              c.editable ? { 'bt-editable': true } : {}),
          }),
        };
        if (c.html) {
          def.cellTemplate = (h, pr) => h('span', {
            class: 'bt-htmlcell',
            innerHTML: c.html((pr.model || {})[String(pr.prop)], pr.model || {}),
          });
        } else if (c.format) {
          def.cellTemplate = (h, pr) => {
            const out = c.format((pr.model || {})[String(pr.prop)], pr.model || {});
            return out === '' ? h('span', { class: 'bt-null' }, '—') : out;
          };
        } else {
          def.cellTemplate = (h, pr) => {
            const v = (pr.model || {})[String(pr.prop)];
            if (v == null || v === '') return h('span', { class: 'bt-null' }, '—');
            return typeof v === 'object' ? JSON.stringify(v) : String(v);
          };
        }
        return def;
      });
      mapped.reverse(); // first configured column renders physically RIGHTMOST

      // per-row actions — physically LEFTMOST (the RTL reading end), my-docs'
      // entityTable convention (e.g. a delete button at the row's far edge)
      if (p.actions && p.actions.length) {
        mapped.unshift({
          prop: '__actions', name: '', size: actW,
          sortable: false, readonly: true, filter: false,
          cellProperties: () => ({ class: { 'bt-selcell': true } }),
          cellTemplate: (h, pr) => h('span', { class: 'bt-actcell' },
            p.actions.map((a) => h('button', {
              class: 'bt-act' + (a.kind ? ' ' + a.kind : ''),
              title: a.title || a.label,
              innerHTML: a.label,
              onClick: (e) => {
                e.stopPropagation();
                a.onClick(pr.model || {});
              },
            }))),
        });
      }
      if (withSelection) {
        // appended after the reverse → far RIGHT beside the row numbers
        mapped.push({
          prop: '__sel', name: '', size: 44,
          sortable: false, readonly: true, filter: false,
          cellProperties: () => ({ class: { 'bt-selcell': true } }),
          cellTemplate: (h, pr) => {
            const id = String((pr.model || {})[p.rowKey] == null ? '' : (pr.model || {})[p.rowKey]);
            return h('input', {
              type: 'checkbox', class: 'bt-selbox',
              checked: st.sel.has(id),
              // the box keeps the whole press. Passed on, it moved the grid's focus to this cell, and on a
              // phone the grid draws its drag handle (30px) over the box before the press ends: the first
              // tap ticked nothing, and a ticked box under the handle could not be unticked
              onMouseDown: stop, onTouchStart: stop,
              onClick: (e) => {
                e.stopPropagation();
                if (st.sel.has(id)) st.sel.delete(id); else st.sel.add(id);
                updateToolbar();
              },
            });
          },
        });
      }
      return mapped;
    }

    // ── source assignment with scroll re-anchor + silent editor cancel ────────
    function vpOf() {
      if (!grid) return null;
      return [...grid.querySelectorAll('revogr-viewport-scroll')]
        .sort((a, b) => b.clientWidth - a.clientWidth)[0] || null;
    }
    function assignSource() {
      if (!grid) return;
      const source = pageView.map((r) => Object.assign({}, r)); // mutation containment
      const vp = vpOf();
      const fromStart = vp ? Math.max(0, vp.scrollWidth - vp.clientWidth - vp.scrollLeft) : 0;
      let tries = 0;
      const apply = () => {
        grid.source = source;
        cancelAnimationFrame(anchorRaf);
        anchorRaf = requestAnimationFrame(function tick() {
          const v = vpOf();
          if (v) {
            const max = v.scrollWidth - v.clientWidth;
            const want = Math.max(0, max - fromStart);
            if (max > 0 && Math.abs(v.scrollLeft - want) > 1) v.scrollLeft = want;
          }
          if (++tries < 8) anchorRaf = requestAnimationFrame(tick);
        });
      };
      // never swap source under an open editor (phantom-afteredit source №1)
      if (grid.querySelector('revogr-edit') && typeof grid.clearFocus === 'function') {
        grid.clearFocus().then(apply, apply);
      } else apply();
    }

    // ── the grid element + event pipeline ──────────────────────────────────────
    function buildGrid() {
      grid = document.createElement('revo-grid');
      grid.theme = p.theme;
      grid.resize = true;
      grid.range = true;
      grid.rowHeaders = true;
      grid.canMoveColumns = true;
      grid.readonly = false;
      grid.rowSize = st.rowSize;
      grid.filter = FILTER_CONFIG;
      grid.setAttribute('role', 'grid');
      grid.setAttribute('aria-label', 'טבלת נתונים');
      gridBox.appendChild(grid);

      let lastPointer = 0;
      grid.addEventListener('pointerdown', () => { lastPointer = performance.now(); });

      grid.addEventListener('beforeeditstart', (e) => {
        const d = e.detail || {};
        if (d.prop != null && typeof d.rowIndex === 'number')
          st.editCell = { rowIndex: d.rowIndex, prop: String(d.prop) };
      });

      grid.addEventListener('afteredit', (e) => {
        const d = e.detail || {};
        if (!p.onEdit || d.prop == null || typeof d.rowIndex !== 'number') return;
        const key = String(d.prop);
        const opened = st.editCell;
        st.editCell = null;
        if (!opened || opened.prop !== key || opened.rowIndex !== d.rowIndex) {
          assignSource(); // phantom save — repaint pristine data, persist nothing
          return;
        }
        const row = pageView[d.rowIndex];
        const id = row ? row[p.rowKey] : undefined;
        const prev = row ? row[key] : undefined;
        if (String(d.val == null ? '' : d.val) === String(prev == null ? '' : prev)) return;

        const col = colByKey.get(key);
        const err = col && col.validate ? col.validate(d.val) : null;
        if (err) {
          assignSource(); // fresh copies of pristine data = the cell reverts
          pushToast('bad', (col && col.label || key) + ': ' + err);
          return;
        }
        Promise.resolve(p.onEdit(id, key, d.val))
          .then(() => {
            if (row) row[key] = d.val; // keep parent data in step (vanilla owns it)
            pushToast('ok', 'נשמר', () => {
              Promise.resolve(p.onEdit(id, key, prev))
                .then(() => { if (row) row[key] = prev; assignSource(); pushToast('ok', 'השינוי בוטל'); })
                .catch(() => pushToast('bad', 'ביטול השינוי נכשל'));
            });
          })
          .catch((ex) => {
            assignSource(); // rollback — never show a value the DB rejected
            pushToast('bad', ex && ex.message ? ex.message : 'השמירה נכשלה');
          });
      });

      grid.addEventListener('afterfocus', (e) => {
        const d = e.detail || {};
        if (typeof d.rowIndex !== 'number') return;
        st.focusRow = d.rowIndex;
        // afterfocus has no top-level prop — the column key is at column.prop
        const prop = d.prop != null ? d.prop : (d.column || {}).prop;
        const ec = st.editCell;
        if (ec && (ec.rowIndex !== d.rowIndex || ec.prop !== prop)) st.editCell = null;
        if (p.onRowClick && prop !== '__sel' && prop !== '__actions'
            && performance.now() - lastPointer < 400) {
          const row = pageView[d.rowIndex];
          if (row) p.onRowClick(row, prop != null ? String(prop) : undefined);
        }
      });

      // the wrapper owns ALL sorting: engine sort is cancelled in both modes
      // (client: whole-view sort in view(); server: the parent refetches).
      // Cycle asc → desc → off on header click.
      grid.addEventListener('beforesortingapply', (e) => {
        e.preventDefault();
        const key = ((e.detail || {}).column || {}).prop;
        if (!key || key === '__sel' || key === '__actions') return;
        const cur = st.sort;
        st.sort = !cur || cur.key !== key
          ? { key: String(key), dir: 'asc' }
          : cur.dir === 'asc' ? { key: String(key), dir: 'desc' } : null;
        st.page = 1;
        if (server) { emitState(0); sync(); } else sync();
      });

      grid.addEventListener('aftercolumnresize', (e) => {
        const d = e.detail || {};
        if (!p.tableId) return;
        const sizes = Object.assign({}, loadPrefs(p.tableId).sizes);
        Object.values(d).forEach((it) => {
          if (it && it.prop != null && typeof it.size === 'number') sizes[String(it.prop)] = it.size;
        });
        savePrefs(p.tableId, { sizes: sizes, manual: true });
      });

      grid.addEventListener('aftersortingapply', () => {
        requestAnimationFrame(() => requestAnimationFrame(() => {
          grid.querySelectorAll('[class*=rgHeaderCell]').forEach((hd) => {
            const cls = hd.className || '';
            hd.setAttribute('aria-sort',
              /\basc\b/.test(cls) ? 'ascending' : /\bdesc\b/.test(cls) ? 'descending' : 'none');
          });
        }));
      });

      // ORCHESTRATED FIRST PAINT: invisible until pinned at the RTL reading
      // start (scroll max in the LTR engine) for 3 stable frames; then reveal.
      // A frame counts only once the engine has LAID OUT (a viewport with a width,
      // and header cells). The engine is loaded on demand, and until it arrived
      // there was no viewport at all — which used to count as "stable": the grid
      // was revealed un-pinned, at the reading END, and every later source swap
      // faithfully kept it there. Measured on the machine page, 2026-10-06:
      // revealed at 1083ms, overflow at 1140ms, scrollLeft 0 of 332 for good —
      // the service's name hidden at every width, and on a phone every column
      // but the last.
      let stable = 0, tries = 0;
      const tick = () => {
        if (st.destroyed) return;
        const vp = vpOf();
        const laid = !!(vp && vp.clientWidth > 0 && grid.querySelector('[class*=rgHeaderCell]'));
        const max = laid ? vp.scrollWidth - vp.clientWidth : 0;
        if (laid && max > 0 && vp.scrollLeft < max - 1) { vp.scrollLeft = max; stable = 0; }
        else if (laid) stable++;
        tries++;
        if (stable >= 3 || tries > 600) {
          st.ready = true;
          gridBox.style.visibility = 'visible';
          return;
        }
        paintRaf = requestAnimationFrame(tick);
      };
      paintRaf = requestAnimationFrame(tick);
    }

    // ── chrome updaters ──
    function updateChips() {
      chipsRow.innerHTML = '';
      if (!p.quickFilters || !p.quickFilters.length) { chipsRow.style.display = 'none'; return; }
      chipsRow.style.display = '';
      const mk = (key, label, count) => {
        const b = h_('button', 'bt-chip' + ((st.activeQF || null) === key ? ' active' : ''));
        b.append(document.createTextNode(label + ' '), h_('span', 'num', count == null ? '' : String(count)));
        b.addEventListener('click', () => {
          st.activeQF = st.activeQF === key ? null : key;
          st.page = 1;
          sync();
        });
        return b;
      };
      chipsRow.appendChild(mk(null, 'הכל', p.data.length));
      p.quickFilters.forEach((f) => {
        chipsRow.appendChild(mk(f.key, f.label, server ? null : p.data.filter((r) => f.fn(r)).length));
      });
    }

    function updatePicker() {
      const enabled = p.columnPicker != null
        ? p.columnPicker
        : (p.columns.some((c) => c.hidden) || st.hiddenKeys.length > 0);
      colpick.style.display = enabled ? '' : 'none';
      if (!enabled) return;
      btnPicker.textContent =
        'עמודות (' + (p.columns.length - st.hiddenKeys.length) + '/' + p.columns.length + ')';
      pickerMenu.innerHTML = '';
      p.columns.forEach((c) => {
        const lab = h_('label', 'bt-colpick-item');
        const cb = h_('input'); cb.type = 'checkbox';
        cb.checked = st.hiddenKeys.indexOf(c.key) < 0;
        cb.addEventListener('change', () => {
          const i = st.hiddenKeys.indexOf(c.key);
          if (i >= 0) st.hiddenKeys.splice(i, 1); else st.hiddenKeys.push(c.key);
          savePrefs(p.tableId, { hidden: st.hiddenKeys });
          sync();
        });
        lab.append(cb, h_('span', null, c.label));
        pickerMenu.appendChild(lab);
      });
    }

    function updateToolbar() {
      const hasSel = st.sel.size > 0;
      search.style.display = p.searchable ? '' : 'none';
      selZone.style.display = withSelection ? '' : 'none';
      selOn.className = hasSel ? '' : 'off';
      selOff.className = !hasSel && view().length > 1 ? '' : 'off';
      // (one is said as one: «1 נבחרו» stood here — and in as few letters as any other count: a longer sentence
      //  for one widened the zone, sent «עוד» to a line of its own in a narrow card, and the rows moved 39px
      //  under the finger that had ticked one. The number is its own token, and the element's `data-n`.)
      selCount.dataset.n = st.sel.size;
      selCount.replaceChildren(st.sel.size === 1 ? 'נבחרה ' : 'נבחרו ', h_('span', 'num', st.sel.size));
      btnDelSel.style.display = p.onDeleteRows ? '' : 'none';
      btnDensity.textContent = st.rowSize === ROW_COMFORT ? 'צפוף' : 'מרווח';
      btnExport.style.display = p.exportable ? '' : 'none';
      btnImport.style.display = p.onImportRows ? '' : 'none';
      btnImport.textContent = st.importing ? 'מייבא…' : 'ייבוא';
      btnImport.disabled = st.importing;
      btnDelRow.style.display = p.onDeleteRow ? '' : 'none';
      btnAdd.style.display = p.onAddRow ? '' : 'none';
      addText.textContent = p.addLabel;
      toolbar.style.display =
        (p.searchable || p.onAddRow || p.onDeleteRow || withSelection || p.exportable) ? '' : 'none';
    }

    function updateFoot() {
      const total = totalCount();
      countEl.textContent =
        (total === 1 ? 'רשומה אחת' : total.toLocaleString('he-IL') + ' רשומות') +
        (!server && st.q && view().length !== p.data.length
          ? ' מתוך ' + p.data.length.toLocaleString('he-IL') : '');
      const ps = effPageSize();
      pagerEl.innerHTML = '';
      pagerEl.style.display = ps ? '' : 'none';
      footHint.style.display = ps ? 'none' : '';
      if (!ps) return;
      const lab = h_('label', 'bt-pagesize', 'שורות לעמוד ');
      const sel = h_('select');
      [10, 25, 50, 100].forEach((n) => {
        const o = h_('option', null, String(n)); o.value = String(n);
        if (n === ps) o.selected = true;
        sel.appendChild(o);
      });
      sel.addEventListener('change', () => {
        st.pageSizePref = Number(sel.value) || 25;
        st.page = 1;
        savePrefs(p.tableId, { pageSize: st.pageSizePref });
        server ? (emitState(0), sync()) : sync();
      });
      lab.appendChild(sel);
      const pg = safePage(), pc = pageCount();
      const btn = (shape, say, dis, go) => {
        const b = h_('button', 'bt-pgbtn');
        b.type = 'button'; b.title = say; b.setAttribute('aria-label', say); b.appendChild(ico_(shape));
        b.disabled = dis;
        b.addEventListener('click', () => { st.page = go(); server ? (emitState(0), sync()) : sync(); });
        return b;
      };
      // the four buttons and the page they frame are ONE piece: in a narrow footer the rows-per-page
      // choice takes a line of its own, and the buttons are never split between two lines
      const nav = h_('span', 'bt-pgnav');
      nav.append(
        btn('first', 'העמוד הראשון', pg <= 1, () => 1),
        btn('prev', 'העמוד הקודם', pg <= 1, () => Math.max(1, pg - 1)),
        h_('span', 'bt-pageinfo num', 'עמוד ' + pg + ' מתוך ' + pc),
        btn('next', 'העמוד הבא', pg >= pc, () => Math.min(pc, pg + 1)),
        btn('last', 'העמוד האחרון', pg >= pc, () => pc));
      pagerEl.append(lab, nav);
    }

    // header sort indicators + aria-sort — painted by US (the engine never
    // applies sorting, so its own .asc/.desc classes never appear). Header DOM
    // order matches the mapped columns order.
    let lastMapped = [];
    let indRaf = 0;
    function paintSortIndicators() {
      // re-assert over several frames: RevoGrid re-renders its headers
      // asynchronously after a columns/source assignment and wipes classes.
      // Headers are matched by LABEL text — column virtualization renders only
      // a subset of header cells, so index math misidentifies them.
      const sc = st.sort ? colByKey.get(st.sort.key) : null;
      const sortLabel = sc ? sc.label : null;
      let frames = 0;
      cancelAnimationFrame(indRaf);
      indRaf = requestAnimationFrame(function tick() {
        if (st.destroyed || !grid) return;
        const heads = [...grid.querySelectorAll('revogr-header [class*=rgHeaderCell]')];
        heads.forEach((hd) => {
          const hc = hd.querySelector('.header-content');
          const text = hc && hc.textContent ? hc.textContent.trim() : '';
          const active = !!(sortLabel && text === sortLabel);
          hd.classList.toggle('asc', active && st.sort.dir === 'asc');
          hd.classList.toggle('desc', active && st.sort.dir === 'desc');
          hd.setAttribute('aria-sort',
            active ? (st.sort.dir === 'asc' ? 'ascending' : 'descending') : 'none');
          const ind = hd.querySelector('.sort-indicator i');
          if (ind) {
            const want = active ? st.sort.dir : 'sort-off';
            if (ind.className !== want) ind.className = want;
          }
        });
        if (++frames < 12) indRaf = requestAnimationFrame(tick);
      });
    }

    // ── main sync: recompute view + push to the grid + refresh chrome ─────────
    function sync() {
      if (st.destroyed || !grid) return;
      const v = view();
      const ps = effPageSize();
      pageView = server || !ps ? v : v.slice((safePage() - 1) * ps, safePage() * ps);
      lastMapped = buildRevoColumns();
      grid.columns = lastMapped;
      grid.rowSize = st.rowSize;
      paintSortIndicators();
      grid.setAttribute('aria-rowcount', String(v.length));
      grid.setAttribute('aria-colcount', String(p.columns.length));
      assignSource();
      loadingEl.style.display = p.loading ? '' : 'none';
      emptyEl.style.display = !p.loading && v.length === 0 ? '' : 'none';
      emptyEl.textContent = p.data.length === 0 ? p.emptyText : p.noMatchText;
      updateChips();
      updatePicker();
      updateToolbar();
      updateFoot();
    }

    // ── toolbar wiring ──
    search.addEventListener('input', () => {
      st.q = search.value;
      st.page = 1;
      if (server) { emitState(350); updateFoot(); }
      else sync();
    });
    btnDensity.addEventListener('click', () => {
      st.rowSize = st.rowSize === ROW_COMFORT ? ROW_COMPACT : ROW_COMFORT;
      savePrefs(p.tableId, { compact: st.rowSize === ROW_COMPACT });
      sync();
    });
    btnPicker.addEventListener('click', () => {
      pickerMenu.style.display = pickerMenu.style.display === 'none' ? 'block' : 'none';
    });
    pickerMenu.addEventListener('mouseleave', () => { pickerMenu.style.display = 'none'; });
    btnSelAll.addEventListener('click', () => {
      st.sel = new Set(view().map((r) => String(r[p.rowKey])));
      sync();
    });
    btnClearSel.addEventListener('click', () => { st.sel = new Set(); sync(); });
    btnDelSel.addEventListener('click', async () => {
      if (!p.onDeleteRows || st.sel.size === 0) return;
      const ids = [...st.sel];
      if (!await binaAsk({ title: 'למחוק ' + ids.length + ' שורות נבחרות?', ok: 'מחיקה', danger: true })) return;
      const res = await p.onDeleteRows(ids);
      st.sel = new Set();
      pushToast(res.fail ? 'bad' : 'ok',
        'נמחקו ' + res.ok + (res.fail ? ', ' + res.fail + ' נכשלו' : ''));
      sync();
    });
    btnDelRow.addEventListener('click', () => {
      const i = st.focusRow;
      if (i == null) return pushToast('warn', 'בחרו תא בשורה למחיקה');
      const row = pageView[i];
      const id = row ? row[p.rowKey] : null;
      if (id != null && p.onDeleteRow) p.onDeleteRow(id);
    });
    btnAdd.addEventListener('click', () => { if (p.onAddRow) p.onAddRow(); });

    btnExport.addEventListener('click', () => {
      const esc = (v) => {
        const s = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      };
      const v = view();
      const rows = st.sel.size > 0 ? v.filter((r) => st.sel.has(String(r[p.rowKey]))) : v;
      const lines = [p.columns.map((c) => esc(c.label)).join(',')]
        .concat(rows.map((r) => p.columns.map((c) => esc(r[c.key])).join(',')));
      const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = (p.tableId || 'table') + '.csv';
      a.click();
      URL.revokeObjectURL(a.href);
    });

    btnImport.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
      const f = fileInput.files && fileInput.files[0];
      if (!f || !p.onImportRows) return;
      st.importing = true; updateToolbar();
      try {
        let raw; // array of {header: value}
        if (/\.xlsx?$/i.test(f.name) && window.XLSX) {
          const wb = window.XLSX.read(await f.arrayBuffer());
          raw = window.XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: '' });
        } else if (/\.xlsx?$/i.test(f.name)) {
          throw new Error('קובצי Excel דורשים את ספריית XLSX — יש לייצא כ-CSV');
        } else {
          const cells = parseCsv(new TextDecoder('utf-8').decode(await f.arrayBuffer()).replace(/^﻿/, ''));
          const head = cells.shift() || [];
          raw = cells.map((rw) => {
            const o = {};
            head.forEach((hd, i) => { o[hd] = rw[i] == null ? '' : rw[i]; });
            return o;
          });
        }
        const byLabel = new Map(p.columns.map((c) => [c.label, c.key]));
        const keys = new Set(p.columns.map((c) => c.key));
        const rows = raw.map((r) => {
          const out = {};
          Object.entries(r).forEach(([hd, vv]) => {
            const k = keys.has(hd) ? hd : byLabel.get(hd);
            if (k && vv !== '') out[k] = vv;
          });
          return out;
        }).filter((r) => Object.keys(r).length > 0);
        if (!rows.length) { pushToast('warn', 'לא נמצאו שורות תואמות בקובץ'); return; }
        const res = await p.onImportRows(rows);
        pushToast(res.fail ? 'bad' : 'ok',
          'ייבוא: ' + res.ok + ' נוספו' + (res.fail ? ', ' + res.fail + ' נכשלו' : ''));
      } catch (e) {
        pushToast('bad', e && e.message ? e.message : 'הייבוא נכשל');
      } finally {
        st.importing = false; fileInput.value = ''; updateToolbar();
      }
    });

    // ── boot: measure, load the component, build, first sync ──────────────────
    // a card 520px wide or less (availW is its width less 54) keeps the table's own tools behind «עוד»
    const narrowed = () => card.classList.toggle('bt-narrow', st.availW <= 466);
    ro = new ResizeObserver(() => {
      const w = Math.max(0, Math.floor(wrap.getBoundingClientRect().width) - 54);
      if (w !== st.availW) { st.availW = w; narrowed(); if (grid) sync(); }
    });
    ro.observe(wrap);
    st.availW = Math.max(0, Math.floor(wrap.getBoundingClientRect().width) - 54);
    narrowed();

    loadDist(p.distBase).then(() => {
      if (st.destroyed) return;
      buildGrid();
      sync();
      if (server) emitState(0); // initial fetch signal
    });

    // ── public handle ──
    return {
      setData(rows, rowCount) {
        p.data = rows || [];
        if (rowCount != null) p.rowCount = rowCount;
        sync();
      },
      setLoading(b) { p.loading = !!b; if (grid) sync(); },
      update(patch) { Object.assign(p, patch); reindexCols(); if (grid) sync(); },
      getState() { return { page: safePage(), pageSize: effPageSize(), search: st.q, sort: st.sort }; },
      refresh() { if (grid) sync(); },
      clearSelection() { st.sel = new Set(); if (grid) sync(); },
      destroy() {
        st.destroyed = true;
        cancelAnimationFrame(anchorRaf);
        cancelAnimationFrame(paintRaf);
        clearTimeout(searchTimer);
        if (ro) ro.disconnect();
        card.remove();
      },
    };
  }

  window.BinaTable = {
    create: create,
    escapeHtml: escapeHtml,
    pillHtml: pillHtml,
    fmtCurrency: fmtCurrency,
    fmtDate: fmtDate,
    loadDist: loadDist,
  };
})();

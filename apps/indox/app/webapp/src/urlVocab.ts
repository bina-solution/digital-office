/** [url-is-the-selector 2026-08-24, owner order] The labeled drill-down URL params —
 *  ONE vocabulary shared by the writer (DashboardPage's links), the parser
 *  (DocumentBrowserPage) and the chip remover. The nav audit found these literals
 *  hand-typed in three unconnected places; adding a drill param is now one row here.
 *  Full param contract: ai/context/console-url-state.md rule 5. */
export const DRILL_PARAM: Record<string, string> = {
  STATUS: 'status',
  TYPE: 'type',
  COMPANY_ID: 'company',
  SOURCE_TYPE: 'source',
};

/** The dashboard's sentinel for the no-SOURCE_TYPE bucket — an empty column value cannot
 *  ride a query parameter, so it travels as this token and is parsed back into a real
 *  is-null clause. */
export const SOURCE_BLANK = '__blank__';

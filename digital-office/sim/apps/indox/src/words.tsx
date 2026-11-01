/* How INDOX's data READS is said by the service, with the data. Every column `GET /repos/<r>` serves carries
   its heading, and a column of a value domain (STATUS, TYPE, SOURCE_TYPE) carries each value's word and colour:
   the live app's catalog — apps/indox/blueprint/schema/display.json, "the one place a human writes how this
   app's data reads" — merged in by the server, and by the simulation's mock from the same file in the same way.
   The fork kept two maps of its own on the dashboard and none anywhere else: a column was headed by its name in
   the database («COMPANY_NAME»), a value shown as the database holds it («INVOICE» in the table, on a sync
   source's tag, in the type it may be given), and whatever the maps missed stood raw beside the Hebrew
   («MISSING», «RECEIPT»). The words have ONE owner; this file only hands on what was served and looks a word
   up in it. A value the catalog does not know reads as itself — never blank, never swallowed. */
import { createContext, ReactNode, useContext, useEffect, useState } from 'react';
import { api, ColumnDef } from './api';

export type Kind = 'ok' | 'warn' | 'bad' | 'muted';
type Columns = readonly ColumnDef[] | null | undefined;

/** the served column of that name */
export const columnOf = (cols: Columns, name: string): ColumnDef | undefined =>
  cols?.find((c) => c.name === name);

/** the word for one value of a column's domain */
export const wordOf = (col: ColumnDef | undefined, v: unknown): string =>
  String(col?.enum_values?.[String(v)]?.label ?? v ?? '');

/** …and its colour, where the domain's values carry one (STATUS does) */
export const kindOf = (col: ColumnDef | undefined, v: unknown): Kind | undefined =>
  col?.enum_values?.[String(v)]?.kind as Kind | undefined;

/* The columns of the instance in view, read once where the instance is known and handed to every screen under
   it: the dashboard's bars and a sync source's tag word a document's type without a table of their own in sight.
   null while they are being read. */
const Served = createContext<Columns>(null);
export const useColumns = (): Columns => useContext(Served);

export function ColumnsOf({ repo, children }: { repo: string | null; children: ReactNode }) {
  const [cols, setCols] = useState<Columns>(null);
  useEffect(() => {
    setCols(null);
    if (repo) api.getRepo(repo).then((r) => setCols(r.repo.columns)).catch(() => setCols([]));
  }, [repo]);
  return <Served.Provider value={cols}>{children}</Served.Provider>;
}

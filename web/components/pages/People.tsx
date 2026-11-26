"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Heading } from "@astryxdesign/core/Heading";
import { Link } from "@astryxdesign/core/Link";
import { Table, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useApi } from "@/lib/query";
import { filterQuery, useFilters, useSetParam } from "@/lib/filters";
import { fmt } from "@/lib/format";

type Col = { name: string; label: string; unit?: string; better?: string; group?: string; status?: string; description?: string; missing?: string[] };
type Cell = { value: number | null; ranked?: boolean; sample?: number | null; reason?: string | null };
type PRow = { person_id?: string | null; name: string; cells: Record<string, Cell | undefined> };
type Matrix = { columns: Col[]; rows: PRow[]; notes?: string[] };
type Line = Record<string, unknown> & { id: string; row: PRow };

const cellValue = (row: PRow, name: string): number | null => row.cells[name]?.value ?? null;

/** Sort people by a column; blanks next, then rows without a person id. */
export function sortRows(rows: PRow[], name: string, dir: "asc" | "desc"): PRow[] {
  if (!name) return rows;
  const sign = dir === "asc" ? 1 : -1;
  const people = rows.filter((r) => r.person_id);
  const unmapped = rows.filter((r) => !r.person_id);
  const present = people.filter((r) => cellValue(r, name) !== null);
  const absent = people.filter((r) => cellValue(r, name) === null);
  present.sort((a, b) => {
    const x = cellValue(a, name) as number;
    const y = cellValue(b, name) as number;
    return x < y ? -sign : x > y ? sign : 0;
  });
  return [...present, ...absent, ...unmapped];
}

export function People() {
  const filters = useFilters();
  const setParam = useSetParam();
  const search = useSearchParams();
  const includeInactive = filters.inactive === "1";
  const matrix = useApi("/api/people-matrix" + filterQuery(filters, { include_inactive: includeInactive ? "true" : "" }));
  const r = matrix.data as Matrix | undefined;

  const shown = (r?.columns ?? []).filter((c) => c.status === "ok");
  const waiting = (r?.columns ?? []).filter((c) => c.status === "waiting");
  const sortName = search.get("sort") ?? "impact_points";
  const sortCol = shown.find((c) => c.name === sortName);
  const sortDir: "asc" | "desc" = sortCol
    ? ((search.get("dir") ?? (sortCol.better === "lower" ? "asc" : "desc")) === "asc" ? "asc" : "desc")
    : "desc";

  const clickHeader = (col: Col) => {
    let dir = col.better === "lower" ? "asc" : "desc";
    if (sortCol?.name === col.name) dir = sortDir === "asc" ? "desc" : "asc";
    setParam("sort", col.name);
    setParam("dir", dir);
  };

  let body: React.ReactNode = null;
  if (matrix.error) body = <Banner status="error" title={(matrix.error as Error).message} />;
  else if (r) {
    const data: Line[] = sortRows(r.rows, sortCol?.name ?? "", sortDir).map((row, i) => ({ id: row.person_id ?? "row-" + i, row }));
    const columns: TableColumn<Line>[] = [
      {
        key: "person", header: "Person",
        renderCell: ({ row }) =>
          row.person_id
            ? <Link as={NextLink} href={"/person" + filterQuery(filters, { id: row.person_id })}>{row.name}</Link>
            : <Text>{row.name}</Text>,
      },
      ...shown.map((col): TableColumn<Line> => ({
        key: col.name, align: "end",
        header: (
          <Button variant="ghost" size="sm" label={col.label + (sortCol?.name === col.name ? (sortDir === "asc" ? " ▲" : " ▼") : "")}
            aria-sort={sortCol?.name === col.name ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
            onClick={() => clickHeader(col)} />
        ),
        renderCell: ({ row }) => {
          const cell = row.cells[col.name];
          if (!cell || cell.value === null || cell.value === undefined) return <span title={cell?.reason ?? undefined}><Text color="secondary">–</Text></span>;
          const sample = cell.sample === null || cell.sample === undefined ? undefined : "sample " + cell.sample;
          return <span title={cell.reason || sample}><Text color={cell.ranked ? "primary" : "secondary"}>{fmt(cell.value, col.unit)}</Text></span>;
        },
      })),
    ];
    body = (
      <VStack gap={2}>
        <Table<Line> data={data} columns={columns} idKey="id" density="compact" />
        {waiting.length > 0 && (
          <Text color="secondary">
            {"Not shown yet: " + waiting.map((c) => `${c.label} (waiting for ${(c.missing ?? []).join(", ")})`).join("; ")}
          </Text>
        )}
        {r.notes?.map((n) => <Text key={n} color="secondary">{n}</Text>)}
      </VStack>
    );
  }

  return (
    <VStack as="main" gap={3}>
      <Heading level={2}>People</Heading>
      <Text color="secondary">
        Impact is story points of completed tickets, split between the people whose code delivered them (Delivery) and whose reviews helped (Participation). Click a column to sort; click a name for the work behind the numbers.
      </Text>
      <CheckboxInput label="include inactive members" value={includeInactive} onChange={(checked) => setParam("inactive", checked ? "1" : "")} />
      {body}
    </VStack>
  );
}

"use client";

import { Link } from "@astryxdesign/core/Link";
import NextLink from "next/link";
import { Banner } from "@astryxdesign/core/Banner";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useApi } from "@/lib/query";
import { filterQuery, useFilters, useSetParam } from "@/lib/filters";
import { fmt, trendInfo } from "@/lib/format";

type Meta = { name: string; label: string; kind: string; group?: string; status?: string; missing?: string[]; description?: string };
type Row = {
  rank?: number | null; person_id?: string | null; name: string; ranked?: boolean; unranked_reason?: string | null;
  value: number | null; previous: number | null; trend: number | null; sample: number; confidence?: string | null;
};
type Result = {
  status?: string; missing?: string[]; error?: string; label: string; unit?: string; better?: string; rows: Row[];
  team?: { value: number | null; p85?: number; sample: number }; window: { label: string }; notes?: string[];
};

const GROUPS: [string, string][] = [
  ["impact", "Impact"], ["delivery", "Delivery"], ["participation", "Participation"], ["activity", "Activity (context)"],
];
const SOURCE_LABELS: Record<string, string> = {
  jira: "Jira", bitbucket: "Bitbucket", claude_usage: "Claude usage", links: "pull request links", confluence: "Confluence",
};
const sourceLabel = (n: string) => SOURCE_LABELS[n] ?? n.replace("_", " ");

type Line = Record<string, unknown> & { id: string; row: Row };

function RankTable({ r, teamSelected, filters }: { r: Result; teamSelected: boolean; filters: ReturnType<typeof useFilters> }) {
  const withConfidence = r.rows.some((row) => row.confidence);
  const data: Line[] = r.rows.map((row, i) => ({ id: row.person_id ?? "row-" + i, row }));
  const columns: TableColumn<Line>[] = [
    { key: "rank", header: "#", renderCell: ({ row }) => (row.rank ? String(row.rank) : "–") },
    {
      key: "person", header: "Person",
      renderCell: ({ row }) => (
        <>
          {row.person_id ? <Link as={NextLink} href={"/person" + filterQuery(filters, { id: row.person_id })}>{row.name}</Link> : <Text>{row.name}</Text>}
          {row.ranked || !row.person_id ? null : <Text color="secondary">{row.unranked_reason ? ` (unranked: ${row.unranked_reason})` : " (unranked)"}</Text>}
        </>
      ),
    },
    { key: "value", header: r.label, align: "end", renderCell: ({ row }) => fmt(row.value, r.unit) },
    { key: "previous", header: "Previous", align: "end", renderCell: ({ row }) => fmt(row.previous, r.unit) },
    {
      key: "trend", header: "Trend", align: "end",
      renderCell: ({ row }) => {
        const t = trendInfo(row.trend, r.better);
        return <Text color={t.kind === "good" ? "accent" : "primary"} data-kind={t.kind}>{t.text}</Text>;
      },
    },
    { key: "sample", header: "Sample", align: "end", renderCell: ({ row }) => String(row.sample) },
    ...(withConfidence ? [{ key: "confidence", header: "Confidence", renderCell: ({ row }: Line) => row.confidence || "–" }] : []),
  ];
  return (
    <VStack gap={2}>
      <Table<Line> data={data} columns={columns} idKey="id" />
      {r.team && (
        <Text color="secondary">
          {"Team: " + fmt(r.team.value, r.unit) +
            (r.team.p85 !== undefined ? ` (85th percentile ${fmt(r.team.p85, r.unit)})` : "") +
            ` over ${r.team.sample} · ${r.window.label}` + (teamSelected ? "" : " · all repositories")}
        </Text>
      )}
      {r.notes?.length ? r.notes.map((n) => <Text key={n} color="secondary">{n}</Text>) : null}
    </VStack>
  );
}

export function Rankings() {
  const filters = useFilters();
  const setParam = useSetParam();
  const chosen = filters.metric || "impact_points";
  const includeInactive = filters.inactive === "1";
  const catalog = useApi("/api/metrics");
  const metrics = (catalog.data as { metrics?: Meta[] } | undefined)?.metrics;
  const result = useApi(metrics ? "/api/metrics/" + chosen + filterQuery(filters, { include_inactive: includeInactive ? "true" : "" }) : null);

  const perPerson = (metrics ?? []).filter((m) => m.kind === "per_person");
  const meta = (metrics ?? []).find((m) => m.name === chosen);
  const r = result.data as Result | undefined;
  const err = catalog.error ?? result.error;

  const sections = GROUPS.flatMap(([key, label]) => {
    const members = perPerson.filter((m) => (m.group || "activity") === key);
    if (!members.length) return [];
    return [{
      type: "section" as const, title: label,
      options: members.map((m) => ({ value: m.name, label: m.label + (m.status === "waiting" ? ` (waiting for ${(m.missing ?? []).join(", ")})` : "") })),
    }];
  });

  let body: React.ReactNode = null;
  if (err) body = <Banner status="error" title={(err as Error).message} />;
  else if (r) {
    if (r.status === "waiting") body = <Text color="secondary">{"Waiting for " + (r.missing ?? []).map(sourceLabel).join(" and ") + " data. This fills in when that source is connected."}</Text>;
    else if (r.status === "error") body = <Banner status="error" title={"This metric failed: " + r.error} />;
    else body = <RankTable r={r} teamSelected={Boolean(filters.team)} filters={filters} />;
  }

  return (
    <VStack as="main" gap={3}>
      <Heading level={2}>Rankings</Heading>
      <HStack gap={3} align="end" wrap="wrap">
        <Selector label="Metric" options={sections} value={chosen} onChange={(v) => setParam("metric", v)} />
        <CheckboxInput label="include inactive members" value={includeInactive} onChange={(checked) => setParam("inactive", checked ? "1" : "")} />
      </HStack>
      <Text color="secondary">{meta?.description ?? ""}</Text>
      {body}
    </VStack>
  );
}

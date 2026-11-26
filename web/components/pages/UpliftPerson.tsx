"use client";

import NextLink from "next/link";
import type { ReactNode } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Card } from "@astryxdesign/core/Card";
import { Heading } from "@astryxdesign/core/Heading";
import { Link } from "@astryxdesign/core/Link";
import { Table, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useApi } from "@/lib/query";
import { filterQuery, useFilters } from "@/lib/filters";
import { UpliftChart } from "@/components/charts/UpliftCharts";
import { ComparePicker, coverageLine, useCompare } from "@/components/pages/Uplift";

const TITLES: Record<string, string> = { story_points_done: "Story points done", prs_merged: "PRs merged", reviews_given: "Reviews given" };
const QUALITY: Record<string, string> = {
  prs_with_tests: "PRs with tests", comments_received_per_pr: "Comments received per PR",
  durability: "Durability", inline_comments_given: "Inline comments given",
};
const WORKED: Record<string, string> = {
  prs_front_end: "Front-end PRs", prs_back_end: "Back-end PRs", prs_database: "Database PRs",
  prs_multi_layer: "Multi-layer PRs", reviews_given: "Reviews given",
  inline_comments_given: "Inline comments given", teammates_reviewed: "Teammates reviewed",
  big_tickets: "Big tickets (8+ points)",
};

type Cell = string | number | null | undefined;
type Stats = { median?: number; average?: number; low?: number; high?: number; count?: number };
type Win = { label: string; value: number; median: number; uplift: number | null; total?: number };
type Blocks = { blocks?: { start: string; no_data?: boolean }[]; short_baseline?: boolean; person?: Record<string, Stats>; everyone?: Record<string, Stats> };
type Detail = {
  compare?: { value: string; label: string; note?: string };
  person: { name: string }; level: string; day0: string; day_reached: number; coverage?: Record<string, string | null>;
  graphs: Record<string, { blocks: Blocks; table: { metric: string; label?: string; before: Cell; before_median_everyone: Cell; windows?: Win[] }[] }>;
  points_by_merge: unknown;
  windows: { label: string; reached: Cell; total: Cell; prorated: Cell; median: Cell; before_median: Cell; uplift: Cell }[];
  verdicts: { label: string; items: { item: string; verdict: Cell; value: Cell; threshold: Cell }[] }[];
  quality: { metric: string; threshold: number | null; blocks: unknown }[];
  how_they_worked: Record<string, { label: string; total: Cell }[]>;
  ai: { starts?: string | null; weeks?: { week: string; cost_usd: Cell; active_days: Cell; points: Cell }[] };
  explain: string[];
};

const show = (v: Cell) => (v === null || v === undefined ? "–" : String(v));

function Grid({ headers, rows }: { headers: string[]; rows: Cell[][] }) {
  type Row = Record<string, unknown> & { id: string; cells: Cell[] };
  const data: Row[] = rows.map((cells, i) => ({ id: "r" + i, cells }));
  const columns: TableColumn<Row>[] = headers.map((h, i) => ({ key: "c" + i, header: h, renderCell: ({ cells }: Row) => show(cells[i]) }));
  return <Table<Row> data={data} columns={columns} idKey="id" />;
}

function Section({ title, note, children }: { title: string; note?: string; children?: ReactNode }) {
  return (
    <Card>
      <VStack gap={2}>
        <Heading level={3}>{title}</Heading>
        {note ? <Text color="secondary">{note}</Text> : null}
        {children}
      </VStack>
    </Card>
  );
}

function beforeAfter(blocks: Blocks, who: string) {
  const rows: Cell[][] = [];
  ([["person", "Person"], ["everyone", who]] as const).forEach(([key, name]) => {
    const group = (blocks[key] ?? {}) as Record<string, Stats>;
    (["before", "after"] as const).forEach((when) => {
      const s = group[when] ?? {};
      rows.push([name, when, s.median, s.average, s.low, s.high, s.count]);
    });
  });
  return <Grid headers={["Who", "When", "Median", "Average", "Low", "High", "Blocks"]} rows={rows} />;
}

function metricTable(table: Detail["graphs"][string]["table"], who: string) {
  const labels: string[] = [];
  table.forEach((r) => (r.windows ?? []).forEach((w) => { if (!labels.includes(w.label)) labels.push(w.label); }));
  const rows = table.map((r) => {
    const byLabel: Record<string, Win> = {};
    (r.windows ?? []).forEach((w) => { byLabel[w.label] = w; });
    return [r.label || r.metric, r.before, r.before_median_everyone, ...labels.map((l) => {
      const w = byLabel[l];
      return w ? `${w.value} (${who} ${w.median}, x${w.uplift === null || w.uplift === undefined ? "–" : w.uplift})` : "–";
    })];
  });
  return <Grid headers={["Metric", "Before", who + " before", ...labels]} rows={rows} />;
}

export function UpliftPerson() {
  const filters = useFilters();
  const { compare } = useCompare();
  const id = filters.id;
  const detail = useApi(id ? "/api/uplift/person/" + encodeURIComponent(id) + filterQuery(filters, { compare }) : null);
  const d = detail.data as Detail | undefined;
  const who = d?.compare?.label ?? "everyone";

  let body: ReactNode;
  if (!id) body = <Text color="secondary">Choose a person from the cohort page.</Text>;
  else if (detail.error) body = <Banner status="error" title={(detail.error as Error).message} />;
  else if (!d) body = <Text color="secondary">Loading… this can take a minute.</Text>;
  else {
    const labels: string[] = [];
    Object.keys(d.how_they_worked).forEach((m) => d.how_they_worked[m].forEach((w) => { if (!labels.includes(w.label)) labels.push(w.label); }));
    body = (
      <VStack gap={3}>
        <Text color="secondary">{`${d.level} · Day 0 ${d.day0} · Day ${d.day_reached} of 90`}</Text>
        <Text color="secondary">{"Data covered up to " + coverageLine(d.coverage)}</Text>
        {Object.keys(d.graphs).map((name) => {
          const g = d.graphs[name];
          const empty = (g.blocks.blocks ?? []).filter((b) => b.no_data).map((b) => b.start);
          const note = [
            g.blocks.short_baseline ? "Short baseline: fewer than 6 blocks before Day 0, so the before numbers are thin." : "",
            empty.length ? `No data for the blocks starting ${empty.join(", ")}: nobody in ${who} has any, so the selected repositories likely do not cover them. They are left out of the figures.` : "",
          ].filter(Boolean).join(" ");
          return (
            <Section key={name} title={TITLES[name] ?? name} note={note}>
              <UpliftChart cohort={g.blocks} compare={compare} />
              {beforeAfter(g.blocks, who)}
              {metricTable(g.table, who)}
            </Section>
          );
        })}
        <Section title="Points by merge date" note="The same points counted on the day the PR merged.">
          <UpliftChart cohort={d.points_by_merge} compare={compare} />
        </Section>
        <Section title="Windows and verdicts">
          <Grid
            headers={["Window", "Days reached", "Total", "Pro-rated to the full window", `Median of ${who} (full window)`, "Before median", "Uplift"]}
            rows={d.windows.map((w) => [w.label, w.reached, w.total, w.prorated, w.median, w.before_median, w.uplift])}
          />
          {d.verdicts.map((v) => (
            <VStack key={v.label} gap={1}>
              <Heading level={4}>{v.label}</Heading>
              <Grid headers={["Item", "Verdict", "Value", "Threshold"]} rows={v.items.map((i) => [i.item, i.verdict, i.value, i.threshold])} />
            </VStack>
          ))}
        </Section>
        {d.quality.map((q) => (
          <Section key={q.metric} title={QUALITY[q.metric] ?? q.metric} note={q.threshold === null ? "" : "Threshold " + q.threshold}>
            <UpliftChart cohort={q.blocks} compare={compare} threshold={q.threshold ?? undefined} />
          </Section>
        ))}
        <Section title="How they worked" note="Per window.">
          <Grid
            headers={["Measure", ...labels]}
            rows={Object.keys(WORKED).map((m) => [WORKED[m], ...labels.map((l) => (d.how_they_worked[m] ?? []).find((w) => w.label === l)?.total ?? null)])}
          />
        </Section>
        <Section title="Claude use by week" note={d.ai.starts ? "Data starts " + d.ai.starts : "No Claude data for this person."}>
          <Grid headers={["Week", "Cost (USD)", "Active days", "Points"]} rows={(d.ai.weeks ?? []).map((w) => [w.week, w.cost_usd, w.active_days, w.points])} />
        </Section>
        <Section title="What the data says">
          <VStack gap={1}>{d.explain.map((t) => <Text key={t}>{t}</Text>)}</VStack>
        </Section>
      </VStack>
    );
  }

  return (
    <VStack as="main" gap={3}>
      <Link as={NextLink} href={"/uplift" + filterQuery(filters, { compare })}>Back to the cohort</Link>
      <Heading level={2}>{d?.person.name ?? "AI uplift"}</Heading>
      <ComparePicker info={d?.compare} />
      {body}
    </VStack>
  );
}

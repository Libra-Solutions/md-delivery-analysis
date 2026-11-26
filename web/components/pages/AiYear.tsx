"use client";

import { useEffect, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Banner } from "@astryxdesign/core/Banner";
import { Card } from "@astryxdesign/core/Card";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Selector } from "@astryxdesign/core/Selector";
import { Switch } from "@astryxdesign/core/Switch";
import { Table, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useApi } from "@/lib/query";
import { filterQuery, useFilters, useSetParam } from "@/lib/filters";
import { seriesColour } from "@/components/charts/Charts";
import { UpliftChart } from "@/components/charts/UpliftCharts";
import { ComparePicker, coverageLine, useCompare } from "@/components/pages/Uplift";

const TITLES: Record<string, string> = { story_points_done: "Story points done", prs_merged: "PRs merged", reviews_given: "Reviews given" };

type Cell = string | number | null | undefined;
type YearPerson = { person_id: string; name: string; level: string; ai_start?: string | null; at_data_start?: boolean };
type Stats = { median?: number | null; average?: number | null; low?: number | null; high?: number | null; count?: number | null };
type Change = { change: number | null; ratio?: number | null };
type Graph = {
  blocks: { name?: string; start: string; index?: number; median?: number | null; average?: number | null; value: number | null; no_data?: boolean; projects?: Record<string, number> }[];
  projects?: string[]; short_baseline?: boolean;
  person?: Record<string, Stats>; everyone?: Record<string, Stats>;
  effect: { person: { median: Change; average: Change }; group: { median: Change; average: Change }; vs_group: number | null };
};
type Detail = {
  compare?: { value: string; label: string; note?: string };
  person: { name: string }; level: string; ai_start?: string | null; at_data_start?: boolean; by?: string; board?: unknown;
  coverage?: Record<string, string | null>; notes: string[];
  graphs: Record<string, Graph>;
  expectations: { label: string; first: string; days: number; items: { item: string; verdict: Cell; value: Cell; threshold: Cell }[] }[];
};

const show = (v: Cell) => (v === null || v === undefined ? "–" : String(v));
const ratio = (r: number | null | undefined) => (r === null || r === undefined ? "–" : "x" + r);

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

/** Story points per block, one bar part per Jira project (lighter before the AI start), with the median and average lines. */
function ProjectStack({ graph }: { graph: Graph }) {
  const projects = graph.projects ?? [];
  const data = graph.blocks.map((b) => {
    const row: Record<string, string | number | null> = { x: b.name || b.start, median: b.median ?? null, average: b.average ?? null };
    projects.forEach((p) => { row[p] = b.projects ? b.projects[p] || 0 : null; });
    return row;
  });
  return (
    <div role="img" aria-label="Story points by Jira project">
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="x" />
          <YAxis />
          <Tooltip />
          <Legend />
          {projects.map((p, k) => (
            <Bar key={p} dataKey={p} stackId="person" fill={seriesColour(k)} maxBarSize={36} isAnimationActive={false}>
              {graph.blocks.map((b, i) => <Cell key={i} fillOpacity={(b.index ?? 0) >= 0 ? 1 : 0.5} />)}
            </Bar>
          ))}
          <Line type="monotone" dataKey="median" name="Median" stroke="var(--color-text-primary)" strokeDasharray="6 4" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="average" name="Average" stroke={seriesColour(1)} strokeDasharray="2 3" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AiYear() {
  const filters = useFilters();
  const params = useSearchParams();
  const setParam = useSetParam();
  const { compare } = useCompare();
  const sprint = params.get("by") === "sprint";
  const unit = (plural?: boolean) => (sprint ? (plural ? "sprints" : "sprint") : plural ? "months" : "month");
  const id = filters.id;

  const peopleQ = useApi("/api/uplift/year/people");
  const people = (peopleQ.data as { people: YearPerson[] } | undefined)?.people;
  useEffect(() => {
    if (!id && people && people.length) setParam("id", people[0].person_id);
  }, [id, people, setParam]);

  const detailQ = useApi(
    id ? "/api/uplift/year/person/" + encodeURIComponent(id) + filterQuery(filters, { compare, by: sprint ? "sprint" : "" }) : null,
  );
  const d = detailQ.data as Detail | undefined;
  const who = d?.compare && d.compare.label !== "Everyone" ? d.compare.label : "everyone";

  const options = (people ?? []).map((p) => ({
    value: p.person_id,
    label: `${p.name} · ${p.level} · ${p.ai_start ? "AI start " + p.ai_start + (p.at_data_start ? " or earlier" : "") : "AI start unknown"}`,
  }));

  function effectLine(e: Graph["effect"]): string {
    const me = e.person.median, them = e.group.median;
    if (me.change === null) return `Not enough ${unit(true)} on both sides of the AI start to compare.`;
    const gap = e.vs_group === null ? "" : e.vs_group > 0 ? `, a bigger rise than ${who}` : e.vs_group < 0 ? `, a smaller rise than ${who}` : `, the same as ${who}`;
    return `Median ${unit()} went from before to since AI by ${me.change} (${ratio(me.ratio)}); ${who} moved by ${show(them.change)} (${ratio(them.ratio)})${gap}. Average moved by ${e.person.average.change} against ${show(e.group.average.change)} for ${who}.`;
  }

  function beforeSince(g: Graph, split: boolean) {
    const rows: Cell[][] = [];
    ([["person", "Person"], ["everyone", who]] as const).forEach(([key, name]) => {
      const group = (g[key] ?? {}) as Record<string, Stats>;
      (split ? ([["before", "Before AI"], ["after", "Since AI"]] as const) : ([["before", "Last 12 months"]] as const)).forEach(([k, label]) => {
        const s = group[k] ?? {};
        rows.push([name, label, s.median, s.average, s.low, s.high, s.count]);
      });
    });
    return <Grid headers={["Who", "When", "Median", "Average", "Low", "High", sprint ? "Sprints" : "Months"]} rows={rows} />;
  }

  let body: ReactNode;
  if (peopleQ.error) body = <Banner status="error" title={(peopleQ.error as Error).message} />;
  else if (people && !people.length) body = <Text color="secondary">No direct reports are set up. Add them with: delivery-analysis cohort set</Text>;
  else if (!id) body = <Text color="secondary">Loading…</Text>;
  else if (detailQ.error) body = <Banner status="error" title={(detailQ.error as Error).message} />;
  else if (!d) body = <Text color="secondary">{sprint ? "Loading the year by sprint…" : "Loading the year…"}</Text>;
  else if (d.by === "sprint" && !d.board) body = <Text color="secondary">No sprints to show for this person.</Text>;
  else {
    body = (
      <VStack gap={3}>
        {Object.keys(d.graphs).map((name) => {
          const g = d.graphs[name];
          const empty = g.blocks.filter((b) => b.no_data).map((b) => b.name || b.start);
          const note = [
            d.ai_start && g.short_baseline ? `Short baseline: fewer than 6 ${unit(true)} of data before the AI start.` : "",
            empty.length ? `No data for ${empty.join(", ")}: nobody in ${who} has any, so the selected repositories likely do not cover it. These ${unit(true)} are left out of the figures.` : "",
          ].filter(Boolean).join(" ");
          const projects = g.projects ?? [];
          return (
            <Section key={name} title={TITLES[name] ?? name} note={note}>
              {projects.length ? <ProjectStack graph={g} /> : <UpliftChart cohort={g} compare={compare} />}
              {projects.length ? (
                <>
                  <Text color="secondary">{"Bars split by Jira project: " + projects.join(", ") + " (lighter before the AI start)."}</Text>
                  <Grid
                    headers={[sprint ? "Sprint" : "Month", ...projects, "Total"]}
                    rows={g.blocks.map((b) => [b.name || b.start, ...projects.map((p) => (b.projects ? b.projects[p] || 0 : null)), b.value])}
                  />
                </>
              ) : null}
              {d.ai_start ? <Text>{"AI effect: " + effectLine(g.effect)}</Text> : null}
              {beforeSince(g, Boolean(d.ai_start))}
            </Section>
          );
        })}
        <Section title="Against the expectations at their level" note={`${d.level} thresholds. These are AI-agnostic: they hold whether or not someone uses AI.`}>
          {d.expectations.map((p) => (
            <VStack key={p.label} gap={1}>
              <Heading level={4}>{`${p.label} · from ${p.first}, ${p.days} days`}</Heading>
              <Grid headers={["Item", "Verdict", "Value", "Threshold"]} rows={p.items.map((i) => [i.item, i.verdict, i.value, i.threshold])} />
            </VStack>
          ))}
        </Section>
      </VStack>
    );
  }

  return (
    <VStack as="main" gap={3}>
      <Heading level={2}>AI year</Heading>
      <Text color="secondary">Each direct report&apos;s last twelve months, split at their first Claude use, against the expectations at their level.</Text>
      <HStack gap={3} align="end" wrap="wrap">
        <Selector label="Person" options={options} value={id || undefined} onChange={(v) => setParam("id", v ?? "")} />
        <Switch label="By sprint" value={sprint} onChange={(on) => setParam("by", on ? "sprint" : "")} />
      </HStack>
      <ComparePicker info={d?.compare} />
      {d ? (
        <VStack gap={1}>
          <Heading level={3}>{d.person.name}</Heading>
          <Text color="secondary">
            {d.level + " · " + (d.ai_start ? "AI start " + d.ai_start + (d.at_data_start ? " (or earlier)" : "") : "AI start unknown")}
          </Text>
          {d.notes.map((n) => <Text key={n}>{n}</Text>)}
          <Text color="secondary">{"Data covered up to " + coverageLine(d.coverage)}</Text>
        </VStack>
      ) : null}
      {body}
    </VStack>
  );
}

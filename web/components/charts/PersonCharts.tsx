"use client";

import { useEffect, useRef, useState, type JSX } from "react";
import NextLink from "next/link";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Banner } from "@astryxdesign/core/Banner";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Link } from "@astryxdesign/core/Link";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { fmt } from "@/lib/format";
import type { Filters } from "@/lib/filters";
import { useApi, useWrite } from "@/lib/query";
import { seriesColour } from "@/components/charts/Charts";

const GROUP_DELAY_MS = 1000; // wait this long after the last tick before recalculating
const MEDIAN_COLOUR = "var(--color-text-secondary)";

type Num = number | null;
type Dataset = {
  label: string; values: Num[]; kind: "line" | "bar"; colour: string; dashed?: boolean; stack?: string;
};
type Comparison = { custom?: boolean; people?: { person_id: string; name: string; selected: boolean }[] };
type Weekly = {
  weeks: string[]; running?: string; points: Num[]; median: Num[]; average: Num[]; comparison?: Comparison;
};
type Summary = {
  window_days: number; impact: Num; claude_cost?: Num; impact_per_dollar?: Num; team_median_impact_per_dollar?: Num;
};
type Series = {
  dates: string[]; series: Record<string, Num[]>; team_median: Record<string, Num[]>;
  summary?: Summary | null; comparison?: Comparison; notes?: string[];
};

const ROWS: { cols: number; cards: [string, string, string][] }[] = [
  { cols: 1, cards: [["weekly_points", "Story points per week", "Plain story points for tickets delivered each calendar week (Dev1/Dev2 credit, no weighting or deductions). The current week is still running."]] },
  { cols: 1, cards: [["impact", "Impact", "Story points of finished tickets, weighted by how central the changed files are; delivery plus reviewing."]] },
  { cols: 2, cards: [
    ["impact_per_dollar", "Impact per dollar", "Impact points for each dollar of Claude usage."],
    ["split", "Delivery and participation", "How the latest window splits between doing the work and helping others get it right, against the team median."],
  ] },
  { cols: 3, cards: [
    ["delivery", "Delivery points", "Points earned as the owner of the pull request, less a small deduction for each review comment that had to be fixed."],
    ["delivery_speed", "Delivery speed", "Hours from a ticket starting to its first pull request merging. Lower is better."],
    ["durability", "Durability", "Share of delivered points on tickets that were never reopened."],
  ] },
  { cols: 3, cards: [
    ["participation", "Participation points", "Points earned when a review comment led to a change in the code."],
    ["prs_reviewed", "PRs reviewed", "Pull requests from other people where a comment was left."],
    ["review_value", "Review value", "Comments left on other people's pull requests, plus half a point for each approval."],
  ] },
];

export const hasValues = (values: Num[] | undefined): boolean => !!values && values.some((v) => v !== null && v !== undefined);

/** Rows for Recharts: one object per label, nulls kept so lines break into gaps. */
export function chartRows(labels: string[], datasets: Dataset[]): Record<string, string | number | null>[] {
  return labels.map((x, i) => {
    const row: Record<string, string | number | null> = { x };
    for (const d of datasets) row[d.label] = d.values[i] ?? null;
    return row;
  });
}

function Chart({ labels, datasets, unit, name }: { labels: string[]; datasets: Dataset[]; unit?: string; name: string }) {
  const format = (v: unknown) => fmt(typeof v === "number" ? v : null, unit);
  return (
    <div role="img" aria-label={name}>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={chartRows(labels, datasets)}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="x" />
          <YAxis tickFormatter={format} />
          <Tooltip formatter={(v) => format(v)} />
          <Legend />
          {datasets.map((d) =>
            d.kind === "bar" ? (
              <Bar key={d.label} dataKey={d.label} fill={d.colour} stackId={d.stack} radius={[3, 3, 0, 0]} maxBarSize={28} isAnimationActive={false} />
            ) : (
              <Line
                key={d.label} type="monotone" dataKey={d.label} stroke={d.colour} strokeWidth={2}
                strokeDasharray={d.dashed ? "6 4" : undefined} dot={d.dashed ? false : { r: 2 }}
                connectNulls={false} isAnimationActive={false}
              />
            ),
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartCard({ id, title, subtitle, empty, children }: {
  id: string; title: string; subtitle: string; empty?: string; children?: JSX.Element | null;
}) {
  return (
    <Card>
      <VStack gap={2} data-testid={"card-" + id}>
        <Heading level={3}>{title}</Heading>
        <Text color="secondary">{subtitle}</Text>
        {empty ? <Text color="secondary">{empty}</Text> : children}
      </VStack>
    </Card>
  );
}

function costState(s: Summary | null | undefined): "waiting" | "unlinked" | "linked" {
  if (!s || s.claude_cost === null || s.claude_cost === undefined) return "waiting";
  return s.claude_cost === 0 ? "unlinked" : "linked";
}

function medianNameFor(team: string, c: Comparison | undefined): string {
  if (!team) return "Everyone's median";
  return c?.custom ? "Selected people's median" : "Team median";
}

function SummaryStrip({ s }: { s: Summary | null | undefined }) {
  if (!s) return null;
  const state = costState(s);
  let line = `Last ${s.window_days} days: Impact ${fmt(s.impact)} · Claude cost ${state === "waiting" ? "–" : fmt(s.claude_cost, "usd")}`;
  if (state === "linked") {
    line += ` · ${fmt(s.impact_per_dollar, "points_per_usd")} impact per dollar (team median ${fmt(s.team_median_impact_per_dollar, "points_per_usd")})`;
  }
  return (
    <VStack gap={1}>
      <Text>{line}</Text>
      {state === "unlinked" ? (
        <Text color="secondary">
          No Claude cost is linked to this person yet, so Impact per dollar is blank. If they use Claude, link their Claude email on the{" "}
          <Link as={NextLink} href="/teams">Teams screen</Link>.
        </Text>
      ) : null}
      {state === "waiting" ? <Text color="secondary">Waiting for Claude usage data.</Text> : null}
    </VStack>
  );
}

function perDollarEmpty(s: Summary | null | undefined): string {
  return costState(s) === "unlinked"
    ? "No Claude cost is linked to this person yet, so Impact per dollar is blank. Link their Claude email on the Teams screen."
    : "Waiting for Claude usage data.";
}

function GroupPanel({ team, comparison }: { team: string; comparison: Comparison | undefined }) {
  const write = useWrite();
  const people = comparison?.people ?? [];
  const [checked, setChecked] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const known = people.map((p) => p.person_id + (p.selected ? "1" : "0")).join(",");

  useEffect(() => {
    setChecked(people.filter((p) => p.selected).map((p) => p.person_id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [known]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  function apply(next: string[]) {
    setChecked(next);
    if (timer.current) clearTimeout(timer.current);
    setFailed(false);
    setMessage("Updating the median in a moment…");
    timer.current = setTimeout(async () => {
      if (!next.length) {
        setFailed(true);
        setMessage("Tick at least one person to compare against.");
        return;
      }
      setMessage("Updating the median…");
      try {
        await write("/api/teams/" + encodeURIComponent(team) + "/comparison", "PUT", {
          person_ids: next.length === people.length ? null : next,
        });
        setMessage("Median updated.");
      } catch (e) {
        setFailed(true);
        setMessage((e as Error).message);
      }
    }, GROUP_DELAY_MS);
  }

  const summary = !team
    ? "Who counts as the team? Pick a team in the Team box at the top first"
    : comparison?.custom
      ? `Who counts as the team? ${checked.length} of ${people.length} people selected`
      : `Who counts as the team? Everyone (${people.length} people)`;

  return (
    <Card>
      <VStack gap={2}>
        <Heading level={4}>{summary}</Heading>
        <Text color="secondary">
          {team
            ? "The dashed median is measured across the people ticked here. Untick anyone who isn't a main contributor; the charts update as you go."
            : "Without a team the dashed line is the median of everyone."}
        </Text>
        {team ? (
          <HStack gap={2}>
            <Button label="Select all" onClick={() => apply(people.map((p) => p.person_id))} />
            <Button label="Clear" onClick={() => apply([])} />
          </HStack>
        ) : null}
        <VStack gap={1}>
          {people.map((p) => (
            <CheckboxInput
              key={p.person_id} label={p.name} value={checked.includes(p.person_id)}
              onChange={(on) => apply(on ? [...checked.filter((x) => x !== p.person_id), p.person_id] : checked.filter((x) => x !== p.person_id))}
            />
          ))}
        </VStack>
        {message ? <Text color={failed ? "accent" : "secondary"}>{message}</Text> : null}
      </VStack>
    </Card>
  );
}

export function PersonCharts({ personId, filters }: { personId: string; filters: Filters }): JSX.Element {
  const team = filters.team;
  const [windowDays, setWindowDays] = useState("30");
  const id = encodeURIComponent(personId);
  const weeklyParams = new URLSearchParams(team ? { team } : {}).toString();
  const seriesParams = new URLSearchParams({ window_days: windowDays, ...(team ? { team } : {}) }).toString();
  const weeklyQ = useApi(`/api/person/${id}/weekly-points` + (weeklyParams ? "?" + weeklyParams : ""));
  const seriesQ = useApi(`/api/person/${id}/series?${seriesParams}`);
  const groupQ = useApi(team ? `/api/teams/${encodeURIComponent(team)}/comparison` : null);
  const weekly = weeklyQ.data as Weekly | undefined;
  const d = seriesQ.data as Series | undefined;
  const comparison = (groupQ.data as Comparison | undefined) ?? d?.comparison ?? weekly?.comparison;
  const median = medianNameFor(team, d?.comparison ?? weekly?.comparison ?? comparison);
  const csv = `/api/people/${id}/export.csv?window_days=${windowDays}`;

  function cardBody(key: string): { empty?: string; chart?: JSX.Element } {
    if (key === "weekly_points") {
      if (weeklyQ.error) return { empty: (weeklyQ.error as Error).message };
      if (!weekly) return { empty: "Loading…" };
      if (!weekly.points.some((v) => v) && !weekly.median.some((v) => v)) return { empty: "No delivered points in these weeks" };
      const labels = weekly.weeks.map((w) => (w === weekly.running ? w + " (running)" : w));
      return { chart: (
        <Chart name="Story points per week" labels={labels} datasets={[
          { label: "Story points", values: weekly.points, kind: "bar", colour: seriesColour(0) },
          { label: median, values: weekly.median, kind: "line", colour: MEDIAN_COLOUR, dashed: true },
          { label: median.replace("median", "average"), values: weekly.average, kind: "line", colour: seriesColour(1), dashed: true },
        ]} />
      ) };
    }
    if (seriesQ.error) return { empty: (seriesQ.error as Error).message };
    if (!d) return { empty: "Loading…" };
    const x = d.dates;
    if (key === "impact") {
      if (!hasValues(d.series.delivery) && !hasValues(d.series.participation)) return { empty: "No data yet" };
      return { chart: (
        <Chart name="Impact" labels={x} datasets={[
          { label: "Delivery", values: d.series.delivery, kind: "bar", colour: seriesColour(0), stack: "impact" },
          { label: "Participation", values: d.series.participation, kind: "bar", colour: seriesColour(2), stack: "impact" },
          { label: median, values: d.team_median.impact, kind: "line", colour: MEDIAN_COLOUR, dashed: true },
        ]} />
      ) };
    }
    if (key === "split") {
      const last = x.length - 1;
      if (last < 0 || (d.series.delivery[last] === null && d.series.participation[last] === null)) return { empty: "No data yet" };
      return { chart: (
        <Chart name="Delivery and participation" labels={["Delivery", "Participation"]} datasets={[
          { label: "This person", values: [d.series.delivery[last], d.series.participation[last]], kind: "bar", colour: seriesColour(0) },
          { label: median, values: [d.team_median.delivery[last], d.team_median.participation[last]], kind: "bar", colour: seriesColour(1) },
        ]} />
      ) };
    }
    const labelOf: Record<string, string> = {
      impact_per_dollar: "Impact per dollar", delivery: "Delivery points", delivery_speed: "Delivery speed (hours)",
      durability: "Durability", participation: "Participation points", prs_reviewed: "PRs reviewed", review_value: "Review value",
    };
    if (!hasValues(d.series[key])) return { empty: key === "impact_per_dollar" ? perDollarEmpty(d.summary) : "No data yet" };
    return { chart: (
      <Chart name={labelOf[key]} labels={x} datasets={[
        { label: labelOf[key], values: d.series[key], kind: "line", colour: seriesColour(0) },
        { label: median, values: d.team_median[key] ?? [], kind: "line", colour: MEDIAN_COLOUR, dashed: true },
      ]} />
    ) };
  }

  return (
    <VStack gap={3}>
      <HStack gap={2} align="center" wrap="wrap">
        <Selector
          label="Rolling window" value={windowDays} onChange={(v) => setWindowDays(v ?? "30")}
          options={[{ value: "30", label: "30 days" }, { value: "60", label: "60 days" }, { value: "90", label: "90 days" }]}
        />
        <Text color="secondary">Each point covers the days up to its date; the dashed line is the median of the people counted as the team.</Text>
        <Button label="Download CSV" href={csv} />
      </HStack>
      {seriesQ.error ? <Banner status="error" title={(seriesQ.error as Error).message} /> : null}
      {d ? <SummaryStrip s={d.summary} /> : <Text color="secondary">Loading…</Text>}
      <GroupPanel team={team} comparison={team ? comparison : undefined} />
      {ROWS.map((row, i) => (
        <HStack key={i} gap={3} align="start">
          {row.cards.map(([key, title, subtitle]) => {
            const body = cardBody(key);
            return <ChartCard key={key} id={key} title={title} subtitle={subtitle} empty={body.empty}>{body.chart}</ChartCard>;
          })}
        </HStack>
      ))}
      {(d?.notes ?? []).length ? (
        <VStack gap={1}>{(d?.notes ?? []).map((n) => <Text key={n} color="secondary">{n}</Text>)}</VStack>
      ) : null}
    </VStack>
  );
}

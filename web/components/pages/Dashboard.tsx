"use client";

import type { ReactNode } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { VStack } from "@astryxdesign/core/VStack";
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { useApi } from "@/lib/query";
import { filterQuery, useFilters, useSetParam } from "@/lib/filters";
import { fmt, trendInfo } from "@/lib/format";
import { BarChart, LineChart } from "@/components/charts/Charts";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = Record<string, any>;
type Metric = {
  status: "ok" | "waiting" | "error";
  missing?: string[];
  error?: string;
  rows: Row[];
  notes?: string[];
  team?: Row | null;
  unit?: string;
};

// Metrics that have a card (or feed one): the "Coming with new sources" list skips them.
const ON_CARDS = ["story_points_weekly", "story_points_done", "issues_done", "points_by_type", "cycle_time_weekly",
  "cycle_time_summary", "prs_linked_weekly", "prs_with_issue_link", "story_points_per_dollar", "ask_generate_ratio",
  "story_points_per_dollar_weekly", "story_points_per_dollar_all_in", "unattributed_cost_share", "cost_by_purpose_weekly",
  "issues_done_weekly", "prs_merged_weekly", "time_to_merge", "lead_time_breakdown", "review_load", "work_in_progress"];

const SOURCE_LABELS: Record<string, string> = {
  jira: "Jira", bitbucket: "Bitbucket", claude_usage: "Claude usage", links: "pull request links", confluence: "Confluence",
};
const sourceLabel = (name: string) => SOURCE_LABELS[name] ?? name.replace("_", " ");

const sum = (rows: Row[], key: string) => rows.reduce((total, row) => total + (row[key] || 0), 0);
const weeks = (rows: Row[]) => rows.map((row) => String(row.week));
const unique = (list: string[]) => list.filter((item, index) => item && list.indexOf(item) === index);

function Stat({ children, label }: { children: ReactNode; label: string }) {
  return (
    <VStack gap={0.5}>
      <Text type="large" weight="bold" as="span">{children}</Text>
      <Text type="supporting" as="span">{label}</Text>
    </VStack>
  );
}

function Stats({ children }: { children: ReactNode }) {
  return <HStack gap={6} wrap="wrap">{children}</HStack>;
}

function Trend({ trend }: { trend: number | null | undefined }) {
  if (trend === null || trend === undefined) return <Text color="secondary" as="span">–</Text>;
  const info = trendInfo(trend, "higher");
  return <Text color={info.kind === "good" ? "accent" : "primary"} as="span">{info.text}</Text>;
}

function Notes({ notes }: { notes?: string[] }) {
  if (!notes || !notes.length) return null;
  return (
    <VStack gap={1}>
      {notes.map((n, i) => (
        <Text key={i} type="supporting">{n}</Text>
      ))}
    </VStack>
  );
}

function DataTable({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  return (
    <Collapsible trigger="Show as table" defaultIsOpen={false}>
      <Table>
        <TableHeader>
          <TableRow isHeaderRow>
            {headers.map((h) => (
              <TableHeaderCell key={h}>{h}</TableHeaderCell>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={i}>
              {row.map((cell, j) => (
                <TableCell key={j}>{String(cell)}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Collapsible>
  );
}

const Note = ({ text }: { text: string }) => <Text type="supporting">{text}</Text>;
const bars = (rows: Row[], label: (r: Row) => string, value: (r: Row) => number) =>
  rows.map((r) => ({ label: label(r), value: value(r) }));
const points = (rows: Row[], key: string) => rows.map((r) => ({ x: String(r.week), y: (r[key] ?? null) as number | null }));

type CardProps = {
  title: string;
  subtitle?: string;
  /** Metric names this card reads; the first one decides whether the card shows data. */
  names: string[];
  render: (m: Metric[]) => ReactNode;
};

function Card_({ title, subtitle, names, render }: CardProps) {
  const f = useFilters();
  const q = filterQuery(f);
  const results = names.map((n) => useApi(`/api/metrics/${n}${q}`)); // eslint-disable-line react-hooks/rules-of-hooks
  const failed = results.find((r) => r.error);
  const loading = results.some((r) => r.data === undefined);
  let body: ReactNode;
  if (failed) body = <Banner status="error" title={(failed.error as Error).message} />;
  else if (loading) body = <Text type="supporting">Loading…</Text>;
  else {
    const data = results.map((r) => r.data as Metric);
    const head = data[0];
    if (head.status === "waiting") {
      body = (
        <Text type="supporting">
          {`Waiting for ${(head.missing ?? []).map(sourceLabel).join(" and ")} data. This fills in when that source is connected.`}
        </Text>
      );
    } else if (head.status === "error") body = <Banner status="error" title={`This metric failed: ${head.error}`} />;
    else body = render(data);
  }
  return (
    <Card padding={4} data-metric={names[0]}>
      <VStack gap={3}>
        <Heading level={3}>{title}</Heading>
        {subtitle ? <Text type="supporting">{subtitle}</Text> : null}
        {body}
      </VStack>
    </Card>
  );
}

const msg = (text: string) => <Text type="supporting">{text}</Text>;

function perPerson(names: string[], title: string, subtitle: string): CardProps {
  return {
    title, subtitle, names,
    render: ([r]) => {
      const rows = r.rows.filter((x) => x.value).slice(0, 10);
      if (!rows.length) return msg("Nothing open right now.");
      return (
        <>
          <BarChart bars={bars(rows, (x) => x.name, (x) => x.value)} unit={r.unit} />
          <DataTable headers={["Person", title]} rows={rows.map((x) => [x.name, fmt(x.value, r.unit)])} />
          <Notes notes={r.notes} />
        </>
      );
    },
  };
}

const CARDS: CardProps[] = [
  {
    title: "Impact delivered",
    subtitle: "Story points of completed issues, credited to the authors of their linked pull requests (the assignee when none is linked)",
    names: ["story_points_weekly", "story_points_done"],
    render: ([weekly, done]) => {
      const hasTeam = done.status === "ok" && !!done.team;
      const total = hasTeam && done.team!.value !== null ? done.team!.value : sum(weekly.rows, "value");
      const completed = sum(weekly.rows, "issues");
      const without = sum(weekly.rows, "unpointed");
      const trend = hasTeam ? done.team!.trend : null;
      const previous = hasTeam ? done.team!.previous : null;
      return (
        <>
          <Stats>
            <Stat label="story points done">{fmt(total, "points")}</Stat>
            <Stat label={previous === null || previous === undefined ? "vs previous window" : `vs previous window (${fmt(previous, "points")} points)`}>
              <Trend trend={trend} />
            </Stat>
            <Stat label="completed issues">{fmt(completed, "count")}</Stat>
            <Stat label="without points">{fmt(without, "count")}</Stat>
          </Stats>
          <BarChart bars={bars(weekly.rows, (w) => w.week, (w) => w.value)} unit="points" />
          <DataTable headers={["Week starting", "Story points", "Issues"]} rows={weekly.rows.map((w) => [w.week, fmt(w.value, "points"), w.issues])} />
          <Note text={`Based on ${completed - without} completed issues with story points.`} />
          <Notes notes={weekly.notes} />
          {trend === null || trend === undefined ? <Notes notes={(done.notes || []).filter((n) => n.indexOf("trend") !== -1)} /> : null}
        </>
      );
    },
  },
  {
    title: "Where it went",
    subtitle: "Story points by issue type",
    names: ["points_by_type"],
    render: ([r]) => {
      if (!r.rows.length) return <>{msg("No completed issues with story points in this window.")}<Notes notes={r.notes} /></>;
      return (
        <>
          <BarChart bars={bars(r.rows, (p) => p.part, (p) => p.value)} unit="points" />
          <DataTable headers={["Issue type", "Story points", "Issues"]} rows={r.rows.map((p) => [p.part, fmt(p.value, "points"), p.count])} />
          <Note text={`Based on ${sum(r.rows, "count")} completed issues with story points.`} />
          <Notes notes={r.notes} />
        </>
      );
    },
  },
  {
    title: "How fast",
    subtitle: "Hours from first In Progress to COMPLETED, and to the first merged linked pull request, counting each issue once",
    names: ["cycle_time_weekly", "cycle_time_summary"],
    render: ([r, summary]) => {
      const count = sum(r.rows, "count");
      if (!count) return <>{msg("No completed issues with a start time in this window.")}<Notes notes={r.notes} /></>;
      return (
        <>
          {summary.status === "ok" ? (
            <Stats>
              {summary.rows.map((p) => (
                <Stat key={p.part} label={`median ${String(p.part).toLowerCase()} (85th percentile ${fmt(p.p85, "hours")}, ${p.count} issues)`}>
                  {fmt(p.median, "hours")}
                </Stat>
              ))}
            </Stats>
          ) : null}
          <LineChart
            unit="hours"
            series={[
              { label: "Median to COMPLETED", points: points(r.rows, "median") },
              { label: "85th percentile to COMPLETED", points: points(r.rows, "p85") },
              { label: "Median to first PR merge", points: points(r.rows, "pr_median") },
            ]}
          />
          <DataTable
            headers={["Week starting", "Median", "85th percentile", "Issues", "Median to first PR merge", "Issues with a merged PR"]}
            rows={r.rows.map((w) => [w.week, fmt(w.median, "hours"), fmt(w.p85, "hours"), w.count, fmt(w.pr_median, "hours"), w.pr_count])}
          />
          <Note text={`Based on ${count} completed issues with a start time.`} />
          <Notes notes={r.notes} />
        </>
      );
    },
  },
  {
    title: "Evidence",
    subtitle: "Merged pull requests per week, split by whether an issue key links them",
    names: ["prs_linked_weekly", "prs_with_issue_link"],
    render: ([weekly, rate]) => {
      const people = rate.status === "ok" ? rate.rows.filter((x) => x.sample > 0) : [];
      return (
        <>
          {rate.status === "ok" && rate.team ? (
            <Stats>
              <Stat label="of merged pull requests link to an issue">{fmt(rate.team.value, "ratio")}</Stat>
              <Stat label="merged pull requests">{String(rate.team.sample)}</Stat>
            </Stats>
          ) : null}
          <LineChart
            series={[
              { label: "Linked to an issue", points: points(weekly.rows, "linked") },
              { label: "No issue key", points: points(weekly.rows, "unlinked") },
            ]}
          />
          <DataTable headers={["Week starting", "Linked", "No issue key"]} rows={weekly.rows.map((w) => [w.week, w.linked, w.unlinked])} />
          {people.length ? (
            <DataTable headers={["Person", "Link rate", "Merged pull requests"]} rows={people.map((x) => [x.name, fmt(x.value, "ratio"), x.sample])} />
          ) : null}
          <Notes notes={weekly.notes} />
        </>
      );
    },
  },
  {
    title: "Impact per token",
    subtitle: "Story points per dollar of attributed Claude cost (cost proxy), by completion week",
    names: ["story_points_per_dollar_weekly", "story_points_per_dollar", "story_points_per_dollar_all_in", "unattributed_cost_share"],
    render: ([weekly, attributed, allIn, share]) => {
      const team = (r: Metric) => (r.team ? r.team.value : null);
      return (
        <>
          <Stats>
            <Stat label="attributed">{fmt(team(attributed), "points_per_usd")}</Stat>
            <Stat label="all-in">{fmt(team(allIn), "points_per_usd")}</Stat>
            <Stat label="unattributed cost share">{fmt(team(share), "ratio")}</Stat>
          </Stats>
          <LineChart unit="points_per_usd" series={[{ label: "Points per dollar", points: points(weekly.rows, "value") }]} />
          <DataTable
            headers={["Week starting", "Tickets", "Points", "Attributed cost", "Points per dollar"]}
            rows={weekly.rows.filter((w) => w.tickets).map((w) => [w.week, w.tickets, fmt(w.points), fmt(w.cost_usd, "usd"), fmt(w.value, "points_per_usd")])}
          />
          <Notes notes={unique((weekly.notes || []).concat(attributed.notes || []))} />
        </>
      );
    },
  },
  {
    title: "Cost and impact by person",
    subtitle: "Attributed Claude cost against credited story points, tickets completed in the window",
    names: ["story_points_per_dollar"],
    render: ([r]) => {
      const people = r.rows.filter((x) => x.person_id && x.denominator !== undefined);
      if (!people.length) return msg("No completed tickets with Claude cost in this window.");
      return (
        <>
          {r.team && r.team.value !== null ? (
            <Note text={`Team: ${fmt(r.team.value, "points_per_usd")} points per dollar. People above that slope deliver more points per dollar than the team; compare people with their own trend first.`} />
          ) : null}
          <DataTable
            headers={["Person", "Cost", "Points", "Points per dollar", "Confidence"]}
            rows={people.map((x) => [
              x.name + (x.ranked ? "" : " (unranked)"), fmt(x.denominator, "usd"), fmt(x.numerator), fmt(x.value, "points_per_usd"), x.confidence || "–",
            ])}
          />
          <Notes notes={r.notes} />
        </>
      );
    },
  },
  {
    title: "Ask vs generate",
    subtitle: "Context only, not a score: Claude cost by purpose per week, a coarse proxy (v1) with low confidence",
    names: ["cost_by_purpose_weekly", "ask_generate_ratio"],
    render: ([weekly, ratio]) => {
      const rows = ratio.status === "ok"
        ? ratio.rows.filter((x) => x.person_id && x.value !== null).sort((a, b) => String(a.name).localeCompare(String(b.name)))
        : [];
      return (
        <>
          <LineChart
            unit="usd"
            series={[
              { label: "Ask", points: points(weekly.rows, "ask") },
              { label: "Generate", points: points(weekly.rows, "generate") },
              { label: "Unclassified", points: points(weekly.rows, "unclassified") },
            ]}
          />
          <DataTable
            headers={["Week starting", "Ask", "Generate", "Unclassified"]}
            rows={weekly.rows.map((w) => [w.week, fmt(w.ask, "usd"), fmt(w.generate, "usd"), fmt(w.unclassified, "usd")])}
          />
          {rows.length ? (
            <>
              <BarChart bars={bars(rows, (x) => x.name, (x) => x.value)} unit={ratio.unit} />
              <DataTable headers={["Person", "Ask to generate"]} rows={rows.map((x) => [x.name, fmt(x.value, ratio.unit)])} />
            </>
          ) : null}
          <Notes notes={unique((weekly.notes || []).concat(ratio.notes || []))} />
        </>
      );
    },
  },
  {
    title: "Throughput by week",
    subtitle: "Pull requests merged per week, and issues done when Jira is connected",
    names: ["prs_merged_weekly", "issues_done_weekly"],
    render: ([r, issues]) => (
      <>
        <BarChart bars={bars(r.rows, (w) => w.week, (w) => w.value)} />
        <DataTable headers={["Week starting", "PRs merged"]} rows={r.rows.map((w) => [w.week, w.value])} />
        <Notes notes={r.notes} />
        {issues.status !== "ok" ? (
          <Note text="Issues done appear here when Jira is connected." />
        ) : (
          <>
            <Note text="Issues done per week" />
            <BarChart bars={bars(issues.rows, (w) => w.week, (w) => w.value)} />
            <DataTable headers={["Week starting", "Issues done"]} rows={issues.rows.map((w) => [w.week, w.value])} />
            <Notes notes={issues.notes} />
          </>
        )}
      </>
    ),
  },
  {
    title: "Time to merge",
    subtitle: "From opening a pull request to merging it",
    names: ["time_to_merge"],
    render: ([r]) => (
      <>
        <Stats>
          <Stat label="median">{fmt(r.team?.value, "hours")}</Stat>
          <Stat label="85th percentile">{fmt(r.team?.p85, "hours")}</Stat>
          <Stat label="pull requests">{String(r.team?.sample ?? "–")}</Stat>
        </Stats>
        <Notes notes={r.notes} />
      </>
    ),
  },
  {
    title: "PR lead time breakdown",
    subtitle: "Median hours in each stage",
    names: ["lead_time_breakdown"],
    render: ([r]) => (
      <>
        <BarChart bars={bars(r.rows, (p) => p.part, (p) => p.median_hours || 0)} unit="hours" />
        <DataTable headers={["Stage", "Median", "Pull requests"]} rows={r.rows.map((p) => [p.part, fmt(p.median_hours, "hours"), p.count])} />
        <Notes notes={r.notes} />
      </>
    ),
  },
  perPerson(["review_load"], "Review load", "Open pull requests waiting on each reviewer, right now"),
  perPerson(["work_in_progress"], "Work in progress", "Open pull requests by author, right now"),
];

function Waiting() {
  const q = useApi("/api/metrics");
  if (q.error) return <Banner status="error" title={(q.error as Error).message} />;
  const data = q.data as { metrics: { name: string; label: string; description: string; status: string; missing: string[] }[] } | undefined;
  if (!data) return <Text type="supporting">Loading…</Text>;
  return (
    <VStack gap={4}>
      {data.metrics
        .filter((m) => m.status === "waiting" && ON_CARDS.indexOf(m.name) === -1)
        .map((m) => (
          <Card padding={4} key={m.name}>
            <VStack gap={2}>
              <Heading level={3}>{m.label}</Heading>
              <Text type="supporting">{m.description}</Text>
              <Text type="supporting">{`Needs ${m.missing.map(sourceLabel).join(" and ")}.`}</Text>
            </VStack>
          </Card>
        ))}
    </VStack>
  );
}

export function Dashboard() {
  const f = useFilters();
  const setParam = useSetParam();
  const detail = f.metric ? CARDS.find((c) => c.names.includes(f.metric)) : undefined;

  if (detail) {
    return (
      <VStack gap={4}>
        <Heading level={2}>Dashboard</Heading>
        <HStack>
          <Button label="Back to dashboard" onClick={() => setParam("metric", "")} />
        </HStack>
        <Card_ {...detail} />
      </VStack>
    );
  }
  return (
    <VStack gap={4}>
      <Heading level={2}>Dashboard</Heading>
      {CARDS.map((c) => (
        <Card_ key={c.title} {...c} />
      ))}
      <Heading level={2}>Coming with new sources</Heading>
      <Waiting />
    </VStack>
  );
}

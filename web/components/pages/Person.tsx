"use client";

import { useEffect, type ReactNode } from "react";
import NextLink from "next/link";
import { Banner } from "@astryxdesign/core/Banner";
import { Card } from "@astryxdesign/core/Card";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Link } from "@astryxdesign/core/Link";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useApi } from "@/lib/query";
import { filterQuery, useFilters, useSetParam, type Filters } from "@/lib/filters";
import { fmt } from "@/lib/format";
import { BarChart } from "@/components/charts/Charts";
import { PersonCharts } from "@/components/charts/PersonCharts";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = Record<string, any>;

const STATS: [string, string][] = [
  ["prs_merged", "PRs merged"], ["reviews_given", "Reviews given"], ["reviews_assigned", "Reviews assigned"],
  ["review_response_rate", "Response rate"], ["time_to_merge", "Median time to merge"], ["commits", "Commits"],
  ["story_points_done", "Story points done"], ["qa_points_done", "QA points done"], ["issues_done", "Issues done"],
  ["cycle_time", "Median cycle time"], ["cost_spent", "Claude cost"], ["story_points_per_dollar", "Points per dollar"],
];

const STORE_KEY = "da.person";
function remembered(): string {
  try { return window.localStorage.getItem(STORE_KEY) || ""; } catch { return ""; }
}
function remember(id: string) {
  try { window.localStorage.setItem(STORE_KEY, id); } catch { /* storage is off: nothing to remember */ }
}
const day = (iso?: string | null) => (iso ? iso.slice(0, 10) : "–");
const cell = (v: unknown) => (v === null || v === undefined ? "–" : String(v));

function List({ headers, rows }: { headers: string[]; rows: unknown[][] }) {
  if (!rows.length) return <Text type="supporting">None in this window.</Text>;
  return (
    <Table>
      <TableHeader>
        <TableRow isHeaderRow>
          {headers.map((h) => (
            <TableHeaderCell key={h}>{h}</TableHeaderCell>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => (
          <TableRow key={i}>
            {r.map((c, j) => (
              <TableCell key={j}>{cell(c)}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card padding={4}>
      <VStack gap={3}>
        <Heading level={3}>{title}</Heading>
        {children}
      </VStack>
    </Card>
  );
}

function StatTile({ name, label, id, filters }: { name: string; label: string; id: string; filters: Filters }) {
  const m = useApi("/api/metrics/" + name + filterQuery(filters, { include_inactive: "true" }));
  const r = m.data as Row | undefined;
  const row = (r?.rows ?? []).find((x: Row) => x.person_id === id);
  const value = r === undefined ? "…" : r.status === "ok" && row ? fmt(row.value, r.unit) : "–";
  return (
    <VStack gap={0.5}>
      <Text type="large" weight="bold" as="span">{value}</Text>
      <Text type="supporting" as="span">{label}</Text>
    </VStack>
  );
}

export function Person() {
  const filters = useFilters();
  const setParam = useSetParam();
  const id = filters.id;

  const teams = useApi("/api/teams");
  const peopleQ = useApi("/api/people" + filterQuery(filters, { include_inactive: "true" }));
  const detailQ = useApi(id ? "/api/people/" + encodeURIComponent(id) + filterQuery(filters) : null);
  const ticketsQ = useApi(id ? "/api/tickets" + filterQuery(filters, { person: id }) : null);

  const teamList: Row[] = (teams.data as Row | undefined)?.teams ?? [];
  const people: Row[] = (peopleQ.data as Row | undefined)?.people ?? [];
  const d = detailQ.data as Row | undefined;
  const t = ticketsQ.data as Row | undefined;

  // With no team chosen and exactly one team defined, that team is the scope.
  useEffect(() => {
    if (!filters.team && teamList.length === 1) setParam("team", teamList[0].team_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.team, teamList.length]);

  // Opening People from the nav lands here with no person: show the one viewed last, else the first by name.
  useEffect(() => {
    if (id || !people.length) return;
    const last = remembered();
    setParam("id", people.some((p) => p.person_id === last) ? last : people[0].person_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, people.length]);

  useEffect(() => {
    if (id) remember(id);
  }, [id]);

  const options = [
    { value: "", label: "Choose a person…" },
    ...people.map((p) => ({ value: p.person_id as string, label: p.status === "inactive" ? p.name + " (inactive)" : p.name })),
  ];
  const err = peopleQ.error ?? detailQ.error;
  const csv = id ? "/api/people/" + encodeURIComponent(id) + "/export.csv" + filterQuery(filters) : "";

  return (
    <VStack as="main" gap={3}>
      <HStack gap={3} align="end" wrap="wrap">
        <Selector label="Person" options={options} value={id} onChange={(v) => { if (v) { remember(v); setParam("id", v); } }} />
        <Link as={NextLink} href={"/people" + filterQuery(filters)}>All people</Link>
        {csv && <Link href={csv}>Download CSV</Link>}
      </HStack>
      {err && <Banner status="error" title={(err as Error).message} />}
      {!id && !people.length && !peopleQ.isPending && <Text type="supporting">No people yet. Add a team and run a sync first.</Text>}
      <Heading level={2}>{d?.person?.name ?? "Person"}</Heading>
      {d && (
        <Text type="supporting">
          {[(d.person.accounts ?? []).join(", "), (d.person.emails ?? []).join(", "), d.window?.label].filter(Boolean).join(" · ")}
        </Text>
      )}
      {id && <PersonCharts personId={id} filters={filters} />}
      {id && (
        <Collapsible trigger="Show the tickets and PRs" defaultIsOpen={false}>
          <VStack gap={3}>
            <Heading level={3}>The work behind the numbers</Heading>
            <HStack gap={6} wrap="wrap">
              {STATS.map(([name, label]) => (
                <StatTile key={name} name={name} label={label} id={id} filters={filters} />
              ))}
            </HStack>
            {d && (
              <>
                <Panel title="Commits by week">
                  <BarChart bars={(d.commits_weekly ?? []).map((w: Row) => ({ label: String(w.week), value: w.value }))} />
                  <List headers={["Week starting", "Commits"]} rows={(d.commits_weekly ?? []).map((w: Row) => [w.week, w.value])} />
                </Panel>
                <Panel title="Reviews waiting on them">
                  <List headers={["#", "Title", "Repository", "Opened"]} rows={(d.reviews_pending ?? []).map((p: Row) => [p.number, p.title, p.repository, day(p.created_at)])} />
                </Panel>
                {d.issues_done && (
                  <Panel title="Completed issues">
                    <List
                      headers={["Issue", "Type", "Story points", "Credit", "Credited via", "Resolved"]}
                      rows={d.issues_done.map((i: Row) => [i.key, i.type, i.points, Math.round(i.share * 100) + "%", i.basis, day(i.resolved_at)])}
                    />
                  </Panel>
                )}
              </>
            )}
            <Panel title="Tickets and Claude cost">
              {ticketsQ.error ? (
                <Banner status="error" title={(ticketsQ.error as Error).message} />
              ) : t ? (
                <>
                  <List
                    headers={["Ticket", "Type", "Points", "Claude cost", "Points per $", "Confidence", "PRs", "Hours to merge"]}
                    rows={(t.tickets ?? []).map((x: Row) => [
                      x.key, x.type, x.points, fmt(x.cost_usd, "usd"), fmt(x.points_per_usd, "points_per_usd"),
                      x.confidence, x.pull_requests, fmt(x.hours_to_merge, "hours"),
                    ])}
                  />
                  {t.cost_weekly?.some((w: Row) => w.cost_usd) && (
                    <BarChart unit="usd" bars={t.cost_weekly.map((w: Row) => ({ label: String(w.week), value: w.cost_usd }))} />
                  )}
                  {(t.notes ?? []).map((n: string, i: number) => (
                    <Text key={i} type="supporting">{n}</Text>
                  ))}
                </>
              ) : (
                <Text type="supporting">Loading…</Text>
              )}
            </Panel>
            {d && (
              <>
                <Panel title="Pull requests">
                  <List
                    headers={["#", "Title", "Repository", "State", "Opened", "Merged"]}
                    rows={(d.pull_requests ?? []).map((p: Row) => [p.number, p.title, p.repository, p.state, day(p.created_at), day(p.merged_at)])}
                  />
                </Panel>
                <Panel title="Reviews given">
                  <List headers={["#", "Title", "Repository", "Kind", "When"]} rows={(d.reviews_given ?? []).map((r: Row) => [r.number, r.title, r.repository, r.type, day(r.occurred_at)])} />
                </Panel>
              </>
            )}
          </VStack>
        </Collapsible>
      )}
    </VStack>
  );
}

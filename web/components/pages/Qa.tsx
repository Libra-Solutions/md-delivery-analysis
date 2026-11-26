"use client";

import { useState, type ReactNode } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Link } from "@astryxdesign/core/Link";
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useApi } from "@/lib/query";
import { filterQuery, useFilters } from "@/lib/filters";
import { fmt } from "@/lib/format";
import { BarChart, LineChart } from "@/components/charts/Charts";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Sprint = Record<string, any>;

const pct = (v: number | null | undefined) => fmt(v, "ratio");
const asPct = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.round(v * 1000) / 10);

type Detail = { title: string; keys: string[] };

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <VStack gap={0.5}>
      <Text type="large" weight="bold" as="span">{value}</Text>
      <Text type="supporting" as="span">{label}</Text>
    </VStack>
  );
}

function Tbl({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
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
        {rows.map((row, i) => (
          <TableRow key={i}>
            {row.map((cell, j) => (
              <TableCell key={j}>{cell}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <Card padding={4}>
      <VStack gap={3}>
        <Heading level={3}>{title}</Heading>
        <Text type="supporting">{subtitle}</Text>
        {children}
      </VStack>
    </Card>
  );
}

export function Qa() {
  const filters = useFilters();
  const qa = useApi("/api/qa");
  const [detail, setDetail] = useState<Detail | null>(null);
  const data = qa.data as Record<string, any> | undefined;

  if (qa.error) return <Banner status="error" title={"Could not load QA numbers: " + (qa.error as Error).message} />;
  if (!data) return <Text type="supporting">Loading…</Text>;

  const keysLink = (text: string, title: string, keys?: string[]): ReactNode =>
    keys && keys.length ? (
      <Link href="#qa-detail" onClick={(e) => { e.preventDefault(); setDetail({ title, keys }); }}>{text}</Link>
    ) : (
      text
    );

  const s = data.headline?.sprint;
  const r = data.headline?.release;
  const sprints: Sprint[] = data.sprints ?? [];
  const months: Sprint[] = data.months ?? [];
  const releases: Sprint[] = data.releases ?? [];
  const labels = sprints.map((x) => x.name + (x.in_progress ? " (in progress)" : ""));
  const relLabels = releases.map((x) => x.release + (x.in_progress ? " (in progress)" : ""));
  const scope =
    `Jira project ${data.project}, ${data.window.start} to ${data.window.end}. ` +
    "Team, sprint and release figures only. The team and window pickers above do not apply here." +
    (data.unsprinted_tested ? ` ${data.unsprinted_tested} tested Stories had no sprint and are left out.` : "");
  const printTitle = `${data.project} QA status · ${data.window.start} to ${data.window.end}`;
  const csv = "/api/qa/export.csv" + filterQuery(filters);

  return (
    <VStack as="main" gap={3}>
      <style>{"@media print { nav, header, .no-print { display: none !important; } .print-only { display: block !important; } }"}</style>
      <Heading level={2}>QA</Heading>
      <Text type="supporting" className="print-only" style={{ display: "none" }}>{printTitle}</Text>
      <Text type="supporting">{scope}</Text>
      <HStack gap={6} wrap="wrap">
        <Stat value={s ? pct(s.fail_rate) : "–"} label={"QA fail rate" + (s ? " · " + s.name : "")} />
        <Stat value={s ? pct(s.escape_rate) : "–"} label={"Escape defect rate" + (s ? " · " + s.name : "")} />
        <Stat value={r ? String(r.bugs) : "–"} label={"Regression bugs" + (r ? " · release " + r.release : "")} />
      </HStack>
      <HStack gap={2} className="no-print">
        <Button label="Save as PDF" onClick={() => window.print()} />
        <Link href={csv}>Download CSV</Link>
      </HStack>

      <Panel title="QA fail rate by sprint" subtitle="Stories that reached In QA and were sent back to development">
        <LineChart series={[{ label: "QA fail rate %", points: sprints.map((x, i) => ({ x: labels[i], y: asPct(x.fail_rate) })) }]} />
        <Tbl
          headers={["Sprint", "Tested", "Failed QA", "Fail rate", "Sub-bugs per Story"]}
          rows={sprints.map((x, i) => [labels[i], String(x.tested), keysLink(String(x.failed), x.name + " · failed QA", x.failed_keys), pct(x.fail_rate), fmt(x.sub_bugs_per_story)])}
        />
      </Panel>

      <Panel title="Escape defect rate by sprint" subtitle="Defects ÷ (Defects + Bugs + Sub-bugs) created during the sprint">
        <LineChart series={[{ label: "Escape defect rate %", points: sprints.map((x, i) => ({ x: labels[i], y: asPct(x.escape_rate) })) }]} />
        <Tbl
          headers={["Sprint", "Defects", "Bugs", "Sub-bugs", "Escape rate"]}
          rows={sprints.map((x, i) => [labels[i], keysLink(String(x.defects), x.name + " · Defects", x.defect_keys), String(x.bugs), String(x.sub_bugs), pct(x.escape_rate)])}
        />
      </Panel>

      <Panel title="Escape defect rate by month" subtitle="Same rate by calendar month (US Eastern)">
        <LineChart series={[{ label: "Escape defect rate %", points: months.map((m) => ({ x: String(m.month), y: asPct(m.escape_rate) })) }]} />
        <Tbl
          headers={["Month", "Defects", "Bugs", "Sub-bugs", "Escape rate"]}
          rows={months.map((m) => [String(m.month), keysLink(String(m.defects), m.month + " · Defects", m.defect_keys), String(m.bugs), String(m.sub_bugs), pct(m.escape_rate)])}
        />
      </Panel>

      <Panel title="Regression bugs by release" subtitle="Bugs linked to the release's X.XX Regression stories">
        <BarChart bars={releases.map((x, i) => ({ label: relLabels[i], value: x.bugs }))} />
        <Tbl
          headers={["Release", "Regression bugs", "Regression stories"]}
          rows={releases.map((x, i) => [relLabels[i], keysLink(String(x.bugs), "Release " + x.release + " · regression bugs", x.bug_keys), (x.regression_stories ?? []).join(", ")])}
        />
      </Panel>

      {detail && (
        <div id="qa-detail" className="no-print">
          <Panel title={detail.title} subtitle={detail.keys.length + " tickets"}>
            <Text>{detail.keys.join(", ")}</Text>
          </Panel>
        </div>
      )}
    </VStack>
  );
}

"use client";
import type { JSX } from "react";
import {
  Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

type Block = {
  index: number; name?: string; start?: string; partial?: boolean;
  value: number | null; median: number | null; average: number | null;
};
type Side = { median?: number | null; average?: number | null };
type Graph = { blocks?: Block[]; person?: { before?: Side; after?: Side } };

const token = (name: string) => `var(--color-data-categorical-${name})`;
const GREY = "var(--color-data-neutral)";
const BLUE = token("blue");
const GREEN = token("green");
const TEAL = token("teal");
const PURPLE = token("purple");
const ORANGE = token("orange");
const RED = token("red");

const present = (v: unknown): v is number => v !== null && v !== undefined;
const isAfter = (b: Block) => b.index >= 0;
export const blockLabel = (b: Block) => (b.name || b.start || String(b.index)) + (b.partial ? " (running)" : "");

export type UpliftRow = {
  label: string; after: boolean; value: number | null; median: number | null; average: number | null;
  beforeMedian: number | null; beforeAverage: number | null; afterMedian: number | null; afterAverage: number | null;
};

/** One row per 30-day block; the person's own before/after figures are drawn only on their side of Day 0. */
export function buildRows(graph: unknown): UpliftRow[] {
  const g = (graph ?? {}) as Graph;
  const blocks = Array.isArray(g.blocks) ? g.blocks : [];
  const before = g.person?.before ?? {};
  const after = g.person?.after ?? {};
  const pick = (side: Side, key: keyof Side, on: boolean, b: Block) =>
    isAfter(b) === on && present(side[key]) ? (side[key] as number) : null;
  return blocks.map((b) => ({
    label: blockLabel(b), after: isAfter(b),
    value: present(b.value) ? b.value : null,
    median: present(b.median) ? b.median : null,
    average: present(b.average) ? b.average : null,
    beforeMedian: pick(before, "median", false, b), beforeAverage: pick(before, "average", false, b),
    afterMedian: pick(after, "median", true, b), afterAverage: pick(after, "average", true, b),
  }));
}

export function UpliftChart(props: { cohort: unknown; compare: string; threshold?: number }): JSX.Element {
  const who = props.compare ? "the comparison group" : "everyone"; // compare is the raw URL value
  const rows = buildRows(props.cohort);
  if (!rows.length) return <p>No blocks to chart yet.</p>;
  const first = rows.find((r) => r.after);
  const line = (key: keyof UpliftRow, name: string, stroke: string, dash?: string) => (
    <Line key={key} dataKey={key} name={name} stroke={stroke} strokeWidth={2} strokeDasharray={dash}
      dot={false} connectNulls={false} isAnimationActive={false} />
  );
  return (
    <div role="img" aria-label={`Blocks of 30 days around Day 0 against the median and average of ${who}`}>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Bar dataKey="value" name="Person" maxBarSize={36} radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.label}
                fill={!r.after ? GREY : present(r.value) && present(r.median) && r.value >= r.median ? GREEN : BLUE} />
            ))}
          </Bar>
          {line("median", `Median of ${who} that month`, "currentColor", "6 4")}
          {line("average", `Average of ${who} that month`, ORANGE, "2 3")}
          {line("beforeMedian", "Own median, before Day 0", TEAL)}
          {line("afterMedian", "Own median, after Day 0", TEAL)}
          {line("beforeAverage", "Own average, before Day 0", PURPLE, "6 4")}
          {line("afterAverage", "Own average, after Day 0", PURPLE, "6 4")}
          {present(props.threshold) && <ReferenceLine y={props.threshold} ifOverflow="extendDomain" stroke={RED} strokeWidth={2} label="Threshold" />}
          {first && <ReferenceLine x={first.label} stroke="currentColor" strokeWidth={2} label="Day 0" />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

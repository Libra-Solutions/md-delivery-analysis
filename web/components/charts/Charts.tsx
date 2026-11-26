"use client";
import {
  Bar, BarChart as RBarChart, CartesianGrid, Legend, Line, LineChart as RLineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fmt } from "@/lib/format";

// Categorical colours cycle through the Astryx data tokens (dataVars custom properties).
const NAMES = ["blue", "orange", "purple", "green", "pink", "cyan", "red", "teal", "brown", "indigo"];
export function seriesColour(i: number): string {
  return `var(--color-data-categorical-${NAMES[i % NAMES.length]})`;
}

export type LineSeries = { label: string; points: { x: string; y: number | null }[] };
export type BarItem = { label: string; value: number };

export function LineChart({ series, unit }: { series: LineSeries[]; unit?: string }) {
  const xs: string[] = [];
  for (const s of series) for (const p of s.points) if (!xs.includes(p.x)) xs.push(p.x);
  const data = xs.map((x) => {
    const row: Record<string, string | number | null> = { x };
    for (const s of series) row[s.label] = s.points.find((p) => p.x === x)?.y ?? null;
    return row;
  });
  const format = (v: unknown) => fmt(typeof v === "number" ? v : null, unit);
  return (
    <div role="img" aria-label={series.map((s) => s.label).join(", ")}>
      <ResponsiveContainer width="100%" height={260}>
        <RLineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="x" />
          <YAxis tickFormatter={format} />
          <Tooltip formatter={(v) => format(v)} />
          {series.length > 1 && <Legend />}
          {series.map((s, i) => (
            <Line key={s.label} type="monotone" dataKey={s.label} stroke={seriesColour(i)}
              strokeWidth={2} dot={{ r: 2 }} connectNulls={false} isAnimationActive={false} />
          ))}
        </RLineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BarChart({ bars, unit }: { bars: BarItem[]; unit?: string }) {
  const format = (v: unknown) => fmt(typeof v === "number" ? v : null, unit);
  return (
    <div role="img" aria-label={bars.map((b) => b.label).join(", ")}>
      <ResponsiveContainer width="100%" height={260}>
        <RBarChart data={bars}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" />
          <YAxis tickFormatter={format} />
          <Tooltip formatter={(v) => format(v)} />
          <Bar dataKey="value" fill={seriesColour(0)} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
        </RBarChart>
      </ResponsiveContainer>
    </div>
  );
}

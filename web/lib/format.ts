export type Trend = { text: string; kind: "" | "good" | "bad" };

export function fmt(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined) {
    return "–";
  }
  if (unit === "ratio") {
    return `${Math.round(value * 100)}%`;
  }
  if (unit === "hours") {
    return value >= 48 ? `${(value / 24).toFixed(1)} d` : `${value.toFixed(1)} h`;
  }
  if (unit === "usd") {
    return `$${value.toFixed(2)}`;
  }
  if (unit === "points_per_usd") {
    return value.toFixed(2);
  }
  if (unit === "multiple") {
    return `${value.toFixed(2)}x`;
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function trendInfo(trend: number | null, better?: string): Trend {
  if (trend === null || trend === undefined) {
    return { text: "–", kind: "" };
  }
  const pct = Math.round(trend * 100);
  const up = pct > 0;
  let kind: Trend["kind"] = "";
  if (better === "higher" && pct !== 0) {
    kind = up ? "good" : "bad";
  }
  if (better === "lower" && pct !== 0) {
    kind = up ? "bad" : "good";
  }
  const prefix = up ? "▲ +" : pct < 0 ? "▼ " : "";
  return { text: `${prefix}${pct}%`, kind };
}

export function ago(iso: string | null, now: number = Date.now()): string {
  if (!iso) {
    return "never";
  }
  const minutes = Math.round((now - Date.parse(iso)) / 60000);
  if (minutes < 1) {
    return "just now";
  }
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  if (minutes < 48 * 60) {
    return `${Math.round(minutes / 60)} h ago`;
  }
  return `${Math.round(minutes / 1440)} d ago`;
}

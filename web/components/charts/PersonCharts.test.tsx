import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const state = vi.hoisted(() => ({ paths: [] as (string | null)[] }));

const weekly = {
  weeks: ["2026-11-02", "2026-11-09"], running: "2026-11-09", points: [5, 8], median: [4, null], average: [4.5, 6],
  comparison: { custom: false, people: [] },
};
const series = {
  dates: ["2026-11-01", "2026-11-02", "2026-11-03"],
  series: {
    delivery: [3, null, 5], participation: [1, 2, 3], impact_per_dollar: [null, null, null], delivery_speed: [null, null, null],
    durability: [null, null, null], prs_reviewed: [null, null, null], review_value: [null, null, null],
  },
  team_median: {
    impact: [2, 3, 4], delivery: [2, 2, 2], participation: [1, 1, 1], impact_per_dollar: [], delivery_speed: [],
    durability: [], prs_reviewed: [], review_value: [],
  },
  summary: { window_days: 30, impact: 12, claude_cost: null },
  comparison: { custom: false },
  notes: [],
};
const group = { custom: false, people: [{ person_id: "p1", name: "Ada", selected: true }, { person_id: "p2", name: "Bo", selected: true }] };

vi.mock("@/lib/query", () => ({
  useApi: (path: string | null) => {
    state.paths.push(path);
    if (!path) return { data: undefined };
    if (path.includes("/weekly-points")) return { data: weekly };
    if (path.includes("/series")) return { data: series };
    if (path.includes("/comparison")) return { data: group };
    return { data: undefined };
  },
  useWrite: () => vi.fn(),
}));
vi.mock("@/components/charts/Charts", () => ({ seriesColour: (i: number) => "c" + i }));
vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: Box,
    ComposedChart: ({ data, children }: { data: unknown[]; children?: React.ReactNode }) => (
      <div data-testid="chart" data-rows={JSON.stringify(data)}>{children}</div>
    ),
    Bar: ({ dataKey }: { dataKey: string }) => <i data-testid="bar" data-key={dataKey} />,
    Line: ({ dataKey, strokeDasharray, connectNulls }: { dataKey: string; strokeDasharray?: string; connectNulls?: boolean }) => (
      <i data-testid="line" data-key={dataKey} data-dash={strokeDasharray ?? ""} data-connect={String(connectNulls)} />
    ),
    CartesianGrid: () => null, Legend: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null,
  };
});

import { PersonCharts } from "./PersonCharts";

const filters = (team: string) => ({ team, window: "", from: "", to: "", metric: "", inactive: "", id: "p1" });

afterEach(() => { cleanup(); state.paths.length = 0; });

describe("PersonCharts", () => {
  it("no_team_shows_pick_a_team_prompt", () => {
    render(<PersonCharts personId="p1" filters={filters("")} />);
    expect(screen.getByText("Who counts as the team? Pick a team in the Team box at the top first")).toBeTruthy();
    expect(screen.getByText("Without a team the dashed line is the median of everyone.")).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(state.paths.some((p) => p?.includes("/comparison"))).toBe(false);
    expect(screen.getAllByTestId("line").some((l) => l.getAttribute("data-key") === "Everyone's median")).toBe(true);
  });

  it("team_comparison_draws_dashed_median", () => {
    render(<PersonCharts personId="p1" filters={filters("core")} />);
    expect(state.paths).toContain("/api/person/p1/series?window_days=30&team=core");
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    const medians = screen.getAllByTestId("line").filter((l) => l.getAttribute("data-key") === "Team median");
    expect(medians.length).toBeGreaterThan(0);
    medians.forEach((l) => {
      expect(l.getAttribute("data-dash")).toBe("6 4");
      expect(l.getAttribute("data-connect")).toBe("false");
    });
    // a missing delivery point stays null so the line breaks
    const rows = screen.getAllByTestId("chart").map((c) => JSON.parse(c.getAttribute("data-rows") ?? "[]"));
    expect(rows.some((r: { Delivery?: number | null }[]) => r.some((x) => x.Delivery === null))).toBe(true);
  });

  it("weekly_points_bars", () => {
    render(<PersonCharts personId="p1" filters={filters("core")} />);
    const bars = screen.getAllByTestId("bar").filter((b) => b.getAttribute("data-key") === "Story points");
    expect(bars).toHaveLength(1);
    const first = JSON.parse(screen.getAllByTestId("chart")[0].getAttribute("data-rows") ?? "[]");
    expect(first.map((r: { x: string }) => r.x)).toEqual(["2026-11-02", "2026-11-09 (running)"]);
    expect(first[1]["Team median"]).toBeNull();
  });
});

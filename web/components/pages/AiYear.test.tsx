import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const state = vi.hoisted(() => ({ paths: [] as (string | null)[], id: "p 1", setParam: vi.fn() }));

const stats = (m: number) => ({ median: m, average: m, low: 1, high: 9, count: 6 });
const detail: any = {  // eslint-disable-line @typescript-eslint/no-explicit-any
  compare: { value: "everyone", label: "Everyone" }, person: { name: "Ada" }, level: "Senior", ai_start: "2026-03-01", at_data_start: false,
  by: "month", board: null, coverage: { jira: "2026-11-01" }, notes: ["A note."],
  graphs: {
    prs_merged: {
      blocks: [{ start: "2026-01", value: 3 }], projects: [], short_baseline: false,
      person: { before: stats(2), after: stats(4) }, everyone: { before: stats(3), after: stats(3) },
      effect: { person: { median: { change: 2, ratio: 2 }, average: { change: 2 } }, group: { median: { change: 0, ratio: 1 }, average: { change: 0 } }, vs_group: 1 },
    },
  },
  expectations: [{ label: "First window", first: "2026-03-01", days: 90, items: [{ item: "Merged PRs", verdict: "meets", value: 7, threshold: 5 }] }],
};

vi.mock("@/lib/query", () => ({
  useApi: (path: string | null) => {
    state.paths.push(path);
    if (path === "/api/uplift/year/people") {
      return { data: { people: [{ person_id: "p 1", name: "Ada", level: "Senior", ai_start: "2026-03-01" }] } };
    }
    if (path && path.startsWith("/api/uplift/year/person/")) return { data: detail };
    return { data: undefined };
  },
}));
vi.mock("@/lib/filters", () => ({
  useFilters: () => ({ team: "core", window: "", from: "", to: "", metric: "", inactive: "", id: state.id }),
  useSetParam: () => state.setParam,
  filterQuery: (f: Record<string, string>, extra: Record<string, string> = {}) => {
    const p = new URLSearchParams();
    if (f.team) p.set("team", f.team);
    Object.entries(extra).forEach(([k, v]) => { if (v) p.set(k, v); });
    return p.toString() ? "?" + p : "";
  },
}));
vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: Box, ComposedChart: Box, Cell: () => null, Legend: () => null, Tooltip: () => null,
    CartesianGrid: () => null, XAxis: () => null, YAxis: () => null,
    Bar: ({ dataKey, stackId }: { dataKey: string; stackId?: string }) => <i data-testid="bar" data-key={dataKey} data-stack={stackId} />,
    Line: () => null,
  };
});
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("") }));
vi.mock("@/components/charts/Charts", () => ({ seriesColour: (i: number) => "c" + i }));
vi.mock("@/components/charts/UpliftCharts", () => ({ UpliftChart: () => <div data-testid="uplift-chart" /> }));
vi.mock("@/components/pages/Uplift", () => ({
  ComparePicker: () => null,
  useCompare: () => ({ compare: "", isCustom: false, ids: [] }),
  coverageLine: (c: Record<string, string | null> | undefined) => Object.keys(c ?? {}).map((k) => k + ": " + c?.[k]).join(" · "),
}));

import { AiYear } from "./AiYear";

afterEach(() => { cleanup(); state.paths.length = 0; });

describe("AiYear", () => {
  it("year_people_rows", () => {
    render(<AiYear />);
    expect(screen.getAllByText("Ada · Senior · AI start 2026-03-01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Before AI")).toHaveLength(2);
    expect(screen.getAllByText("Since AI")).toHaveLength(2);
    expect(screen.getByText("Merged PRs")).toBeTruthy();
    expect(screen.getByText("meets")).toBeTruthy();
  });

  it("stacks_bars_per_project", () => {
    const g = detail.graphs.prs_merged;
    g.projects = ["ABC", "XYZ"];
    g.blocks = [{ start: "2026-01", index: -1, value: 3, projects: { ABC: 2, XYZ: 1 } }];
    render(<AiYear />);
    const bars = screen.getAllByTestId("bar");
    expect(bars.map((b) => b.getAttribute("data-key"))).toEqual(["ABC", "XYZ"]);
    expect(bars.every((b) => b.getAttribute("data-stack") === "person")).toBe(true);
    g.projects = [];
  });

  it("person_detail_on_id_param", () => {
    render(<AiYear />);
    expect(state.paths).toContain("/api/uplift/year/person/p%201?team=core");
    expect(screen.getByText("Ada")).toBeTruthy();
  });
});

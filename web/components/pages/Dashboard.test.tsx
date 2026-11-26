import { afterEach, describe, it, expect, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const params = vi.hoisted(() => ({ metric: "" }));
const names = vi.hoisted(() => ({ person: "Ada" }));

const fixtures: Record<string, unknown> = {
  story_points_weekly: { status: "ok", rows: [{ week: "2026-11-02", value: 8, issues: 3, unpointed: 1 }], notes: [] },
  story_points_done: { status: "ok", rows: [], team: { value: 8, trend: 0.12, previous: 5 }, notes: [] },
  review_load: { status: "ok", unit: "count", rows: [{ name: "x", value: 3 }], notes: [] },
};

vi.mock("@/lib/query", () => ({
  useApi: (path: string | null) => {
    if (!path) return { data: undefined, isPending: false, error: null };
    if (path === "/api/metrics") return { data: { metrics: [] }, isPending: false, error: null };
    const m = /^\/api\/metrics\/([a-z_]+)/.exec(path);
    const key = m?.[1] ?? "";
    let data: unknown = fixtures[key] ?? { status: "waiting", missing: ["jira"], rows: [] };
    if (key === "review_load") {
      data = { ...(data as object), rows: [{ name: names.person, value: 3 }] };
    }
    return { data, isPending: false, error: null };
  },
}));
vi.mock("@/lib/filters", () => ({
  useFilters: () => ({ team: "core", window: "", from: "", to: "", metric: params.metric, inactive: "", id: "" }),
  filterQuery: (f: { team?: string }) => (f.team ? `?team=${f.team}` : ""),
  useSetParam: () => vi.fn(),
}));
vi.mock("@/components/charts/Charts", () => ({
  LineChart: () => <div data-testid="line-chart" />,
  BarChart: ({ bars }: { bars: { label: string }[] }) => <div data-testid="bar-chart">{bars.map((b) => b.label).join(",")}</div>,
}));

import { Dashboard } from "./Dashboard";

afterEach(cleanup);

describe("Dashboard", () => {
  it("renders_metric_cards_with_fmt", () => {
    params.metric = "";
    render(<Dashboard />);
    expect(screen.getByText("Impact delivered")).toBeTruthy();
    expect(screen.getByText("▲ +12%")).toBeTruthy();
    expect(screen.getByText("vs previous window (5 points)")).toBeTruthy();
    expect(screen.getAllByText("Waiting for Jira data. This fills in when that source is connected.").length).toBeGreaterThan(0);
  });

  it("metric_param_opens_detail", () => {
    params.metric = "points_by_type";
    render(<Dashboard />);
    expect(screen.getByRole("heading", { name: "Where it went" })).toBeTruthy();
    expect(screen.queryByText("Impact delivered")).toBeNull();
    expect(screen.getByText("Back to dashboard")).toBeTruthy();
  });

  it("script_in_name_is_text", () => {
    params.metric = "";
    names.person = "<script>alert(1)</script>";
    const { container } = render(<Dashboard />);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getAllByText("<script>alert(1)</script>").length).toBeGreaterThan(0);
  });
});

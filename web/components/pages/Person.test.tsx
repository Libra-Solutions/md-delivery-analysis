import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

const state = vi.hoisted(() => ({
  setParam: vi.fn(),
  teams: [{ team_id: "t1", name: "One" }] as { team_id: string; name: string }[],
  filters: { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "p1" } as Record<string, string>,
}));

const detail = {
  person: { name: "Ada", accounts: ["ada"], emails: ["a@x.io"] }, window: { label: "Last 30 days" },
  commits_weekly: [{ week: "2026-11-02", value: 4 }], reviews_pending: [], issues_done: null,
  pull_requests: [], reviews_given: [],
};
const tickets = {
  tickets: [{ key: "T-1", type: "Story", points: 3, cost_usd: 1.5, points_per_usd: 2, confidence: "high", pull_requests: 2, hours_to_merge: 5 }],
  cost_weekly: [], notes: [],
};

vi.mock("@/lib/query", () => ({
  useApi: (path: string | null) => {
    if (!path) return { data: undefined };
    if (path === "/api/teams") return { data: { teams: state.teams } };
    if (path.startsWith("/api/people?")) return { data: { people: [{ person_id: "p1", name: "Ada" }, { person_id: "p2", name: "Bob", status: "inactive" }] } };
    if (path.startsWith("/api/people/")) return { data: detail };
    if (path.startsWith("/api/tickets")) return { data: tickets };
    if (path.startsWith("/api/metrics/")) return { data: { status: "ok", unit: "", rows: [] } };
    return { data: undefined };
  },
}));
vi.mock("@/lib/filters", () => ({
  useFilters: () => state.filters,
  useSetParam: () => state.setParam,
  filterQuery: (f: Record<string, string>, extra: Record<string, string> = {}) => {
    const p = new URLSearchParams();
    if (f.team) p.set("team", f.team);
    for (const [k, v] of Object.entries(extra)) if (v) p.set(k, v);
    return p.toString() ? "?" + p : "";
  },
}));
vi.mock("@/lib/format", () => ({ fmt: (v: number | null | undefined) => (v === null || v === undefined ? "–" : String(v)) }));
vi.mock("@/components/charts/Charts", () => ({ BarChart: () => <div data-testid="bar" /> }));
vi.mock("@/components/charts/PersonCharts", () => ({ PersonCharts: ({ personId }: { personId: string }) => <div data-testid="pc">{personId}</div> }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import { Person } from "./Person";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  state.teams = [{ team_id: "t1", name: "One" }];
  state.filters = { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "p1" };
});

describe("Person", () => {
  it("single_team_is_auto_selected", () => {
    render(<Person />);
    expect(state.setParam).toHaveBeenCalledWith("team", "t1");
    cleanup();
    state.setParam.mockClear();
    state.teams = [{ team_id: "t1", name: "One" }, { team_id: "t2", name: "Two" }];
    render(<Person />);
    expect(state.setParam).not.toHaveBeenCalledWith("team", expect.anything());
  });

  it("tickets_table_rows", () => {
    render(<Person />);
    expect(screen.getByText("T-1")).toBeInTheDocument();
    expect(screen.getByText("Story")).toBeInTheDocument();
    expect(screen.getByTestId("pc")).toHaveTextContent("p1");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Ada");
  });

  it("csv_link_for_person", () => {
    state.filters.team = "t1";
    render(<Person />);
    expect(screen.getByRole("link", { name: "Download CSV" })).toHaveAttribute("href", "/api/people/p1/export.csv?team=t1");
  });
});

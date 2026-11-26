import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const state = vi.hoisted(() => ({
  setParam: vi.fn(),
  paths: [] as (string | null)[],
  filters: { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "" } as Record<string, string>,
}));

const catalog = {
  metrics: [
    { name: "impact_points", label: "Impact points", kind: "per_person", group: "impact", description: "Points shipped" },
    { name: "cycle", label: "Cycle time", kind: "per_person", group: "delivery", description: "d" },
    { name: "team_only", label: "Team thing", kind: "team", group: "delivery" },
  ],
};
const result = {
  label: "Impact points", unit: "points", better: "higher", window: { label: "Last 30 days" },
  team: { value: 12, sample: 3 },
  rows: [
    { rank: 1, person_id: "p1", name: "Ada", ranked: true, value: 10, previous: 8, trend: 0.25, sample: 4 },
    { rank: null, person_id: "p2", name: "Bob", ranked: false, unranked_reason: "too few", value: 1, previous: null, trend: null, sample: 1 },
  ],
};

vi.mock("@/lib/query", () => ({
  useApi: (path: string | null) => {
    state.paths.push(path);
    if (path === "/api/metrics") return { data: catalog };
    if (path && path.startsWith("/api/metrics/")) return { data: result };
    return { data: undefined };
  },
}));
vi.mock("@/lib/filters", () => ({
  useFilters: () => state.filters,
  useSetParam: () => state.setParam,
  filterQuery: (_f: unknown, extra: Record<string, string> = {}) => {
    const p = new URLSearchParams(Object.entries(extra).filter(([, v]) => v));
    return p.toString() ? "?" + p : "";
  },
}));
vi.mock("@/lib/format", () => ({
  fmt: (v: number | null) => (v === null ? "–" : String(v)),
  trendInfo: (t: number | null) => (t === null ? { text: "–", kind: "" } : { text: "▲ +25%", kind: "good" }),
}));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import { Rankings } from "./Rankings";

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  state.paths = [];
  state.filters = { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "" };
});

describe("Rankings", () => {
  it("ranks_by_selected_metric", () => {
    state.filters.metric = "cycle";
    render(<Rankings />);
    expect(state.paths).toContain("/api/metrics/cycle");
    expect(screen.getByRole("link", { name: "Ada" })).toHaveAttribute("href", "/person?id=p1");
    expect(screen.getByText(/unranked: too few/)).toBeInTheDocument();
    expect(screen.getByText(/all repositories/)).toBeInTheDocument();
    expect(screen.getByText("▲ +25%").closest("[data-kind]")).toHaveAttribute("data-kind", "good");
    expect(screen.queryByText("Team thing")).toBeNull();
  });

  it("metric_select_sets_param", async () => {
    render(<Rankings />);
    expect(state.paths).toContain("/api/metrics/impact_points");
    fireEvent.click(screen.getByRole("combobox", { name: /Metric/ }));
    fireEvent.click(await screen.findByRole("option", { name: /Cycle time/ }));
    expect(state.setParam).toHaveBeenCalledWith("metric", "cycle");
    fireEvent.click(screen.getByRole("checkbox", { name: /include inactive/ }));
    expect(state.setParam).toHaveBeenCalledWith("inactive", "1");
  });
});

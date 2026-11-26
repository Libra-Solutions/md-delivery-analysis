import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const state = vi.hoisted(() => ({
  setParam: vi.fn(),
  paths: [] as (string | null)[],
  filters: { team: "core", window: "", from: "", to: "", metric: "", inactive: "", id: "" } as Record<string, string>,
  search: "" as string,
}));

const cohort = {
  compare: { value: "everyone", label: "everyone" },
  coverage: { jira: "2026-01-02", claude_usage: null },
  people: [
    {
      person_id: "p1", name: "<b>Ada</b>", level: "Senior", day_reached: 40,
      at_or_above_median: { before: { count: 2, of: 5 }, after: { count: 3, of: 4 } },
      grid: [{ value: 5, median: 4 }, { value: null, median: null }, { value: 2, median: 3, partial: true }], points: { marker: "p1-points" },
    },
  ],
};
const detail = {
  compare: { value: "everyone", label: "everyone" }, person: { name: "Ada" }, level: "Senior", day0: "2026-01-01", day_reached: 40,
  coverage: {}, graphs: {}, points_by_merge: [], windows: [], verdicts: [], quality: [{ metric: "durability", threshold: 0.8, blocks: { q: 1 } }], how_they_worked: {},
  ai: { starts: null, weeks: [] }, explain: ["It went up."],
};

vi.mock("@/lib/query", () => ({
  useApi: (path: string | null) => {
    state.paths.push(path);
    if (path === "/api/uplift/compare-options") {
      return { data: { options: [{ value: "everyone", label: "Everyone", size: 9 }, { value: "people:", label: "Custom people…" }] } };
    }
    if (path && path.startsWith("/api/uplift/cohort")) return { data: cohort };
    if (path && path.startsWith("/api/uplift/person/")) return { data: detail };
    return { data: undefined };
  },
}));
vi.mock("@/lib/filters", () => ({
  useFilters: () => state.filters,
  useSetParam: () => state.setParam,
  filterQuery: (f: Record<string, string>, extra: Record<string, string> = {}) => {
    const p = new URLSearchParams();
    if (f.team) p.set("team", f.team);
    Object.entries(extra).forEach(([k, v]) => { if (v) p.set(k, v); });
    return p.toString() ? "?" + p : "";
  },
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(state.search) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("@/components/charts/UpliftCharts", () => ({
  UpliftChart: ({ compare, cohort, threshold }: { compare: string; cohort: unknown; threshold?: number }) => <div data-testid="chart">{"chart:" + compare + ":" + JSON.stringify(cohort) + (threshold === undefined ? "" : ":t" + threshold)}</div>,
}));

import { Uplift } from "./Uplift";
import { UpliftPerson } from "./UpliftPerson";

beforeEach(() => { state.paths = []; state.search = ""; state.filters.id = ""; });
afterEach(cleanup);

describe("Uplift", () => {
  it("cohort_table_and_compare_select", () => {
    state.search = "compare=group%3Aa";
    render(<Uplift />);
    expect(state.paths).toContain("/api/uplift/compare-options");
    expect(state.paths).toContain("/api/uplift/cohort?team=core&compare=group%3Aa");
    expect(screen.getByText("Compare against")).toBeInTheDocument();
    expect(screen.getByText("Block 2")).toBeInTheDocument();
    expect(screen.getByText("2 (running)")).toBeInTheDocument();
    // names render as text, not markup
    const link = screen.getAllByText("<b>Ada</b>").map((e) => e.closest("a")).find(Boolean);
    expect(link).toHaveAttribute("href", "/uplift/person?team=core&id=p1&compare=group%3Aa");
    expect(screen.getByText(/Data covered up to jira: 2026-01-02 · claude usage: –/)).toBeInTheDocument();
    expect(screen.getByTestId("chart")).toHaveTextContent('chart:group:a:{"marker":"p1-points"}');
  });

  it("uplift_person_reads_id_param", () => {
    state.filters.id = "p 1";
    render(<UpliftPerson />);
    expect(state.paths).toContain("/api/uplift/person/p%201?team=core");
    expect(screen.getByRole("heading", { name: "Ada" })).toBeInTheDocument();
    expect(screen.getByText("It went up.")).toBeInTheDocument();
    expect(screen.getAllByTestId("chart").some((c) => c.textContent === 'chart::{"q":1}:t0.8')).toBe(true);
  });

  it("uplift_person_without_id_asks_for_one", () => {
    render(<UpliftPerson />);
    expect(screen.getByText("Choose a person from the cohort page.")).toBeInTheDocument();
    expect(state.paths).not.toContain(expect.stringContaining("/api/uplift/person/"));
  });
});

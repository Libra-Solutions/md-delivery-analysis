import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

const data = {
  project: "PROJ", window: { start: "2026-01-01", end: "2026-06-30" }, unsprinted_tested: 2,
  headline: { sprint: { name: "S2", fail_rate: 0.25, escape_rate: 0.1 }, release: { release: "1.02", bugs: 3 } },
  sprints: [
    { name: "S1", in_progress: false, tested: 8, failed: 2, failed_keys: ["A-1", "A-2"], fail_rate: 0.25, sub_bugs_per_story: 0.5, defects: 1, defect_keys: ["D-1"], bugs: 2, sub_bugs: 1, escape_rate: 0.1 },
    { name: "S2", in_progress: true, tested: 4, failed: 0, failed_keys: [], fail_rate: 0, sub_bugs_per_story: null, defects: 0, defect_keys: [], bugs: 0, sub_bugs: 0, escape_rate: null },
  ],
  months: [{ month: "2026-01", defects: 1, defect_keys: ["D-1"], bugs: 2, sub_bugs: 1, escape_rate: 0.25 }],
  releases: [{ release: "1.02", in_progress: false, bugs: 3, bug_keys: ["B-1"], regression_stories: ["R-1", "R-2"] }],
};

vi.mock("@/lib/query", () => ({ useApi: (p: string) => ({ data: p === "/api/qa" ? data : undefined }) }));
vi.mock("@/lib/filters", () => ({
  useFilters: () => ({ team: "t1", window: "30d", from: "", to: "", metric: "", inactive: "", id: "" }),
  filterQuery: (f: { team: string; window: string }) => `?team=${f.team}&window=${f.window}`,
}));
vi.mock("@/lib/format", () => ({
  fmt: (v: number | null | undefined, unit?: string) => (v === null || v === undefined ? "–" : unit === "ratio" ? Math.round(v * 100) + "%" : String(v)),
}));
vi.mock("@/components/charts/Charts", () => ({ LineChart: () => <div data-testid="line" />, BarChart: () => <div data-testid="bar" /> }));

import { Qa } from "./Qa";

afterEach(cleanup);

describe("Qa", () => {
  it("shows_fail_rate_by_sprint", () => {
    render(<Qa />);
    expect(screen.getAllByText("S1").length).toBe(2);
    expect(screen.getAllByText("S2 (in progress)").length).toBe(2);
    expect(screen.getByText("QA fail rate · S2")).toBeInTheDocument();
    expect(screen.getAllByText("25%").length).toBeGreaterThan(0);
    expect(screen.getByText(/2 tested Stories had no sprint/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "2" }));
    expect(screen.getByText("A-1, A-2")).toBeInTheDocument();
  });

  it("csv_link_keeps_filters", () => {
    render(<Qa />);
    expect(screen.getByRole("link", { name: "Download CSV" })).toHaveAttribute("href", "/api/qa/export.csv?team=t1&window=30d");
  });
});

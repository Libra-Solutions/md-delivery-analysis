import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const state = vi.hoisted(() => ({
  setParam: vi.fn(),
  paths: [] as (string | null)[],
  filters: { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "" } as Record<string, string>,
}));

const matrix = {
  columns: [
    { name: "impact_points", label: "Impact points", unit: "points", group: "impact", status: "ok" },
    { name: "cycle", label: "Cycle", unit: "days", better: "lower", group: "delivery", status: "ok" },
    { name: "review_value", label: "Review value", status: "waiting", missing: ["bitbucket"] },
  ],
  rows: [
    { person_id: "p1", name: "Ada", cells: { impact_points: { value: 10, ranked: true }, cycle: { value: 2, ranked: true } } },
    { person_id: null, name: "Unmapped", cells: {} },
  ],
  notes: ["A note"],
};

vi.mock("@/lib/query", () => ({
  useApi: (path: string | null) => {
    state.paths.push(path);
    return { data: matrix };
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
vi.mock("@/lib/format", () => ({ fmt: (v: number | null) => (v === null ? "–" : String(v)) }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("") }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import { People } from "./People";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  state.paths = [];
  state.filters = { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "" };
});

describe("People", () => {
  it("matrix_rows_link_to_person", () => {
    render(<People />);
    expect(state.paths).toContain("/api/people-matrix");
    expect(screen.getByRole("link", { name: "Ada" })).toHaveAttribute("href", "/person?id=p1");
    expect(screen.getByText("Unmapped")).toBeInTheDocument();
    expect(screen.getByText(/Review value \(waiting for bitbucket\)/)).toBeInTheDocument();
    expect(screen.getByText("A note")).toBeInTheDocument();
  });

  it("inactive_toggle_sets_param", () => {
    render(<People />);
    fireEvent.click(screen.getByRole("checkbox", { name: /include inactive/ }));
    expect(state.setParam).toHaveBeenCalledWith("inactive", "1");
    fireEvent.click(screen.getByRole("button", { name: /Cycle/ }));
    expect(state.setParam).toHaveBeenCalledWith("sort", "cycle");
    expect(state.setParam).toHaveBeenCalledWith("dir", "asc");
  });
});

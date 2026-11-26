import { cloneElement, type ReactElement } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("recharts", async (orig) => {
  const mod = await orig<typeof import("recharts")>();
  return {
    ...mod,
    ResponsiveContainer: ({ children, height }: { children: ReactElement<{ width?: number; height?: number }>; height: number }) => (
      <div style={{ width: 600, height }}>{cloneElement(children, { width: 600, height })}</div>
    ),
  };
});
import { UpliftChart, buildRows } from "./UpliftCharts";

const graph = {
  blocks: [
    { index: -1, name: "B-1", value: 2, median: 3, average: 3 },
    { index: 0, name: "B0", value: 4, median: 3, average: 3 },
    { index: 1, name: "B1", value: null, median: 3, average: 3, partial: true },
  ],
  person: { before: { median: 2, average: 2.5 }, after: { median: 4, average: 4.5 } },
};

describe("UpliftChart", () => {
  it("before_after_split_at_cutover", () => {
    const rows = buildRows(graph);
    expect(rows.map((r) => r.beforeMedian)).toEqual([2, null, null]);
    expect(rows.map((r) => r.afterMedian)).toEqual([null, 4, 4]);
    expect(rows.map((r) => r.value)).toEqual([2, 4, null]);
    expect(rows[2].label).toBe("B1 (running)");
  });

  it("comparison_series_dashed", () => {
    const { container } = render(<UpliftChart cohort={graph} compare="group:a" />);
    const dashed = Array.from(container.querySelectorAll("path.recharts-line-curve"))
      .filter((p) => p.getAttribute("stroke-dasharray"));
    expect(dashed.length).toBeGreaterThanOrEqual(1);
    expect(container.querySelector('[aria-label*="the comparison group"]')).not.toBeNull();
  });

  it("threshold_line_drawn", () => {
    const plain = render(<UpliftChart cohort={graph} compare="" />);
    const without = plain.container.querySelectorAll(".recharts-reference-line").length;
    plain.unmount();
    const { container, getByText } = render(<UpliftChart cohort={graph} compare="" threshold={0.7} />);
    expect(container.querySelectorAll(".recharts-reference-line").length).toBe(without + 1);
    expect(getByText("Threshold")).toBeTruthy();
  });
});

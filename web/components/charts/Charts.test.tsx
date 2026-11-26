import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/format", () => ({
  fmt: (v: number | null | undefined, unit?: string) =>
    v == null ? "-" : unit === "ratio" ? `${Math.round(v * 100)}%` : String(v),
}));
vi.mock("recharts", async (orig) => {
  const mod = await orig<typeof import("recharts")>();
  return {
    ...mod,
    ResponsiveContainer: ({ children, height }: { children: React.ReactElement; height: number }) =>
      <div style={{ width: 600, height }}>{(children as React.ReactElement<{ width?: number; height?: number }>) && 
        // give the chart a fixed size so jsdom can render it
        (require("react") as typeof import("react")).cloneElement(children as React.ReactElement<{ width?: number; height?: number }>, { width: 600, height })}</div>,
  };
});
import { BarChart, LineChart } from "./Charts";

beforeAll(() => {
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
});

describe("charts", () => {
  it("line_chart_renders_one_path_per_series", () => {
    const { container } = render(
      <LineChart series={[
        { label: "A", points: [{ x: "w1", y: 1 }, { x: "w2", y: null }, { x: "w3", y: 3 }] },
        { label: "B", points: [{ x: "w1", y: 2 }, { x: "w2", y: 2 }, { x: "w3", y: 4 }] },
      ]} />,
    );
    expect(container.querySelectorAll("path.recharts-line-curve").length).toBe(2);
  });

  it("bar_chart_labels", () => {
    render(<BarChart bars={[{ label: "Alpha", value: 1 }, { label: "Beta", value: 2 }]} />);
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
  });

  it("tooltip_uses_fmt_unit", async () => {
    render(<BarChart bars={[{ label: "Alpha", value: 0.42 }]} unit="ratio" />);
    const ticks = await screen.findAllByText(/%$/);
    expect(ticks.length).toBeGreaterThan(0);
  });
});

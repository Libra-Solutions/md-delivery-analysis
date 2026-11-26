import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const state = vi.hoisted(() => ({
  sources: {} as unknown,
  refetch: vi.fn(),
  write: vi.fn(),
  recheck: vi.fn(),
  setParam: vi.fn(),
  filters: { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "" } as Record<string, string>,
}));

vi.mock("@/lib/query", () => ({
  useApi: (path: string) =>
    path === "/api/teams"
      ? { data: { teams: [{ team_id: "t1", name: "Team One" }] } }
      : { data: state.sources, refetch: state.refetch },
  useWrite: () => state.write,
  recheckVersion: state.recheck,
}));
vi.mock("@/lib/filters", () => ({
  useFilters: () => state.filters,
  useSetParam: () => state.setParam,
  windowOptions: () => [["", "Team default"], ["30d", "Last 30 days"], ["custom", "Custom dates"]],
}));
vi.mock("@/lib/format", () => ({ ago: (iso: string | null) => (iso ? "5 min ago" : "never") }));

import { Header } from "./Header";

const sources = (running: boolean) => ({
  sources: [
    { connector: "jira", failed: false, age_minutes: 10, last_run: "x", error: null },
    { connector: "bitbucket", failed: false, age_minutes: 500, last_run: "y", error: null },
    { connector: "claude_usage", failed: true, age_minutes: 1, last_run: "z", error: "boom <b>" },
  ],
  configured: ["jira", "bitbucket", "claude_usage"],
  waiting: ["confluence"],
  refresh_after_minutes: 60,
  refresh: { running },
});

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  state.write.mockResolvedValue({});
  state.filters = { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "" };
  state.sources = sources(false);
});

describe("Header", () => {
  it("custom_dates_only_for_custom_window", () => {
    const { unmount } = render(<Header />);
    expect(screen.queryByLabelText("From")).toBeNull();
    unmount();
    state.filters.window = "custom";
    render(<Header />);
    expect(screen.getByLabelText("From")).toBeInTheDocument();
    expect(screen.getByLabelText("To")).toBeInTheDocument();
  });

  it("chip_kinds_from_sources", () => {
    render(<Header />);
    const kind = (t: string) => screen.getByText(t).closest("[data-kind]")?.getAttribute("data-kind");
    expect(kind("jira synced 5 min ago")).toBe("fresh");
    expect(kind("bitbucket synced 5 min ago")).toBe("stale");
    expect(kind("claude_usage failed")).toBe("failed");
    expect(screen.getByText("claude_usage failed").closest("[data-error]")).toHaveAttribute("data-error", "boom <b>");
    expect(kind("confluence not connected")).toBe("waiting");
  });

  it("finished_refresh_rechecks_version", () => {
    state.sources = sources(true);
    const { rerender } = render(<Header />);
    expect(screen.getByText("refreshing")).toBeInTheDocument();
    expect(state.recheck).not.toHaveBeenCalled();
    state.sources = sources(false);
    rerender(<Header />);
    expect(state.recheck).toHaveBeenCalledTimes(1);
  });

  it("polls_only_while_running", () => {
    vi.useFakeTimers();
    try {
      state.sources = sources(false);
      const idle = render(<Header />);
      state.refetch.mockClear();
      act(() => { vi.advanceTimersByTime(9000); });
      expect(state.refetch).not.toHaveBeenCalled();
      idle.unmount();
      state.sources = sources(true);
      render(<Header />);
      state.refetch.mockClear();
      act(() => { vi.advanceTimersByTime(9000); });
      expect(state.refetch).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("auto_refresh_posts_only_stale_once", () => {
    const { rerender } = render(<Header />);
    rerender(<Header />);
    expect(state.write).toHaveBeenCalledTimes(1);
    expect(state.write).toHaveBeenCalledWith("/api/refresh", "POST", { only_stale: true });
  });

  it("refresh_failure_shows_message", async () => {
    render(<Header />);
    state.write.mockRejectedValueOnce(new Error("nope"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Refresh failed: nope")).toBeInTheDocument();
  });
});

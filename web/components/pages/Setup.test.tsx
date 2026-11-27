import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const write = vi.fn();
const fixtures: Record<string, unknown> = {
  "/api/repos": {
    repos: [{ repository_id: "{abc/1}", workspace: "acme", slug: "web", status: "ok", last_run: null, detail_done: 3, detail_total: 4 }],
  },
  "/api/settings": {
    report_tz: "Europe/London", window_days: 90, overlap_hours: 2, refresh_after_minutes: 30,
    database: "data/da.sqlite", credentials: { BITBUCKET: true, JIRA: false },
  },
};
vi.mock("@/lib/query", () => ({
  useApi: (path: string) => ({ data: fixtures[path] }),
  useWrite: () => write,
  recheckVersion: vi.fn(),
}));

import { SelectionView, SettingsView } from "./Setup";

afterEach(cleanup);
beforeEach(() => {
  write.mockReset();
  write.mockResolvedValue({ workspace: "acme", slug: "api" });
});

describe("Setup", () => {
  it("add_repo_posts_and_rechecks", async () => {
    render(<SelectionView />);
    fireEvent.change(screen.getByLabelText(/Repository/), { target: { value: "acme/api" } });
    fireEvent.click(screen.getByText("Add repository"));
    await waitFor(() => expect(write).toHaveBeenCalledWith("/api/repos", "POST", { repo: "bitbucket:acme/api" }));
    await screen.findByText("Added acme/api.");
  });

  it("remove_repo_deletes", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SelectionView />);
    fireEvent.click(screen.getByText("Remove"));
    await waitFor(() => expect(write).toHaveBeenCalledWith("/api/repos/" + encodeURIComponent("{abc/1}"), "DELETE"));
  });

  it("settings_values_shown", () => {
    render(<SettingsView />);
    expect(screen.getByText("Europe/London")).toBeTruthy();
    expect(screen.getByText("90 days")).toBeTruthy();
    expect(screen.getByText("missing")).toBeTruthy();
  });
});

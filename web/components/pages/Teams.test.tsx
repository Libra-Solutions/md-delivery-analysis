import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const write = vi.fn();
const setParam = vi.fn();
const fixtures: Record<string, unknown> = {
  "/api/teams": {
    teams: [{ team_id: "t1", name: "Core <b>", repos: [{ repository_id: "{r1}", name: "web" }], members: { active: 2, inactive: 1, excluded: 0 } }],
  },
  "/api/repos": { repos: [{ repository_id: "{r1}", slug: "web" }, { repository_id: "{r2}", slug: "api" }] },
  "/api/teams/t1": {
    team_id: "t1", name: "Core <b>", possible_duplicates: [],
    members: [{ person_id: "p1", name: "Ann", status: "active", manual: false, last_commit: "2026-10-01T00:00:00Z", emails: ["a@x.io"] }],
  },
  "/api/teams/t1/comparison": {
    team_id: "t1", custom: false,
    people: [{ person_id: "p1", name: "Ann", selected: true }, { person_id: "p2", name: "Bob", selected: true }],
  },
  "/api/identities/unmapped": {
    unmapped: [{ source: "bitbucket", account: "acc1", name_hint: "Zed", activity: 5 }],
    people: [{ person_id: "p1", name: "Ann" }],
  },
};
vi.mock("@/lib/query", () => ({
  useApi: (path: string | null) => ({ data: path ? fixtures[path] : undefined }),
  useWrite: () => write,
  recheckVersion: vi.fn(),
}));
vi.mock("@/lib/filters", () => ({
  useFilters: () => ({ team: "t1", window: "", from: "", to: "", metric: "", inactive: "", id: "" }),
  useSetParam: () => setParam,
}));

import { TeamsView } from "./Teams";

afterEach(cleanup);
beforeEach(() => {
  write.mockReset();
  write.mockResolvedValue({ team_id: "t9", summary: "added 3" });
  setParam.mockReset();
});

describe("Teams", () => {
  it("renders names as text", () => {
    render(<TeamsView />);
    expect(screen.getAllByText("Core <b>").length).toBeGreaterThan(0);
  });

  it("create_team_posts", async () => {
    render(<TeamsView />);
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Platform" } });
    fireEvent.click(screen.getByLabelText("api"));
    fireEvent.click(screen.getByText("Create from these repositories"));
    await waitFor(() =>
      expect(write).toHaveBeenCalledWith("/api/teams", "POST", { name: "Platform", repos: ["bitbucket:{r1}"] }),
    );
    await screen.findByText("added 3");
    expect(setParam).toHaveBeenCalledWith("team", "t9");
  });

  it("member_toggle_posts", async () => {
    render(<TeamsView />);
    fireEvent.click(screen.getByText("Exclude"));
    await waitFor(() => expect(write).toHaveBeenCalledWith("/api/teams/t1/members/p1", "POST", { status: "excluded" }));
  });

  it("map_identity_posts", async () => {
    render(<TeamsView />);
    fireEvent.change(screen.getByLabelText("New person name"), { target: { value: "Zed Z" } });
    fireEvent.click(screen.getByText("Map"));
    await waitFor(() =>
      expect(write).toHaveBeenCalledWith("/api/identities", "POST", {
        source: "bitbucket", account: "acc1", team_id: "t1", new_name: "Zed Z",
      }),
    );
  });

  it("comparison_put", async () => {
    render(<TeamsView />);
    fireEvent.click(screen.getByLabelText("Bob"));
    fireEvent.click(screen.getByText("Save comparison group"));
    await waitFor(() =>
      expect(write).toHaveBeenCalledWith("/api/teams/t1/comparison", "PUT", { person_ids: ["p1"] }),
    );
    fireEvent.click(screen.getByText("Reset to whole team"));
    await waitFor(() =>
      expect(write).toHaveBeenCalledWith("/api/teams/t1/comparison", "PUT", { person_ids: null }),
    );
  });
});

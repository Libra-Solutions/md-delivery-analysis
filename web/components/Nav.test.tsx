import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let pathname = "/";
let team = "";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("@/lib/filters", () => ({
  useFilters: () => ({ team }),
  filterQuery: (f: { team?: string }) => (f.team ? `?team=${f.team}` : ""),
}));

import { Nav } from "./Nav";

afterEach(cleanup);
beforeEach(() => {
  pathname = "/";
  team = "";
});

describe("Nav", () => {
  it("links_keep_team_and_window", () => {
    team = "core";
    render(<Nav />);
    for (const a of screen.getAllByRole("link")) expect(a.getAttribute("href")).toMatch(/\?team=core$/);
  });

  it("people_active_on_people_path", () => {
    pathname = "/people";
    render(<Nav />);
    expect(screen.getByRole("link", { name: "People" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("aria-current")).toBeNull();
  });

  it("people_links_to_the_people_list_and_is_active_on_person", () => {
    pathname = "/person";
    render(<Nav />);
    const a = screen.getByRole("link", { name: "People" });
    expect(a.getAttribute("href")).toBe("/people");
    expect(a.getAttribute("aria-current")).toBe("page");
  });

  it("eleven_links_in_order", () => {
    render(<Nav />);
    expect(screen.getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Dashboard", "People", "AI uplift", "AI year", "Rankings", "QA", "Ask",
      "Selection", "Teams", "Sources", "Settings",
    ]);
  });
});

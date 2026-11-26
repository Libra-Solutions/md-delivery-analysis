import { describe, expect, it } from "vitest";
import { filterQuery } from "./filter-query";

describe("filter-query", () => {
  it("builds a query string without importing next/navigation", () => {
    expect(filterQuery({ team: "core" })).toBe("?team=core");
  });
});

import { describe, expect, it } from "vitest";
import { filterQuery, windowOptions, type Filters } from "./filters";

const empty: Filters = { team: "", window: "", from: "", to: "", metric: "", inactive: "", id: "" };

describe("filterQuery", () => {
  it("returns an empty string when no filters are set", () => {
    expect(filterQuery(empty)).toBe("");
  });

  it("accepts partial filters, treating missing fields as empty", () => {
    expect(filterQuery({ team: "core" })).toBe("?team=core");
  });

  it("includes from and to only for a custom window", () => {
    expect(
      filterQuery({ ...empty, team: "core", window: "custom", from: "2026-10-01", to: "2026-10-31" }),
    ).toBe("?team=core&window=custom&from=2026-10-01&to=2026-10-31");
    expect(filterQuery({ ...empty, team: "core", window: "30d", from: "2026-10-01", to: "2026-10-31" })).toBe(
      "?team=core&window=30d",
    );
  });

  it("appends extra params and skips undefined or empty values", () => {
    expect(filterQuery({ ...empty, team: "core" }, { metric: "lead", id: undefined, inactive: "" })).toBe(
      "?team=core&metric=lead",
    );
  });

  it("URL-encodes values", () => {
    expect(filterQuery({ ...empty, team: "a b&c=d/é" })).toBe("?team=a+b%26c%3Dd%2F%C3%A9");
    expect(filterQuery(empty, { id: "x?y#z" })).toBe("?id=x%3Fy%23z");
  });
});

describe("windowOptions", () => {
  const options = windowOptions(new Date(2026, 10, 25));

  it("returns the default, two fixed, six month and custom options", () => {
    expect(options).toHaveLength(10);
    expect(options[0]).toEqual(["", "Team default"]);
    expect(options[1]).toEqual(["30d", "Last 30 days"]);
    expect(options[2]).toEqual(["90d", "Last 90 days"]);
    expect(options[9]).toEqual(["custom", "Custom dates"]);
  });

  it("lists the current month first, then the five before it", () => {
    expect(options[3]).toEqual(["month:2026-11", "November 2026"]);
    expect(options[4]).toEqual(["month:2026-10", "October 2026"]);
    expect(options[8]).toEqual(["month:2026-06", "June 2026"]);
  });
});

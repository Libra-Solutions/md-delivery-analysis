import { describe, expect, it } from "vitest";
import { ago, fmt, trendInfo } from "./format";

describe("fmt", () => {
  it("formats ratios as rounded percentages", () => {
    expect(fmt(0.42, "ratio")).toBe("42%");
  });

  it("formats hours under 48 as hours and 48 or more as days", () => {
    expect(fmt(50, "hours")).toBe("2.1 d");
    expect(fmt(5, "hours")).toBe("5.0 h");
  });

  it("formats usd, points per usd and multiples", () => {
    expect(fmt(3.5, "usd")).toBe("$3.50");
    expect(fmt(1.234, "points_per_usd")).toBe("1.23");
    expect(fmt(2, "multiple")).toBe("2.00x");
  });

  it("returns a dash for null and undefined", () => {
    expect(fmt(null)).toBe("–");
    expect(fmt(undefined)).toBe("–");
  });

  it("prints integers as-is and other numbers to one decimal", () => {
    expect(fmt(3)).toBe("3");
    expect(fmt(3.14159)).toBe("3.1");
  });
});

describe("trendInfo", () => {
  it("marks a rise on a higher-is-better metric as good", () => {
    expect(trendInfo(0.12, "higher")).toEqual({ text: "▲ +12%", kind: "good" });
  });

  it("marks a fall on a lower-is-better metric as good", () => {
    expect(trendInfo(-0.05, "lower")).toEqual({ text: "▼ -5%", kind: "good" });
  });

  it("marks a rise on a lower-is-better metric as bad", () => {
    expect(trendInfo(0.2, "lower")).toEqual({ text: "▲ +20%", kind: "bad" });
  });

  it("gives no kind when the change rounds to zero or no direction is given", () => {
    expect(trendInfo(0, "higher")).toEqual({ text: "0%", kind: "" });
    expect(trendInfo(0.3, undefined)).toEqual({ text: "▲ +30%", kind: "" });
  });

  it("returns a dash with no kind for a null trend", () => {
    expect(trendInfo(null, "higher")).toEqual({ text: "–", kind: "" });
  });
});

describe("ago", () => {
  const now = Date.parse("2026-11-25T12:00:00Z");
  const isoMinutesAgo = (minutes: number) => new Date(now - minutes * 60000).toISOString();

  it("returns never for null", () => {
    expect(ago(null, now)).toBe("never");
  });

  it("returns just now for under a minute", () => {
    expect(ago(isoMinutesAgo(0), now)).toBe("just now");
  });

  it("formats minutes, hours and days", () => {
    expect(ago(isoMinutesAgo(30), now)).toBe("30 min ago");
    expect(ago(isoMinutesAgo(180), now)).toBe("3 h ago");
    expect(ago(isoMinutesAgo(3 * 1440), now)).toBe("3 d ago");
  });
});

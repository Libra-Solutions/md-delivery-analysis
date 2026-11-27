// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { handleApi, isCacheable } from "./api-proxy";
import { _resetServerApiCache } from "./server-api";

const calls: { url: string; method: string; origin: string | null }[] = [];

beforeEach(() => {
  calls.length = 0;
  _resetServerApiCache();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    calls.push({ url, method: init?.method ?? "GET", origin: headers.get("origin") });
    const body = url.endsWith("/api/version") ? { version: "v1" } : { url };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }));
});

const req = (path: string, init?: { method?: string; body?: string; headers?: Record<string, string> }) =>
  new NextRequest("http://localhost:8000" + path, init);
const upstream = (suffix: string) => calls.filter((c) => c.url.endsWith(suffix)).length;

describe("api proxy", () => {
  it("live_status_reads_and_writes_are_not_cacheable", () => {
    expect(isCacheable("GET", "/api/metrics/x")).toBe(true);
    expect(isCacheable("GET", "/api/sources")).toBe(false);
    expect(isCacheable("GET", "/api/version")).toBe(false);
    expect(isCacheable("GET", "/api/repos")).toBe(false);
    expect(isCacheable("POST", "/api/teams")).toBe(false);
  });

  it("repeat_reads_hit_the_cache", async () => {
    const a = await handleApi(req("/api/metrics/x?team=t"));
    const b = await handleApi(req("/api/metrics/x?team=t"));
    expect(await a.json()).toEqual(await b.json());
    expect(a.headers.get("content-type")).toContain("application/json");
    expect(upstream("/api/metrics/x?team=t")).toBe(1);
  });

  it("sources_is_always_passed_through", async () => {
    await handleApi(req("/api/sources"));
    await handleApi(req("/api/sources"));
    expect(upstream("/api/sources")).toBe(2);
  });

  it("writes_pass_through_with_method_body_and_origin", async () => {
    const res = await handleApi(req("/api/teams", {
      method: "POST", body: JSON.stringify({ name: "x" }),
      headers: { origin: "http://localhost:8000", "content-type": "application/json" },
    }));
    expect(res.status).toBe(200);
    expect(calls[0]).toEqual({ url: "http://127.0.0.1:8001/api/teams", method: "POST", origin: "http://localhost:8000" });
  });
});

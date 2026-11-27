import { beforeEach, describe, expect, it, vi } from "vitest";
import { _resetServerApiCache, prefetch, serverApi } from "./server-api";

let version = "v1";
const fetchMock = vi.fn(async (url: string) => {
  const path = url.replace("http://127.0.0.1:8001", "");
  return { ok: true, status: 200, json: async () => (path === "/api/version" ? { version } : { path, version }) };
});

beforeEach(() => {
  vi.useRealTimers();
  version = "v1";
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
  _resetServerApiCache();
});

const pathCalls = (p: string) => fetchMock.mock.calls.filter((c) => String(c[0]).endsWith(p)).length;

describe("server api", () => {
  it("server_api_reuses_result_for_same_version", async () => {
    await serverApi("/api/teams");
    await serverApi("/api/teams");
    expect(pathCalls("/api/teams")).toBe(1);
  });

  it("new_version_refetches", async () => {
    vi.useFakeTimers();
    await serverApi("/api/teams");
    version = "v2";
    vi.advanceTimersByTime(6000);
    await serverApi("/api/teams");
    expect(pathCalls("/api/teams")).toBe(2);
  });

  it("prefetch_keys_are_version_then_path", async () => {
    const state = await prefetch(["/api/teams"]);
    expect(state.queries).toHaveLength(1);
    expect(state.queries[0].queryKey).toEqual(["v1", "/api/teams"]);
  });

  it("cache_caps_at_500", async () => {
    for (let i = 0; i < 501; i++) await serverApi(`/api/x${i}`);
    await serverApi("/api/x0");
    expect(pathCalls("/api/x0")).toBe(2);
    await serverApi("/api/x500");
    expect(pathCalls("/api/x500")).toBe(1);
  });
});

describe("server api sharing and render budget", () => {
  it("concurrent_requests_share_one_upstream_call", async () => {
    await Promise.all([serverApi("/api/people"), serverApi("/api/people"), serverApi("/api/people")]);
    expect(pathCalls("/api/people")).toBe(1);
  });

  it("non_200_responses_are_not_cached", async () => {
    fetchMock.mockImplementationOnce(async () => ({ ok: true, status: 200, json: async () => ({ version }) }));
    fetchMock.mockImplementationOnce((async () => ({ ok: false, status: 500, json: async () => ({}) })) as never);
    await expect(serverApi("/api/flaky")).rejects.toThrow("500");
    await serverApi("/api/flaky");
    expect(pathCalls("/api/flaky")).toBe(2);
  });

  it("prefetch_sends_what_is_ready_within_the_budget_and_keeps_filling_the_cache", async () => {
    let release: () => void = () => undefined;
    const slow = new Promise<void>((r) => { release = r; });
    fetchMock.mockImplementation(async (url: string) => {
      const path = url.replace("http://127.0.0.1:8001", "");
      if (path === "/api/slow") await slow;
      return { ok: true, status: 200, json: async () => (path === "/api/version" ? { version } : { path, version }) };
    });
    const state = await prefetch(["/api/fast", "/api/slow"], 50);
    expect(state.queries.map((q) => q.queryKey[1])).toEqual(["/api/fast"]);
    release();
    await new Promise((r) => setTimeout(r, 0));
    await serverApi("/api/slow");
    expect(pathCalls("/api/slow")).toBe(1);
  });
});

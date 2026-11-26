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

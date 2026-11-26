import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));
import { api } from "@/lib/api";
import {
  VersionContext,
  dropStaleQueries,
  makeQueryClient,
  setQueryClient,
  useApi,
  useWrite,
} from "@/lib/query";

const apiMock = vi.mocked(api);
let serverVersion = "v1";

function wrapperFor(client: QueryClient, version = "v1") {
  setQueryClient(client);
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <VersionContext.Provider value={version}>{children}</VersionContext.Provider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  serverVersion = "v1";
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string) => {
    if (path === "/api/version") return { version: serverVersion };
    return { path, version: serverVersion };
  });
});

const dataCalls = () => apiMock.mock.calls.filter((c) => c[0] !== "/api/version");

describe("query hooks", () => {
  it("same_version_second_mount_no_fetch", async () => {
    const client = makeQueryClient();
    const wrapper = wrapperFor(client);
    const first = renderHook(() => useApi("/api/teams"), { wrapper });
    await waitFor(() => expect(first.result.current.data).toBeDefined());
    first.unmount();
    const second = renderHook(() => useApi("/api/teams"), { wrapper });
    expect(second.result.current.data).toEqual({ path: "/api/teams", version: "v1" });
    expect(dataCalls()).toHaveLength(1);
  });

  it("version_change_drops_old_queries_and_refetches", async () => {
    const client = makeQueryClient();
    const wrapper = wrapperFor(client);
    const { result } = renderHook(() => useApi("/api/teams"), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual({ path: "/api/teams", version: "v1" }));
    serverVersion = "v2";
    const { recheckVersion } = await import("@/lib/query");
    await act(async () => {
      await recheckVersion();
    });
    await waitFor(() => expect(result.current.data).toEqual({ path: "/api/teams", version: "v2" }));
    expect(client.getQueryCache().findAll().filter((q) => q.queryKey[0] === "v1")).toHaveLength(0);
    expect(dataCalls()).toHaveLength(2);
  });

  it("persisted_old_version_is_not_shown", async () => {
    const client = makeQueryClient();
    client.setQueryData(["old", "/api/teams"], { stale: true });
    const wrapper = wrapperFor(client, "v1");
    dropStaleQueries(client, "v1");
    const { result } = renderHook(() => useApi("/api/teams"), { wrapper });
    expect(result.current.data).toBeUndefined();
    await waitFor(() => expect(result.current.data).toEqual({ path: "/api/teams", version: "v1" }));
  });

  it("null_path_does_not_fetch", async () => {
    const client = makeQueryClient();
    const { result } = renderHook(() => useApi(null), { wrapper: wrapperFor(client) });
    await act(async () => {});
    expect(result.current.fetchStatus).toBe("idle");
    expect(dataCalls()).toHaveLength(0);
  });

  it("write_rechecks_version", async () => {
    const client = makeQueryClient();
    const wrapper = wrapperFor(client);
    const { result } = renderHook(() => useWrite(), { wrapper });
    await act(async () => {
      await result.current("/api/teams", "POST", { a: 1 });
    });
    expect(apiMock).toHaveBeenCalledWith("/api/teams", { method: "POST", body: { a: 1 } });
    expect(apiMock).toHaveBeenCalledWith("/api/version");
    apiMock.mockClear();
    await act(async () => {
      await result.current("/api/refresh", "POST");
    });
    expect(apiMock).not.toHaveBeenCalledWith("/api/version");
  });

  it("write_succeeds_when_version_recheck_fails", async () => {
    const client = makeQueryClient();
    const wrapper = wrapperFor(client);
    const { result } = renderHook(() => useWrite(), { wrapper });
    apiMock.mockImplementation(async (path: string) => {
      if (path === "/api/version") throw new Error("down");
      return { ok: true };
    });
    let out: unknown;
    await act(async () => {
      out = await result.current("/api/teams", "POST", {});
    });
    expect(out).toEqual({ ok: true });
  });
});

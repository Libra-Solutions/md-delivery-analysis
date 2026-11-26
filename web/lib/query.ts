"use client";

import { createContext, useCallback, useContext } from "react";
import { QueryClient, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { api } from "@/lib/api";

export const VERSION_KEY = "__version";
export const SEVEN_DAYS = 7 * 24 * 60 * 60 * 1000;
export const VERSION_POLL_MS = 60_000;

/** Version known at render time (set by the layout through Providers). */
export const VersionContext = createContext<string>("");

let activeClient: QueryClient | null = null;

export function setQueryClient(client: QueryClient | null): void {
  activeClient = client;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, gcTime: SEVEN_DAYS, retry: false } },
  });
}

async function fetchVersion(): Promise<string> {
  const body = (await api("/api/version")) as { version: string };
  return body.version;
}

/** Remove every cached API query that belongs to a version other than `version`. */
export function dropStaleQueries(client: QueryClient, version: string): void {
  client.removeQueries({
    predicate: (q) => q.queryKey[0] !== VERSION_KEY && q.queryKey[0] !== version,
  });
}

export function useVersionQuery(extra: { watch?: boolean } = {}): UseQueryResult<string> {
  const initial = useContext(VersionContext);
  const client = useQueryClient();
  return useQuery(
    {
      queryKey: [VERSION_KEY],
      queryFn: fetchVersion,
      initialData: initial || undefined,
      initialDataUpdatedAt: 0,
      staleTime: extra.watch ? 0 : Infinity,
      refetchInterval: extra.watch ? VERSION_POLL_MS : false,
      refetchOnWindowFocus: extra.watch ? "always" : false,
      refetchOnMount: extra.watch ? "always" : false,
    },
    client,
  );
}

export function useDataVersion(): string {
  const q = useVersionQuery();
  return q.data ?? "";
}

export async function recheckVersion(): Promise<void> {
  const client = activeClient;
  if (!client) return;
  const next = await client.fetchQuery({ queryKey: [VERSION_KEY], queryFn: fetchVersion, staleTime: 0 });
  dropStaleQueries(client, next);
}

export function useApi(path: string | null): UseQueryResult<unknown> {
  const version = useDataVersion();
  const client = useQueryClient();
  return useQuery(
    {
      queryKey: [version, path],
      queryFn: () => api(path as string),
      enabled: path !== null && version !== "",
      staleTime: Infinity,
      gcTime: SEVEN_DAYS,
    },
    client,
  );
}

export function useWrite(): (path: string, method: string, body?: unknown) => Promise<unknown> {
  return useCallback(async (path: string, method: string, body?: unknown) => {
    const result = await api(path, { method, body });
    if (path !== "/api/refresh") {
      // The write already succeeded; a failed version check must not report it as failed.
      await recheckVersion().catch(() => undefined);
    }
    return result;
  }, []);
}

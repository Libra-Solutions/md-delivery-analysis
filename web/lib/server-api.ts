import { QueryClient, dehydrate, type DehydratedState } from "@tanstack/react-query";

const origin = () => process.env.API_ORIGIN ?? "http://127.0.0.1:8001";
const VERSION_TTL_MS = 5000;
const MAX_ENTRIES = 500;

let versionCache: { value: string; at: number } | null = null;
const results = new Map<string, unknown>();

async function getJson(path: string): Promise<unknown> {
  const res = await fetch(origin() + path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

async function currentVersion(): Promise<string> {
  if (versionCache && Date.now() - versionCache.at < VERSION_TTL_MS) return versionCache.value;
  const body = (await getJson("/api/version")) as { version: string };
  if (versionCache && versionCache.value !== body.version) results.clear();
  versionCache = { value: body.version, at: Date.now() };
  return body.version;
}

export async function serverApi(path: string): Promise<unknown> {
  const version = await currentVersion();
  const key = version + path;
  if (results.has(key)) return results.get(key);
  const data = await getJson(path);
  results.set(key, data);
  while (results.size > MAX_ENTRIES) results.delete(results.keys().next().value as string);
  return data;
}

export async function prefetch(paths: string[]): Promise<DehydratedState> {
  const version = await currentVersion();
  const client = new QueryClient();
  await Promise.all(
    paths.map((path) =>
      client.prefetchQuery({ queryKey: [version, path], queryFn: () => serverApi(path) }),
    ),
  );
  return dehydrate(client);
}

/** Test helper: reset module caches. */
export function _resetServerApiCache(): void {
  versionCache = null;
  results.clear();
}

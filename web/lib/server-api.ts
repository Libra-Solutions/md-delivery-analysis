import { QueryClient, dehydrate, type DehydratedState } from "@tanstack/react-query";

export const apiOrigin = () => process.env.API_ORIGIN ?? "http://127.0.0.1:8001";
const VERSION_TTL_MS = 5000;
const MAX_ENTRIES = 500;
/** How long a server render waits for its data before sending the page; slower queries load in the browser. */
export const RENDER_BUDGET_MS = 1000;

/** A cached upstream GET: enough to replay it to a browser or parse it for a server render. */
export type CachedResponse = { status: number; headers: Record<string, string>; body: string };

const KEPT_HEADERS = ["content-type", "content-disposition"];

type Store = {
  version: { value: string; at: number } | null;
  results: Map<string, CachedResponse>;
  inflight: Map<string, Promise<CachedResponse>>;
};

// One store per Node process, shared by page renders and the /api route handler (separate module instances).
const STORE = Symbol.for("delivery-analysis.server-api");
function store(): Store {
  const g = globalThis as unknown as Record<symbol, Store | undefined>;
  return (g[STORE] ??= { version: null, results: new Map(), inflight: new Map() });
}

async function upstream(path: string): Promise<CachedResponse> {
  const res = await fetch(apiOrigin() + path, { cache: "no-store" });
  const headers: Record<string, string> = {};
  for (const name of KEPT_HEADERS) {
    const value = res.headers?.get?.(name);
    if (value) headers[name] = value;
  }
  const body = typeof res.text === "function" ? await res.text() : JSON.stringify(await res.json());
  return { status: res.status, headers, body };
}

async function currentVersion(): Promise<string> {
  const s = store();
  if (s.version && Date.now() - s.version.at < VERSION_TTL_MS) return s.version.value;
  const res = await upstream("/api/version");
  if (res.status !== 200) throw new Error(`/api/version failed: ${res.status}`);
  const value = (JSON.parse(res.body) as { version: string }).version;
  if (s.version && s.version.value !== value) s.results.clear();
  s.version = { value, at: Date.now() };
  return value;
}

/**
 * GET `path` from the API through the version-keyed cache. Only 200 responses are kept; concurrent
 * requests for the same version and path share one upstream call.
 */
export async function cachedGet(path: string): Promise<CachedResponse> {
  const s = store();
  const version = await currentVersion();
  const key = version + path;
  const hit = s.results.get(key);
  if (hit) return hit;
  const running = s.inflight.get(key);
  if (running) return running;
  const call = upstream(path)
    .then((res) => {
      if (res.status === 200) {
        s.results.set(key, res);
        while (s.results.size > MAX_ENTRIES) s.results.delete(s.results.keys().next().value as string);
      }
      return res;
    })
    .finally(() => s.inflight.delete(key));
  s.inflight.set(key, call);
  return call;
}

export async function serverApi(path: string): Promise<unknown> {
  const res = await cachedGet(path);
  if (res.status !== 200) throw new Error(`${path} failed: ${res.status}`);
  return JSON.parse(res.body);
}

/**
 * Prefetch `paths` for a server render, waiting at most `budgetMs`. Queries still running are left
 * out of the dehydrated state (the browser fetches them) but keep running and fill the cache.
 */
export async function prefetch(paths: string[], budgetMs: number = RENDER_BUDGET_MS): Promise<DehydratedState> {
  const version = await currentVersion();
  const client = new QueryClient();
  const all = Promise.all(
    paths.map((path) =>
      client.prefetchQuery({ queryKey: [version, path], queryFn: () => serverApi(path) }),
    ),
  );
  let timer: ReturnType<typeof setTimeout> | undefined;
  const budget = new Promise<void>((resolve) => { timer = setTimeout(resolve, budgetMs); });
  await Promise.race([all, budget]);
  clearTimeout(timer);
  return dehydrate(client);
}

/** Test helper: reset module caches. */
export function _resetServerApiCache(): void {
  const s = store();
  s.version = null;
  s.results.clear();
  s.inflight.clear();
}

// Proxy for browser calls to /api/* (app/api/[...path]/route.ts). Reads go through the Node cache (keyed by data
// version, one upstream call per version and path); live status reads and all writes go straight to FastAPI.
import type { NextRequest } from "next/server";
import { apiOrigin, cachedGet } from "@/lib/server-api";

/** Reads that report live progress, so they must never be served from the cache. */
const LIVE = new Set(["/api/version", "/api/sources", "/api/repos", "/api/health"]);

const DROP_REQUEST = ["host", "connection", "content-length", "accept-encoding"];
const DROP_RESPONSE = ["content-length", "content-encoding", "transfer-encoding", "connection"];

export function isCacheable(method: string, pathname: string): boolean {
  return method === "GET" && !LIVE.has(pathname) && !pathname.startsWith("/api/refresh");
}

async function pass(req: NextRequest, target: string): Promise<Response> {
  const headers = new Headers(req.headers);
  for (const name of DROP_REQUEST) headers.delete(name);
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const res = await fetch(apiOrigin() + target, {
    method: req.method,
    headers,
    body: hasBody ? await req.arrayBuffer() : undefined,
    cache: "no-store",
    redirect: "manual",
  });
  const out = new Headers(res.headers);
  for (const name of DROP_RESPONSE) out.delete(name);
  return new Response(res.body, { status: res.status, headers: out });
}

export async function handleApi(req: NextRequest): Promise<Response> {
  const { pathname, search } = req.nextUrl;
  const target = pathname + search;
  if (!isCacheable(req.method, pathname)) return pass(req, target);
  try {
    const hit = await cachedGet(target);
    return new Response(hit.body, { status: hit.status, headers: hit.headers });
  } catch {
    return pass(req, target); // the version check failed; let the API answer for itself
  }
}


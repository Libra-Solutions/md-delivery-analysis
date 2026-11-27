// Every browser call to /api/* lands here; see lib/api-proxy.ts.
import { handleApi } from "@/lib/api-proxy";

export const dynamic = "force-dynamic";

export const GET = handleApi;
export const POST = handleApi;
export const PUT = handleApi;
export const PATCH = handleApi;
export const DELETE = handleApi;

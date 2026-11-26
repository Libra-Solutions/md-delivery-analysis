export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type ApiInit = { method?: string; body?: unknown };

type ErrorBody = { detail?: unknown };

function errorMessage(data: ErrorBody, status: number): string {
  const detail = data.detail;
  if (Array.isArray(detail)) {
    return detail.map((item: { msg: string }) => item.msg).join("; ");
  }
  if (detail) {
    return String(detail);
  }
  return `HTTP ${status}`;
}

export async function api<T = unknown>(path: string, init?: ApiInit): Promise<T> {
  const headers: Record<string, string> = {};
  const requestInit: RequestInit = { method: init?.method ?? "GET", headers };
  if (init?.body !== undefined) {
    headers["Content-Type"] = "application/json";
    requestInit.body = JSON.stringify(init.body);
  }
  const response = await fetch(path, requestInit);
  const parsed = (await response.json().catch(() => ({}))) as ErrorBody | null;
  const data = parsed ?? {};
  if (!response.ok) {
    throw new ApiError(errorMessage(data, response.status), response.status);
  }
  return data as T;
}

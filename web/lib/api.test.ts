import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("returns_json", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ version: "a1b2c3d4e5f6" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api("/api/version")).resolves.toEqual({ version: "a1b2c3d4e5f6" });
    expect(fetchMock).toHaveBeenCalledWith("/api/version", { method: "GET", headers: {} });
  });

  it("posts_json_body_with_content_type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await api("/api/teams/x", { method: "PUT", body: { name: "Core" } });
    expect(fetchMock).toHaveBeenCalledWith("/api/teams/x", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Core" }),
    });
  });

  it("detail_string_becomes_message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "No team" }, 404)));

    const error = await api("/api/teams/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toBeInstanceOf(Error);
    expect((error as ApiError).message).toBe("No team");
    expect((error as ApiError).status).toBe(404);
  });

  it("detail_array_joined", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: [{ msg: "a" }, { msg: "b" }] }, 422)),
    );

    const error = (await api("/api/x").catch((e: unknown) => e)) as ApiError;
    expect(error.message).toBe("a; b");
    expect(error.status).toBe(422);
  });

  it("no_detail_uses_status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>oops</html>", { status: 500 })));

    const error = (await api("/api/x").catch((e: unknown) => e)) as ApiError;
    expect(error.message).toBe("HTTP 500");
    expect(error.status).toBe(500);
  });
});

import { describe, expect, it, vi } from "vitest";
import { ApiError, api, getSessionToken } from "../api";

describe("api client", () => {
  it("reads session token from meta tag and attaches X-UI-Token on mutations", async () => {
    document.head.innerHTML = '<meta name="ai-gov-token" content="tok-123" />';
    expect(getSessionToken()).toBe("tok-123");

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      text: async () => JSON.stringify({ note: { ref: "personal/demo" } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.createNote({
      title: "Demo",
      body: "Body",
      kind: "gotcha",
      scope: "personal",
      tags: [],
      repos: [],
    });

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init.headers);
    expect(headers.get("X-UI-Token")).toBe("tok-123");
    vi.unstubAllGlobals();
  });

  it("throws ApiError with status and code on 422 secret rejection", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: async () =>
        JSON.stringify({ detail: { message: "Secret rejected", code: "secret_rejected" } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      api.createNote({
        title: "Secret",
        body: "token=abc",
        kind: "gotcha",
        scope: "personal",
        tags: [],
        repos: [],
      })
    ).rejects.toMatchObject({ status: 422, code: "secret_rejected" } satisfies Partial<ApiError>);
    vi.unstubAllGlobals();
  });
});

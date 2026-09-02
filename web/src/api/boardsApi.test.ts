import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./ApiError";
import { createHttpBoardsApi } from "./boardsApi";

function board(overrides: Record<string, unknown> = {}) {
  return {
    id: "1",
    name: "Example",
    url: "https://example.com",
    type: "html_crawl",
    active: true,
    posting_count: null,
    health: null,
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
    ...overrides,
  };
}

describe("createHttpBoardsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists boards with credentials same-origin", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [board()] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createHttpBoardsApi().listBoards();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/boards",
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
    expect(result.items).toHaveLength(1);
  });

  it("creates a board by posting name, url and type as JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => board(),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpBoardsApi().createBoard({
      name: "Example",
      url: "https://example.com",
      type: "html_crawl",
      active: true,
    });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/boards");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      name: "Example",
      url: "https://example.com",
      type: "html_crawl",
      active: true,
    });
  });

  it("updates a board by putting name, url and active, with the id percent-encoded", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => board({ name: "Renamed" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpBoardsApi().updateBoard("a b", {
      name: "Renamed",
      url: "https://renamed.example.com",
      active: false,
    });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/boards/a%20b");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      name: "Renamed",
      url: "https://renamed.example.com",
      active: false,
    });
  });

  it("deletes a board", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpBoardsApi().deleteBoard("1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/boards/1",
      expect.objectContaining({ method: "DELETE", credentials: "same-origin" }),
    );
  });

  it("throws an ApiError carrying the response status and detail on a 409", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => ({
          detail: "A board with that name or url already exists",
        }),
      }),
    );

    await expect(
      createHttpBoardsApi().createBoard({
        name: "Example",
        url: "https://example.com",
        type: "html_crawl",
        active: true,
      }),
    ).rejects.toMatchObject({
      status: 409,
      message: "A board with that name or url already exists",
    } satisfies Partial<ApiError>);
  });
});

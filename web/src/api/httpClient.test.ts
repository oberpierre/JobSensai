import { afterEach, describe, expect, it, vi } from "vitest";
import { httpJson } from "./httpClient";
import { ApiError } from "./ApiError";

describe("httpJson error bodies", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("joins a list-shaped detail's msg entries into readable text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: "Unprocessable Content",
        json: async () => ({
          detail: [
            { loc: ["body", "name"], msg: "field required", type: "missing" },
            {
              loc: ["body", "url"],
              msg: "value is not a valid url",
              type: "value_error",
            },
          ],
        }),
      }),
    );

    await expect(httpJson("/api/boards")).rejects.toMatchObject({
      status: 422,
      message: "field required, value is not a valid url",
    });
  });

  it("falls back to statusText when the body is neither a string nor a list detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        json: async () => ({ error: "boom" }),
      }),
    );

    await expect(httpJson("/api/boards")).rejects.toMatchObject({
      status: 503,
      message: "Service Unavailable",
    });
  });

  it("names the status code when the body isn't JSON and statusText is empty (HTTP/2)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        statusText: "",
        json: async () => {
          throw new SyntaxError("Unexpected token < in JSON");
        },
      }),
    );

    let caught: unknown;
    try {
      await httpJson("/api/boards");
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).message).not.toBe("");
  });
});

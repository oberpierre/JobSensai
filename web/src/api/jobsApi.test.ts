import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./ApiError";
import { createHttpJobsApi } from "./jobsApi";

describe("createHttpJobsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls fetch with credentials same-origin and no base URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [],
        total: 0,
        page: 1,
        page_size: 25,
        company_count: 0,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpJobsApi().listJobs({});

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("sends q, page and include_closed as the wire query string", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [],
        total: 0,
        page: 2,
        page_size: 25,
        company_count: 0,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpJobsApi().listJobs({
      q: "staff",
      page: 2,
      includeClosed: true,
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("/api/jobs?q=staff&page=2&include_closed=true");
  });

  it("throws an ApiError carrying the response status on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: "Service unavailable" }),
      }),
    );

    await expect(createHttpJobsApi().listJobs({})).rejects.toMatchObject({
      status: 503,
      message: "Service unavailable",
    } satisfies Partial<ApiError>);
  });
});

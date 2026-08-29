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

  it("sends repeated facet params and sort as the wire query string", async () => {
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

    await createHttpJobsApi().listJobs({
      location: ["Zurich", "Singapore"],
      company: ["Acme"],
      employmentType: ["__unspecified__"],
      sort: "oldest",
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "/api/jobs?location=Zurich&location=Singapore&company=Acme" +
        "&employment_type=__unspecified__&sort=oldest",
    );
  });

  it("getFacets calls /api/jobs/facets with q and include_closed", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ location: [], company: [], employment_type: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpJobsApi().getFacets({ q: "staff", includeClosed: true });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs/facets?q=staff&include_closed=true",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("getFacets sends the active facet filters as the wire query string", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ location: [], company: [], employment_type: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpJobsApi().getFacets({
      location: ["Zurich", "Singapore"],
      company: ["Acme"],
      employmentType: ["__unspecified__"],
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "/api/jobs/facets?location=Zurich&location=Singapore&company=Acme" +
        "&employment_type=__unspecified__",
    );
  });

  it("getJob calls /api/jobs/{id} with credentials same-origin", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "1",
        url: "https://example.com/1",
        title: "Backend Engineer",
        company_name: "Acme",
        employment_type: null,
        locations: [],
        categories: [],
        metadata: {},
        description: "",
        first_seen: "2026-01-01T00:00:00+00:00",
        last_seen: "2026-01-01T00:00:00+00:00",
        closed: false,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createHttpJobsApi().getJob("1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs/1",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("getJob throws an ApiError carrying 404 for an unknown id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: "No posting with that id" }),
      }),
    );

    await expect(createHttpJobsApi().getJob("missing")).rejects.toMatchObject({
      status: 404,
      message: "No posting with that id",
    } satisfies Partial<ApiError>);
  });
});

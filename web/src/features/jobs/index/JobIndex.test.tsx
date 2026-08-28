import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { JobIndex } from "./JobIndex";
import { JobsApiProvider } from "../../../api/JobsApiProvider";
import { ApiError } from "../../../api/ApiError";
import type { JobsApi } from "../../../api/jobsApi";
import type { JobListResponse, JobSummary } from "../../../api/types";

// Typed once here so every test's mock rejects/resolves against the real
// listJobs signature instead of `unknown`.
function mockListJobs() {
  return vi.fn<JobsApi["listJobs"]>();
}

function job(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: "1",
    url: "https://example.com/1",
    title: "Backend Engineer",
    company_name: "Acme",
    employment_type: "full_time",
    locations: ["Zurich"],
    categories: [],
    metadata: {},
    snippet: "A great role.",
    first_seen: new Date().toISOString(),
    last_seen: new Date().toISOString(),
    closed: false,
    ...overrides,
  };
}

function listResponse(items: JobSummary[]): JobListResponse {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 25,
    company_count: new Set(items.map((item) => item.company_name)).size,
  };
}

function renderWithProviders(api: JobsApi, initialEntries = ["/"]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <JobsApiProvider api={api}>
          <JobIndex />
        </JobsApiProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("JobIndex", () => {
  it("renders the loading state before the response resolves", () => {
    const api: JobsApi = { listJobs: () => new Promise(() => {}) };
    renderWithProviders(api);
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("renders the empty state when nothing matches", async () => {
    const listJobs = mockListJobs().mockResolvedValue(listResponse([]));
    renderWithProviders({ listJobs });
    expect(
      await screen.findByText("Nothing matches these filters."),
    ).toBeInTheDocument();
  });

  it("renders the error state and its status code", async () => {
    const listJobs = mockListJobs().mockRejectedValue(
      new ApiError(503, "Service unavailable"),
    );
    renderWithProviders({ listJobs });
    expect(
      await screen.findByText("Couldn't load postings"),
    ).toBeInTheDocument();
    expect(screen.getByText("GET /api/jobs → 503")).toBeInTheDocument();
  });

  it("retries the request when Retry is clicked", async () => {
    const listJobs = mockListJobs()
      .mockRejectedValueOnce(new ApiError(503, "Service unavailable"))
      .mockResolvedValueOnce(listResponse([job()]));
    renderWithProviders({ listJobs });
    await screen.findByText("Couldn't load postings");

    await userEvent.click(screen.getByText("Retry"));

    expect(await screen.findByText("Backend Engineer")).toBeInTheDocument();
    expect(listJobs).toHaveBeenCalledTimes(2);
  });

  it("renders a closed posting struck through", async () => {
    const listJobs = mockListJobs().mockResolvedValue(
      listResponse([job({ title: "Closed Role", closed: true })]),
    );
    renderWithProviders({ listJobs });
    const title = await screen.findByText("Closed Role");
    expect(title.className).toMatch(/title/);
    expect(title.closest("li")?.className).toMatch(/rowClosed/);
  });

  it("writes the search text into the q query parameter", async () => {
    const listJobs = mockListJobs().mockResolvedValue(listResponse([job()]));
    renderWithProviders({ listJobs });
    await screen.findByText("Backend Engineer");

    await userEvent.type(
      screen.getByPlaceholderText("Title or company"),
      "staff",
    );

    await waitFor(() => {
      const lastCall = listJobs.mock.calls.at(-1)?.[0];
      expect(lastCall?.q).toBe("staff");
    });
  });
});

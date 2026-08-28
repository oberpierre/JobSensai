import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { JobIndex } from "./JobIndex";
import { JobsApiProvider } from "../../../api/JobsApiProvider";
import { ApiError } from "../../../api/ApiError";
import { createQueryClient } from "../../../api/queryClient";
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

function listResponse(
  items: JobSummary[],
  overrides: Partial<JobListResponse> = {},
): JobListResponse {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 25,
    company_count: new Set(items.map((item) => item.company_name)).size,
    ...overrides,
  };
}

// Exercises real back-navigation rather than a second render, which is the only
// way to reproduce the history-navigation defects this suite pins.
function ShowUrl() {
  const location = useLocation();
  return <span data-testid="url">{location.pathname + location.search}</span>;
}

function GoBack() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(-1)}>
      go back
    </button>
  );
}

function renderWithProviders(
  api: JobsApi,
  initialEntries = ["/"],
  initialIndex?: number,
) {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries} initialIndex={initialIndex}>
        <JobsApiProvider api={api}>
          <GoBack />
          <ShowUrl />
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

  it("pluralizes the posting count", async () => {
    const listJobs = mockListJobs().mockResolvedValue(
      listResponse([job()], { total: 1 }),
    );
    renderWithProviders({ listJobs });
    expect(await screen.findByText("1 posting")).toBeInTheDocument();
  });

  it("renders the total rather than a false empty state on page two", async () => {
    const listJobs = mockListJobs().mockImplementation(async ({ page }) => {
      if (page === 2) {
        return listResponse([], { total: 5, page: 2 });
      }
      return listResponse([job()], { total: 5, page: 1 });
    });
    renderWithProviders({ listJobs }, ["/?page=2"]);

    expect(await screen.findByText("5 postings")).toBeInTheDocument();
    expect(
      screen.queryByText("Nothing matches these filters."),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Include closed postings"));

    await waitFor(() => {
      const lastCall = listJobs.mock.calls.at(-1)?.[0];
      expect(lastCall?.page).toBe(1);
    });
  });

  it("restores includeClosed from the URL on reload", async () => {
    const listJobs = mockListJobs().mockResolvedValue(listResponse([job()]));
    renderWithProviders({ listJobs }, ["/?include_closed=true"]);
    await screen.findByText("Backend Engineer");

    expect(screen.getByLabelText("Include closed postings")).toBeChecked();
    expect(listJobs.mock.calls[0][0]).toMatchObject({ includeClosed: true });
  });

  it("pages forward and back with prev/next", async () => {
    const listJobs = mockListJobs().mockImplementation(async ({ page }) => {
      if (page === 2) {
        return listResponse([job({ id: "2", title: "Staff Engineer" })], {
          total: 30,
          page: 2,
        });
      }
      return listResponse([job({ id: "1", title: "Backend Engineer" })], {
        total: 30,
        page: 1,
      });
    });
    renderWithProviders({ listJobs });
    await screen.findByText("Backend Engineer");

    await userEvent.click(screen.getByText("next →"));
    await screen.findByText("Staff Engineer");

    await userEvent.click(screen.getByText("← prev"));
    await screen.findByText("Backend Engineer");
  });

  it("keeps the search input in step with q after a back navigation", async () => {
    const listJobs = mockListJobs().mockResolvedValue(listResponse([job()]));
    renderWithProviders({ listJobs }, ["/?q=foo", "/?q=bar"], 1);
    await screen.findByText("Backend Engineer");

    expect(screen.getByPlaceholderText("Title or company")).toHaveValue("bar");

    await userEvent.click(screen.getByText("go back"));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Title or company")).toHaveValue(
        "foo",
      );
    });
  });

  it("keeps the unfiltered list reachable by back after a first search", async () => {
    const listJobs = mockListJobs().mockResolvedValue(listResponse([job()]));
    renderWithProviders({ listJobs });
    await screen.findByText("Backend Engineer");

    await userEvent.type(screen.getByRole("textbox"), "AI");
    await waitFor(() =>
      expect(screen.getByTestId("url")).toHaveTextContent("q=AI"),
    );

    await userEvent.click(screen.getByText("go back"));
    await waitFor(() =>
      expect(screen.getByTestId("url")).toHaveTextContent("/"),
    );
    expect(screen.getByTestId("url")).not.toHaveTextContent("q=AI");
  });

  it("does not add a history entry while a search is being refined", async () => {
    const listJobs = mockListJobs().mockResolvedValue(listResponse([job()]));
    renderWithProviders({ listJobs });
    await screen.findByText("Backend Engineer");

    const box = screen.getByRole("textbox");
    await userEvent.type(box, "A");
    await waitFor(() =>
      expect(screen.getByTestId("url")).toHaveTextContent("q=A"),
    );
    await userEvent.type(box, "I");
    await waitFor(() =>
      expect(screen.getByTestId("url")).toHaveTextContent("q=AI"),
    );

    // One entry for the whole search, so back lands on the unfiltered list
    // rather than on the half-typed query.
    await userEvent.click(screen.getByText("go back"));
    await waitFor(() =>
      expect(screen.getByTestId("url")).toHaveTextContent("/"),
    );
    expect(screen.getByTestId("url")).not.toHaveTextContent("q=");
  });

  it("drops the page parameter rather than writing page=1", async () => {
    const listJobs = mockListJobs().mockResolvedValue(
      listResponse([job()], { total: 40, page: 2 }),
    );
    renderWithProviders({ listJobs }, ["/?page=2"]);
    await screen.findByText("Backend Engineer");

    await userEvent.click(screen.getByText("← prev"));
    await waitFor(() =>
      expect(screen.getByTestId("url")).not.toHaveTextContent("page"),
    );
  });
});

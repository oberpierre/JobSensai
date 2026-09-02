import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { JobDetail } from "./JobDetail";
import { ApiError } from "../../../api/ApiError";
import { renderWithProviders } from "../../../../test/TestProviders";
import type { JobsApi } from "../../../api/jobsApi";
import type { JobDetail as JobDetailPayload } from "../../../api/types";

function detail(overrides: Partial<JobDetailPayload> = {}): JobDetailPayload {
  return {
    id: "1",
    url: "https://example.com/1",
    title: "Backend Engineer",
    company_name: "Acme",
    employment_type: null,
    locations: ["Zurich"],
    categories: [],
    metadata: {},
    description: "Full description body.",
    first_seen: new Date().toISOString(),
    last_seen: new Date().toISOString(),
    closed: false,
    ...overrides,
  };
}

function renderJobDetailWithProviders(api: Partial<JobsApi>, id = "1") {
  return renderWithProviders(
    <Routes>
      <Route path="/jobs/:id" element={<JobDetail />} />
    </Routes>,
    { jobsApi: api, initialEntries: [`/jobs/${id}`] },
  );
}

describe("JobDetail", () => {
  it("renders the loading state before the response resolves", () => {
    renderJobDetailWithProviders({ getJob: () => new Promise(() => {}) });
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("renders title, company and description once loaded", async () => {
    const getJob = vi.fn<JobsApi["getJob"]>().mockResolvedValue(detail());
    renderJobDetailWithProviders({ getJob });
    expect(await screen.findByText("Backend Engineer")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Full description body.")).toBeInTheDocument();
    expect(getJob).toHaveBeenCalledWith("1");
  });

  it("renders a metadata key no component knows about", async () => {
    const getJob = vi
      .fn<JobsApi["getJob"]>()
      .mockResolvedValue(detail({ metadata: { salary_range: "$100k-$120k" } }));
    renderJobDetailWithProviders({ getJob });
    expect(await screen.findByText("Salary range")).toBeInTheDocument();
    expect(screen.getByText("$100k-$120k")).toBeInTheDocument();
  });

  it("gives a known experience level its hue-mapped chip", async () => {
    const getJob = vi
      .fn<JobsApi["getJob"]>()
      .mockResolvedValue(detail({ metadata: { experience_level: "Mid" } }));
    renderJobDetailWithProviders({ getJob });
    const chip = await screen.findByText("Mid");
    expect(chip.className).toMatch(/chip/);
  });

  it("renders a 404 as a not-found state rather than the generic error", async () => {
    const getJob = vi
      .fn<JobsApi["getJob"]>()
      .mockRejectedValue(new ApiError(404, "No posting with that id"));
    renderJobDetailWithProviders({ getJob });
    expect(await screen.findByText("not found")).toBeInTheDocument();
    expect(screen.getByText("No posting with that id.")).toBeInTheDocument();
  });

  it("renders the generic error state with retry for a non-404 failure", async () => {
    const getJob = vi
      .fn<JobsApi["getJob"]>()
      .mockRejectedValueOnce(new ApiError(503, "Service unavailable"))
      .mockResolvedValueOnce(detail());
    renderJobDetailWithProviders({ getJob });
    await screen.findByText("Couldn't load this posting");
    expect(screen.getByText("GET /api/jobs/:id → 503")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Retry"));
    expect(await screen.findByText("Backend Engineer")).toBeInTheDocument();
  });

  it("greys the source link and marks it likely dead when closed", async () => {
    const getJob = vi
      .fn<JobsApi["getJob"]>()
      .mockResolvedValue(detail({ closed: true }));
    renderJobDetailWithProviders({ getJob });
    const links = await screen.findAllByText("Original posting (likely dead)");
    expect(links.length).toBeGreaterThan(0);
    expect(screen.getByText("Closed")).toBeInTheDocument();
  });
});

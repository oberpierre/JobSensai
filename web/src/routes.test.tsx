import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "./routes";
import { JobsApiProvider } from "./api/JobsApiProvider";
import { BoardsApiProvider } from "./api/BoardsApiProvider";
import { createQueryClient } from "./api/queryClient";
import type { JobsApi } from "./api/jobsApi";
import type { BoardsApi } from "./api/boardsApi";

// Every path here renders whichever screen matches, and every screen queries
// its own API on mount, so both providers wrap every case. The other two
// screens' calls are left pending on purpose, since the assertions below only
// need markup each screen renders before its data arrives.
function renderAt(path: string) {
  const jobsApi: JobsApi = {
    listJobs: () => new Promise(() => {}),
    getFacets: () => new Promise(() => {}),
    getJob: () => new Promise(() => {}),
  };
  const boardsApi: BoardsApi = {
    listBoards: () => new Promise(() => {}),
    createBoard: () => new Promise(() => {}),
    updateBoard: () => new Promise(() => {}),
    deleteBoard: () => new Promise(() => {}),
  };
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <JobsApiProvider api={jobsApi}>
        <BoardsApiProvider api={boardsApi}>
          <MemoryRouter initialEntries={[path]}>
            <AppRoutes />
          </MemoryRouter>
        </BoardsApiProvider>
      </JobsApiProvider>
    </QueryClientProvider>,
  );
}

// Every link the app emits is canonical (trailing slash), but the patterns in
// routes.tsx are not, so this pins that React Router's matcher accepts both
// forms rather than trusting it by inspection.
describe("AppRoutes canonical trailing-slash locations", () => {
  it("renders the job index at /", () => {
    renderAt("/");
    expect(screen.getByPlaceholderText("Title or company")).toBeInTheDocument();
  });

  it("renders the job detail screen at /jobs/<id>/", () => {
    renderAt("/jobs/1/");
    expect(screen.getByText("← all postings")).toBeInTheDocument();
  });

  it("renders the admin dashboard at /admin/", () => {
    renderAt("/admin/");
    expect(screen.getByText("Job boards")).toBeInTheDocument();
  });
});

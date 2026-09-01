import type { ReactElement, ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { JobsApiProvider } from "../src/api/JobsApiProvider";
import { BoardsApiProvider } from "../src/api/BoardsApiProvider";
import { createQueryClient } from "../src/api/queryClient";
import type { JobsApi } from "../src/api/jobsApi";
import type { BoardsApi } from "../src/api/boardsApi";

// A stub that never settles holds a component in its pending branch
// deterministically, with no timer and no retry to race against assertions.
const PENDING_JOBS_API: JobsApi = {
  listJobs: () => new Promise(() => {}),
  getFacets: () => new Promise(() => {}),
  getJob: () => new Promise(() => {}),
};

const PENDING_BOARDS_API: BoardsApi = {
  listBoards: () => new Promise(() => {}),
  createBoard: () => new Promise(() => {}),
  updateBoard: () => new Promise(() => {}),
  deleteBoard: () => new Promise(() => {}),
};

export interface TestProvidersProps {
  children: ReactNode;
  jobsApi?: Partial<JobsApi>;
  boardsApi?: Partial<BoardsApi>;
  initialEntries?: string[];
  initialIndex?: number;
}

// Always all four providers, since one nothing consumes costs a test nothing
// whereas a missing one throws confusingly from whichever hook reaches for it.
export function TestProviders({
  children,
  jobsApi,
  boardsApi,
  initialEntries = ["/"],
  initialIndex,
}: TestProvidersProps) {
  const fullJobsApi: JobsApi = { ...PENDING_JOBS_API, ...jobsApi };
  const fullBoardsApi: BoardsApi = { ...PENDING_BOARDS_API, ...boardsApi };
  const queryClient = createQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries} initialIndex={initialIndex}>
        <JobsApiProvider api={fullJobsApi}>
          <BoardsApiProvider api={fullBoardsApi}>{children}</BoardsApiProvider>
        </JobsApiProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

export type RenderWithProvidersOptions = Omit<TestProvidersProps, "children"> &
  Omit<RenderOptions, "wrapper">;

// Passed through RTL's `wrapper` option rather than rendering
// `<TestProviders>{ui}</TestProviders>` directly, so the providers survive a
// `rerender` instead of being torn down with the first tree.
// eslint-disable-next-line react-refresh/only-export-components -- test-only file, never loaded through the dev server this rule protects.
export function renderWithProviders(
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
) {
  const { jobsApi, boardsApi, initialEntries, initialIndex, ...renderOptions } =
    options;
  return render(ui, {
    ...renderOptions,
    wrapper: ({ children }) => (
      <TestProviders
        jobsApi={jobsApi}
        boardsApi={boardsApi}
        initialEntries={initialEntries}
        initialIndex={initialIndex}
      >
        {children}
      </TestProviders>
    ),
  });
}

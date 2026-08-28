import { ApiError } from "./ApiError";
import type { JobListResponse } from "./types";

export interface ListJobsParams {
  q?: string;
  page?: number;
  includeClosed?: boolean;
}

export interface JobsApi {
  listJobs(params: ListJobsParams): Promise<JobListResponse>;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      body !== null &&
      typeof body === "object" &&
      "detail" in body &&
      typeof (body as { detail: unknown }).detail === "string"
    ) {
      return (body as { detail: string }).detail;
    }
  } catch {
    // The body wasn't JSON, so fall through to the status text below.
  }
  return response.statusText;
}

// The only place calling fetch, and the only place that knows the wire path: the
// relative "/api/..." Vite proxies in development and one origin serves in
// production, so no base URL and no environment branch is needed here.
export function createHttpJobsApi(): JobsApi {
  return {
    async listJobs({ q, page, includeClosed }) {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (page) params.set("page", String(page));
      if (includeClosed) params.set("include_closed", "true");
      const query = params.toString();

      const response = await fetch(`/api/jobs${query ? `?${query}` : ""}`, {
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new ApiError(response.status, await errorDetail(response));
      }
      return (await response.json()) as JobListResponse;
    },
  };
}

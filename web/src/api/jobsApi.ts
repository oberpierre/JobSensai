import { httpJson } from "./httpClient";
import type { FacetsResponse, JobDetail, JobListResponse } from "./types";

export type SortOrder = "newest" | "oldest";

export interface ListJobsParams {
  q?: string;
  location?: string[];
  company?: string[];
  employmentType?: string[];
  includeClosed?: boolean;
  sort?: SortOrder;
  page?: number;
}

export interface GetFacetsParams {
  q?: string;
  includeClosed?: boolean;
  location?: string[];
  company?: string[];
  employmentType?: string[];
}

export interface JobsApi {
  listJobs(params: ListJobsParams): Promise<JobListResponse>;
  getFacets(params: GetFacetsParams): Promise<FacetsResponse>;
  getJob(jobId: string): Promise<JobDetail>;
}

function get<T>(path: string, params: URLSearchParams): Promise<T> {
  const query = params.toString();
  return httpJson<T>(`${path}${query ? `?${query}` : ""}`);
}

export function createHttpJobsApi(): JobsApi {
  return {
    async listJobs({
      q,
      page,
      includeClosed,
      location,
      company,
      employmentType,
      sort,
    }) {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (page) params.set("page", String(page));
      if (includeClosed) params.set("include_closed", "true");
      for (const value of location ?? []) params.append("location", value);
      for (const value of company ?? []) params.append("company", value);
      for (const value of employmentType ?? [])
        params.append("employment_type", value);
      if (sort) params.set("sort", sort);
      return get<JobListResponse>("/api/jobs", params);
    },

    async getFacets({ q, includeClosed, location, company, employmentType }) {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (includeClosed) params.set("include_closed", "true");
      for (const value of location ?? []) params.append("location", value);
      for (const value of company ?? []) params.append("company", value);
      for (const value of employmentType ?? [])
        params.append("employment_type", value);
      return get<FacetsResponse>("/api/jobs/facets", params);
    },

    async getJob(jobId) {
      return get<JobDetail>(
        `/api/jobs/${encodeURIComponent(jobId)}`,
        new URLSearchParams(),
      );
    },
  };
}

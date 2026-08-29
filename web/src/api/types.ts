// A hand-written transcription of the JobSummary/JobListResponse payloads the API
// returns, field names kept verbatim so the wire shape needs no mapping layer.

export interface JobSummary {
  id: string;
  url: string;
  title: string;
  company_name: string;
  employment_type: string | null;
  locations: string[];
  categories: string[];
  metadata: Record<string, unknown>;
  snippet: string;
  first_seen: string;
  last_seen: string;
  closed: boolean;
}

export interface JobDetail {
  id: string;
  url: string;
  title: string;
  company_name: string;
  employment_type: string | null;
  locations: string[];
  categories: string[];
  metadata: Record<string, unknown>;
  description: string;
  first_seen: string;
  last_seen: string;
  closed: boolean;
}

export interface JobListResponse {
  items: JobSummary[];
  total: number;
  page: number;
  page_size: number;
  company_count: number;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface FacetsResponse {
  location: FacetValue[];
  company: FacetValue[];
  employment_type: FacetValue[];
}

export type BoardType = "html_crawl" | "json_api";

export interface Board {
  id: string;
  name: string;
  url: string;
  type: BoardType;
  posting_count: number | null;
  health: null;
  created_at: string;
  updated_at: string;
}

export interface BoardListResponse {
  items: Board[];
}

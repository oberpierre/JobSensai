import type { ReactNode } from "react";
import { JobsApiContext } from "./useJobsApi";
import type { JobsApi } from "./jobsApi";

export function JobsApiProvider({
  api,
  children,
}: {
  api: JobsApi;
  children: ReactNode;
}) {
  return (
    <JobsApiContext.Provider value={api}>{children}</JobsApiContext.Provider>
  );
}

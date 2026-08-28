import { createContext, useContext } from "react";
import { createHttpJobsApi, type JobsApi } from "./jobsApi";

// The default context value is the real implementation, so nothing needs to wrap
// the app in a provider just to reach the network. Tests override it to inject a
// stub without touching main.tsx.
export const JobsApiContext = createContext<JobsApi>(createHttpJobsApi());

export function useJobsApi(): JobsApi {
  return useContext(JobsApiContext);
}

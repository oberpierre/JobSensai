import { QueryClient } from "@tanstack/react-query";

// The job index already offers its own Retry action on a failed request, so an
// automatic retry would only delay the error state without buying anything.
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

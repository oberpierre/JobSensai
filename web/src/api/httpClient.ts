import { ApiError } from "./ApiError";

// The only place calling fetch, and the only place that knows the wire path: the
// relative "/api/..." Vite proxies in development and one origin serves in
// production, so no base URL and no environment branch is needed here. Every
// caller gets "credentials: same-origin" here rather than repeating it, since
// the SPA and API share one origin and there is no token to attach.

async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body !== null && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail)) {
        const messages = detail
          .map((entry) => extractMsg(entry))
          .filter((msg): msg is string => msg !== null);
        if (messages.length > 0) {
          return messages.join(", ");
        }
      }
    }
  } catch {
    // The body wasn't JSON, so fall through to the status text below.
  }
  return response.statusText;
}

function extractMsg(entry: unknown): string | null {
  if (
    entry !== null &&
    typeof entry === "object" &&
    "msg" in entry &&
    typeof (entry as { msg: unknown }).msg === "string"
  ) {
    return (entry as { msg: string }).msg;
  }
  return null;
}

export async function httpFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  return response;
}

export async function httpJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await httpFetch(path, init);
  return (await response.json()) as T;
}

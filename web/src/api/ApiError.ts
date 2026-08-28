// Carries the HTTP status so a caller can tell a 503 apart from a 404 without
// re-parsing the response.
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

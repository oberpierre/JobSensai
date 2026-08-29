import { ApiError } from "./ApiError";
import type { Board, BoardListResponse, BoardType } from "./types";

export interface CreateBoardParams {
  name: string;
  url: string;
  type: BoardType;
}

export interface UpdateBoardParams {
  name: string;
  url: string;
}

export interface BoardsApi {
  listBoards(): Promise<BoardListResponse>;
  createBoard(params: CreateBoardParams): Promise<Board>;
  updateBoard(boardId: string, params: UpdateBoardParams): Promise<Board>;
  deleteBoard(boardId: string): Promise<void>;
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

async function send<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  return (await response.json()) as T;
}

async function del(path: string): Promise<void> {
  const response = await fetch(path, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
}

const JSON_HEADERS = { "Content-Type": "application/json" };

// The only place calling fetch for boards, sending "credentials: same-origin"
// exactly as the jobs client does for the same reason: one origin, no token.
export function createHttpBoardsApi(): BoardsApi {
  return {
    async listBoards() {
      return send<BoardListResponse>("/api/boards", { method: "GET" });
    },

    async createBoard(params) {
      return send<Board>("/api/boards", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(params),
      });
    },

    async updateBoard(boardId, params) {
      return send<Board>(`/api/boards/${encodeURIComponent(boardId)}`, {
        method: "PUT",
        headers: JSON_HEADERS,
        body: JSON.stringify(params),
      });
    },

    async deleteBoard(boardId) {
      await del(`/api/boards/${encodeURIComponent(boardId)}`);
    },
  };
}

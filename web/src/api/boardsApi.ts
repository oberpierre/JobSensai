import { httpFetch, httpJson } from "./httpClient";
import type { Board, BoardListResponse, BoardType } from "./types";

export interface CreateBoardParams {
  name: string;
  url: string;
  type: BoardType;
  active: boolean;
}

export interface UpdateBoardParams {
  name: string;
  url: string;
  active: boolean;
}

export interface BoardsApi {
  listBoards(): Promise<BoardListResponse>;
  createBoard(params: CreateBoardParams): Promise<Board>;
  updateBoard(boardId: string, params: UpdateBoardParams): Promise<Board>;
  deleteBoard(boardId: string): Promise<void>;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function createHttpBoardsApi(): BoardsApi {
  return {
    async listBoards() {
      return httpJson<BoardListResponse>("/api/boards", { method: "GET" });
    },

    async createBoard(params) {
      return httpJson<Board>("/api/boards", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(params),
      });
    },

    async updateBoard(boardId, params) {
      return httpJson<Board>(`/api/boards/${encodeURIComponent(boardId)}`, {
        method: "PUT",
        headers: JSON_HEADERS,
        body: JSON.stringify(params),
      });
    },

    async deleteBoard(boardId) {
      await httpFetch(`/api/boards/${encodeURIComponent(boardId)}`, {
        method: "DELETE",
      });
    },
  };
}

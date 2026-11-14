import { AdminBoards } from "../src/features/admin/AdminBoards";
import { renderWithProviders } from "./TestProviders";
import type { BoardsApi } from "../src/api/boardsApi";
import type { Board } from "../src/api/types";

export function board(overrides: Partial<Board> = {}): Board {
  return {
    id: "1",
    name: "Google · all roles",
    url: "https://www.google.com/careers",
    type: "html_crawl",
    active: true,
    posting_count: 12,
    health: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

export function renderAdminBoardsWithProviders(api: Partial<BoardsApi>) {
  return renderWithProviders(<AdminBoards />, { boardsApi: api });
}

import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { AdminBoards } from "./AdminBoards";
import { BoardsApiProvider } from "../../api/BoardsApiProvider";
import { ApiError } from "../../api/ApiError";
import { createQueryClient } from "../../api/queryClient";
import type { BoardsApi } from "../../api/boardsApi";
import type { Board } from "../../api/types";

function board(overrides: Partial<Board> = {}): Board {
  return {
    id: "1",
    name: "Google · all roles",
    url: "https://www.google.com/careers",
    type: "html_crawl",
    posting_count: 12,
    health: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function renderWithProvider(api: Partial<BoardsApi>) {
  const fullApi: BoardsApi = {
    listBoards: () => new Promise(() => {}),
    createBoard: () => new Promise(() => {}),
    updateBoard: () => new Promise(() => {}),
    deleteBoard: () => new Promise(() => {}),
    ...api,
  } as BoardsApi;
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <BoardsApiProvider api={fullApi}>
        <AdminBoards />
      </BoardsApiProvider>
    </QueryClientProvider>,
  );
}

describe("AdminBoards", () => {
  it("renders the loading state before the response resolves", () => {
    renderWithProvider({ listBoards: () => new Promise(() => {}) });
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("renders the error state on a failed request", async () => {
    renderWithProvider({
      listBoards: () => Promise.reject(new Error("boom")),
    });
    expect(await screen.findByText("Couldn't load boards")).toBeInTheDocument();
  });

  it("renders boards ordered as the API returns them, with their type", async () => {
    renderWithProvider({
      listBoards: vi.fn<BoardsApi["listBoards"]>().mockResolvedValue({
        items: [
          board({ id: "1", name: "Alpha", type: "html_crawl" }),
          board({ id: "2", name: "Zebra", type: "json_api" }),
        ],
      }),
    });

    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Zebra")).toBeInTheDocument();
    expect(screen.getByText("HTML crawl")).toBeInTheDocument();
    expect(screen.getByText("JSON API")).toBeInTheDocument();
  });

  it("renders a null posting_count as an em dash", async () => {
    renderWithProvider({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board({ posting_count: null })] }),
    });

    expect(await screen.findByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("renders a numeric posting_count as-is", async () => {
    renderWithProvider({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board({ posting_count: 381 })] }),
    });

    expect(await screen.findByText("381")).toBeInTheDocument();
  });

  it("renders the empty state when there are no boards", async () => {
    renderWithProvider({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [] }),
    });

    expect(await screen.findByText("Nothing here yet.")).toBeInTheDocument();
  });

  it("adds a board through the new-board form", async () => {
    const listBoards = vi
      .fn<BoardsApi["listBoards"]>()
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValue({ items: [board()] });
    const createBoard = vi
      .fn<BoardsApi["createBoard"]>()
      .mockResolvedValue(board());
    renderWithProvider({ listBoards, createBoard });

    await screen.findByText("Nothing here yet.");
    const user = userEvent.setup();
    await user.click(screen.getByText("+ Add board"));
    await user.type(screen.getByPlaceholderText(/e.g. Google/), "New board");
    await user.type(
      screen.getByPlaceholderText("https://…"),
      "https://new.example.com",
    );
    await user.click(screen.getByText("Save"));

    await waitFor(() =>
      expect(createBoard).toHaveBeenCalledWith({
        name: "New board",
        url: "https://new.example.com",
        type: "html_crawl",
      }),
    );
  });

  it("the edit form carries no type control", async () => {
    renderWithProvider({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board()] }),
    });

    const user = userEvent.setup();
    await user.click(await screen.findByText("Edit"));

    expect(
      screen.queryByText("HTML crawl", { selector: "button" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("JSON API", { selector: "button" }),
    ).not.toBeInTheDocument();
  });

  it("edits a board's name and url", async () => {
    const updateBoard = vi
      .fn<BoardsApi["updateBoard"]>()
      .mockResolvedValue(board({ name: "Renamed" }));
    renderWithProvider({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board()] }),
      updateBoard,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByText("Edit"));
    const nameField = screen.getByDisplayValue("Google · all roles");
    await user.clear(nameField);
    await user.type(nameField, "Renamed");
    await user.click(screen.getByText("Save"));

    await waitFor(() =>
      expect(updateBoard).toHaveBeenCalledWith("1", {
        name: "Renamed",
        url: "https://www.google.com/careers",
      }),
    );
  });

  it("shows the API's message when creating a duplicate board", async () => {
    const createBoard = vi
      .fn<BoardsApi["createBoard"]>()
      .mockRejectedValue(
        new ApiError(409, "A board with that name or url already exists"),
      );
    renderWithProvider({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [] }),
      createBoard,
    });

    await screen.findByText("Nothing here yet.");
    const user = userEvent.setup();
    await user.click(screen.getByText("+ Add board"));
    await user.type(screen.getByPlaceholderText(/e.g. Google/), "Dup");
    await user.type(
      screen.getByPlaceholderText("https://…"),
      "https://dup.example.com",
    );
    await user.click(screen.getByText("Save"));

    expect(
      await screen.findByText("A board with that name or url already exists"),
    ).toBeInTheDocument();
  });

  it("removes a board", async () => {
    const deleteBoard = vi
      .fn<BoardsApi["deleteBoard"]>()
      .mockResolvedValue(undefined);
    renderWithProvider({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board()] }),
      deleteBoard,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByText("Remove"));

    await waitFor(() => expect(deleteBoard).toHaveBeenCalledWith("1"));
  });
});

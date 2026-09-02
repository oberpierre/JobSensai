import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { AdminBoards } from "./AdminBoards";
import { ApiError } from "../../api/ApiError";
import { renderWithProviders } from "../../../test/TestProviders";
import type { BoardsApi } from "../../api/boardsApi";
import type { Board } from "../../api/types";

function board(overrides: Partial<Board> = {}): Board {
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

function renderAdminBoardsWithProviders(api: Partial<BoardsApi>) {
  return renderWithProviders(<AdminBoards />, { boardsApi: api });
}

// Renders alongside AdminBoards so the test can read the same client the
// component's own useQueryClient() call would see, without reaching into
// TestProviders internals.
function QueryClientProbe({
  onClient,
}: {
  onClient: (client: QueryClient) => void;
}) {
  onClient(useQueryClient());
  return null;
}

describe("AdminBoards", () => {
  it("renders the loading state before the response resolves", () => {
    renderAdminBoardsWithProviders({ listBoards: () => new Promise(() => {}) });
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("renders the error state on a failed request", async () => {
    renderAdminBoardsWithProviders({
      listBoards: () => Promise.reject(new Error("boom")),
    });
    expect(await screen.findByText("Couldn't load boards")).toBeInTheDocument();
  });

  it("renders boards ordered as the API returns them, with their type", async () => {
    renderAdminBoardsWithProviders({
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
    renderAdminBoardsWithProviders({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board({ posting_count: null })] }),
    });

    expect(await screen.findByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("renders a numeric posting_count as-is", async () => {
    renderAdminBoardsWithProviders({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board({ posting_count: 381 })] }),
    });

    expect(await screen.findByText("381")).toBeInTheDocument();
  });

  it("renders the empty state when there are no boards", async () => {
    renderAdminBoardsWithProviders({
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
    renderAdminBoardsWithProviders({ listBoards, createBoard });

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
        active: true,
        type: "html_crawl",
      }),
    );
  });

  it("the edit form carries no type control", async () => {
    renderAdminBoardsWithProviders({
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
    renderAdminBoardsWithProviders({
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
        active: true,
      }),
    );
  });

  it("shows the API's message when creating a duplicate board", async () => {
    const createBoard = vi
      .fn<BoardsApi["createBoard"]>()
      .mockRejectedValue(
        new ApiError(409, "A board with that name or url already exists"),
      );
    renderAdminBoardsWithProviders({
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
    renderAdminBoardsWithProviders({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board()] }),
      deleteBoard,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByText("Remove"));

    await waitFor(() => expect(deleteBoard).toHaveBeenCalledWith("1"));
  });

  it("shows the API's message when a delete fails", async () => {
    const deleteBoard = vi
      .fn<BoardsApi["deleteBoard"]>()
      .mockRejectedValue(new ApiError(404, "No board with that id"));
    renderAdminBoardsWithProviders({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board()] }),
      deleteBoard,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByText("Remove"));

    expect(
      await screen.findByText("Remove failed: No board with that id"),
    ).toBeInTheDocument();
  });

  it("shows a failed row action outside an open edit form, and clears it on the next success", async () => {
    const deleteBoard = vi
      .fn<BoardsApi["deleteBoard"]>()
      .mockRejectedValueOnce(new ApiError(500, "boom"))
      .mockResolvedValueOnce(undefined);
    renderAdminBoardsWithProviders({
      listBoards: vi.fn<BoardsApi["listBoards"]>().mockResolvedValue({
        items: [
          board({ id: "1", name: "Alpha" }),
          board({ id: "2", name: "Zebra" }),
        ],
      }),
      deleteBoard,
    });

    const user = userEvent.setup();
    await screen.findByText("Alpha");
    await user.click(screen.getAllByText("Edit")[0]);

    await user.click(await screen.findByText("Remove"));

    const rowError = await screen.findByText("Remove failed: boom");
    expect(rowError.closest("form")).toBeNull();

    await user.click(screen.getByText("Remove"));
    await waitFor(() =>
      expect(screen.queryByText("Remove failed: boom")).not.toBeInTheDocument(),
    );
  });

  it("clears a failed row action once an unrelated action succeeds", async () => {
    const deleteBoard = vi
      .fn<BoardsApi["deleteBoard"]>()
      .mockRejectedValueOnce(new ApiError(500, "boom"));
    const createBoard = vi
      .fn<BoardsApi["createBoard"]>()
      .mockResolvedValue(board({ id: "2", name: "New board" }));
    renderAdminBoardsWithProviders({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board()] }),
      deleteBoard,
      createBoard,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByText("Remove"));
    await screen.findByText("Remove failed: boom");

    await user.click(screen.getByText("+ Add board"));
    await user.type(screen.getByPlaceholderText(/e.g. Google/), "New board");
    await user.type(
      screen.getByPlaceholderText("https://…"),
      "https://new.example.com",
    );
    await user.click(screen.getByText("Save"));

    await waitFor(() =>
      expect(screen.queryByText("Remove failed: boom")).not.toBeInTheDocument(),
    );
  });

  it("greys a json_api row and leaves an html_crawl row plain", async () => {
    renderAdminBoardsWithProviders({
      listBoards: vi.fn<BoardsApi["listBoards"]>().mockResolvedValue({
        items: [
          board({ id: "1", name: "Alpha", type: "html_crawl" }),
          board({ id: "2", name: "Zebra", type: "json_api" }),
        ],
      }),
    });

    const htmlRow = (await screen.findByText("Alpha")).parentElement
      ?.parentElement;
    expect(htmlRow?.className).not.toMatch(/rowGreyed/);

    const jsonRow = screen.getByText("Zebra").parentElement?.parentElement;
    expect(jsonRow?.className).toMatch(/rowGreyed/);
  });

  it("renders the toggle on for an active row and off for an inactive one", async () => {
    renderAdminBoardsWithProviders({
      listBoards: vi.fn<BoardsApi["listBoards"]>().mockResolvedValue({
        items: [
          board({ id: "1", name: "Alpha", active: true }),
          board({ id: "2", name: "Zebra", active: false }),
        ],
      }),
    });

    await screen.findByText("Alpha");
    const switches = screen.getAllByRole("switch");
    expect(switches[0]).toHaveAttribute("aria-checked", "true");
    expect(switches[1]).toHaveAttribute("aria-checked", "false");
  });

  it("names each row's switch for its board, since the control has no text", async () => {
    renderAdminBoardsWithProviders({
      listBoards: vi.fn<BoardsApi["listBoards"]>().mockResolvedValue({
        items: [
          board({ id: "1", name: "Alpha", active: true }),
          board({ id: "2", name: "Zebra", active: false }),
        ],
      }),
    });

    await screen.findByText("Alpha");

    expect(screen.getByRole("switch", { name: /Alpha/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("switch", { name: /Zebra/ })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("toggling a row's switch PUTs its existing name and url with active flipped", async () => {
    const updateBoard = vi
      .fn<BoardsApi["updateBoard"]>()
      .mockResolvedValue(board({ active: false }));
    renderAdminBoardsWithProviders({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board({ active: true })] }),
      updateBoard,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("switch"));

    await waitFor(() =>
      expect(updateBoard).toHaveBeenCalledWith("1", {
        name: "Google · all roles",
        url: "https://www.google.com/careers",
        active: false,
      }),
    );
  });

  // AdminBoards.tsx reads useQueryClient() itself to invalidate BOARDS_QUERY_KEY
  // after a save. If that call returns a different object than the one the
  // mounted useQuery observer is pinned to, the invalidation lands on a client
  // nothing observes and the list silently never refreshes.
  it("keeps the same query client instance across a rerender", async () => {
    const listBoards = vi
      .fn<BoardsApi["listBoards"]>()
      .mockResolvedValue({ items: [] });
    const seenClients: QueryClient[] = [];
    // A fresh element per call, since reusing one React element reference
    // across render and rerender lets React bail out of revisiting it.
    const probe = () => (
      <>
        <QueryClientProbe onClient={(client) => seenClients.push(client)} />
        <AdminBoards />
      </>
    );
    const { rerender } = renderWithProviders(probe(), {
      boardsApi: { listBoards },
    });
    await screen.findByText("Nothing here yet.");

    rerender(probe());
    await screen.findByText("Nothing here yet.");

    expect(seenClients[1]).toBe(seenClients[0]);
  });
});

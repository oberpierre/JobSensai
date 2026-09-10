import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/ApiError";
import {
  board,
  renderAdminBoardsWithProviders,
} from "../../../test/AdminBoardsHarness";
import type { BoardsApi } from "../../api/boardsApi";

// Drives the form through the screen that owns its mutations, so the payload each
// mode submits is asserted at the API boundary.
describe("BoardForm", () => {
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

  it("picking API in the create form reaches createBoard as the type", async () => {
    const listBoards = vi
      .fn<BoardsApi["listBoards"]>()
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValue({ items: [board({ type: "api" })] });
    const createBoard = vi
      .fn<BoardsApi["createBoard"]>()
      .mockResolvedValue(board({ type: "api" }));
    renderAdminBoardsWithProviders({ listBoards, createBoard });

    await screen.findByText("Nothing here yet.");
    const user = userEvent.setup();
    await user.click(screen.getByText("+ Add board"));
    await user.type(screen.getByPlaceholderText(/e.g. Google/), "New board");
    await user.type(
      screen.getByPlaceholderText("https://…"),
      "https://new.example.com",
    );
    await user.click(screen.getByText("API", { selector: "button" }));
    await user.click(screen.getByText("Save"));

    await waitFor(() =>
      expect(createBoard).toHaveBeenCalledWith({
        name: "New board",
        url: "https://new.example.com",
        active: true,
        type: "api",
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
      screen.queryByText("API", { selector: "button" }),
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
});

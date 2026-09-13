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
        company_name: null,
        type: "html_crawl",
      }),
    );
  });

  it("typing a company name in the create form reaches createBoard as company_name", async () => {
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
    await user.type(screen.getByLabelText("Company"), "Acme Corp");
    await user.click(screen.getByText("Save"));

    await waitFor(() =>
      expect(createBoard).toHaveBeenCalledWith({
        name: "New board",
        url: "https://new.example.com",
        active: true,
        company_name: "Acme Corp",
        type: "html_crawl",
      }),
    );
  });

  it("typing only spaces into Company in the create form sends company_name: null", async () => {
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
    await user.type(screen.getByLabelText("Company"), "   ");
    await user.click(screen.getByText("Save"));

    await waitFor(() =>
      expect(createBoard).toHaveBeenCalledWith({
        name: "New board",
        url: "https://new.example.com",
        active: true,
        company_name: null,
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
        company_name: null,
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
        company_name: null,
      }),
    );
  });

  it("shows an edited board's company name and resubmits it unchanged", async () => {
    const updateBoard = vi
      .fn<BoardsApi["updateBoard"]>()
      .mockResolvedValue(board({ company_name: "Acme Corp" }));
    renderAdminBoardsWithProviders({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board({ company_name: "Acme Corp" })] }),
      updateBoard,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByText("Edit"));
    expect(screen.getByLabelText("Company")).toHaveValue("Acme Corp");
    await user.click(screen.getByText("Save"));

    await waitFor(() =>
      expect(updateBoard).toHaveBeenCalledWith("1", {
        name: "Google · all roles",
        url: "https://www.google.com/careers",
        active: true,
        company_name: "Acme Corp",
      }),
    );
  });

  it("clearing an edited board's company name sends company_name: null", async () => {
    const updateBoard = vi
      .fn<BoardsApi["updateBoard"]>()
      .mockResolvedValue(board({ company_name: null }));
    renderAdminBoardsWithProviders({
      listBoards: vi
        .fn<BoardsApi["listBoards"]>()
        .mockResolvedValue({ items: [board({ company_name: "Acme Corp" })] }),
      updateBoard,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByText("Edit"));
    await user.clear(screen.getByLabelText("Company"));
    await user.click(screen.getByText("Save"));

    await waitFor(() =>
      expect(updateBoard).toHaveBeenCalledWith("1", {
        name: "Google · all roles",
        url: "https://www.google.com/careers",
        active: true,
        company_name: null,
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

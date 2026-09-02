import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { Nav } from "./Nav";

describe("Nav", () => {
  it("marks the active tab", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Nav />
      </MemoryRouter>,
    );
    expect(screen.getByText("Jobs")).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Jobs").tagName).toBe("A");
  });

  it("does not mark Jobs active for a path that merely starts with /jobs", () => {
    render(
      <MemoryRouter initialEntries={["/jobsomething"]}>
        <Nav />
      </MemoryRouter>,
    );
    expect(screen.getByText("Jobs")).not.toHaveAttribute("aria-current");
  });

  it("offers no destination that has no route", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Nav />
      </MemoryRouter>,
    );
    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(screen.queryByText("My CV")).not.toBeInTheDocument();
    expect(screen.queryByText("basic auth")).not.toBeInTheDocument();
  });

  it("marks Dashboard active on /admin and not on a path merely starting with it", () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/admin"]}>
        <Nav />
      </MemoryRouter>,
    );
    expect(screen.getByText("Dashboard")).toHaveAttribute(
      "aria-current",
      "page",
    );
    unmount();

    render(
      <MemoryRouter initialEntries={["/adminsomething"]}>
        <Nav />
      </MemoryRouter>,
    );
    expect(screen.getByText("Dashboard")).not.toHaveAttribute("aria-current");
  });

  it("emits the canonical trailing-slash Dashboard link and stays active there", () => {
    render(
      <MemoryRouter initialEntries={["/admin/"]}>
        <Nav />
      </MemoryRouter>,
    );
    expect(screen.getByText("Dashboard")).toHaveAttribute("href", "/admin/");
    expect(screen.getByText("Dashboard")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

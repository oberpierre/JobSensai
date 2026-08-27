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

  it("offers no destination that has no route", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Nav />
      </MemoryRouter>,
    );
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.queryByText("My CV")).not.toBeInTheDocument();
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
    expect(screen.queryByText("basic auth")).not.toBeInTheDocument();
  });
});

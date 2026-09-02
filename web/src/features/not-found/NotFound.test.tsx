import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { NotFound } from "./NotFound";

describe("NotFound", () => {
  it("shows the path that was asked for when redirected with state", () => {
    render(
      <MemoryRouter
        initialEntries={[{ pathname: "/not-found", state: { from: "/jobs" } }]}
      >
        <NotFound />
      </MemoryRouter>,
    );
    expect(screen.getByText("/jobs")).toBeInTheDocument();
  });

  it("drops the redirected-from section, label included, on a direct visit", () => {
    render(
      <MemoryRouter initialEntries={["/not-found"]}>
        <NotFound />
      </MemoryRouter>,
    );
    expect(screen.queryByText("redirected from")).not.toBeInTheDocument();
    expect(screen.queryByText("/jobs")).not.toBeInTheDocument();
  });
});

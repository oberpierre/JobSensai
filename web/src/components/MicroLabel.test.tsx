import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MicroLabel } from "./MicroLabel";

describe("MicroLabel", () => {
  it("is faint by default, the panel labels being the quiet case", () => {
    render(<MicroLabel>section</MicroLabel>);
    expect(screen.getByText("section").className).not.toMatch(/accent/);
  });

  it("takes the accent when the label is the loudest thing on the screen", () => {
    render(<MicroLabel tone="accent">404 · not found</MicroLabel>);
    expect(screen.getByText("404 · not found").className).toMatch(/accent/);
  });
});

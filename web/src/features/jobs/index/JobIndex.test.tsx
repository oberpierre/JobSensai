import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JobIndex } from "./JobIndex";

describe("JobIndex", () => {
  it("renders the empty state, reading no data", () => {
    render(<JobIndex />);
    expect(screen.getByText("no postings")).toBeInTheDocument();
    expect(screen.getByText("Nothing indexed yet.")).toBeInTheDocument();
  });
});

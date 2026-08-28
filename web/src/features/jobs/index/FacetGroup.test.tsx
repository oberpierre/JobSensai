import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FacetGroup } from "./FacetGroup";
import type { FacetValue } from "../../../api/types";

function values(count: number): FacetValue[] {
  return Array.from({ length: count }, (_, i) => ({
    value: `Location ${i + 1}`,
    count: count - i,
  }));
}

describe("FacetGroup", () => {
  it("renders nothing at all when the facet holds no values", () => {
    const { container } = render(
      <FacetGroup
        label="Employment type"
        values={[]}
        selected={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("Employment type")).not.toBeInTheDocument();
  });

  it("shows the first four values and hides the rest behind the expander", () => {
    render(
      <FacetGroup
        label="Location"
        values={values(25)}
        selected={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("Location 4")).toBeInTheDocument();
    expect(screen.queryByText("Location 5")).not.toBeInTheDocument();
    expect(screen.getByText("+ 21 more")).toBeInTheDocument();
  });

  it("collapses again once expanded, so a long facet can be scrolled past", async () => {
    render(
      <FacetGroup
        label="Location"
        values={values(25)}
        selected={[]}
        onToggle={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("+ 21 more"));
    expect(screen.getByText("Location 25")).toBeInTheDocument();

    await userEvent.click(screen.getByText("− show fewer"));
    expect(screen.queryByText("Location 25")).not.toBeInTheDocument();
    expect(screen.getByText("+ 21 more")).toBeInTheDocument();
  });
});

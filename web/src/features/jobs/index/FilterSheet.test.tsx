import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FilterSheet } from "./FilterSheet";
import type { FacetsResponse } from "../../../api/types";

function facets(): FacetsResponse {
  return {
    location: [{ value: "Zurich", count: 3 }],
    company: [{ value: "Acme", count: 3 }],
    employment_type: [],
  };
}

function noopFilters() {
  return {
    locations: [],
    companies: [],
    employmentTypes: [],
    includeClosed: false,
  };
}

describe("FilterSheet", () => {
  it("renders nothing while closed", () => {
    const { container } = render(
      <FilterSheet
        open={false}
        onClose={vi.fn()}
        facets={facets()}
        filters={noopFilters()}
        onToggleFacet={vi.fn()}
        onIncludeClosedChange={vi.fn()}
        onClearAll={vi.fn()}
        total={3}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("opens as a dialog", () => {
    render(
      <FilterSheet
        open
        onClose={vi.fn()}
        facets={facets()}
        filters={noopFilters()}
        onToggleFacet={vi.fn()}
        onIncludeClosedChange={vi.fn()}
        onClearAll={vi.fn()}
        total={3}
      />,
    );
    expect(screen.getByRole("dialog", { name: "Filters" })).toBeInTheDocument();
  });

  it("closes when the close button is clicked", async () => {
    const onClose = vi.fn();
    render(
      <FilterSheet
        open
        onClose={onClose}
        facets={facets()}
        filters={noopFilters()}
        onToggleFacet={vi.fn()}
        onIncludeClosedChange={vi.fn()}
        onClearAll={vi.fn()}
        total={3}
      />,
    );
    await userEvent.click(screen.getByLabelText("Close filters"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Clear all empties every filter", async () => {
    const onClearAll = vi.fn();
    render(
      <FilterSheet
        open
        onClose={vi.fn()}
        facets={facets()}
        filters={{
          locations: ["Zurich"],
          companies: ["Acme"],
          employmentTypes: [],
          includeClosed: true,
        }}
        onToggleFacet={vi.fn()}
        onIncludeClosedChange={vi.fn()}
        onClearAll={onClearAll}
        total={3}
      />,
    );
    await userEvent.click(screen.getByText("Clear all"));
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  it("Show N postings carries the filtered total rather than a facet count", () => {
    render(
      <FilterSheet
        open
        onClose={vi.fn()}
        facets={facets()}
        filters={noopFilters()}
        onToggleFacet={vi.fn()}
        onIncludeClosedChange={vi.fn()}
        onClearAll={vi.fn()}
        total={128}
      />,
    );
    // The facet counts above are both 3, so a button reading "Show 3 postings"
    // would mean the total prop was ignored in favour of one of them.
    expect(screen.getByText("Show 128 postings")).toBeInTheDocument();
  });
});

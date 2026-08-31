import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
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

    await userEvent.click(screen.getByText("- show fewer"));
    expect(screen.queryByText("Location 25")).not.toBeInTheDocument();
    expect(screen.getByText("+ 21 more")).toBeInTheDocument();
  });

  it("keeps a selected value on the list after it leaves the response", async () => {
    const onToggle = vi.fn();
    render(
      <FacetGroup
        label="Location"
        values={values(4)}
        selected={["Munich, Germany"]}
        onToggle={onToggle}
      />,
    );

    // Narrowing the search can drop a selected value from the counts. Without a
    // row for it the filter stays applied with nothing on the page to clear it.
    const orphan = screen.getByText("Munich, Germany");
    expect(orphan).toBeInTheDocument();
    await userEvent.click(orphan);
    expect(onToggle).toHaveBeenCalledWith("Munich, Germany");
  });

  it("shows a selected value even when the facet is otherwise empty", () => {
    render(
      <FacetGroup
        label="Location"
        values={[]}
        selected={["Nowhere"]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("Nowhere")).toBeInTheDocument();
  });

  it("renders a checked checkbox for a below-fold selection while collapsed, keeping the top four in order", () => {
    render(
      <FacetGroup
        label="Location"
        values={values(25)}
        selected={["Location 5"]}
        onToggle={vi.fn()}
      />,
    );

    const rows = screen
      .getAllByText(/^Location \d+$/)
      .map((value) => value.textContent);
    expect(rows).toEqual([
      "Location 1",
      "Location 2",
      "Location 3",
      "Location 4",
      "Location 5",
    ]);
    const orphanRow = screen.getByText("Location 5").closest("label");
    expect(orphanRow?.querySelector("input")).toBeChecked();
  });

  it("leaves every row in the same position when ticking a value already visible", async () => {
    // Owns its own selected state, the way FacetSidebar does, so the click below
    // drives a real re-render rather than a mock that leaves the DOM untouched.
    // Starts with nothing selected: a below-fold starting selection makes the
    // pre-click assertion fail before the click under test even runs.
    function Controlled() {
      const [selected, setSelected] = useState<string[]>([]);
      return (
        <FacetGroup
          label="Location"
          values={values(25)}
          selected={selected}
          onToggle={(value) =>
            setSelected((current) =>
              current.includes(value)
                ? current.filter((v) => v !== value)
                : [...current, value],
            )
          }
        />
      );
    }
    render(<Controlled />);

    const expectedOrder = [
      "Location 1",
      "Location 2",
      "Location 3",
      "Location 4",
    ];
    const rowsBefore = screen
      .getAllByText(/^Location \d+$/)
      .map((value) => value.textContent);
    expect(rowsBefore).toEqual(expectedOrder);

    await userEvent.click(screen.getByText("Location 2"));

    const rowsAfter = screen
      .getAllByText(/^Location \d+$/)
      .map((value) => value.textContent);
    expect(rowsAfter).toEqual(expectedOrder);
  });

  it("excludes a below-fold selection from the expander's count and keeps the control while expanded", async () => {
    render(
      <FacetGroup
        label="Location"
        values={values(25)}
        selected={["Location 10"]}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText("+ 20 more")).toBeInTheDocument();

    await userEvent.click(screen.getByText("+ 20 more"));
    expect(screen.getByText("- show fewer")).toBeInTheDocument();
  });
});

import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, it } from "vitest";
import { useJobFilters } from "./useJobFilters";

// Reads the URL alongside the hook under test, since that is the one place a
// write to useJobFilters is actually observable.
function useFiltersAndLocation() {
  return { jobFilters: useJobFilters(), location: useLocation() };
}

function useHarness(initialEntries: string[]) {
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
    );
  }
  return renderHook(useFiltersAndLocation, { wrapper });
}

describe("useJobFilters", () => {
  it("ticking a facet value writes exactly that value into the URL", () => {
    const { result } = useHarness(["/"]);

    act(() => result.current.jobFilters.toggleFacetValue("location", "Zurich"));

    expect(result.current.jobFilters.filters.locations).toEqual(["Zurich"]);
    expect(
      new URLSearchParams(result.current.location.search).getAll("location"),
    ).toEqual(["Zurich"]);
  });

  it("unticking a facet value removes exactly it, leaving other facets alone", () => {
    const { result } = useHarness([
      "/?location=Zurich&location=Berlin&company=Acme",
    ]);

    act(() => result.current.jobFilters.toggleFacetValue("location", "Zurich"));

    expect(result.current.jobFilters.filters.locations).toEqual(["Berlin"]);
    expect(result.current.jobFilters.filters.companies).toEqual(["Acme"]);
  });

  it("setSort writes sort=oldest into the URL", () => {
    const { result } = useHarness(["/"]);

    act(() => result.current.jobFilters.setSort("oldest"));

    expect(result.current.jobFilters.filters.sort).toBe("oldest");
    expect(
      new URLSearchParams(result.current.location.search).get("sort"),
    ).toBe("oldest");
  });

  it("setSort back to newest drops the parameter rather than writing it", () => {
    const { result } = useHarness(["/?sort=oldest"]);

    act(() => result.current.jobFilters.setSort("newest"));

    expect(result.current.jobFilters.filters.sort).toBe("newest");
    expect(
      new URLSearchParams(result.current.location.search).has("sort"),
    ).toBe(false);
  });

  it("reads a non-numeric page as page 1 rather than sending NaN to the route", () => {
    const { result } = useHarness(["/?page=abc"]);

    expect(result.current.jobFilters.filters.page).toBe(1);
  });

  it("reads a negative page as page 1 rather than a value the route's ge=1 rejects", () => {
    const { result } = useHarness(["/?page=-2"]);

    expect(result.current.jobFilters.filters.page).toBe(1);
  });
});

import "@testing-library/jest-dom/vitest";
import { useEffect } from "react";
import { screen } from "@testing-library/react";
import { useLocation, useNavigationType } from "react-router";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "./routes";
import { renderWithProviders } from "../test/TestProviders";

// Every path here renders whichever screen matches, and every screen queries
// its own API on mount, so both providers wrap every case. The other two
// screens' calls are left pending on purpose, since the assertions below only
// need markup each screen renders before its data arrives.
function renderAt(path: string) {
  return renderWithProviders(<AppRoutes />, { initialEntries: [path] });
}

// Records one entry per location commit, mounted beside AppRoutes inside the
// same router so a redirect it fires is observed rather than only its result.
function NavigationLog({
  entries,
}: {
  entries: { pathname: string; type: string }[];
}) {
  const location = useLocation();
  const type = useNavigationType();
  useEffect(() => {
    entries.push({ pathname: location.pathname, type });
  }, [location.pathname, type, entries]);
  return null;
}

function renderAtWithLog(path: string) {
  const entries: { pathname: string; type: string }[] = [];
  renderWithProviders(
    <>
      <AppRoutes />
      <NavigationLog entries={entries} />
    </>,
    { initialEntries: [path] },
  );
  return entries;
}

// Every link the app emits is canonical (trailing slash), but the patterns in
// routes.tsx are not, so this pins that React Router's matcher accepts both
// forms rather than trusting it by inspection.
describe("AppRoutes canonical trailing-slash locations", () => {
  it("renders the job index at /", () => {
    renderAt("/");
    expect(screen.getByPlaceholderText("Title or company")).toBeInTheDocument();
  });

  it("renders the job detail screen at /jobs/<id>/", () => {
    renderAt("/jobs/1/");
    expect(screen.getByText("← all postings")).toBeInTheDocument();
  });

  it("renders the admin dashboard at /admin/", () => {
    renderAt("/admin/");
    expect(screen.getByText("Job boards")).toBeInTheDocument();
  });
});

describe("AppRoutes unmatched paths", () => {
  it("sends /nonsense/ to /not-found/", () => {
    const entries = renderAtWithLog("/nonsense/");
    expect(
      screen.getByText("Nothing lives at this address"),
    ).toBeInTheDocument();
    expect(entries.at(-1)?.pathname).toBe("/not-found/");
  });

  it("sends /jobs to /not-found/, the address the nav's active check implies is real", () => {
    const entries = renderAtWithLog("/jobs");
    expect(
      screen.getByText("Nothing lives at this address"),
    ).toBeInTheDocument();
    expect(entries.at(-1)?.pathname).toBe("/not-found/");
  });

  it("replaces rather than pushes, so nothing before the redirect stays reachable", () => {
    const entries = renderAtWithLog("/nonsense/");
    // Exactly one navigation: the initial unmatched location, then the
    // redirect. A loop that still landed on the right address would show up
    // here as more than two, which checking only the final path would miss.
    expect(entries).toHaveLength(2);
    expect(entries[0]).toEqual({ pathname: "/nonsense/", type: "POP" });
    expect(entries[1]).toEqual({ pathname: "/not-found/", type: "REPLACE" });
  });
});

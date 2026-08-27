import { Outlet, Route, Routes } from "react-router";
import { Nav } from "./components/Nav";
import { JobIndex } from "./features/jobs/index/JobIndex";

// The nav wraps every route, so a later route joins this shell without
// restructuring it.
function AppShell() {
  return (
    <>
      <Nav />
      <Outlet />
    </>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<JobIndex />} />
      </Route>
    </Routes>
  );
}

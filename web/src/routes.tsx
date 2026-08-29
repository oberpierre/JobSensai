import { Outlet, Route, Routes } from "react-router";
import { Nav } from "./components/Nav";
import { JobIndex } from "./features/jobs/index/JobIndex";
import { JobDetail } from "./features/jobs/detail/JobDetail";
import { AdminBoards } from "./features/admin/AdminBoards";

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
        <Route path="/jobs/:id" element={<JobDetail />} />
        <Route path="/admin" element={<AdminBoards />} />
      </Route>
    </Routes>
  );
}

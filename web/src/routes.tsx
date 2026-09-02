import { Navigate, Outlet, Route, Routes, useLocation } from "react-router";
import { Nav } from "./components/Nav";
import { JobIndex } from "./features/jobs/index/JobIndex";
import { JobDetail } from "./features/jobs/detail/JobDetail";
import { AdminBoards } from "./features/admin/AdminBoards";
import { NotFound } from "./features/not-found/NotFound";

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

// Carries the path nothing matched into router state rather than a query
// parameter, so a direct visit or a reload has nothing to echo back.
function NotFoundRedirect() {
  const location = useLocation();
  return (
    <Navigate to="/not-found/" replace state={{ from: location.pathname }} />
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<JobIndex />} />
        <Route path="/jobs/:id" element={<JobDetail />} />
        <Route path="/admin" element={<AdminBoards />} />
        <Route path="/not-found" element={<NotFound />} />
        <Route path="*" element={<NotFoundRedirect />} />
      </Route>
    </Routes>
  );
}

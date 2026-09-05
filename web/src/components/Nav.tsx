import { Link, useLocation } from "react-router";
import logoUrl from "../assets/logo.svg";
import styles from "./Nav.module.scss";

interface Tab {
  label: string;
  to: string;
  isActive: (pathname: string) => boolean;
}

// A tab appears here when its route does, so the nav never offers a destination
// that does not exist.
const TABS: Tab[] = [
  {
    label: "Jobs",
    to: "/",
    isActive: (path) =>
      path === "/" || path === "/jobs" || path.startsWith("/jobs/"),
  },
  {
    label: "Dashboard",
    to: "/admin/",
    isActive: (path) => path === "/admin" || path.startsWith("/admin/"),
  },
];

export function Nav() {
  const { pathname } = useLocation();
  return (
    <nav className={styles.nav}>
      <div className={styles.tabs}>
        <Link to="/" className={styles.lockup}>
          <img src={logoUrl} alt="" className={styles.mark} />
          <span className={styles.wordmark}>jobsensai</span>
        </Link>
        {TABS.map((tab) => {
          const active = tab.isActive(pathname);
          return (
            <Link
              key={tab.label}
              to={tab.to}
              className={active ? styles.tabActive : styles.tab}
              aria-current={active ? "page" : undefined}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

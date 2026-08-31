import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const NAV = [
  { to: "/admin/dashboard", label: "Dashboard" },
  { to: "/admin/attendance", label: "Attendance" },
  { to: "/admin/performance", label: "Performance" },
  { to: "/admin/activity", label: "Activity" },
  { to: "/admin/employees", label: "Employees" },
  { to: "/admin/audit", label: "Audit log" },
  { to: "/admin/settings", label: "Settings" },
];

export default function AdminLayout() {
  const { employee, logout } = useAuth();

  return (
    <div className="min-h-screen md:flex">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:w-56 md:flex-col md:border-r md:border-border md:bg-white md:min-h-screen">
        <div className="px-5 py-5 border-b border-border">
          <p className="font-mono text-sm text-ink">Admin</p>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive ? "bg-brand-tint text-brand-dark" : "text-slate-muted hover:bg-surface"
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-5 py-4 border-t border-border">
          <p className="text-xs text-slate-muted truncate">{employee?.name}</p>
          <button onClick={logout} className="text-xs text-brand font-medium mt-1">
            Log out
          </button>
        </div>
      </aside>

      <div className="flex-1 min-w-0">
        {/* Mobile top bar + tab strip */}
        <header className="md:hidden sticky top-0 z-30 bg-white border-b border-border">
          <div className="px-4 h-14 flex items-center justify-between">
            <p className="font-mono text-sm text-ink">Admin</p>
            <button onClick={logout} className="text-sm text-slate-muted">
              Log out
            </button>
          </div>
          <nav className="flex overflow-x-auto px-2 pb-2 gap-1 no-scrollbar">
            {NAV.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium ${
                    isActive ? "bg-brand-tint text-brand-dark" : "text-slate-muted"
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </header>

        <main className="max-w-6xl mx-auto px-4 md:px-8 py-6 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

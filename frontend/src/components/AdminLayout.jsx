import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useState } from "react";
import PasswordChangeModal from "./PasswordChangeModal";

const NAV = [
  { to: "/admin/dashboard", label: "Dashboard" },
  { to: "/admin/attendance", label: "Attendance" },
  { to: "/admin/attendance-by-month", label: "Attendance by Month" },
  { to: "/admin/monthly-attendance", label: "Monthly Attendance" },
  { to: "/admin/performance", label: "Performance" },
  { to: "/admin/activity", label: "Activity" },
  { to: "/admin/employees", label: "Employees" },
  { to: "/admin/audit", label: "Audit log" },
  { to: "/admin/settings", label: "Settings" },
  { to: "/admin/calendar", label: "Calendar" },
  { to: "/admin/salary", label: "Salary" },
];

export default function AdminLayout() {
  const { employee, logout } = useAuth();
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const isSuperAdmin = employee?.role === "super_admin";
  const nav = NAV.filter((item) => !(item.to === "/admin/monthly-attendance" && isSuperAdmin));

  return (
    <div className="min-h-screen md:flex">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:w-56 md:flex-col md:border-r md:border-border md:bg-white md:min-h-screen">
        <div className="px-5 py-5 border-b border-border">
          <p className="font-mono text-sm text-ink">Admin</p>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {nav.map(({ to, label }) => (
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
          <div className="flex flex-col items-start">
            <button onClick={() => setShowPasswordModal(true)} className="text-xs text-brand font-medium mt-1">
              Change password
            </button>
            <button onClick={logout} className="text-xs text-slate-muted font-medium mt-1">
              Log out
            </button>
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0">
        {/* Mobile top bar + tab strip */}
        <header className="md:hidden sticky top-0 z-30 bg-white border-b border-border">
          <div className="px-4 h-14 flex items-center justify-between">
            <p className="font-mono text-sm text-ink">Admin</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setShowPasswordModal(true)} className="text-sm text-brand font-medium">
                Password
              </button>
              <button onClick={logout} className="text-sm text-slate-muted">
                Log out
              </button>
            </div>
          </div>
          <nav className="flex overflow-x-auto px-2 pb-2 gap-1 no-scrollbar">
            {nav.map(({ to, label }) => (
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

        {showPasswordModal && <PasswordChangeModal onClose={() => setShowPasswordModal(false)} />}

        <main className="max-w-6xl mx-auto px-4 md:px-8 py-6 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

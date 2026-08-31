import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import useLaptopPresence from "../hooks/useLaptopPresence";

const TABS = [
  { to: "/employee/dashboard", label: "Home", icon: HomeIcon },
  { to: "/employee/attendance", label: "Attendance", icon: CalendarIcon },
  { to: "/employee/performance", label: "Performance", icon: ClipboardIcon },
];

export default function EmployeeLayout() {
  const { employee, logout } = useAuth();
  useLaptopPresence();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-30 bg-white border-b border-border">
        <div className="max-w-lg mx-auto px-4 h-14 flex items-center justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink truncate">{employee?.name}</p>
            <p className="text-xs text-slate-muted truncate">{employee?.department || employee?.employee_code}</p>
          </div>
          <button
            onClick={logout}
            className="text-sm text-slate-muted hover:text-ink px-2 py-1 rounded-lg transition-colors"
          >
            Log out
          </button>
        </div>
      </header>

      <main className="flex-1 max-w-lg w-full mx-auto px-4 py-5 pb-24">
        <Outlet />
      </main>

      <nav className="fixed bottom-0 left-0 right-0 z-30 bg-white border-t border-border">
        <div className="max-w-lg mx-auto grid grid-cols-3">
          {TABS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex flex-col items-center gap-1 py-2.5 text-xs font-medium transition-colors ${
                  isActive ? "text-brand" : "text-slate-muted"
                }`
              }
            >
              <Icon className="h-5 w-5" />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

function HomeIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
      <path d="M3 11.5 12 4l9 7.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 10v9.5a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V10" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CalendarIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
      <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
      <path d="M8 3v4M16 3v4M3.5 10h17" strokeLinecap="round" />
    </svg>
  );
}

function ClipboardIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
      <rect x="5" y="4.5" width="14" height="16" rx="2" />
      <path d="M9 4V3.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1V4" strokeLinecap="round" />
      <path d="M8.5 11h7M8.5 14.5h7M8.5 18h4" strokeLinecap="round" />
    </svg>
  );
}

import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import LoadingScreen from "./LoadingScreen";

/**
 * Frontend route protection. This is a convenience for the user, NOT a
 * security boundary — every backend endpoint independently enforces
 * authentication and role via get_current_employee / require_role,
 * regardless of what this component does or doesn't render (see README
 * "No client-side security").
 */
export default function ProtectedRoute({ allowedRoles, children }) {
  const { loading, isAuthenticated, employee, profileError } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingScreen />;

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (profileError) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <p className="text-danger font-medium">{profileError}</p>
        </div>
      </div>
    );
  }

  if (allowedRoles && !allowedRoles.includes(employee.role)) {
    const fallback = employee.role === "employee" ? "/employee/dashboard" : "/admin/dashboard";
    return <Navigate to={fallback} replace />;
  }

  return children;
}

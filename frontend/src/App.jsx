import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ToastProvider } from "./context/ToastContext";
import ProtectedRoute from "./components/ProtectedRoute";
import EmployeeLayout from "./components/EmployeeLayout";
import AdminLayout from "./components/AdminLayout";
import LoadingScreen from "./components/LoadingScreen";
import Login from "./pages/Login";
import EmployeeDashboard from "./pages/EmployeeDashboard";
import Attendance from "./pages/Attendance";
import Performance from "./pages/Performance";
import Calendar from "./pages/Calendar";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminAttendance from "./pages/admin/AdminAttendance";
import AdminPerformance from "./pages/admin/AdminPerformance";
import AdminActivity from "./pages/admin/AdminActivity";
import Employees from "./pages/admin/Employees";
import AuditLogs from "./pages/admin/AuditLogs";
import CompanySettings from "./pages/admin/CompanySettings";
import AdminCalendar from "./pages/admin/Calendar";
import Salary from "./pages/admin/Salary";

function RootRedirect() {
  const { loading, isAuthenticated, employee } = useAuth();
  if (loading) return <LoadingScreen />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return (
    <Navigate
      to={employee.role === "employee" ? "/employee/dashboard" : "/admin/dashboard"}
      replace
    />
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Routes>
          <Route path="/" element={<RootRedirect />} />
          <Route path="/login" element={<Login />} />

          <Route
            path="/employee"
            element={
              <ProtectedRoute allowedRoles={["employee", "admin"]}>
                <EmployeeLayout />
              </ProtectedRoute>
            }
          >
            <Route path="dashboard" element={<EmployeeDashboard />} />
            <Route path="attendance" element={<Attendance />} />
            <Route path="performance" element={<Performance />} />
            <Route path="calendar" element={<Calendar />} />
          </Route>

          <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRoles={["admin", "super_admin"]}>
                <AdminLayout />
              </ProtectedRoute>
            }
          >
            <Route path="dashboard" element={<AdminDashboard />} />
            <Route path="attendance" element={<AdminAttendance />} />
            <Route path="performance" element={<AdminPerformance />} />
            <Route path="activity" element={<AdminActivity />} />
            <Route path="employees" element={<Employees />} />
            <Route path="audit" element={<AuditLogs />} />
            <Route path="settings" element={<CompanySettings />} />
            <Route path="calendar" element={<AdminCalendar />} />
            <Route path="salary" element={<Salary />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ToastProvider>
    </AuthProvider>
  );
}

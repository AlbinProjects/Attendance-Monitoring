import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../../services/api";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import Card from "../../components/Card";
import Modal from "../../components/Modal";
import EmployeeForm from "../../components/admin/EmployeeForm";

export default function Employees() {
  const { employee: currentEmployee } = useAuth();
  const { showToast } = useToast();
  const isSuperAdmin = currentEmployee?.role === "super_admin";

  const [employees, setEmployees] = useState(null);
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState(null); // { mode: 'create' | 'edit', employee? }
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(() => {
    api.get("/admin/employees").then((res) => setEmployees(res.data));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!employees) return [];
    if (!search.trim()) return employees;
    const s = search.toLowerCase();
    return employees.filter(
      (e) =>
        e.name?.toLowerCase().includes(s) ||
        e.email?.toLowerCase().includes(s) ||
        e.employee_code?.toLowerCase().includes(s)
    );
  }, [employees, search]);

  async function handleCreate(values) {
    setSubmitting(true);
    try {
      const res = await api.post("/admin/employees", {
        ...values,
        joining_date: values.joining_date || null,
      });
      showToast(
        `Employee created. Temporary password: ${res.data.temporary_password} — share this securely.`
      );
      setModal(null);
      load();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't create employee.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUpdate(employeeId, values) {
    setSubmitting(true);
    try {
      await api.put(`/admin/employees/${employeeId}`, {
        ...values,
        joining_date: values.joining_date || null,
      });
      showToast("Employee updated.");
      setModal(null);
      load();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't update employee.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold text-ink">Employees</h1>
        {isSuperAdmin && (
          <button
            onClick={() => setModal({ mode: "create" })}
            className="rounded-xl bg-ink text-white text-sm font-medium px-4 py-2"
          >
            + Add employee
          </button>
        )}
      </div>

      <input
        type="search"
        placeholder="Search by name, email, or code…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full sm:w-80 rounded-xl border border-border bg-white px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
      />

      <Card className="!p-0 overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead>
            <tr className="border-b border-border text-left text-xs text-slate-muted">
              <th className="px-4 py-3 font-medium">Name</th>
              <th className="px-4 py-3 font-medium">Code</th>
              <th className="px-4 py-3 font-medium">Department</th>
              <th className="px-4 py-3 font-medium">Role</th>
              <th className="px-4 py-3 font-medium">Status</th>
              {isSuperAdmin && <th className="px-4 py-3 font-medium"></th>}
            </tr>
          </thead>
          <tbody>
            {employees === null ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-muted">
                  Loading…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-muted">
                  No employees match your search.
                </td>
              </tr>
            ) : (
              filtered.map((e) => (
                <tr key={e.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-medium text-ink">{e.name}</td>
                  <td className="px-4 py-3 font-mono text-slate-muted">{e.employee_code}</td>
                  <td className="px-4 py-3 text-slate-muted">{e.department || "--"}</td>
                  <td className="px-4 py-3 capitalize text-slate-muted">{e.role.replace("_", " ")}</td>
                  <td className="px-4 py-3">
                    {e.is_active ? (
                      <span className="text-brand-dark text-xs font-medium">Active</span>
                    ) : (
                      <span className="text-danger text-xs font-medium">Disabled</span>
                    )}
                  </td>
                  {isSuperAdmin && (
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => setModal({ mode: "edit", employee: e })}
                        className="text-brand text-xs font-medium"
                      >
                        Edit
                      </button>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>

      {modal?.mode === "create" && (
        <Modal title="Add employee" onClose={() => setModal(null)}>
          <EmployeeForm mode="create" onSubmit={handleCreate} submitting={submitting} />
        </Modal>
      )}

      {modal?.mode === "edit" && (
        <Modal title={`Edit ${modal.employee.name}`} onClose={() => setModal(null)}>
          <EmployeeForm
            mode="edit"
            initial={modal.employee}
            onSubmit={(values) => handleUpdate(modal.employee.id, values)}
            submitting={submitting}
          />
        </Modal>
      )}
    </div>
  );
}

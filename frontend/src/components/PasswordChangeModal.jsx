import { useState } from "react";
import api from "../services/api";
import Modal from "./Modal";
import { useToast } from "../context/ToastContext";

export default function PasswordChangeModal({ onClose }) {
  const { showToast } = useToast();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      showToast("New passwords do not match.", "error");
      return;
    }
    if (newPassword.length < 8) {
      showToast("New password must be at least 8 characters.", "error");
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/auth/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      showToast("Password changed successfully.");
      onClose();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't change your password.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  const inputCls =
    "w-full border border-border rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand";

  return (
    <Modal title="Change password" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Current password">
          <input type="password" required autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} className={inputCls} />
        </Field>
        <Field label="New password">
          <input type="password" required minLength={8} maxLength={72} autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className={inputCls} />
          <p className="text-xs text-slate-muted mt-1">At least 8 characters.</p>
        </Field>
        <Field label="Confirm new password">
          <input type="password" required minLength={8} maxLength={72} autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className={inputCls} />
        </Field>
        <button type="submit" disabled={submitting} className="w-full rounded-xl bg-brand text-white font-medium py-3 disabled:opacity-60">
          {submitting ? "Changing…" : "Change password"}
        </button>
      </form>
    </Modal>
  );
}

function Field({ label, children }) {
  return (
    <label className="block text-sm">
      <span className="block text-xs text-slate-muted mb-1">{label}</span>
      {children}
    </label>
  );
}

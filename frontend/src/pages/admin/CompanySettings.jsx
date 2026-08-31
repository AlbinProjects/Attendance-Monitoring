import { useEffect, useState } from "react";
import api from "../../services/api";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import Card from "../../components/Card";

const inputCls =
  "w-full border border-border rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand disabled:opacity-60 disabled:bg-surface";

export default function CompanySettings() {
  const { employee } = useAuth();
  const { showToast } = useToast();
  const isSuperAdmin = employee?.role === "super_admin";

  const [values, setValues] = useState(null);
  const [saving, setSaving] = useState(false);
  const [locating, setLocating] = useState(false);

  useEffect(() => {
    api.get("/admin/settings").then((res) =>
      setValues({
        network_mode: res.data.network_mode || "dynamic",
        allowed_ips: (res.data.allowed_ips || []).join(", "),
        office_latitude: res.data.office_latitude ?? "",
        office_longitude: res.data.office_longitude ?? "",
        office_gps_radius_meters: res.data.office_gps_radius_meters ?? "",
        max_gps_accuracy_meters: res.data.max_gps_accuracy_meters ?? "",
        laptop_presence_freshness_minutes: res.data.laptop_presence_freshness_minutes ?? "",
      })
    );
  }, []);

  function update(field, value) {
    setValues((prev) => ({ ...prev, [field]: value }));
  }

  function useCurrentLocation() {
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        update("office_latitude", position.coords.latitude.toFixed(6));
        update("office_longitude", position.coords.longitude.toFixed(6));
        setLocating(false);
        showToast("Location filled in from this device — review before saving.");
      },
      () => {
        setLocating(false);
        showToast("Couldn’t get your location. Please enter coordinates manually.", "error");
      },
      { enableHighAccuracy: true, timeout: 15_000 }
    );
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        network_mode: values.network_mode,
        allowed_ips: values.allowed_ips
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        office_latitude: values.office_latitude === "" ? null : Number(values.office_latitude),
        office_longitude: values.office_longitude === "" ? null : Number(values.office_longitude),
        office_gps_radius_meters:
          values.office_gps_radius_meters === "" ? null : Number(values.office_gps_radius_meters),
        max_gps_accuracy_meters:
          values.max_gps_accuracy_meters === "" ? null : Number(values.max_gps_accuracy_meters),
        laptop_presence_freshness_minutes:
          values.laptop_presence_freshness_minutes === ""
            ? null
            : Number(values.laptop_presence_freshness_minutes),
      };
      await api.put("/admin/settings", payload);
      showToast("Company settings saved.");
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn’t save settings.", "error");
    } finally {
      setSaving(false);
    }
  }

  if (!values) return null;

  const isStatic = values.network_mode === "static";

  return (
    <div className="space-y-5 max-w-xl">
      <div>
        <h1 className="text-xl font-semibold text-ink">Company settings</h1>
        <p className="text-sm text-slate-muted mt-1">
          Controls how attendance is verified for every employee.
          {!isSuperAdmin && " Only a Super Admin can make changes here."}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <Card>
          <p className="text-xs uppercase tracking-wide text-slate-muted mb-3">Network mode</p>
          <div className="space-y-2">
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="radio"
                name="network_mode"
                checked={values.network_mode === "dynamic"}
                disabled={!isSuperAdmin}
                onChange={() => update("network_mode", "dynamic")}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium text-ink">Dynamic IP (recommended)</span>
                <p className="text-xs text-slate-muted">
                  GPS location only. Use this if your office doesn’t have a fixed public IP address
                  (e.g. CGNAT, or an ISP that changes your IP over time).
                </p>
              </span>
            </label>
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="radio"
                name="network_mode"
                checked={values.network_mode === "static"}
                disabled={!isSuperAdmin}
                onChange={() => update("network_mode", "static")}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium text-ink">Static IP</span>
                <p className="text-xs text-slate-muted">
                  Requires BOTH GPS location AND a matching office IP address. Only use this if your
                  office has a genuine, unchanging public IP.
                </p>
              </span>
            </label>
          </div>

          {isStatic && (
            <div className="mt-4">
              <label className="block text-sm">
                <span className="block text-xs text-slate-muted mb-1">
                  Allowed IP addresses (comma-separated)
                </span>
                <input
                  disabled={!isSuperAdmin}
                  value={values.allowed_ips}
                  onChange={(e) => update("allowed_ips", e.target.value)}
                  placeholder="103.42.196.118, 103.42.196.0/24"
                  className={inputCls}
                />
              </label>
            </div>
          )}
        </Card>

        <Card>
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs uppercase tracking-wide text-slate-muted">Office location</p>
            {isSuperAdmin && (
              <button
                type="button"
                onClick={useCurrentLocation}
                disabled={locating}
                className="text-xs text-brand font-medium"
              >
                {locating ? "Locating…" : "Use my current location"}
              </button>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="block text-xs text-slate-muted mb-1">Latitude</span>
              <input
                type="number"
                step="any"
                disabled={!isSuperAdmin}
                value={values.office_latitude}
                onChange={(e) => update("office_latitude", e.target.value)}
                className={inputCls}
              />
            </label>
            <label className="block text-sm">
              <span className="block text-xs text-slate-muted mb-1">Longitude</span>
              <input
                type="number"
                step="any"
                disabled={!isSuperAdmin}
                value={values.office_longitude}
                onChange={(e) => update("office_longitude", e.target.value)}
                className={inputCls}
              />
            </label>
            <label className="block text-sm">
              <span className="block text-xs text-slate-muted mb-1">Radius (meters)</span>
              <input
                type="number"
                min="1"
                disabled={!isSuperAdmin}
                value={values.office_gps_radius_meters}
                onChange={(e) => update("office_gps_radius_meters", e.target.value)}
                className={inputCls}
              />
            </label>
            <label className="block text-sm">
              <span className="block text-xs text-slate-muted mb-1">Max GPS accuracy (meters)</span>
              <input
                type="number"
                min="1"
                disabled={!isSuperAdmin}
                value={values.max_gps_accuracy_meters}
                onChange={(e) => update("max_gps_accuracy_meters", e.target.value)}
                className={inputCls}
              />
            </label>
          </div>
          <p className="text-xs text-slate-muted mt-3">
            Leave a field blank to use the deployment’s default. GPS can be spoofed on some devices
            and accuracy varies indoors — this is a practical presence signal, not proof of physical
            presence.
          </p>
        </Card>

        <Card>
          <p className="text-xs uppercase tracking-wide text-slate-muted mb-3">Laptop presence</p>
          <label className="block text-sm max-w-xs">
            <span className="block text-xs text-slate-muted mb-1">
              Freshness window (minutes)
            </span>
            <input
              type="number"
              min="1"
              disabled={!isSuperAdmin}
              value={values.laptop_presence_freshness_minutes}
              onChange={(e) => update("laptop_presence_freshness_minutes", e.target.value)}
              className={inputCls}
            />
          </label>
          <p className="text-xs text-slate-muted mt-2">
            How recently an employee’s laptop must have had the app open before their phone can
            check in.
          </p>
        </Card>

        {isSuperAdmin && (
          <button
            type="submit"
            disabled={saving}
            className="rounded-xl bg-brand text-white font-medium px-6 py-3 disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save settings"}
          </button>
        )}
      </form>
    </div>
  );
}

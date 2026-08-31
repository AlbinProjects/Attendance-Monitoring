import Card from "./Card";

/**
 * Shown only before check-in, since that's when the laptop-presence
 * requirement (Phase 14) applies. `connected === null` means the status
 * hasn't loaded yet — render nothing rather than a misleading state.
 */
export default function LaptopStatusCard({ connected }) {
  if (connected === null) return null;

  return (
    <Card className={connected ? "!bg-brand-tint !border-brand/20" : "!bg-amber-tint !border-amber/30"}>
      <div className="flex items-center gap-2.5">
        <span className="text-lg">💻</span>
        <div>
          <p className={`text-sm font-medium ${connected ? "text-brand-dark" : "text-amber"}`}>
            {connected ? "Laptop connected" : "Laptop not detected"}
          </p>
          {!connected && (
            <p className="text-xs text-amber/80 mt-0.5">
              Open this app on your laptop before checking in from your phone.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

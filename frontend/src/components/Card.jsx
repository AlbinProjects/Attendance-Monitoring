export default function Card({ children, className = "", padded = true }) {
  return (
    <div
      className={`bg-white rounded-2xl border border-border shadow-card ${
        padded ? "p-5" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div style={{ marginTop: 40, textAlign: "center", color: "#8A95A2", fontSize: 14, fontWeight: 500 }}>
      {label}
    </div>
  );
}

export function ErrorState({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div className="state-panel">
      <div className="state-icon" style={{ background: "#FBEAE8", color: "#B42318" }}>
        ⚠
      </div>
      <h2 style={{ margin: "18px 0 6px", fontSize: 18, fontWeight: 700 }}>{title}</h2>
      <p style={{ margin: "0 auto", fontSize: 14, color: "#6B7686", maxWidth: 360, lineHeight: 1.5 }}>{message}</p>
      {onRetry && (
        <button className="btn-primary" style={{ marginTop: 22 }} onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="state-panel">
      <div className="state-icon" style={{ background: "#E7F4EC", color: "#1F7A4D" }}>
        ✓
      </div>
      <h2 style={{ margin: "18px 0 6px", fontSize: 18, fontWeight: 700 }}>{title}</h2>
      <p style={{ margin: "0 auto", fontSize: 14, color: "#6B7686", maxWidth: 380, lineHeight: 1.5 }}>{message}</p>
    </div>
  );
}

import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { voluntarySignOut } from "../auth/RequireAuth";

export function LoginPage() {
  const { user, login, isAuthenticating } = useAuth();
  const location = useLocation();
  const [tenantSlug, setTenantSlug] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Once mounted, the sign-out flag has done its job (suppressing `from` on
  // however many stale RequireAuth re-fires happened during the redirect
  // race -- see RequireAuth.tsx). Clear it so a later genuine session
  // expiry on this tab can attach `from` normally.
  useEffect(() => {
    voluntarySignOut.current = false;
  }, []);

  // The single source of truth for the post-login redirect target -- once
  // `user` becomes truthy (set by handleSubmit's login() call below), this
  // takes over and renders instead of the form. No separate imperative
  // navigate() call after login, so there's no race between the two.
  if (user) {
    const from = (location.state as { from?: Location })?.from?.pathname ?? "/board";
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await login(tenantSlug, email, password);
    } catch {
      setError("Invalid tenant, email, or password.");
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#E9EDF0",
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="card"
        style={{ width: 360, display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 6 }}>
          <span
            style={{
              width: 30,
              height: 30,
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#fff",
              fontWeight: 800,
              fontSize: 15,
              background: "#0E7C86",
            }}
          >
            C
          </span>
          <div>
            <div style={{ fontWeight: 800, fontSize: 16 }}>Copilot</div>
            <div style={{ fontSize: 11, color: "#8A95A2", fontWeight: 600 }}>Sign in</div>
          </div>
        </div>

        <label style={{ fontSize: 12, fontWeight: 700, color: "#5A6573" }}>
          College
          <input
            required
            value={tenantSlug}
            onChange={(e) => setTenantSlug(e.target.value)}
            placeholder="demo-eng"
            style={{
              display: "block",
              width: "100%",
              marginTop: 6,
              border: "1px solid #DDE4E9",
              borderRadius: 9,
              padding: "10px 12px",
              fontSize: 14,
            }}
          />
        </label>
        <label style={{ fontSize: 12, fontWeight: 700, color: "#5A6573" }}>
          Email
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{
              display: "block",
              width: "100%",
              marginTop: 6,
              border: "1px solid #DDE4E9",
              borderRadius: 9,
              padding: "10px 12px",
              fontSize: 14,
            }}
          />
        </label>
        <label style={{ fontSize: 12, fontWeight: 700, color: "#5A6573" }}>
          Password
          <input
            required
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{
              display: "block",
              width: "100%",
              marginTop: 6,
              border: "1px solid #DDE4E9",
              borderRadius: 9,
              padding: "10px 12px",
              fontSize: 14,
            }}
          />
        </label>

        {error && <div style={{ color: "#B42318", fontSize: 13, fontWeight: 600 }}>{error}</div>}

        <button className="btn-primary" type="submit" disabled={isAuthenticating} style={{ marginTop: 6 }}>
          {isAuthenticating ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

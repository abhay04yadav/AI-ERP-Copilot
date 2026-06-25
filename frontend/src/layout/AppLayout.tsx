import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { hasFullVisibility, useAuth } from "../auth/AuthContext";
import { voluntarySignOut } from "../auth/RequireAuth";
import { AlertsBell } from "./AlertsBell";
import { StaleBanner } from "./StaleBanner";

function navStyle(active: boolean) {
  return active
    ? {
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "9px 10px",
        borderRadius: 8,
        background: "#E3F1F2",
        color: "#0A656D",
        fontWeight: 700,
        fontSize: 13.5,
        borderLeft: "3px solid #0E7C86",
        width: "100%",
        textAlign: "left" as const,
      }
    : {
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "9px 10px",
        borderRadius: 8,
        background: "transparent",
        color: "#5A6573",
        fontWeight: 600,
        fontSize: 13.5,
        width: "100%",
        textAlign: "left" as const,
      };
}

export function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const privileged = user ? hasFullVisibility(user.role) : false;
  const initials = user ? user.role.slice(0, 2).toUpperCase() : "";

  // Navigates explicitly with no `state` rather than letting RequireAuth's
  // generic "redirect unauthenticated access back to where it came from"
  // handle it -- that `from` is meant for involuntary redirects (session
  // expired), not a voluntary sign-out. Without this, browser history's
  // persisted state (history.state survives a full reload) carries the
  // page the user just left into the *next* person's post-login redirect
  // if they log in again in the same tab.
  function handleSignOut() {
    voluntarySignOut.current = true;
    logout();
    navigate("/login", { replace: true, state: null });
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", color: "#161E29" }}>
      <aside
        className="app-rail"
        style={{
          width: 230,
          flex: "none",
          background: "#fff",
          borderRight: "1px solid #E1E7EC",
          display: "flex",
          flexDirection: "column",
          padding: "20px 16px",
          position: "sticky",
          top: 0,
          height: "100vh",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "4px 6px 0" }}>
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
          <div style={{ lineHeight: 1.1 }}>
            <div style={{ fontWeight: 800, fontSize: 15, letterSpacing: "-.01em" }}>Copilot</div>
            <div style={{ fontSize: 11, color: "#8A95A2", fontWeight: 600, marginTop: 1 }}>College welfare</div>
          </div>
        </div>

        <nav style={{ marginTop: 26, display: "flex", flexDirection: "column", gap: 3 }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".09em", color: "#A2ACB8", padding: "0 8px 8px" }}>
            WORKSPACE
          </div>
          <NavLink to="/board" style={({ isActive }) => navStyle(isActive)}>
            <span style={{ width: 17, display: "inline-flex", justifyContent: "center" }}>▦</span> Risk Board
          </NavLink>
          {privileged && (
            <NavLink to="/dashboard" style={({ isActive }) => navStyle(isActive)}>
              <span style={{ width: 17, display: "inline-flex", justifyContent: "center" }}>◳</span> Dashboard
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: 9.5,
                  fontWeight: 700,
                  letterSpacing: ".04em",
                  color: "#B3BCC6",
                  border: "1px solid #E1E7EC",
                  borderRadius: 5,
                  padding: "1px 5px",
                }}
              >
                LEADERSHIP
              </span>
            </NavLink>
          )}
          {user?.role === "admin" && (
            <>
              <NavLink to="/config" style={({ isActive }) => navStyle(isActive)}>
                <span style={{ width: 17, display: "inline-flex", justifyContent: "center" }}>⚙</span> Risk config
              </NavLink>
              <NavLink to="/imports" style={({ isActive }) => navStyle(isActive)}>
                <span style={{ width: 17, display: "inline-flex", justifyContent: "center" }}>⇪</span> Imports
              </NavLink>
            </>
          )}
        </nav>

        <div style={{ flex: 1 }} />

        <div
          style={{
            borderTop: "1px solid #EDF1F4",
            paddingTop: 14,
            display: "flex",
            alignItems: "center",
            gap: 11,
          }}
        >
          <span
            style={{
              width: 36,
              height: 36,
              borderRadius: "50%",
              background: "#E3F1F2",
              color: "#0A656D",
              fontWeight: 700,
              fontSize: 13,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "none",
            }}
          >
            {initials}
          </span>
          <div style={{ lineHeight: 1.2, minWidth: 0, flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 13, textTransform: "capitalize" }}>{user?.role}</div>
            <button onClick={handleSignOut} style={{ fontSize: 11, color: "#8A95A2", fontWeight: 600 }}>
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <StaleBanner />
        <div
          style={{
            padding: "14px 32px",
            display: "flex",
            justifyContent: "flex-end",
            borderBottom: "1px solid #E1E7EC",
            background: "#fff",
          }}
        >
          <AlertsBell />
        </div>
        <Outlet />
      </main>
    </div>
  );
}

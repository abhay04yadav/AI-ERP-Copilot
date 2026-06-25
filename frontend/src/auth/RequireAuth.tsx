import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "./AuthContext";

// Set synchronously by AppLayout's sign-out handler, read here, and cleared
// by LoginPage once mounted. A plain module flag (not React state) is used
// deliberately: navigate()'s history update and logout()'s user=null update
// don't always land in the same React commit, so RequireAuth can still
// render against the pre-navigate location after an explicit sign-out
// navigate() call has already fired. That stale render would otherwise
// re-attach the page-being-left as `from`, clobbering the explicit redirect
// with a target meant for the *next* person who logs in. The flag survives
// across however many of those stale re-fires happen before /login mounts.
export const voluntarySignOut = { current: false };

export function RequireAuth() {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) {
    const state = voluntarySignOut.current ? undefined : { from: location };
    return <Navigate to="/login" state={state} replace />;
  }
  return <Outlet />;
}

// UX guard only (Phase 3 guide §B.3): hides the route from a faculty user.
// The server is the real boundary -- GET /risk/summary already returns the
// caller's own scope (or 403 for the student role) regardless of this check.
export function RequirePrivileged() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  const privileged = ["admin", "principal", "registrar", "iqac"].includes(user.role);
  if (!privileged) return <Navigate to="/board" replace />;
  return <Outlet />;
}

export function RequireAdmin() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "admin") return <Navigate to="/board" replace />;
  return <Outlet />;
}

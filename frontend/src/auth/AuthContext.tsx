import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { login as apiLogin } from "../api/auth";
import { setOnAuthExpired } from "../api/client";
import { clearTokens, decodeAccessToken, getAccessToken, setTokens } from "./tokenStorage";

interface AuthUser {
  userId: string;
  tenantId: string;
  role: string;
}

interface AuthState {
  user: AuthUser | null;
  isAuthenticating: boolean;
  login: (tenantSlug: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

function userFromToken(token: string | null): AuthUser | null {
  if (!token) return null;
  const payload = decodeAccessToken(token);
  if (!payload) return null;
  return { userId: payload.sub, tenantId: payload.tenant_id, role: payload.role };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => userFromToken(getAccessToken()));
  const [isAuthenticating, setIsAuthenticating] = useState(false);

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
  }, []);

  useEffect(() => {
    setOnAuthExpired(logout);
  }, [logout]);

  const login = useCallback(async (tenantSlug: string, email: string, password: string) => {
    setIsAuthenticating(true);
    try {
      const tokens = await apiLogin(tenantSlug, email, password);
      setTokens(tokens.access_token, tokens.refresh_token);
      setUser(userFromToken(tokens.access_token));
    } finally {
      setIsAuthenticating(false);
    }
  }, []);

  const value = useMemo(() => ({ user, isAuthenticating, login, logout }), [user, isAuthenticating, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export const PRIVILEGED_ROLES = ["admin", "principal", "registrar", "iqac"] as const;

export function hasFullVisibility(role: string): boolean {
  return (PRIVILEGED_ROLES as readonly string[]).includes(role);
}

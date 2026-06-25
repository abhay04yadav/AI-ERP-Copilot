const ACCESS_KEY = "copilot.access_token";
const REFRESH_KEY = "copilot.refresh_token";

export interface AccessTokenPayload {
  sub: string;
  tenant_id: string;
  role: string;
  exp: number;
  type: "access";
}

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

// Decodes the JWT payload for UI role-gating only (nav visibility, route
// guards). Never trusted as an authorization decision -- the server is
// always the security boundary (Phase 3 guide rule #3) and re-checks role
// and tenant scope on every request regardless of what this returns.
export function decodeAccessToken(token: string): AccessTokenPayload | null {
  try {
    const payloadSegment = token.split(".")[1];
    const json = atob(payloadSegment.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as AccessTokenPayload;
  } catch {
    return null;
  }
}

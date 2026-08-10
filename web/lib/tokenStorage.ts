const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";

// sessionStorage, not localStorage or an httpOnly cookie — no backend
// cookie/CSRF support exists (see mobile/src/services/tokenStorage.ts for
// the same constraint on web builds there), and this HR dashboard must not
// silently stay signed in across browser restarts: sessionStorage clears
// when the tab/browser closes, so each fresh run of the app requires
// sign-in again. A future hardening pass could move to httpOnly cookies.

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens(accessToken: string, refreshToken: string): void {
  window.sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  window.sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearTokens(): void {
  window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
}

import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

import { getApiBaseUrl } from "./config";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "./tokenStorage";

let onSessionExpired: (() => void) | null = null;

export function setSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler;
}

/**
 * Without this, an unreachable backend (wrong LAN IP, dead tunnel, phone on
 * the wrong Wi-Fi) hangs on the OS's own connect timeout — 60s+ on mobile —
 * with the button just spinning and no error surfaced for the whole wait.
 *
 * 30s, not 15s: face-verification-gated requests (check-in/out, break
 * start/end) run a real ONNX detect+embed pass server-side on top of the
 * network round trip and a base64 selfie upload — 15s was tight enough to
 * false-positive-timeout a legitimate slow-but-working response (see
 * AI-CHANGELOG.md). The backend now warms the model at startup so this
 * shouldn't routinely run long, but 30s leaves real headroom for a slow
 * connection rather than trading one failure mode for another.
 */
const API_TIMEOUT_MS = 30_000;

export const api = axios.create({
  baseURL: getApiBaseUrl(),
  timeout: API_TIMEOUT_MS,
});

api.interceptors.request.use(async (config) => {
  const token = await getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
}

let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const refreshToken = await getRefreshToken();
  if (!refreshToken) {
    throw new Error("no refresh token available");
  }
  const response = await axios.post(
    `${getApiBaseUrl()}/auth/refresh`,
    { refresh_token: refreshToken },
    { timeout: API_TIMEOUT_MS },
  );
  const { access_token, refresh_token } = response.data;
  await setTokens(access_token, refresh_token);
  return access_token;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined;

    if (error.response?.status !== 401 || !config) {
      throw error;
    }
    if (config.url?.includes("/auth/refresh") || config.url?.includes("/auth/login")) {
      throw error;
    }
    if (config._retried) {
      // Refresh already succeeded once for this request and the retry with
      // the new access token STILL 401'd — the refresh token itself must
      // have been invalidated since (revoked on another device, password
      // change, admin action). Without this, auth.status stays
      // "authenticated" forever: every subsequent call silently 401s and
      // there is no path back to the login screen.
      await clearTokens();
      onSessionExpired?.();
      throw error;
    }

    config._retried = true;
    try {
      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
      }
      const newAccessToken = await refreshPromise;
      config.headers = config.headers ?? {};
      config.headers.Authorization = `Bearer ${newAccessToken}`;
      return api(config);
    } catch (refreshError) {
      await clearTokens();
      onSessionExpired?.();
      throw refreshError;
    }
  },
);

import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

import { getApiBaseUrl } from "./config";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "./tokenStorage";

let onSessionExpired: (() => void) | null = null;

export function setSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler;
}

export const api = axios.create({
  baseURL: getApiBaseUrl(),
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
  const response = await axios.post(`${getApiBaseUrl()}/auth/refresh`, {
    refresh_token: refreshToken,
  });
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

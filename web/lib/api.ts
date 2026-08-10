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

api.interceptors.request.use((config) => {
  const token = getAccessToken();
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
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new Error("no refresh token available");
  }
  const response = await axios.post(`${getApiBaseUrl()}/auth/refresh`, {
    refresh_token: refreshToken,
  });
  const { access_token, refresh_token } = response.data;
  setTokens(access_token, refresh_token);
  return access_token;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined;

    if (error.response?.status !== 401 || !config || config._retried) {
      throw error;
    }
    if (config.url?.includes("/auth/refresh") || config.url?.includes("/auth/login")) {
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
      clearTokens();
      onSessionExpired?.();
      throw refreshError;
    }
  },
);

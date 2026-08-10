import { api } from "./api";
import { clearTokens, getRefreshToken, setTokens } from "./tokenStorage";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  is_verified: boolean;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await api.post("/auth/login", { email, password });
  const { access_token, refresh_token } = response.data;
  setTokens(access_token, refresh_token);
  return getMe();
}

export async function getMe(): Promise<User> {
  const response = await api.get<User>("/auth/me");
  return response.data;
}

export async function logout(): Promise<void> {
  const refreshToken = getRefreshToken();
  try {
    if (refreshToken) {
      await api.post("/auth/logout", { refresh_token: refreshToken });
    }
  } finally {
    clearTokens();
  }
}

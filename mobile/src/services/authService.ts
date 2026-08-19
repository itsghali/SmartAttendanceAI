import { api } from "./api";
import { clearTokens, getRefreshToken, setTokens } from "./tokenStorage";

export interface User {
  id: string;
  email: string;
  full_name: string;
  phone_number: string | null;
  role: string;
  is_active: boolean;
  is_verified: boolean;
  workforce_intelligence_notice_acknowledged_at: string | null;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await api.post("/auth/login", { email, password });
  const { access_token, refresh_token } = response.data;
  await setTokens(access_token, refresh_token);
  return getMe();
}

export async function register(
  email: string,
  password: string,
  fullName: string,
  phoneNumber: string,
): Promise<User> {
  const response = await api.post<User>("/auth/register", {
    email,
    password,
    full_name: fullName,
    phone_number: phoneNumber,
  });
  return response.data;
}

export async function getMe(): Promise<User> {
  const response = await api.get<User>("/auth/me");
  return response.data;
}

// GOVERNANCE.md Section 2 — records that the WorkforceIntelligenceNoticeModal
// was dismissed. Not a permission/consent gate: nothing downstream reads or
// branches on this beyond deciding whether to show the modal again.
export async function acknowledgeWorkforceIntelligenceNotice(): Promise<User> {
  const response = await api.post<User>("/auth/acknowledge-workforce-intelligence-notice");
  return response.data;
}

export async function logout(): Promise<void> {
  const refreshToken = await getRefreshToken();
  try {
    if (refreshToken) {
      await api.post("/auth/logout", { refresh_token: refreshToken });
    }
  } finally {
    await clearTokens();
  }
}

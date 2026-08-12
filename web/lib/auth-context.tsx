"use client";

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from "react";

import { getMe, login as loginRequest, logout as logoutRequest, User } from "./authService";
import { getAccessToken } from "./tokenStorage";
import { setSessionExpiredHandler } from "./api";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const clearSession = useCallback(() => {
    setUser(null);
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(clearSession);

    if (!getAccessToken()) {
      setLoading(false);
      return;
    }
    getMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [clearSession]);

  async function login(email: string, password: string): Promise<User> {
    const loggedInUser = await loginRequest(email, password);
    setUser(loggedInUser);
    return loggedInUser;
  }

  async function logout(): Promise<void> {
    await logoutRequest();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

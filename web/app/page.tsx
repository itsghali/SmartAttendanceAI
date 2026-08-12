"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "../lib/auth-context";
import { roleLandingPath } from "../lib/roleRouting";

export default function RootPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? roleLandingPath(user.role) : "/login");
  }, [loading, user, router]);

  return null;
}

"use client";

import Link from "next/link";
import { ReactNode } from "react";

import { useAuth } from "../lib/auth-context";
import { usePollingExceptions } from "./site-status/usePollingExceptions";

type NavKey = "geofences" | "employees" | "face-enrollment" | "site-status";

const NAV_ITEMS: { key: NavKey; label: string; href: string }[] = [
  { key: "geofences", label: "Geofences", href: "/geofences" },
  { key: "employees", label: "Employees", href: "/employees" },
  { key: "face-enrollment", label: "Face Enrollment", href: "/face-enrollment" },
  { key: "site-status", label: "Site Status", href: "/site-status" },
];

const BADGE_POLL_INTERVAL_MS = 30_000;

export default function AppHeader({
  current,
  title,
  subtitle,
  extraActions,
}: {
  current: NavKey;
  title: string;
  subtitle?: string;
  extraActions?: ReactNode;
}) {
  const { user, logout } = useAuth();
  // Reuses the same polling hook site-status's own table uses — a second,
  // independent poll loop while ON site-status is a small redundancy
  // (accepted rather than threading its count through a prop), but the
  // badge itself is only rendered on the OTHER three pages, where this was
  // previously invisible entirely (see product-completeness audit P1 #3).
  const { needsAttentionCount } = usePollingExceptions(BADGE_POLL_INTERVAL_MS);

  return (
    <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
      <div className="flex items-center gap-4">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">{title}</h1>
        {subtitle && <span className="text-sm text-zinc-500">{subtitle}</span>}
        {NAV_ITEMS.filter((item) => item.key !== current).map((item) => (
          <Link
            key={item.key}
            href={item.href}
            className="flex items-center gap-1.5 text-sm text-blue-600 underline"
          >
            {item.label}
            {item.key === "site-status" && needsAttentionCount > 0 && (
              <span
                className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-600 px-1.5 text-xs font-semibold text-white no-underline"
                aria-label={`${needsAttentionCount} attendance exception${needsAttentionCount === 1 ? "" : "s"} need${needsAttentionCount === 1 ? "s" : ""} attention`}
              >
                {needsAttentionCount}
              </span>
            )}
          </Link>
        ))}
      </div>
      <div className="flex items-center gap-4 text-sm text-zinc-600 dark:text-zinc-400">
        {extraActions}
        <span>
          {user?.full_name} ({user?.role})
        </span>
        <button onClick={() => logout()} className="underline">
          Sign out
        </button>
      </div>
    </header>
  );
}

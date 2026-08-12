"use client";

import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";

import { useAuth } from "../lib/auth-context";
import { listProblemReports } from "../lib/problemReportService";
import { usePollingExceptions } from "./site-status/usePollingExceptions";

type NavKey = "geofences" | "employees" | "face-enrollment" | "site-status" | "reports";

const NAV_ITEMS: { key: NavKey; label: string; href: string }[] = [
  { key: "geofences", label: "Geofences", href: "/geofences" },
  { key: "employees", label: "Employees", href: "/employees" },
  { key: "face-enrollment", label: "Face Enrollment", href: "/face-enrollment" },
  { key: "site-status", label: "Site Status", href: "/site-status" },
  { key: "reports", label: "Reports", href: "/reports" },
];

const BADGE_POLL_INTERVAL_MS = 30_000;

// A count-only poll — unlike usePollingExceptions this badge never renders
// the report bodies, so there's no row-identity/no-flicker concern to solve,
// just "how many are open right now."
function useOpenReportCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await listProblemReports({ status: "open", limit: 1 });
        if (!cancelled) setCount(data.total);
      } catch {
        // A failed poll leaves the last-known count showing rather than
        // flashing to 0 — same "don't mislead the viewer" reasoning as the
        // exceptions badge's error handling.
      }
    }
    load();
    const interval = setInterval(load, BADGE_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return count;
}

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
  // badge itself is only rendered on the OTHER pages, where this was
  // previously invisible entirely (see product-completeness audit P1 #3).
  const { needsAttentionCount } = usePollingExceptions(BADGE_POLL_INTERVAL_MS);
  const openReportCount = useOpenReportCount();
  const badgeCounts: Partial<Record<NavKey, number>> = {
    "site-status": needsAttentionCount,
    reports: openReportCount,
  };

  return (
    <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
      <div className="flex items-center gap-4">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">{title}</h1>
        {subtitle && <span className="text-sm text-zinc-500">{subtitle}</span>}
        {NAV_ITEMS.filter((item) => item.key !== current).map((item) => {
          const count = badgeCounts[item.key] ?? 0;
          return (
            <Link
              key={item.key}
              href={item.href}
              className="flex items-center gap-1.5 text-sm text-blue-600 underline"
            >
              {item.label}
              {count > 0 && (
                <span
                  className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-600 px-1.5 text-xs font-semibold text-white no-underline"
                  aria-label={`${count} ${item.key === "reports" ? "open problem report" : "attendance exception"}${count === 1 ? "" : "s"}`}
                >
                  {count}
                </span>
              )}
            </Link>
          );
        })}
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

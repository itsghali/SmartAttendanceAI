"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  AppNotification,
  getUnreadNotificationCount,
  listNotifications,
  markNotificationRead,
} from "../lib/notificationService";

const POLL_INTERVAL_MS = 30_000;

function severityBadgeClass(severity: string): string {
  return severity === "high"
    ? "rounded bg-red-50 px-2 py-0.5 text-xs text-red-700 dark:bg-red-950 dark:text-red-300"
    : "rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-950 dark:text-amber-300";
}

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function NotificationCenter() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(async () => {
    try {
      setUnreadCount(await getUnreadNotificationCount());
    } catch {
      // A failed poll leaves the last-known count showing, same reasoning
      // as AppHeader's other badges — don't flash to 0 on a transient error.
    }
  }, []);

  useEffect(() => {
    refreshCount();
    const interval = setInterval(refreshCount, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refreshCount]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function toggleOpen() {
    const next = !open;
    setOpen(next);
    if (next) {
      setLoading(true);
      try {
        const result = await listNotifications({ limit: 10 });
        setItems(result.items);
      } finally {
        setLoading(false);
      }
    }
  }

  async function viewDetails(notification: AppNotification) {
    if (!notification.is_read) {
      try {
        await markNotificationRead(notification.id);
        setItems((prev) =>
          prev.map((n) => (n.id === notification.id ? { ...n, is_read: true } : n)),
        );
        setUnreadCount((c) => Math.max(0, c - 1));
      } catch {
        // Non-fatal — navigation below still proceeds even if the read-state
        // write failed; the badge will just stay stale until the next poll.
      }
    }
    setOpen(false);
    router.push(`/anomaly-detection?employee_id=${notification.employee_id}`);
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={toggleOpen}
        aria-label={`Notifications${unreadCount > 0 ? `, ${unreadCount} unread` : ""}`}
        className="relative flex items-center gap-1.5 text-sm text-blue-600 underline"
      >
        Notifications
        {unreadCount > 0 && (
          <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-600 px-1.5 text-xs font-semibold text-white no-underline">
            {unreadCount}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-96 rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
          <div className="border-b border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-500 dark:border-zinc-800">
            Notifications
          </div>
          <div className="max-h-96 overflow-y-auto">
            {loading && <p className="p-4 text-sm text-zinc-500">Loading…</p>}
            {!loading && items.length === 0 && (
              <p className="p-4 text-sm text-zinc-500">No notifications yet.</p>
            )}
            {!loading &&
              items.map((n) => (
                <button
                  key={n.id}
                  onClick={() => viewDetails(n)}
                  className="flex w-full flex-col gap-1 border-b border-zinc-100 px-4 py-3 text-left last:border-0 hover:bg-zinc-50 dark:border-zinc-900 dark:hover:bg-zinc-800"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 font-medium text-zinc-900 dark:text-zinc-50">
                      {!n.is_read && (
                        <span className="h-2 w-2 rounded-full bg-blue-600" aria-hidden />
                      )}
                      {n.title}
                    </span>
                    <span className={severityBadgeClass(n.severity)}>{n.severity}</span>
                  </div>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">{n.summary}</p>
                  <span className="text-xs text-zinc-400">{relativeTime(n.detected_at)}</span>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

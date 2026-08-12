export function formatTime(isoString: string | null): string {
  if (!isoString) {
    return "--:--";
  }
  return new Date(isoString).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function formatDate(isoDateString: string): string {
  return new Date(isoDateString).toLocaleDateString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** Elapsed time between two timestamps, for showing how long a break ran. */
export function formatDuration(startIso: string, endIso: string | null): string {
  if (!endIso) {
    return "";
  }
  const minutes = Math.round(
    (new Date(endIso).getTime() - new Date(startIso).getTime()) / 60_000,
  );
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}`;
}

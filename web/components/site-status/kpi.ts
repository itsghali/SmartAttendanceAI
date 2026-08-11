import { AttendanceException } from "../../lib/siteStatusService";

export interface Kpis {
  currentlyOutside: number;
  staleSignals: number;
}

// Extracted as a pure function (eng review requirement) so the two KPI
// counts are unit-testable without rendering the component. Both counts
// read different fields (needs_attention vs monitoring_status) and are
// computed across the WHOLE exceptions array — not scoped to any UI
// subgroup — so a row that is in principle both flagged and stale is
// still counted correctly in both, instead of silently dropped from one.
export function computeKpis(exceptions: AttendanceException[]): Kpis {
  let outside = 0;
  let stale = 0;
  for (const e of exceptions) {
    if (e.needs_attention) outside += 1;
    if (e.monitoring_status === "stale") stale += 1;
  }
  return { currentlyOutside: outside, staleSignals: stale };
}

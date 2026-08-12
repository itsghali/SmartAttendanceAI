import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { NativeStackScreenProps } from "@react-navigation/native-stack";

import { LocationConsentModal } from "../components/LocationConsentModal";
import { SelfieCapture } from "../components/SelfieCapture";
import { GeofenceMonitor } from "../services/geofenceMonitor";
import { logout } from "../store/authSlice";
import { checkIn, checkOut, endBreak, fetchToday, startBreak } from "../store/attendanceSlice";
import { useAppDispatch, useAppSelector } from "../store/hooks";
import { formatDuration, formatTime } from "../utils/attendanceFormat";

export function CheckInScreen({ navigation }: NativeStackScreenProps<any>) {
  const insets = useSafeAreaInsets();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const { today, sessions, loadStatus, loadError, actionStatus, actionError } = useAppSelector(
    (state) => state.attendance,
  );
  // Selfie capture always runs before check-in/check-out/start-break/end-break,
  // even while the backend's FACE_VERIFICATION_ENABLED is off — the field is a
  // harmless no-op server-side until the flag flips, which lets this whole UX
  // get exercised safely in production before enforcement is turned on (see
  // PLAN.md rollout decision). `pendingAction` records which button opened the
  // camera so the capture callback dispatches the right thunk.
  type PendingAction = "check-in" | "check-out" | "start-break" | "end-break" | null;
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  // Gates every button behind an explicit, per-tap location consent modal —
  // the OS permission dialog only ever appears once per install and cannot be
  // forced to reappear on a granted permission (see locationService.ts), so
  // this app-level modal is what actually satisfies "ask every time".
  const [consentAction, setConsentAction] = useState<PendingAction>(null);
  const consentLabels: Record<Exclude<PendingAction, null>, string> = {
    "check-in": "check-in",
    "check-out": "check-out",
    "start-break": "break",
    "end-break": "break end",
  };

  useEffect(() => {
    dispatch(fetchToday());
  }, [dispatch]);

  const refresh = useCallback(() => {
    dispatch(fetchToday());
  }, [dispatch]);

  // `today` is the OPEN session, so it is null both before the first check-in
  // and after checking out of a site — in the second case the employee can
  // simply check in at the next chantier, which is why there is no "day is
  // over" state any more.
  const isOnSite = today !== null;
  const completedSessions = sessions.filter((s) => s.check_out_at != null);
  const openBreak = today?.breaks.find((b) => b.break_end_at === null) ?? null;
  const isSubmitting = actionStatus !== "idle";

  // Pinging must stop for the duration of an open break — CNIL doctrine bars
  // location tracking during legally-protected rest time, and a break is
  // exactly that. isOnSite alone stays true across a break (only check-out
  // flips it), so it can't be the only gate here.
  const isMonitoring = isOnSite && !openBreak;
  const monitorRef = useRef<GeofenceMonitor | null>(null);
  if (monitorRef.current === null) {
    monitorRef.current = new GeofenceMonitor();
  }

  useEffect(() => {
    const monitor = monitorRef.current!;
    if (isMonitoring) {
      monitor.start((result) => {
        // event_fired means an EXIT/RETURN just landed server-side — refetch
        // so the banner below reflects it. Every other ping is a silent no-op.
        if (result.event_fired !== null) {
          dispatch(fetchToday());
        }
      });
    } else {
      monitor.stop();
    }
    return () => monitor.stop();
  }, [isMonitoring, dispatch]);

  // Banner reflects the latest geofence event for today's shift — persistent
  // (not a toast) so it survives the app being backgrounded and reopened.
  const latestEvent = today?.geofence_events[today.geofence_events.length - 1] ?? null;
  const showExitBanner = latestEvent?.event_type === "exit";
  const showReturnBanner = latestEvent?.event_type === "return";
  // No ping heard from this device in a while while checked in — could be a
  // killed app, a dead battery, or lost signal. Surfacing it is the whole
  // point: a frozen "live" status silently trusted forever is exactly the
  // wage-integrity gap this field exists to close.
  const showStaleBanner = today?.monitoring_status === "stale";

  return (
    <ScrollView
      style={styles.container}
      // The navigator runs with headerShown: false, so nothing inflates the
      // notch area for us. Without these insets the header row sits under the
      // status bar on a notched phone and "Log out" cannot be tapped.
      contentContainerStyle={[
        styles.content,
        { paddingTop: insets.top + 24, paddingBottom: insets.bottom + 24 },
      ]}
      refreshControl={<RefreshControl refreshing={loadStatus === "loading"} onRefresh={refresh} />}
    >
      <View style={styles.header}>
        <Text style={styles.greeting}>Hi, {user?.full_name ?? "there"}</Text>
        <View style={styles.headerActions}>
          <TouchableOpacity
            testID="history-button"
            accessibilityRole="button"
            accessibilityLabel="View attendance history"
            onPress={() => navigation.navigate("History")}
          >
            <Text style={styles.logout}>History</Text>
          </TouchableOpacity>
          <TouchableOpacity
            testID="report-problem-button"
            accessibilityRole="button"
            accessibilityLabel="Report a problem"
            onPress={() => navigation.navigate("ReportProblem", { attendanceId: today?.id ?? null })}
          >
            <Text style={styles.logout}>Report</Text>
          </TouchableOpacity>
          <TouchableOpacity
            testID="logout-button"
            accessibilityRole="button"
            accessibilityLabel="Log out"
            onPress={() => dispatch(logout())}
          >
            <Text style={styles.logout}>Log out</Text>
          </TouchableOpacity>
        </View>
      </View>

      {showExitBanner && (
        <View
          style={styles.exitBanner}
          testID="geofence-exit-banner"
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
        >
          <Text style={styles.exitBannerText}>
            You&apos;ve left the work zone. This is recorded on your attendance record.
          </Text>
        </View>
      )}
      {showReturnBanner && (
        <View
          style={styles.returnBanner}
          testID="geofence-return-banner"
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
        >
          <Text style={styles.returnBannerText}>Welcome back — you&apos;re on site.</Text>
        </View>
      )}
      {showStaleBanner && (
        <View
          style={styles.staleBanner}
          testID="monitoring-stale-banner"
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
        >
          <Text style={styles.staleBannerText}>
            We haven&apos;t heard from this device in a while. Reopen the app to resume
            location tracking, or check out if your shift has ended.
          </Text>
        </View>
      )}

      {loadStatus === "error" && loadError && (
        <Text testID="load-error" style={styles.error}>
          {loadError}
        </Text>
      )}

      <View style={styles.card}>
        {/* A failed refetch must not be read as "not checked in" — `today` and
            `sessions` are just whatever the last successful load left behind,
            which for a checked-in employee is a real open session being hidden
            behind a network blip. */}
        {!today && completedSessions.length === 0 && loadStatus !== "error" && (
          <Text style={styles.statusText}>Not checked in yet today</Text>
        )}
        {/* Says "not checked in", never "not on site". Once the employee checks
            out, monitoring stops and the app has no idea where they are — it
            told people standing on site that they were not there. */}
        {!today && completedSessions.length > 0 && (
          <Text style={styles.statusText}>
            You&apos;re checked out. Check in again when you start your next session.
          </Text>
        )}
        {today && (
          <>
            <Text style={styles.statusText}>Checked in at {formatTime(today.check_in_at)}</Text>
            {/* Breaks already finished in this session — without these the
                employee has no way to see what has been deducted so far. */}
            {today.breaks
              .filter((b) => b.break_end_at !== null)
              .map((b) => (
                <Text key={b.id} style={styles.breakText}>
                  Break {formatTime(b.break_start_at)} — {formatTime(b.break_end_at)} (
                  {formatDuration(b.break_start_at, b.break_end_at)})
                </Text>
              ))}
            {openBreak && <Text style={styles.statusText}>On break since {formatTime(openBreak.break_start_at)}</Text>}
          </>
        )}
      </View>

      {completedSessions.length > 0 && (
        <View style={styles.card} testID="sessions-today">
          <Text style={styles.sessionsTitle}>Today</Text>
          {completedSessions.map((session) => (
            <View key={session.id} style={styles.sessionRow}>
              <Text style={styles.statusText}>
                {formatTime(session.check_in_at)} — {formatTime(session.check_out_at)}
              </Text>
              {session.breaks.map((b) => (
                <Text key={b.id} style={styles.breakText}>
                  Break {formatTime(b.break_start_at)} — {formatTime(b.break_end_at)} (
                  {formatDuration(b.break_start_at, b.break_end_at)})
                </Text>
              ))}
            </View>
          ))}
        </View>
      )}

      {actionError ? (
        <Text testID="action-error" style={styles.error}>
          {actionError}
        </Text>
      ) : null}

      {isSubmitting && <ActivityIndicator style={styles.spinner} />}

      {!isSubmitting && !isOnSite && (
        <TouchableOpacity
          testID="check-in-button"
          style={styles.button}
          accessibilityRole="button"
          accessibilityLabel="Check in"
          onPress={() => setConsentAction("check-in")}
        >
          <Text style={styles.buttonText}>Check In</Text>
        </TouchableOpacity>
      )}

      <LocationConsentModal
        visible={consentAction !== null}
        actionLabel={consentAction ? consentLabels[consentAction] : ""}
        onCancel={() => setConsentAction(null)}
        onAllow={() => {
          setPendingAction(consentAction);
          setConsentAction(null);
        }}
      />

      <SelfieCapture
        visible={pendingAction !== null}
        onCancel={() => setPendingAction(null)}
        onCapture={(base64) => {
          const action = pendingAction;
          setPendingAction(null);
          switch (action) {
            case "check-in":
              dispatch(checkIn(base64));
              break;
            case "check-out":
              dispatch(checkOut(base64));
              break;
            case "start-break":
              dispatch(startBreak(base64));
              break;
            case "end-break":
              dispatch(endBreak(base64));
              break;
          }
        }}
      />

      {!isSubmitting && isOnSite && !openBreak && (
        <>
          <TouchableOpacity
            testID="start-break-button"
            style={[styles.button, styles.secondaryButton]}
            accessibilityRole="button"
            accessibilityLabel="Start break"
            onPress={() => setConsentAction("start-break")}
          >
            <Text style={styles.buttonText}>Start Break</Text>
          </TouchableOpacity>
          <TouchableOpacity
            testID="check-out-button"
            style={styles.button}
            accessibilityRole="button"
            accessibilityLabel="Check out"
            onPress={() => setConsentAction("check-out")}
          >
            <Text style={styles.buttonText}>Check Out</Text>
          </TouchableOpacity>
        </>
      )}

      {!isSubmitting && isOnSite && openBreak && (
        <TouchableOpacity
          testID="end-break-button"
          style={styles.button}
          accessibilityRole="button"
          accessibilityLabel="End break"
          onPress={() => setConsentAction("end-break")}
        >
          <Text style={styles.buttonText}>End Break</Text>
        </TouchableOpacity>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#fff",
  },
  content: {
    padding: 24,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 24,
  },
  greeting: {
    fontSize: 20,
    fontWeight: "700",
  },
  headerActions: {
    flexDirection: "row",
    gap: 16,
  },
  logout: {
    color: "#2563eb",
    fontSize: 14,
  },
  card: {
    backgroundColor: "#f3f4f6",
    borderRadius: 12,
    padding: 16,
    marginBottom: 24,
  },
  // Amber, not the existing error-red — leaving the geofence is a status
  // change, not a mistake the employee made (see PLAN.md Design review Pass 5).
  exitBanner: {
    backgroundColor: "#fef3c7",
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  exitBannerText: {
    color: "#b45309",
    fontSize: 14,
    fontWeight: "600",
    textAlign: "center",
  },
  returnBanner: {
    backgroundColor: "#d1fae5",
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  returnBannerText: {
    color: "#059669",
    fontSize: 14,
    fontWeight: "600",
    textAlign: "center",
  },
  // Neutral gray, not amber/red — this is a device-connectivity notice, not a
  // geofence status change or an error the employee caused.
  staleBanner: {
    backgroundColor: "#e5e7eb",
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  staleBannerText: {
    color: "#374151",
    fontSize: 14,
    fontWeight: "600",
    textAlign: "center",
  },
  statusText: {
    fontSize: 16,
    marginBottom: 4,
  },
  sessionsTitle: {
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 8,
    color: "#374151",
  },
  sessionRow: {
    marginBottom: 8,
  },
  // Indented and quieter than the session line — a break is detail inside a
  // session, not a session of its own.
  breakText: {
    fontSize: 14,
    color: "#6b7280",
    marginLeft: 12,
    marginBottom: 2,
  },
  error: {
    color: "#c0392b",
    marginBottom: 16,
    textAlign: "center",
  },
  spinner: {
    marginBottom: 16,
  },
  button: {
    backgroundColor: "#2563eb",
    borderRadius: 8,
    padding: 14,
    alignItems: "center",
    marginBottom: 12,
  },
  secondaryButton: {
    backgroundColor: "#6b7280",
  },
  buttonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
  doneText: {
    textAlign: "center",
    fontSize: 16,
    color: "#059669",
    fontWeight: "600",
  },
});

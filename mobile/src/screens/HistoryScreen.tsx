import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { NativeStackScreenProps } from "@react-navigation/native-stack";

import { Attendance, listMyAttendance } from "../services/attendanceService";
import { extractErrorMessage } from "../utils/apiError";
import { formatDate, formatDuration, formatTime } from "../utils/attendanceFormat";

type LoadState = "idle" | "loading" | "loadingMore" | "error";

export function HistoryScreen({ navigation }: NativeStackScreenProps<any>) {
  const insets = useSafeAreaInsets();
  const [sessions, setSessions] = useState<Attendance[]>([]);
  const [total, setTotal] = useState(0);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);

  const loadPage = useCallback(async (offset: number, replace: boolean) => {
    setLoadState(replace ? "loading" : "loadingMore");
    setError(null);
    try {
      const page = await listMyAttendance({ offset });
      setSessions((prev) => (replace ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
      setLoadState("idle");
    } catch (err) {
      setError(extractErrorMessage(err));
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    loadPage(0, true);
  }, [loadPage]);

  const hasMore = sessions.length < total;

  return (
    <View
      style={[styles.container, { paddingTop: insets.top + 16, paddingBottom: insets.bottom }]}
    >
      <View style={styles.header}>
        <TouchableOpacity
          testID="history-back-button"
          accessibilityRole="button"
          accessibilityLabel="Back"
          onPress={() => navigation.goBack()}
        >
          <Text style={styles.back}>Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Attendance History</Text>
        <View style={styles.backSpacer} />
      </View>

      {loadState === "loading" && (
        <ActivityIndicator style={styles.spinner} testID="history-loading" />
      )}

      {error && (
        <View style={styles.errorBox}>
          <Text testID="history-error" style={styles.errorText}>
            {error}
          </Text>
          <TouchableOpacity
            testID="history-retry-button"
            accessibilityRole="button"
            accessibilityLabel="Retry"
            onPress={() => loadPage(0, true)}
          >
            <Text style={styles.retry}>Retry</Text>
          </TouchableOpacity>
        </View>
      )}

      {loadState !== "loading" && !error && sessions.length === 0 && (
        <Text testID="history-empty" style={styles.empty}>
          No past attendance yet.
        </Text>
      )}

      <FlatList
        data={sessions}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => (
          <View style={styles.card} testID="history-session-row">
            <Text style={styles.dateText}>{formatDate(item.attendance_date)}</Text>
            <Text style={styles.statusText}>
              {formatTime(item.check_in_at)} — {formatTime(item.check_out_at)}
              {item.status !== "present" ? `  ·  ${item.status}` : ""}
            </Text>
            {item.breaks.map((b) => (
              <Text key={b.id} style={styles.breakText}>
                Break {formatTime(b.break_start_at)} — {formatTime(b.break_end_at)} (
                {formatDuration(b.break_start_at, b.break_end_at)})
              </Text>
            ))}
          </View>
        )}
        ListFooterComponent={
          hasMore ? (
            <TouchableOpacity
              testID="history-load-more-button"
              style={styles.loadMoreButton}
              accessibilityRole="button"
              accessibilityLabel="Load more"
              disabled={loadState === "loadingMore"}
              onPress={() => loadPage(sessions.length, false)}
            >
              {loadState === "loadingMore" ? (
                <ActivityIndicator />
              ) : (
                <Text style={styles.loadMoreText}>Load more</Text>
              )}
            </TouchableOpacity>
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#fff",
    paddingHorizontal: 24,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 16,
  },
  back: {
    color: "#2563eb",
    fontSize: 14,
    minWidth: 48,
  },
  // Balances the "Back" link's width so the title stays visually centered.
  backSpacer: {
    minWidth: 48,
  },
  title: {
    fontSize: 18,
    fontWeight: "700",
  },
  list: {
    paddingBottom: 24,
  },
  card: {
    backgroundColor: "#f3f4f6",
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
  },
  dateText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#374151",
    marginBottom: 4,
  },
  statusText: {
    fontSize: 16,
    marginBottom: 4,
  },
  breakText: {
    fontSize: 14,
    color: "#6b7280",
    marginLeft: 12,
    marginBottom: 2,
  },
  empty: {
    textAlign: "center",
    color: "#6b7280",
    marginTop: 32,
  },
  errorBox: {
    alignItems: "center",
    marginBottom: 16,
  },
  errorText: {
    color: "#c0392b",
    textAlign: "center",
    marginBottom: 8,
  },
  retry: {
    color: "#2563eb",
    fontSize: 14,
  },
  spinner: {
    marginTop: 32,
  },
  loadMoreButton: {
    alignItems: "center",
    paddingVertical: 12,
  },
  loadMoreText: {
    color: "#2563eb",
    fontSize: 14,
    fontWeight: "600",
  },
});

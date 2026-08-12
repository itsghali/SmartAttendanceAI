import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { NativeStackScreenProps } from "@react-navigation/native-stack";

import { createProblemReport } from "../services/problemReportService";
import { extractErrorMessage } from "../utils/apiError";

const MAX_MESSAGE_LENGTH = 2000;

export function ReportProblemScreen({ navigation, route }: NativeStackScreenProps<any>) {
  const insets = useSafeAreaInsets();
  // Set by CheckInScreen to the currently open session, if any — lets HR
  // jump straight to the relevant check-in without the employee having to
  // describe which one. Null when reporting something unrelated to a
  // specific session (e.g. the app crashed before checking in at all).
  const attendanceId: string | null = route.params?.attendanceId ?? null;

  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  async function handleSubmit() {
    if (!message.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await createProblemReport(message.trim(), attendanceId);
      setSubmitted(true);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <View
        style={[
          styles.container,
          styles.centered,
          { paddingTop: insets.top + 16, paddingBottom: insets.bottom },
        ]}
      >
        <Text testID="report-submitted" style={styles.doneText}>
          Thanks — HR can see this now.
        </Text>
        <TouchableOpacity
          testID="report-done-button"
          style={styles.button}
          accessibilityRole="button"
          accessibilityLabel="Back to check-in"
          onPress={() => navigation.goBack()}
        >
          <Text style={styles.buttonText}>Done</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={[styles.content, { paddingTop: insets.top + 16, paddingBottom: insets.bottom + 24 }]}>
        <View style={styles.header}>
          <TouchableOpacity
            testID="report-back-button"
            accessibilityRole="button"
            accessibilityLabel="Back"
            onPress={() => navigation.goBack()}
          >
            <Text style={styles.back}>Back</Text>
          </TouchableOpacity>
          <Text style={styles.title}>Report a Problem</Text>
          <View style={styles.backSpacer} />
        </View>

        <Text style={styles.helperText}>
          Tell HR what happened. They&apos;ll see this on their dashboard.
        </Text>

        <TextInput
          testID="report-message-input"
          style={styles.input}
          placeholder="e.g. My check-in didn't register this morning"
          placeholderTextColor="#9ca3af"
          value={message}
          onChangeText={setMessage}
          multiline
          maxLength={MAX_MESSAGE_LENGTH}
          textAlignVertical="top"
        />

        {error && (
          <Text testID="report-error" style={styles.error}>
            {error}
          </Text>
        )}

        {submitting ? (
          <ActivityIndicator style={styles.spinner} />
        ) : (
          <TouchableOpacity
            testID="report-submit-button"
            style={[styles.button, !message.trim() && styles.buttonDisabled]}
            accessibilityRole="button"
            accessibilityLabel="Submit report"
            disabled={!message.trim()}
            onPress={handleSubmit}
          >
            <Text style={styles.buttonText}>Submit</Text>
          </TouchableOpacity>
        )}
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#fff",
  },
  centered: {
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
  content: {
    flex: 1,
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
  backSpacer: {
    minWidth: 48,
  },
  title: {
    fontSize: 18,
    fontWeight: "700",
  },
  helperText: {
    fontSize: 14,
    color: "#6b7280",
    marginBottom: 12,
  },
  input: {
    minHeight: 140,
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    marginBottom: 16,
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
  buttonDisabled: {
    opacity: 0.5,
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
    marginBottom: 24,
  },
});

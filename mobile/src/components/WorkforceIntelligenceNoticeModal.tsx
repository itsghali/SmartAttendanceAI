import { Modal, StyleSheet, Text, TouchableOpacity, View } from "react-native";

interface WorkforceIntelligenceNoticeModalProps {
  visible: boolean;
  onAcknowledge: () => void;
}

/**
 * One-time, dismissible notice (GOVERNANCE.md Section 2) — NOT a consent
 * gate like LocationConsentModal. Acknowledging this doesn't unlock or
 * block anything; Workforce Intelligence's data flow is unchanged either
 * way. It exists purely so employees are told, once, that their attendance
 * patterns may be analyzed for anomaly detection — a new PURPOSE for
 * already-collected attendance/location data, which is why fresh notice is
 * warranted even though no new data is gathered.
 */
export function WorkforceIntelligenceNoticeModal({
  visible,
  onAcknowledge,
}: WorkforceIntelligenceNoticeModalProps) {
  if (!visible) {
    return null;
  }

  return (
    <Modal visible transparent animationType="fade" testID="wi-notice-modal">
      <View style={styles.overlay}>
        <View style={styles.card}>
          <Text style={styles.title}>How your attendance data is used</Text>
          <Text style={styles.message}>
            Your attendance patterns (check-in times, break lengths, site visits) may be
            analyzed to help HR spot unusual patterns early — like a scheduling problem or a
            site issue. This is not used for discipline or performance scoring, and a person
            always reviews anything flagged before any action is taken.
          </Text>
          <TouchableOpacity
            testID="wi-notice-acknowledge-button"
            style={styles.button}
            accessibilityRole="button"
            accessibilityLabel="Got it"
            onPress={onAcknowledge}
          >
            <Text style={styles.buttonText}>Got it</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  card: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
  },
  title: {
    fontSize: 17,
    fontWeight: "600",
    marginBottom: 12,
    textAlign: "center",
  },
  message: {
    fontSize: 15,
    lineHeight: 21,
    marginBottom: 20,
    textAlign: "center",
    color: "#374151",
  },
  button: {
    backgroundColor: "#2563eb",
    borderRadius: 8,
    padding: 14,
    alignItems: "center",
  },
  buttonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
});

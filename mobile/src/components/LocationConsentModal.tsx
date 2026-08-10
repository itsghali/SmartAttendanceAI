import { Modal, StyleSheet, Text, TouchableOpacity, View } from "react-native";

interface LocationConsentModalProps {
  visible: boolean;
  actionLabel: string;
  onAllow: () => void;
  onCancel: () => void;
}

/**
 * Explicit per-action consent gate for location sharing.
 *
 * The OS location permission dialog only appears once per app install and
 * cannot be forced to reappear on a granted permission (no iOS/Android API
 * for that — see locationService.ts ensureNativePermission()). This modal is
 * the app-level substitute: it re-asks the employee, every single tap,
 * before their position is read and sent, satisfying an explicit
 * per-use-consent requirement that the OS permission model cannot provide.
 */
export function LocationConsentModal({ visible, actionLabel, onAllow, onCancel }: LocationConsentModalProps) {
  if (!visible) {
    return null;
  }

  return (
    <Modal visible transparent animationType="fade" testID="location-consent-modal">
      <View style={styles.overlay}>
        <View style={styles.card}>
          <Text style={styles.message}>
            Share your current location to confirm you&apos;re on site for this {actionLabel}?
          </Text>
          <TouchableOpacity
            testID="location-consent-allow-button"
            style={styles.button}
            accessibilityRole="button"
            accessibilityLabel="Allow location"
            onPress={onAllow}
          >
            <Text style={styles.buttonText}>Allow</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="location-consent-cancel-button" onPress={onCancel}>
            <Text style={styles.cancel}>Cancel</Text>
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
  message: {
    fontSize: 16,
    marginBottom: 20,
    textAlign: "center",
  },
  button: {
    backgroundColor: "#2563eb",
    borderRadius: 8,
    padding: 14,
    alignItems: "center",
    marginBottom: 12,
  },
  buttonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
  cancel: {
    textAlign: "center",
    color: "#6b7280",
    fontSize: 14,
  },
});

import { useRef, useState } from "react";
import { ActivityIndicator, Linking, Modal, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";

interface SelfieCaptureProps {
  visible: boolean;
  onCapture: (base64: string) => void;
  onCancel: () => void;
}

// expo-camera's web implementation has no raw-base64-only capture mode —
// canvas.toDataURL() is the only primitive available there, so
// takePictureAsync({base64:true}) returns a full "data:image/...;base64,<data>"
// string on web. Native platforms return raw base64 with no prefix. The
// backend does a strict base64.b64decode(..., validate=True), which rejects
// the "data:...," prefix outright — strip it here so both platforms send the
// same shape. No-op when there's no prefix to strip (native).
export function stripDataUrlPrefix(value: string): string {
  const commaIndex = value.indexOf(",");
  return value.startsWith("data:") && commaIndex !== -1 ? value.slice(commaIndex + 1) : value;
}

/**
 * Full-screen selfie capture, shown before check-in submits when face
 * verification requires a photo. Mirrors the permission-denied surfacing
 * pattern already proven for GPS in locationService.ts: distinguish "can
 * still prompt again" from "permanently denied, needs Settings" rather than
 * showing one generic error for both.
 */
export function SelfieCapture({ visible, onCapture, onCancel }: SelfieCaptureProps) {
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);
  const [capturing, setCapturing] = useState(false);

  if (!visible) {
    return null;
  }

  if (!permission) {
    return (
      <Modal visible transparent testID="selfie-capture-loading">
        <View style={styles.center}>
          <ActivityIndicator />
        </View>
      </Modal>
    );
  }

  if (!permission.granted) {
    return (
      <Modal visible transparent animationType="slide" testID="selfie-permission-modal">
        <View style={styles.center}>
          <Text style={styles.message}>
            Camera access is needed to take the selfie that confirms your identity when you
            check in.
          </Text>
          {permission.canAskAgain ? (
            <TouchableOpacity
              testID="camera-permission-button"
              style={styles.button}
              accessibilityRole="button"
              accessibilityLabel="Allow camera access"
              onPress={requestPermission}
            >
              <Text style={styles.buttonText}>Allow Camera</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              testID="camera-open-settings-button"
              style={styles.button}
              accessibilityRole="button"
              accessibilityLabel="Open settings"
              onPress={() => Linking.openSettings()}
            >
              <Text style={styles.buttonText}>Open Settings</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity testID="selfie-cancel-button" onPress={onCancel}>
            <Text style={styles.cancel}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </Modal>
    );
  }

  async function handleCapture() {
    if (!cameraRef.current || capturing) {
      return;
    }
    setCapturing(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.5 });
      if (photo?.base64) {
        onCapture(stripDataUrlPrefix(photo.base64));
      }
    } finally {
      setCapturing(false);
    }
  }

  return (
    <Modal visible animationType="slide" testID="selfie-camera-modal">
      <View style={styles.container}>
        <CameraView ref={cameraRef} style={styles.camera} facing="front" />
        <View style={styles.controls}>
          {capturing ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <TouchableOpacity
              testID="capture-selfie-button"
              style={styles.captureButton}
              accessibilityRole="button"
              accessibilityLabel="Take selfie"
              onPress={handleCapture}
            >
              <Text style={styles.buttonText}>Take Selfie</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity testID="selfie-cancel-button" onPress={onCancel}>
            <Text style={styles.cancel}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#000",
  },
  camera: {
    flex: 1,
  },
  controls: {
    padding: 24,
    alignItems: "center",
    backgroundColor: "#000",
  },
  captureButton: {
    backgroundColor: "#2563eb",
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 32,
    marginBottom: 12,
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "rgba(0,0,0,0.85)",
    padding: 24,
  },
  message: {
    color: "#fff",
    fontSize: 16,
    textAlign: "center",
    marginBottom: 24,
  },
  button: {
    backgroundColor: "#2563eb",
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 32,
    marginBottom: 12,
  },
  buttonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
  cancel: {
    color: "#d1d5db",
    fontSize: 14,
  },
});

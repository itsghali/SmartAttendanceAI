import { File } from "expo-file-system";
import * as Linking from "expo-linking";
import { Platform } from "react-native";

/**
 * Best-effort JS-level jailbreak heuristic for iOS — not authoritative. A
 * sufficiently sophisticated jailbreak (or a hiding tweak) can evade every
 * check here, the same class of limitation as Android's `isFromMockProvider`
 * self-report (see locationService.ts / PLAN.md T1). This is why the backend
 * only flags a jailbroken check-in for HR review rather than blocking it
 * outright, unlike GPS-spoof detection, which blocks.
 *
 * Android is not checked here — mock-location detection is Android's
 * equivalent signal, already wired into the same check-in flow.
 */

const JAILBREAK_FILE_PATHS = [
  "/Applications/Cydia.app",
  "/Applications/Sileo.app",
  "/Applications/Zebra.app",
  "/Applications/Filza.app",
  "/Library/MobileSubstrate/MobileSubstrate.dylib",
  "/bin/bash",
  "/usr/sbin/sshd",
  "/etc/apt",
  "/private/var/lib/apt",
];

const JAILBREAK_URL_SCHEMES = ["cydia://", "sileo://", "zbra://", "filza://"];

function anyJailbreakPathExists(): boolean {
  for (const path of JAILBREAK_FILE_PATHS) {
    try {
      // These paths are outside this app's sandbox on a normal device —
      // `.exists` is expected to read false, or the access itself may throw.
      // Either a caught exception or a genuine `false` means "not detected
      // by this path," never a crash for the caller.
      if (new File(path).exists) {
        return true;
      }
    } catch {
      continue;
    }
  }
  return false;
}

async function anyJailbreakUrlSchemeOpenable(): Promise<boolean> {
  for (const scheme of JAILBREAK_URL_SCHEMES) {
    try {
      if (await Linking.canOpenURL(scheme)) {
        return true;
      }
    } catch {
      continue;
    }
  }
  return false;
}

export async function checkIsJailbroken(): Promise<boolean> {
  if (Platform.OS !== "ios") {
    return false;
  }
  if (anyJailbreakPathExists()) {
    return true;
  }
  return anyJailbreakUrlSchemeOpenable();
}

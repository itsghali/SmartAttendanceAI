import { File } from "expo-file-system";
import * as Linking from "expo-linking";
import { Platform } from "react-native";

import { checkIsJailbroken } from "./deviceIntegrityService";

jest.mock("expo-file-system", () => ({ File: jest.fn() }));
jest.mock("expo-linking");

const ORIGINAL_PLATFORM = Platform.OS;

function setPlatform(os: typeof Platform.OS) {
  Object.defineProperty(Platform, "OS", { value: os, configurable: true, writable: true });
}

function mockFileExists(existingPaths: string[]) {
  (File as unknown as jest.Mock).mockImplementation((path: string) => ({
    get exists() {
      return existingPaths.includes(path);
    },
  }));
}

describe("deviceIntegrityService.checkIsJailbroken", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFileExists([]);
    (Linking.canOpenURL as jest.Mock).mockResolvedValue(false);
  });

  afterEach(() => {
    setPlatform(ORIGINAL_PLATFORM);
  });

  it("SECURITY: never checks on Android — mock-location detection is Android's equivalent signal", async () => {
    setPlatform("android");

    const result = await checkIsJailbroken();

    expect(result).toBe(false);
    expect(File).not.toHaveBeenCalled();
    expect(Linking.canOpenURL).not.toHaveBeenCalled();
  });

  it("returns false on iOS with no jailbreak indicators", async () => {
    setPlatform("ios");

    expect(await checkIsJailbroken()).toBe(false);
  });

  it("detects a known jailbreak file path", async () => {
    setPlatform("ios");
    mockFileExists(["/Applications/Cydia.app"]);

    expect(await checkIsJailbroken()).toBe(true);
  });

  it("detects a known jailbreak URL scheme when no file path matches", async () => {
    setPlatform("ios");
    (Linking.canOpenURL as jest.Mock).mockImplementation(
      async (url: string) => url === "sileo://",
    );

    expect(await checkIsJailbroken()).toBe(true);
  });

  it("treats a throwing file check as not-detected rather than crashing", async () => {
    setPlatform("ios");
    (File as unknown as jest.Mock).mockImplementation(() => {
      throw new Error("permission denied");
    });

    await expect(checkIsJailbroken()).resolves.toBe(false);
  });

  it("treats a rejecting canOpenURL as not-detected rather than crashing", async () => {
    setPlatform("ios");
    (Linking.canOpenURL as jest.Mock).mockRejectedValue(new Error("scheme not declared"));

    await expect(checkIsJailbroken()).resolves.toBe(false);
  });
});

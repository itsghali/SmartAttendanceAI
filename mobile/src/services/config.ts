export function getApiBaseUrl(): string {
  const url = process.env.EXPO_PUBLIC_API_BASE_URL;
  if (!url) {
    throw new Error("EXPO_PUBLIC_API_BASE_URL is not set");
  }
  return url.replace(/\/+$/, "");
}

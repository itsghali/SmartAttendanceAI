export function getApiBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!url) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");
  }
  return url.replace(/\/+$/, "");
}

export function apiUrl(path: string): string {
  const base = getApiBaseUrl();
  return `${base}/${path.replace(/^\/+/, "")}`;
}

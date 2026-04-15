export function getApiBaseUrl(): string {
  return String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
}


export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}${normalizedPath}`;
}

import { buildApiUrl } from "@/lib/api";

/** GET one API path as JSON; a non-2xx answer becomes an Error carrying the server's `detail`. */
export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(buildApiUrl(path));
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
  return payload as T;
}
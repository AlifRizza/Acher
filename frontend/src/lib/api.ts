// Thin fetch wrappers over the backend read API. No state library — callers use
// these from useEffect and hold results in useState (see research.md §3).

import type { ActivitySpan, AppConfig, ScreenshotPage, Stats, Timesheet } from "../types";

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} for ${url}`);
  }
  return res.json() as Promise<T>;
}

export interface ListParams {
  limit?: number;
  offset?: number;
  app?: string;
  q?: string;
  is_manual?: boolean;
}

export function listScreenshots(params: ListParams = {}): Promise<ScreenshotPage> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.app) qs.set("app", params.app);
  if (params.q) qs.set("q", params.q);
  if (params.is_manual != null) qs.set("is_manual", String(params.is_manual));
  const query = qs.toString();
  return getJSON<ScreenshotPage>(`/api/screenshots${query ? `?${query}` : ""}`);
}

export function getStats(): Promise<Stats> {
  return getJSON<Stats>("/api/stats");
}

export interface RangeParams {
  start?: string;
  end?: string;
}

function rangeQuery(params: RangeParams): string {
  const qs = new URLSearchParams();
  if (params.start) qs.set("start", params.start);
  if (params.end) qs.set("end", params.end);
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export function getTimesheet(params: RangeParams = {}): Promise<Timesheet> {
  return getJSON<Timesheet>(`/api/timesheet${rangeQuery(params)}`);
}

// URL for the export download; used as an <a href> so the browser saves the file.
export function timesheetExportUrl(fmt: "csv" | "xlsx", params: RangeParams = {}): string {
  const qs = new URLSearchParams({ fmt });
  if (params.start) qs.set("start", params.start);
  if (params.end) qs.set("end", params.end);
  return `/api/timesheet/export?${qs.toString()}`;
}

// Fetch all screenshots within a [start, end] window (one day for the timeline).
// Uses a large limit so a full day of captures comes back in one call.
export function listScreenshotsInRange(start: string, end: string): Promise<ScreenshotPage> {
  return getJSON<ScreenshotPage>(
    `/api/screenshots?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&limit=500`,
  );
}

// Full-text search across app / tab / note / tags (backend /api/search).
export function searchScreenshots(q: string, limit = 100): Promise<ScreenshotPage> {
  return getJSON<ScreenshotPage>(
    `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`,
  );
}

// Continuous activity spans (active/idle/locked) for a day, from the watcher.
export function getActivity(start: string, end: string): Promise<{ rows: ActivitySpan[] }> {
  return getJSON<{ rows: ActivitySpan[] }>(
    `/api/activity?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  );
}

// Read current runtime settings (Settings tab).
export function getConfig(): Promise<AppConfig> {
  return getJSON<AppConfig>("/api/config");
}

// Persist a partial settings update. Throws with the backend's message on a
// validation error (HTTP 400) so the form can show it.
export async function saveConfig(patch: Partial<AppConfig>): Promise<AppConfig> {
  const res = await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<AppConfig>;
}

// Image URLs are served directly by the backend; used as <img src>.
export function imageUrl(id: number): string {
  return `/api/screenshots/${id}/image`;
}

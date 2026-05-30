// Mirrors the JSON shapes returned by the backend read API (backend/acher/api.py).

export interface Screenshot {
  id: number;
  timestamp: string; // ISO8601 UTC
  app_name: string;
  tab_title: string | null;
  local_path: string;
  drive_file_id: string | null;
  upload_status: "pending" | "uploaded" | "failed";
  is_manual: boolean;
  activity_note: string | null;
  tags: string | null;
}

export interface ScreenshotPage {
  total: number;
  limit: number;
  offset: number;
  items: Screenshot[];
}

export interface Stats {
  total: number;
  manual: number;
  by_status: Record<string, number>;
  by_app: { app_name: string; count: number }[];
  earliest: string | null;
  latest: string | null;
}

export interface TimesheetRow {
  app_name: string;
  shots: number;
  minutes: number;
}

export interface Timesheet {
  start: string | null;
  end: string | null;
  interval_minutes: number;
  total_minutes: number;
  total_shots: number;
  rows: TimesheetRow[];
}

// A contiguous run of same-label captures, reconstructed client-side from
// point-in-time screenshots (see lib/timeline.ts). Used to draw timeline blocks.
export interface Block {
  label: string; // app name or tab title
  startMs: number; // epoch ms of first capture in the run
  endMs: number; // epoch ms of last capture + one interval (so blocks have width)
  shots: Screenshot[]; // captures that make up this block, time-ordered
}

// A continuous activity span from the backend watcher (second-accurate).
export interface ActivitySpan {
  id: number;
  start_ts: string; // ISO8601 UTC
  end_ts: string; // ISO8601 UTC
  state: "active" | "idle" | "locked";
  app_name: string | null;
  tab_title: string | null;
}


// Reconstruct timeline "blocks" from point-in-time screenshots.
//
// Acher captures one screenshot every few minutes; it does not record
// continuous spans. To draw a ManicTime-style timeline we merge consecutive
// captures that share a label (app name, or tab title) into a single block,
// estimating each block's width from the capture cadence.

import type { ActivitySpan, Block, Screenshot } from "../types";

// Estimate the typical gap between captures (ms) as the median of consecutive
// gaps. Falls back to 3 minutes when there's too little data. This is what
// gives a lone screenshot a sensible visible width.
export function estimateIntervalMs(shots: Screenshot[]): number {
  if (shots.length < 2) return 3 * 60_000;
  const times = shots.map((s) => Date.parse(s.timestamp)).sort((a, b) => a - b);
  const gaps: number[] = [];
  for (let i = 1; i < times.length; i++) gaps.push(times[i] - times[i - 1]);
  gaps.sort((a, b) => a - b);
  const mid = Math.floor(gaps.length / 2);
  const median = gaps.length % 2 ? gaps[mid] : (gaps[mid - 1] + gaps[mid]) / 2;
  // Guard against absurd values (e.g. one giant gap on a sparse day).
  return Math.min(Math.max(median, 30_000), 15 * 60_000);
}

// Build blocks for a single "track" keyed by `labelOf`. Captures are grouped
// into a run while (a) the label is unchanged and (b) the gap to the next
// capture is within `mergeGap` (default 2× the estimated interval). Captures
// whose label is null (e.g. tab title on a non-browser) are skipped.
export function buildBlocks(
  shots: Screenshot[],
  labelOf: (s: Screenshot) => string | null,
  intervalMs: number,
): Block[] {
  const sorted = [...shots]
    .filter((s) => labelOf(s) !== null)
    .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));

  const mergeGap = intervalMs * 2;
  const blocks: Block[] = [];
  let current: Block | null = null;

  for (const s of sorted) {
    const label = labelOf(s)!;
    const t = Date.parse(s.timestamp);
    if (
      current &&
      current.label === label &&
      t - Date.parse(current.shots[current.shots.length - 1].timestamp) <= mergeGap
    ) {
      current.shots.push(s);
      current.endMs = t + intervalMs;
    } else {
      if (current) blocks.push(current);
      current = { label, startMs: t, endMs: t + intervalMs, shots: [s] };
    }
  }
  if (current) blocks.push(current);
  return blocks;
}

// Convert backend activity spans into timeline blocks. These are second-accurate
// (from the watcher) rather than inferred from screenshots. `labelOf` picks the
// block label; spans where it returns null are skipped. Screenshots that fall
// within a span are attached so the hover popup still has an image to show.
export function spansToBlocks(
  spans: ActivitySpan[],
  shots: Screenshot[],
  labelOf: (s: ActivitySpan) => string | null,
): Block[] {
  const shotTimes = shots
    .map((s) => ({ t: Date.parse(s.timestamp), s }))
    .sort((a, b) => a.t - b.t);

  const blocks: Block[] = [];
  for (const span of spans) {
    const label = labelOf(span);
    if (label === null) continue;
    const startMs = Date.parse(span.start_ts);
    const endMs = Math.max(Date.parse(span.end_ts), startMs + 1000);
    const inSpan = shotTimes.filter((x) => x.t >= startMs && x.t <= endMs).map((x) => x.s);
    blocks.push({ label, startMs, endMs, shots: inSpan });
  }
  return blocks;
}

// The screenshot closest to a given epoch-ms within a block (for hover popups).
export function nearestShot(block: Block, atMs: number): Screenshot {
  let best = block.shots[0];
  let bestDist = Infinity;
  for (const s of block.shots) {
    const d = Math.abs(Date.parse(s.timestamp) - atMs);
    if (d < bestDist) {
      bestDist = d;
      best = s;
    }
  }
  return best;
}

// Human-readable duration for a block, e.g. "1h 05m" or "12m".
export function formatDuration(ms: number): string {
  const totalMin = Math.max(1, Math.round(ms / 60_000));
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

// Local-day bounds [startMs, endMs] (midnight to midnight) for a YYYY-MM-DD string.
export function dayBounds(dateStr: string): { startMs: number; endMs: number } {
  const start = new Date(`${dateStr}T00:00:00`);
  const end = new Date(`${dateStr}T00:00:00`);
  end.setDate(end.getDate() + 1);
  return { startMs: start.getTime(), endMs: end.getTime() };
}

// ISO bounds for the API (?start=&end=) covering the given local day.
export function dayISOBounds(dateStr: string): { startISO: string; endISO: string } {
  const { startMs, endMs } = dayBounds(dateStr);
  return {
    startISO: new Date(startMs).toISOString(),
    endISO: new Date(endMs - 1000).toISOString(),
  };
}

// Today as YYYY-MM-DD in local time.
export function todayStr(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

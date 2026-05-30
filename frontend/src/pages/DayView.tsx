import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ActivitySpan, Block, Screenshot } from "../types";
import { getActivity, listScreenshotsInRange, searchScreenshots } from "../lib/api";
import {
  buildBlocks,
  dayBounds,
  dayISOBounds,
  estimateIntervalMs,
  formatDuration,
  spansToBlocks,
  todayStr,
} from "../lib/timeline";
import { TimelineRow } from "../components/TimelineRow";
import { ScreenshotPopup, type PopupData } from "../components/ScreenshotPopup";
import { MiniScrubber } from "../components/MiniScrubber";
import { SearchPanel } from "../components/SearchPanel";
import { ScreenshotModal } from "../components/ScreenshotModal";
import { ScreenshotCard } from "../components/ScreenshotCard";

// Zoom presets (Q12): how much of the day fills the base viewport width.
const ZOOMS: { label: string; windowHours: number }[] = [
  { label: "Day", windowHours: 24 },
  { label: "4h", windowHours: 4 },
  { label: "1h", windowHours: 1 },
  { label: "30m", windowHours: 0.5 },
];
const BASE_WIDTH = 1100; // px the zoom window maps onto

// All timeline rows are toggleable (Q2). Order top→bottom.
const ROW_KEYS = [
  "Computer Usage",
  "Applications",
  "Browser Tabs",
  "Screenshots",
  "Manual Entries",
] as const;
type RowKey = (typeof ROW_KEYS)[number];

// Shift a YYYY-MM-DD string by ±n days.
function addDays(dateStr: string, n: number): string {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + n);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export function DayView() {
  const [date, setDate] = useState(todayStr());
  const [shots, setShots] = useState<Screenshot[]>([]);
  const [spans, setSpans] = useState<ActivitySpan[]>([]);
  const [zoom, setZoom] = useState(0); // index into ZOOMS
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState<Record<RowKey, boolean>>({
    "Computer Usage": true,
    Applications: true,
    "Browser Tabs": true,
    Screenshots: true,
    "Manual Entries": true,
  });
  const [popup, setPopup] = useState<PopupData | null>(null);
  const [selected, setSelected] = useState<Screenshot | null>(null);
  const [view, setView] = useState({ startMs: 0, endMs: 0 });

  // Search state.
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [results, setResults] = useState<Screenshot[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  const { startMs: dayStartMs, endMs: dayEndMs } = useMemo(() => dayBounds(date), [date]);
  const pxPerMs = useMemo(
    () => BASE_WIDTH / (ZOOMS[zoom].windowHours * 3600_000),
    [zoom],
  );
  const trackWidth = (dayEndMs - dayStartMs) * pxPerMs;

  // ---- data loading ----
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const { startISO, endISO } = dayISOBounds(date);
    Promise.all([listScreenshotsInRange(startISO, endISO), getActivity(startISO, endISO)])
      .then(([page, act]) => {
        if (cancelled) return;
        setShots(page.items);
        setSpans(act.rows);
      })
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [date]);

  // ---- block building ----
  const intervalMs = useMemo(() => estimateIntervalMs(shots), [shots]);
  // Prefer real activity spans (second-accurate). Fall back to screenshot-
  // inferred blocks when no spans exist (e.g. data captured before the watcher).
  const hasSpans = spans.length > 0;
  const activeSpans = useMemo(() => spans.filter((s) => s.state === "active"), [spans]);
  const appBlocks = useMemo(
    () =>
      hasSpans
        ? spansToBlocks(activeSpans, shots, (s) => s.app_name)
        : buildBlocks(shots, (s) => s.app_name, intervalMs),
    [hasSpans, activeSpans, shots, intervalMs],
  );
  const tabBlocks = useMemo(
    () =>
      hasSpans
        ? spansToBlocks(activeSpans, shots, (s) => s.tab_title)
        : buildBlocks(shots, (s) => s.tab_title, intervalMs),
    [hasSpans, activeSpans, shots, intervalMs],
  );
  // Computer Usage row: every span, labelled by state (active/idle/locked).
  const usageBlocks = useMemo(
    () => spansToBlocks(spans, shots, (s) => s.state),
    [spans, shots],
  );
  // Screenshots + Manual rows are one block per capture (point markers).
  const shotMarkers = useMemo<Block[]>(
    () =>
      shots.map((s) => {
        const t = Date.parse(s.timestamp);
        return { label: s.app_name, startMs: t, endMs: t + intervalMs / 3, shots: [s] };
      }),
    [shots, intervalMs],
  );
  const manualMarkers = useMemo<Block[]>(
    () =>
      shots
        .filter((s) => s.is_manual)
        .map((s) => {
          const t = Date.parse(s.timestamp);
          return { label: "Manual Entries", startMs: t, endMs: t + intervalMs / 3, shots: [s] };
        }),
    [shots, intervalMs],
  );

  const matchedShotIds = useMemo(
    () => (searchOpen && query ? new Set(results.map((r) => r.id)) : null),
    [searchOpen, query, results],
  );

  // ---- view window tracking (for the scrubber) ----
  const updateView = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setView({
      startMs: dayStartMs + el.scrollLeft / pxPerMs,
      endMs: dayStartMs + (el.scrollLeft + el.clientWidth) / pxPerMs,
    });
  }, [dayStartMs, pxPerMs]);

  useEffect(updateView, [updateView, trackWidth, shots]);

  // Scroll so that `centerMs` sits in the middle of the viewport.
  const seekTo = useCallback(
    (centerMs: number) => {
      const el = scrollRef.current;
      if (!el) return;
      el.scrollLeft = (centerMs - dayStartMs) * pxPerMs - el.clientWidth / 2;
      updateView();
    },
    [dayStartMs, pxPerMs, updateView],
  );

  // On first load of a day with data, jump to the earliest capture (auto-zoom intent).
  useEffect(() => {
    if (shots.length && scrollRef.current) {
      seekTo(Date.parse(shots[0].timestamp));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shots, pxPerMs]);

  // ---- hover popup ----
  // Show one representative screenshot per block (the middle one) so moving the
  // cursor within a block never reloads the image — no flicker.
  const onHover = useCallback((block: Block, x: number, y: number) => {
    const rep = block.shots[Math.floor(block.shots.length / 2)];
    setPopup({
      shot: rep ?? null,
      label: block.label,
      durationText: formatDuration(block.endMs - block.startMs),
      x,
      y,
    });
  }, []);
  const onLeave = useCallback(() => setPopup(null), []);

  // ---- search ----
  function runSearch(q: string) {
    setQuery(q);
    if (!q.trim()) {
      setResults([]);
      setSearchOpen(false);
      return;
    }
    setSearchOpen(true);
    setSearching(true);
    setSearchError(null);
    searchScreenshots(q)
      .then((page) => setResults(page.items))
      .catch((e) => setSearchError(String(e)))
      .finally(() => setSearching(false));
  }

  // Jump the timeline to a search result (switch day if needed, then scroll).
  function jumpTo(shot: Screenshot) {
    const d = new Date(shot.timestamp);
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const ds = `${d.getFullYear()}-${mm}-${dd}`;
    if (ds !== date) setDate(ds);
    setTimeout(() => seekTo(d.getTime()), 50);
    setSelected(shot);
  }

  // Focus the search box with "/" (Q text default).
  const searchInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ---- hour ticks for the time axis ----
  const ticks = useMemo(() => {
    const out: { left: number; label: string }[] = [];
    // Denser labels when zoomed in.
    const stepHours = ZOOMS[zoom].windowHours <= 1 ? 0.25 : ZOOMS[zoom].windowHours <= 4 ? 1 : 2;
    for (let h = 0; h <= 24; h += stepHours) {
      const ms = dayStartMs + h * 3600_000;
      const hh = Math.floor(h);
      const mm = Math.round((h - hh) * 60);
      out.push({
        left: (ms - dayStartMs) * pxPerMs,
        label: `${String(hh % 24).padStart(2, "0")}:${String(mm).padStart(2, "0")}`,
      });
    }
    return out;
  }, [dayStartMs, pxPerMs, zoom]);

  const rowData: Record<RowKey, { blocks: Block[]; variant: "bar" | "marker" | "usage" }> = {
    "Computer Usage": { blocks: usageBlocks, variant: "usage" },
    Applications: { blocks: appBlocks, variant: "bar" },
    "Browser Tabs": { blocks: tabBlocks, variant: "bar" },
    Screenshots: { blocks: shotMarkers, variant: "marker" },
    "Manual Entries": { blocks: manualMarkers, variant: "marker" },
  };

  return (
    <div className="dayview">
      {/* Controls */}
      <div className="dayview-controls">
        <div className="date-nav">
          <button className="icon-btn" onClick={() => setDate(addDays(date, -1))}>‹</button>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <button className="icon-btn" onClick={() => setDate(addDays(date, 1))}>›</button>
          <button className="btn-ghost" onClick={() => setDate(todayStr())}>Today</button>
        </div>

        <div className="zoom-controls">
          {ZOOMS.map((z, i) => (
            <button
              key={z.label}
              className={i === zoom ? "zoom active" : "zoom"}
              onClick={() => setZoom(i)}
            >
              {z.label}
            </button>
          ))}
        </div>

        <div className="search-box">
          <input
            ref={searchInputRef}
            type="search"
            placeholder="Search app / tab / note / tags  ( / )"
            value={query}
            onChange={(e) => runSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Row visibility toggles + legend */}
      <div className="row-toggles">
        {ROW_KEYS.map((k) => (
          <label key={k} className="toggle">
            <input
              type="checkbox"
              checked={visible[k]}
              onChange={(e) => setVisible((v) => ({ ...v, [k]: e.target.checked }))}
            />
            {k}
          </label>
        ))}
        <span className="muted small">{shots.length} captures</span>
        {visible["Computer Usage"] && hasSpans && (
          <span className="usage-legend">
            <span><span className="swatch" style={{ background: "#3fb950" }} />active</span>
            <span><span className="swatch" style={{ background: "#d29922" }} />idle</span>
            <span><span className="swatch" style={{ background: "#6e7681" }} />off</span>
          </span>
        )}
      </div>

      {error && <div className="error">Failed to load: {error}</div>}
      {!error && !loading && shots.length === 0 && (
        <div className="empty">No captures for {date}.</div>
      )}

      {/* The scrollable timeline */}
      <div className="timeline-scroll" ref={scrollRef} onScroll={updateView}>
        <div className="timeline-inner" style={{ width: trackWidth }}>
          <div className="time-axis">
            {ticks.map((t, i) => (
              <div className="tick" key={i} style={{ left: t.left }}>
                <span>{t.label}</span>
              </div>
            ))}
          </div>
          {ROW_KEYS.filter((k) => visible[k]).map((k) => (
            <TimelineRow
              key={k}
              label={k}
              blocks={rowData[k].blocks}
              variant={rowData[k].variant}
              viewStartMs={dayStartMs}
              pxPerMs={pxPerMs}
              matchedShotIds={matchedShotIds}
              onHover={onHover}
              onLeave={onLeave}
              onClick={(b) => setSelected(b.shots[Math.floor(b.shots.length / 2)])}
            />
          ))}
        </div>
      </div>

      {/* Mini scrubber */}
      {shots.length > 0 && (
        <MiniScrubber
          dayStartMs={dayStartMs}
          dayEndMs={dayEndMs}
          viewStartMs={view.startMs}
          viewEndMs={view.endMs}
          appBlocks={appBlocks}
          onSeek={seekTo}
        />
      )}

      {/* Screenshot grid for the selected day, newest first (the classic grid
          view, kept below the timeline). Dimmed when it doesn't match an active
          search, mirroring the timeline's highlight behavior. */}
      {shots.length > 0 && (
        <div className="day-grid-section">
          <h2 className="day-grid-title">Screenshots — {date}</h2>
          <div className="grid">
            {[...shots]
              .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
              .map((s) => (
                <div
                  key={s.id}
                  className={matchedShotIds && !matchedShotIds.has(s.id) ? "dimmed" : ""}
                >
                  <ScreenshotCard shot={s} onOpen={setSelected} />
                </div>
              ))}
          </div>
        </div>
      )}

      {popup && <ScreenshotPopup data={popup} />}
      {searchOpen && (
        <SearchPanel
          query={query}
          results={results}
          loading={searching}
          error={searchError}
          onJump={jumpTo}
          onClose={() => setSearchOpen(false)}
        />
      )}
      {selected && <ScreenshotModal shot={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

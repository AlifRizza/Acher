import { useEffect, useMemo, useState } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Bar } from "react-chartjs-2";
import type { Screenshot, Timesheet } from "../types";
import { getTimesheet, listScreenshotsInRange } from "../lib/api";

// Register only the Chart.js pieces we use (tree-shakeable build).
ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend);

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// Default range: the last 7 days (inclusive).
function defaultRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 6);
  const fmt = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { start: fmt(start), end: fmt(end) };
}

export function Statistics() {
  const [{ start, end }, setRange] = useState(defaultRange);
  const [timesheet, setTimesheet] = useState<Timesheet | null>(null);
  const [shots, setShots] = useState<Screenshot[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startISO = `${start}T00:00:00+00:00`;
  const endISO = `${end}T23:59:59+00:00`;

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([
      getTimesheet({ start: startISO, end: endISO }),
      listScreenshotsInRange(startISO, endISO),
    ])
      .then(([ts, page]) => {
        if (cancelled) return;
        setTimesheet(ts);
        setShots(page.items);
        setTruncated(page.total > page.items.length);
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [startISO, endISO]);

  // Top 10 apps by estimated minutes → Chart.js bar.
  const barData = useMemo(() => {
    const rows = (timesheet?.rows ?? []).slice(0, 10);
    return {
      labels: rows.map((r) => r.app_name),
      datasets: [
        {
          label: "Minutes",
          data: rows.map((r) => r.minutes),
          backgroundColor: "#5b8cff",
          borderRadius: 4,
        },
      ],
    };
  }, [timesheet]);

  // Hourly heatmap: counts bucketed by [day-of-week][hour], from captures.
  const heatmap = useMemo(() => {
    const grid: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0));
    let max = 0;
    for (const s of shots) {
      const d = new Date(s.timestamp);
      const g = grid[d.getDay()][d.getHours()] + 1;
      grid[d.getDay()][d.getHours()] = g;
      if (g > max) max = g;
    }
    return { grid, max };
  }, [shots]);

  return (
    <div className="statistics">
      <div className="controls range-controls">
        <label>
          From <input type="date" value={start} onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))} />
        </label>
        <label>
          To <input type="date" value={end} onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))} />
        </label>
      </div>

      {error && <div className="error">Failed to load: {error}</div>}

      <section className="stat-section">
        <h2>Top apps by time</h2>
        {timesheet && timesheet.rows.length > 0 ? (
          <div className="chart-wrap">
            <Bar
              data={barData}
              options={{
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                  x: { ticks: { color: "#9aa0ac" }, grid: { color: "#2c303a" } },
                  y: { ticks: { color: "#e6e8ee" }, grid: { display: false } },
                },
              }}
            />
          </div>
        ) : (
          <div className="empty">No activity in this range.</div>
        )}
      </section>

      <section className="stat-section">
        <h2>Hourly activity</h2>
        {truncated && (
          <div className="muted small">
            Showing the most recent 500 captures — older ones in this range are omitted.
          </div>
        )}
        <div className="heatmap">
          <div className="heatmap-hours">
            <span className="heatmap-corner" />
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="heatmap-hour">{h % 3 === 0 ? h : ""}</span>
            ))}
          </div>
          {heatmap.grid.map((row, day) => (
            <div className="heatmap-row" key={day}>
              <span className="heatmap-day">{DAYS[day]}</span>
              {row.map((count, h) => {
                const intensity = heatmap.max ? count / heatmap.max : 0;
                return (
                  <span
                    key={h}
                    className="heatmap-cell"
                    title={`${DAYS[day]} ${h}:00 — ${count} captures`}
                    style={{
                      background:
                        count === 0 ? "var(--panel-2)" : `rgba(91, 140, 255, ${0.15 + intensity * 0.85})`,
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

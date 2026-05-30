import { useEffect, useState } from "react";
import type { Timesheet } from "../types";
import { getTimesheet, timesheetExportUrl } from "../lib/api";

// Per-app time roll-up with optional date range and CSV/XLSX download.
// Time is estimated as (screenshot count) × capture interval — see the backend
// queries.timesheet docstring.
export function TimesheetPage() {
  const [data, setData] = useState<Timesheet | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Convert a <input type="date"> value into an ISO bound, or undefined.
  const startISO = start ? `${start}T00:00:00+00:00` : undefined;
  const endISO = end ? `${end}T23:59:59+00:00` : undefined;

  useEffect(() => {
    let cancelled = false;
    setError(null);
    getTimesheet({ start: startISO, end: endISO })
      .then((t) => !cancelled && setData(t))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [startISO, endISO]);

  function fmtMinutes(m: number): string {
    const h = Math.floor(m / 60);
    const min = m % 60;
    return h > 0 ? `${h}h ${min}m` : `${min}m`;
  }

  const range = { start: startISO, end: endISO };

  return (
    <div className="timesheet">
      <div className="controls range-controls">
        <label>
          From <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          To <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <a className="btn" href={timesheetExportUrl("csv", range)}>
          Export CSV
        </a>
        <a className="btn" href={timesheetExportUrl("xlsx", range)}>
          Export XLSX
        </a>
      </div>

      {error && <div className="error">Failed to load: {error}</div>}

      {data && (
        <>
          <div className="timesheet-total">
            <strong>{fmtMinutes(data.total_minutes)}</strong> across{" "}
            {data.total_shots} screenshots ({data.interval_minutes}-min interval)
          </div>

          {data.rows.length === 0 ? (
            <div className="empty">No activity in this range.</div>
          ) : (
            <table className="sheet">
              <thead>
                <tr>
                  <th>App</th>
                  <th>Screenshots</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.app_name}>
                    <td>{r.app_name}</td>
                    <td>{r.shots}</td>
                    <td>{fmtMinutes(r.minutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

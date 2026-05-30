import type { Stats } from "../types";

// Compact roll-up shown above the timeline: totals + the top apps.
export function StatsBar({ stats }: { stats: Stats }) {
  return (
    <div className="stats-bar">
      <div className="stat">
        <span className="stat-value">{stats.total}</span>
        <span className="stat-label">screenshots</span>
      </div>
      <div className="stat">
        <span className="stat-value">{stats.manual}</span>
        <span className="stat-label">manual</span>
      </div>
      {stats.by_app.slice(0, 5).map((a) => (
        <div className="stat stat-app" key={a.app_name}>
          <span className="stat-value">{a.count}</span>
          <span className="stat-label">{a.app_name}</span>
        </div>
      ))}
    </div>
  );
}

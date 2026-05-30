import { useEffect, useState } from "react";
import type { Screenshot, Stats } from "../types";
import { listScreenshots, getStats } from "../lib/api";
import { StatsBar } from "../components/StatsBar";
import { ScreenshotCard } from "../components/ScreenshotCard";
import { ScreenshotModal } from "../components/ScreenshotModal";

const PAGE_SIZE = 50;

// The one page for v1 (research.md §2.4): a grid of screenshots, newest first,
// with app filtering, search, and a "load more" pager. State is plain hooks.
export function Timeline() {
  const [items, setItems] = useState<Screenshot[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const [appFilter, setAppFilter] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Screenshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reload the first page whenever a filter changes.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listScreenshots({
      limit: PAGE_SIZE,
      offset: 0,
      app: appFilter || undefined,
      q: search || undefined,
    })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
        setOffset(page.items.length);
      })
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [appFilter, search]);

  // Stats refresh on mount and when filters reset the view.
  useEffect(() => {
    getStats()
      .then(setStats)
      .catch(() => setStats(null));
  }, [appFilter, search]);

  function loadMore() {
    setLoading(true);
    listScreenshots({
      limit: PAGE_SIZE,
      offset,
      app: appFilter || undefined,
      q: search || undefined,
    })
      .then((page) => {
        setItems((prev) => [...prev, ...page.items]);
        setOffset((prev) => prev + page.items.length);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  return (
    <div className="timeline">
      <header className="topbar">
        <div className="controls">
          <input
            type="search"
            placeholder="Search app or tab…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {stats && stats.by_app.length > 0 && (
            <select value={appFilter} onChange={(e) => setAppFilter(e.target.value)}>
              <option value="">All apps</option>
              {stats.by_app.map((a) => (
                <option key={a.app_name} value={a.app_name}>
                  {a.app_name} ({a.count})
                </option>
              ))}
            </select>
          )}
        </div>
      </header>

      {stats && <StatsBar stats={stats} />}

      {error && <div className="error">Failed to load: {error}</div>}

      {!error && items.length === 0 && !loading && (
        <div className="empty">No screenshots yet.</div>
      )}

      <div className="grid">
        {items.map((shot) => (
          <ScreenshotCard key={shot.id} shot={shot} onOpen={setSelected} />
        ))}
      </div>

      <div className="pager">
        {items.length < total ? (
          <button onClick={loadMore} disabled={loading}>
            {loading ? "Loading…" : `Load more (${items.length} of ${total})`}
          </button>
        ) : (
          items.length > 0 && <span className="muted">All {total} shown</span>
        )}
      </div>

      {selected && (
        <ScreenshotModal shot={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

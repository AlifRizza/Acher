import type { Screenshot } from "../types";
import { imageUrl } from "../lib/api";
import { formatTimestamp, parseTags } from "../lib/format";

// Slide-in results list for a search. Clicking a result jumps the timeline to
// that capture's moment (handled by the parent). Matching blocks are also
// highlighted on the timeline itself, so this is the "panel + highlight" mode.

export interface SearchPanelProps {
  query: string;
  results: Screenshot[];
  loading: boolean;
  error: string | null;
  onJump: (shot: Screenshot) => void;
  onClose: () => void;
}

export function SearchPanel(props: SearchPanelProps) {
  const { query, results, loading, error } = props;
  return (
    <aside className="search-panel">
      <div className="search-panel-head">
        <span>
          {loading
            ? "Searching…"
            : `${results.length} result${results.length === 1 ? "" : "s"} for “${query}”`}
        </span>
        <button className="icon-btn" onClick={props.onClose} aria-label="Close search">
          ×
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="search-results">
        {results.map((s) => (
          <button key={s.id} className="search-result" onClick={() => props.onJump(s)}>
            <img src={imageUrl(s.id)} alt={s.app_name} loading="lazy" />
            <div className="search-result-meta">
              <div className="search-result-app">{s.app_name}</div>
              {s.tab_title && <div className="search-result-sub">{s.tab_title}</div>}
              {s.activity_note && <div className="search-result-note">📝 {s.activity_note}</div>}
              <div className="search-result-time">{formatTimestamp(s.timestamp)}</div>
              {parseTags(s.tags).length > 0 && (
                <div className="card-tags">
                  {parseTags(s.tags).map((t) => (
                    <span className="tag" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </button>
        ))}
        {!loading && results.length === 0 && !error && (
          <div className="empty">No matches.</div>
        )}
      </div>
    </aside>
  );
}

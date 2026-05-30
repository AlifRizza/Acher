import type { Screenshot } from "../types";
import { imageUrl } from "../lib/api";
import { formatTime, parseTags } from "../lib/format";

// One thumbnail in the timeline grid. Clicking opens the full-size modal.
export function ScreenshotCard({
  shot,
  onOpen,
}: {
  shot: Screenshot;
  onOpen: (shot: Screenshot) => void;
}) {
  const label = shot.tab_title || shot.app_name;
  return (
    <button className="card" onClick={() => onOpen(shot)} title={label}>
      <div className="card-thumb">
        <img src={imageUrl(shot.id)} alt={label} loading="lazy" />
        {shot.is_manual && <span className="badge badge-manual">manual</span>}
      </div>
      <div className="card-meta">
        <div className="card-app">{shot.app_name}</div>
        {shot.tab_title && <div className="card-tab">{shot.tab_title}</div>}
        <div className="card-time">{formatTime(shot.timestamp)}</div>
        {parseTags(shot.tags).length > 0 && (
          <div className="card-tags">
            {parseTags(shot.tags).map((t) => (
              <span className="tag" key={t}>
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
    </button>
  );
}

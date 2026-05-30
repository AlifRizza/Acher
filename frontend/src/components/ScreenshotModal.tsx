import { useEffect } from "react";
import type { Screenshot } from "../types";
import { imageUrl } from "../lib/api";
import { formatTimestamp, parseTags } from "../lib/format";

// Full-size screenshot with its metadata. Closes on backdrop click or Esc.
export function ScreenshotModal({
  shot,
  onClose,
}: {
  shot: Screenshot;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const tags = parseTags(shot.tags);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <img className="modal-img" src={imageUrl(shot.id)} alt={shot.app_name} />
        <div className="modal-meta">
          <h2>{shot.tab_title || shot.app_name}</h2>
          <dl>
            <dt>App</dt>
            <dd>{shot.app_name}</dd>
            <dt>When</dt>
            <dd>{formatTimestamp(shot.timestamp)}</dd>
            <dt>Type</dt>
            <dd>{shot.is_manual ? "Manual capture" : "Automatic"}</dd>
            <dt>Upload</dt>
            <dd>{shot.upload_status}</dd>
            {shot.activity_note && (
              <>
                <dt>Note</dt>
                <dd>{shot.activity_note}</dd>
              </>
            )}
            {tags.length > 0 && (
              <>
                <dt>Tags</dt>
                <dd>
                  {tags.map((t) => (
                    <span className="tag" key={t}>
                      {t}
                    </span>
                  ))}
                </dd>
              </>
            )}
          </dl>
        </div>
      </div>
    </div>
  );
}

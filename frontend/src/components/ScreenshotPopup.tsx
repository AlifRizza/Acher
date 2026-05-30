import { useState } from "react";
import type { Screenshot } from "../types";
import { imageUrl } from "../lib/api";
import { formatTimestamp } from "../lib/format";

// Floating screenshot preview shown while hovering a timeline block. It tracks
// the cursor and flips to the other side when it would overflow the viewport,
// so it never gets clipped at the right or bottom edge.

const WIDTH = 480; // px, per design default (Q7)
const MARGIN = 16;

export interface PopupData {
  shot: Screenshot | null; // null → placeholder (gap with no screenshot)
  label: string;
  durationText: string;
  x: number; // cursor viewport coords
  y: number;
}

export function ScreenshotPopup({ data }: { data: PopupData }) {
  // Track whether the current image has loaded so we can show a skeleton first.
  // Keyed by shot id below via the `key` prop on <img>, so each block resets it.
  const [loaded, setLoaded] = useState(false);

  // Estimated height: 480px wide at ~16:10 plus a meta strip.
  const estHeight = (WIDTH * 10) / 16 + 90;
  const flipX = data.x + WIDTH + MARGIN * 2 > window.innerWidth;
  const flipY = data.y + estHeight + MARGIN * 2 > window.innerHeight;

  const left = flipX ? data.x - WIDTH - MARGIN : data.x + MARGIN;
  const top = flipY ? Math.max(MARGIN, data.y - estHeight - MARGIN) : data.y + MARGIN;

  return (
    <div className="popup" style={{ left, top, width: WIDTH }}>
      <div className="popup-thumb">
        {data.shot ? (
          <>
            {!loaded && <div className="popup-skeleton" />}
            <img
              key={data.shot.id}
              src={imageUrl(data.shot.id)}
              alt={data.label}
              style={{ display: loaded ? "block" : "none" }}
              onLoad={() => setLoaded(true)}
            />
          </>
        ) : (
          <div className="popup-placeholder">No screenshot for this period</div>
        )}
      </div>
      <div className="popup-meta">
        <div className="popup-title">{data.label}</div>
        {data.shot?.tab_title && data.shot.tab_title !== data.label && (
          <div className="popup-sub">{data.shot.tab_title}</div>
        )}
        <div className="popup-sub">
          {data.shot ? formatTimestamp(data.shot.timestamp) : ""} · {data.durationText}
        </div>
      </div>
    </div>
  );
}

import { colorForLabel } from "../lib/colors";
import type { Block } from "../types";

// Compressed 24h overview bar under the timeline. Shows the whole day's app
// blocks at a tiny scale, with a draggable viewport window. Clicking or
// dragging anywhere moves the main timeline to that time.

export interface MiniScrubberProps {
  dayStartMs: number;
  dayEndMs: number;
  viewStartMs: number;
  viewEndMs: number;
  appBlocks: Block[];
  onSeek: (centerMs: number) => void; // center the view on this time
}

export function MiniScrubber(props: MiniScrubberProps) {
  const { dayStartMs, dayEndMs, viewStartMs, viewEndMs, appBlocks, onSeek } = props;
  const span = dayEndMs - dayStartMs;

  // Translate a click x-fraction of the bar into an epoch-ms and seek there.
  function handleClick(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(dayStartMs + frac * span);
  }

  const winLeft = `${((viewStartMs - dayStartMs) / span) * 100}%`;
  const winWidth = `${((viewEndMs - viewStartMs) / span) * 100}%`;

  return (
    <div className="scrubber" onClick={handleClick}>
      {appBlocks.map((b, i) => (
        <div
          key={i}
          className="scrubber-block"
          style={{
            left: `${((b.startMs - dayStartMs) / span) * 100}%`,
            width: `${Math.max(0.2, ((b.endMs - b.startMs) / span) * 100)}%`,
            background: colorForLabel(b.label),
          }}
        />
      ))}
      <div className="scrubber-window" style={{ left: winLeft, width: winWidth }} />
    </div>
  );
}

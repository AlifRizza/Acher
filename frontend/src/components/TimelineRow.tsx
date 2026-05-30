import type { Block } from "../types";
import { colorForLabel } from "../lib/colors";

// One horizontal track of the timeline. Renders each block as an absolutely
// positioned bar whose left/width come from the time→pixel mapping passed in.
// Hover handlers bubble the block + cursor position up to the page so the
// shared screenshot popup can render once (not per row).

export interface TimelineRowProps {
  label: string;
  blocks: Block[];
  viewStartMs: number;
  pxPerMs: number;
  // matchedShotIds is null when no search is active; otherwise only blocks
  // containing a matched screenshot stay fully opaque.
  matchedShotIds: Set<number> | null;
  onHover: (block: Block, clientX: number, clientY: number) => void;
  onLeave: () => void;
  onClick: (block: Block) => void;
  // Render style: "bar" = wide colored blocks; "marker" = thin ticks/flags;
  // "usage" = active/idle/locked colored by fixed state colors.
  variant?: "bar" | "marker" | "usage";
}

// Fixed colors for the Computer Usage row (block.label is the state name).
const STATE_COLORS: Record<string, string> = {
  active: "#3fb950", // green — working
  idle: "#d29922", // amber — away
  locked: "#6e7681", // gray — screen off
};

export function TimelineRow(props: TimelineRowProps) {
  const { blocks, viewStartMs, pxPerMs, matchedShotIds, variant = "bar" } = props;

  return (
    <div className="trow">
      <div className="trow-label">{props.label}</div>
      <div className="trow-track">
        {blocks.map((b, i) => {
          const left = (b.startMs - viewStartMs) * pxPerMs;
          const width = Math.max(variant === "marker" ? 3 : 2, (b.endMs - b.startMs) * pxPerMs);
          const dimmed =
            matchedShotIds !== null && !b.shots.some((s) => matchedShotIds.has(s.id));
          const bg =
            variant === "usage"
              ? STATE_COLORS[b.label] ?? colorForLabel(b.label)
              : variant === "marker" && props.label === "Manual Entries"
                ? "var(--accent)"
                : colorForLabel(b.label);
          return (
            <div
              key={i}
              className={`block ${variant} ${dimmed ? "dimmed" : ""}`}
              style={{ left, width, background: bg }}
              title={b.label}
              onMouseMove={(e) => props.onHover(b, e.clientX, e.clientY)}
              onMouseEnter={(e) => props.onHover(b, e.clientX, e.clientY)}
              onMouseLeave={props.onLeave}
              onClick={() => props.onClick(b)}
            />
          );
        })}
      </div>
    </div>
  );
}

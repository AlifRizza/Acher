// Deterministic per-label color assignment: the same app/tab name always maps
// to the same color, with no central registry. We hash the string into a hue
// and use fixed saturation/lightness so colors stay distinct and readable on
// the dark theme.

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0; // force 32-bit
  }
  return Math.abs(h);
}

// Returns an HSL color string for a label, stable across renders and sessions.
export function colorForLabel(label: string): string {
  const hue = hashString(label) % 360;
  return `hsl(${hue}, 60%, 55%)`;
}

import type { ObservationResult } from "../types";

interface StackTrackProps {
  order: string[]; // bottom -> top
  rows: ObservationResult[];
}

// Layer strips are stacked bottom-to-top; each observation is an arrow from
// its lower layer to its upper layer. An upward arrow is satisfied; a
// downward arrow is a violation (its weight is paid). Everything is SVG so
// the audit trail stays sharp at any zoom level.
const WIDTH = 780;
const LABEL_W = 96;
const TRACK_H = 30;
const GAP = 12;
const PAD_TOP = 18;
const PAD_BOTTOM = 18;

const PALETTE = [
  "#c97b4a", "#7a9e7e", "#5f7fa8", "#b06a8a", "#9c8f54",
  "#5a9e9b", "#a86c4f", "#7b7aa8", "#8f9e5f", "#a85f6f",
];

function trackColor(id: string, key: number): string {
  let hash = 0;
  for (const ch of id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[(hash + key) % PALETTE.length];
}

export default function StackTrack({ order, rows }: StackTrackProps) {
  const n = order.length;
  const height = PAD_TOP + PAD_BOTTOM + n * TRACK_H + (n - 1) * GAP;

  // y of the CENTER of the track at position pos (pos 0 = bottom).
  const centerY = (pos: number): number =>
    height - PAD_BOTTOM - (pos + 1) * TRACK_H - pos * GAP + TRACK_H / 2;

  const innerLeft = LABEL_W + 8;
  const innerRight = WIDTH - 16;
  const slotCount = Math.max(rows.length, 1);
  const xFor = (i: number): number =>
    innerLeft + ((innerRight - innerLeft) * (i + 0.5)) / slotCount;

  const showLabels = rows.length <= 40;

  return (
    <svg
      className="stack-track"
      viewBox={`0 0 ${WIDTH} ${height}`}
      role="img"
      aria-label="从底到顶的图层叠压轨道与观察箭头"
    >
      <defs>
        <marker id="arrow-ok" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#2f8f4e" />
        </marker>
        <marker id="arrow-bad" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#c0392b" />
        </marker>
      </defs>

      {/* arrows first, so track strips sit above their endpoints */}
      {rows.map((row, i) => {
        const x = xFor(i);
        const y1 = centerY(row.lower_position);
        const y2 = centerY(row.upper_position);
        const violated = row.violated;
        const bend = (i % 5 - 2) * 6;
        const midX = x + bend;
        const midY = (y1 + y2) / 2;
        return (
          <g key={`arrow-${i}`} opacity={0.75}>
            <title>
              {`${row.lower} → ${row.upper}  权重 ${row.weight}${
                violated ? `（违背，代价 ${row.cost}）` : "（满足，代价 0）"
              }`}
            </title>
            <path
              d={`M ${x} ${y1} Q ${midX} ${midY} ${x} ${y2}`}
              fill="none"
              stroke={violated ? "#c0392b" : "#2f8f4e"}
              strokeWidth={violated ? 2 : 1.4}
              markerEnd={`url(#${violated ? "arrow-bad" : "arrow-ok"})`}
            />
            {showLabels && (
              <text x={midX + 3} y={midY - 2} fontSize="9"
                fill={violated ? "#a02c1f" : "#246b3c"}>
                {row.weight}
              </text>
            )}
          </g>
        );
      })}

      {order.map((id, pos) => {
        const y = centerY(pos) - TRACK_H / 2;
        return (
          <g key={`${id}-${pos}`}>
            <text x={LABEL_W - 6} y={centerY(pos) + 4} textAnchor="end"
              fontSize="13" fontWeight={600} fill="#2b2b2b">
              {id}
            </text>
            <rect x={LABEL_W} y={y} width={WIDTH - LABEL_W - 12} height={TRACK_H}
              rx={5} fill={trackColor(id, pos)} opacity={0.85}
              stroke="#00000022" />
            <text x={LABEL_W + 10} y={centerY(pos) + 4} fontSize="11"
              fill="#ffffffdd" fontWeight={600}>
              {`#${pos + 1} · ${pos === 0 ? "最底层" : pos === n - 1 ? "最顶层" : "中间层"}`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

"use client";

import clsx from "clsx";

type Point = {
  label?: string;
  value: number;
};

function buildPath(points: Point[], width: number, height: number, padding: number) {
  if (!points.length) {
    return "";
  }
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return points
    .map((point, index) => {
      const x =
        padding +
        (index / Math.max(points.length - 1, 1)) * Math.max(width - padding * 2, 1);
      const normalized = (point.value - min) / range;
      const y = height - padding - normalized * Math.max(height - padding * 2, 1);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function buildAreaPath(linePath: string, points: Point[], width: number, height: number, padding: number) {
  if (!linePath || !points.length) {
    return "";
  }
  const firstX = padding;
  const lastX = padding + Math.max(width - padding * 2, 1);
  const floorY = height - padding;
  return `${linePath} L ${lastX.toFixed(2)} ${floorY.toFixed(2)} L ${firstX.toFixed(2)} ${floorY.toFixed(2)} Z`;
}

export function MiniLineChart({
  points,
  tone = "cyan",
  height = 140,
  className,
}: {
  points: Point[];
  tone?: "cyan" | "orange" | "green";
  height?: number;
  className?: string;
}) {
  const width = 640;
  const padding = 14;
  const linePath = buildPath(points, width, height, padding);
  const areaPath = buildAreaPath(linePath, points, width, height, padding);
  const toneStroke =
    tone === "orange" ? "#ff7a18" : tone === "green" ? "#22c55e" : "#53f2ff";
  const toneFill =
    tone === "orange"
      ? "rgba(255, 122, 24, 0.14)"
      : tone === "green"
        ? "rgba(34, 197, 94, 0.14)"
        : "rgba(83, 242, 255, 0.14)";

  return (
    <div className={clsx("relative overflow-hidden rounded-[24px] border border-white/8 bg-black/20", className)}>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full">
        <defs>
          <linearGradient id={`tone-${tone}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={toneFill} />
            <stop offset="100%" stopColor="rgba(255,255,255,0)" />
          </linearGradient>
        </defs>
        <g opacity="0.18">
          {[0.25, 0.5, 0.75].map((fraction) => (
            <line
              key={fraction}
              x1={padding}
              x2={width - padding}
              y1={height * fraction}
              y2={height * fraction}
              stroke="rgba(255,255,255,0.18)"
              strokeDasharray="4 8"
            />
          ))}
        </g>
        {areaPath ? <path d={areaPath} fill={`url(#tone-${tone})`} /> : null}
        {linePath ? (
          <path
            d={linePath}
            fill="none"
            stroke={toneStroke}
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
      </svg>
    </div>
  );
}

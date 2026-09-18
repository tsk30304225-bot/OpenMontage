import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { railLayoutAtTime, RailElement, VisualTimeline } from "./timelineRail";

export type VisualModelCut = {
  model_id: string;
  region?: "full" | "left" | "right";
  caption?: string;
};

// Neutral fallback only; a video's identity comes from visual_models[].palette.
const DEFAULT_PALETTE = {
  background: "#FFFFFF",
  ink: "#1F2937",
  planned: "#2563EB",
  delay: "#D97706",
  rule: "#CBD5E1",
  idle: "#E5E7EB",
};

/**
 * Renders a persistent visual model for one cut. `cutStartSeconds` converts the
 * Sequence-local frame back to absolute video time, so consecutive cuts on the
 * same model continue the same state instead of restarting it.
 */
export const VisualModelScene: React.FC<{
  timeline: VisualTimeline;
  cut: VisualModelCut;
  cutStartSeconds: number;
  fontFamily?: string;
  drawBackground?: boolean;
}> = ({ timeline, cut, cutStartSeconds, fontFamily, drawBackground = true }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const model = timeline.models.find((m) => m.id === cut.model_id);
  if (!model) {
    throw new Error(`visual_model cut references unknown model ${cut.model_id}`);
  }
  const palette = { ...DEFAULT_PALETTE, ...(model.palette ?? {}) };
  const t = cutStartSeconds + frame / fps;

  const region = cut.region ?? "full";
  const margin = width * 0.06;
  const half = (width - margin * 3) / 2;
  const box = {
    x: region === "right" ? margin * 2 + half : margin,
    y: height * 0.22,
    w: region === "full" ? width - margin * 2 : half,
    h: height * 0.56,
  };
  const { elements } = railLayoutAtTime(model, timeline.events, t, box);
  const u = box.h / 10;
  const font = Math.round(Math.min(width, height) * (region === "full" ? 0.024 : 0.019));

  return (
    <AbsoluteFill style={{ background: drawBackground ? palette.background : "transparent", fontFamily, color: palette.ink }}>
      {(cut.caption || (region === "full" && model.title)) && (
        <div
          style={{
            position: "absolute",
            left: box.x,
            top: height * 0.1,
            width: box.w,
            fontSize: font * 1.7,
            fontWeight: 700,
            letterSpacing: "-0.01em",
          }}
        >
          {cut.caption ?? model.title}
        </div>
      )}
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        {elements.map((e) => renderElement(e, palette, font, u))}
      </svg>
    </AbsoluteFill>
  );
};

const renderElement = (e: RailElement, c: typeof DEFAULT_PALETTE, font: number, u: number) => {
  if (e.opacity <= 0.001) return null;
  const common = { key: e.key, opacity: e.opacity };
  switch (e.kind) {
    case "tick":
      return (
        <g {...common}>
          <line x1={e.x} x2={e.x} y1={e.y + font * 1.1} y2={e.y + e.h} stroke={c.rule} strokeWidth={1} strokeDasharray="2 6" />
          <text x={e.x} y={e.y + font * 0.6} fontSize={font * 0.8} fill={c.ink} fillOpacity={0.6} textAnchor="middle">
            {e.label}
          </text>
        </g>
      );
    case "rail":
      return <rect {...common} x={e.x} y={e.y} width={e.w} height={e.h} fill={c.rule} />;
    case "railLabel":
      return (
        <text {...common} x={e.x + e.w} y={e.y + e.h / 2 + font * 0.35} fontSize={font} fontWeight={700} fill={c.ink} textAnchor="end">
          {e.label}
        </text>
      );
    case "planned":
      return (
        <g {...common}>
          <rect x={e.x} y={e.y} width={e.w} height={e.h} rx={8} fill={c.background} stroke={c.planned} strokeWidth={3} />
          {e.w > font * 0.85 * 0.58 * (e.label ?? "").length + 10 && (
            <text x={e.x + e.w / 2} y={e.y + e.h / 2 + font * 0.33} fontSize={font * 0.85} fontWeight={700} fill={c.planned} textAnchor="middle">
              {e.label}
            </text>
          )}
          {e.struck && <line x1={e.x + 6} x2={e.x + e.w - 6} y1={e.y + e.h / 2} y2={e.y + e.h / 2} stroke={c.delay} strokeWidth={4} />}
        </g>
      );
    case "link":
      return (
        <path
          {...common}
          d={`M ${e.x} ${e.y} C ${e.x} ${e.y + e.h / 2}, ${e.x + e.w} ${e.y + e.h / 2}, ${e.x + e.w} ${e.y + e.h}`}
          fill="none"
          stroke={c.planned}
          strokeWidth={2}
          strokeDasharray="6 6"
        />
      );
    case "block":
      return (
        <g {...common}>
          <rect x={e.x} y={e.y} width={e.w} height={e.h} rx={10} fill={c.planned} stroke={c.background} strokeWidth={3} />
          {e.label && (
            <text x={e.x + e.w / 2} y={e.y + e.h / 2 + font * 0.38} fontSize={font * 1.05} fontWeight={700} fill={c.background} textAnchor="middle">
              {e.label}
            </text>
          )}
        </g>
      );
    case "idle":
      return (
        <rect {...common} x={e.x} y={e.y} width={e.w} height={e.h} rx={10} fill={c.idle} stroke={c.rule} strokeWidth={2} strokeDasharray="8 6" />
      );
    case "wait":
      return <rect {...common} x={e.x} y={e.y} width={e.w} height={e.h} rx={e.h / 2} fill={c.delay} />;
    case "deadline":
      return (
        <g {...common}>
          <line x1={e.x} x2={e.x} y1={e.y} y2={e.y + e.h} stroke={c.delay} strokeWidth={e.w} strokeDasharray="10 8" />
          <text x={e.x + 10} y={e.y + font * 0.2} fontSize={font * 0.8} fontWeight={700} fill={c.delay}>
            {e.label}
          </text>
        </g>
      );
    case "overrun":
      return <rect {...common} x={e.x} y={e.y} width={e.w} height={e.h} rx={10} fill={c.delay} fillOpacity={0.22} stroke={c.delay} strokeWidth={2} />;
    case "measure": {
      const mid = e.x + e.w / 2;
      const tick = u * 0.3;
      // Below the wait lanes the bracket opens upward and the label hangs under it; above the rail the reverse.
      const d = e.below
        ? `M ${e.x} ${e.y - tick} V ${e.y} H ${e.x + e.w} V ${e.y - tick}`
        : `M ${e.x} ${e.y + tick} V ${e.y} H ${e.x + e.w} V ${e.y + tick}`;
      const textY = e.below ? e.y + font * 1.45 : e.y - font * 0.45;
      return (
        <g {...common}>
          <path d={d} fill="none" stroke={c.delay} strokeWidth={3} />
          <text
            x={mid} y={textY} fontSize={font * 1.25} fontWeight={800} fill={c.delay} textAnchor="middle"
            stroke={c.background} strokeWidth={font * 0.3} paintOrder="stroke" strokeLinejoin="round"
          >
            {e.label}
          </text>
        </g>
      );
    }
  }
};

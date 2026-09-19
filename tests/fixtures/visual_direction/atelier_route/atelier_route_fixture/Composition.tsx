import React from "react";
import { AbsoluteFill, CalculateMetadataFunction, Sequence, useVideoConfig } from "remotion";
// Contract runtime (engine plumbing, no look). Resolved from the staged copy
// under remotion-composer/projects/<slug>/.
import {
  DirectionElement,
  DirectionProvider,
  DirectionTimeline,
  ElementView,
  useMeasures,
} from "../../src/direction";
// Shared caption infrastructure (no look of its own): allowed in atelier by exact module path.
import { PhraseCaptions } from "../../src/components/PhraseCaptions";

// Synthetic atelier fixture: the visual_direction contract says WHAT changes and
// visual_timeline says WHEN; this file only decides HOW it looks.

export type SceneWindow = { id: string; start: number; end: number };

export interface SceneProps {
  visualTimeline: DirectionTimeline;
  scenes: SceneWindow[];
  durationSeconds: number;
  /** Negative control only: draw the final route from the first frame. */
  negativeControl?: "static_final";
  /** Narration word timings for karaoke captions ({word, startMs, endMs}). */
  captions?: { word: string; startMs: number; endMs: number; pageBreakAfter?: boolean }[];
}

const INK = "#1B1F3B";
const PAPER = "#F6F1E7";
const ROUTE = "#2F6F5E";
const LATE = "#D1495B";

const POS: Record<string, [number, number]> = {
  warehouse: [300, 600],
  hub: [760, 420],
  locker: [1260, 620],
  customer: [1640, 430],
};

const Node: React.FC<{ id: string; label: string; v: Pick<ElementView, "presence" | "active"> }> = ({ id, label, v }) => {
  const [x, y] = POS[id];
  return (
    <g opacity={v.presence} transform={`translate(${x} ${y}) scale(${0.6 + 0.4 * v.presence})`}>
      {v.active && <circle r={74} fill="none" stroke={LATE} strokeWidth={6} opacity={0.7} />}
      <circle r={52} fill={PAPER} stroke={v.active ? LATE : INK} strokeWidth={6} />
      <text y={100} textAnchor="middle" fontSize={34} fontWeight={700} fill={INK}>
        {label}
      </text>
    </g>
  );
};

const Leg: React.FC<{ from: string; to: string; v: Pick<ElementView, "presence" | "attrs"> }> = ({ from, to, v }) => {
  const [x1, y1] = POS[from];
  const [x2, y2] = POS[to];
  const len = Math.hypot(x2 - x1, y2 - y1);
  const delay = Number(v.attrs.delay ?? 0);
  const late = Math.min(1, delay / 40);
  return (
    <line
      x1={x1} y1={y1} x2={x2} y2={y2}
      stroke={late > 0 ? LATE : ROUTE}
      strokeWidth={10 + 22 * late}
      strokeLinecap="round"
      strokeDasharray={`${len} ${len}`}
      strokeDashoffset={len * (1 - v.presence)}
    />
  );
};

// Every element is drawn only through the direction runtime, so nothing is on
// screen before the beat that reveals it and nothing restarts at a scene cut.
const RouteMap: React.FC<{ caption: string }> = ({ caption }) => {
  const measures = useMeasures("route");
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <div style={{ position: "absolute", left: 120, top: 90, fontSize: 60, fontWeight: 800, color: INK }}>{caption}</div>
      <svg width={1920} height={1080}>
        <DirectionElement model="route" id="leg1">{(v) => <Leg from="warehouse" to="hub" v={v} />}</DirectionElement>
        <DirectionElement model="route" id="leg2">{(v) => <Leg from="hub" to="locker" v={v} />}</DirectionElement>
        <DirectionElement model="route" id="warehouse">{(v) => <Node id="warehouse" label="Warehouse" v={v} />}</DirectionElement>
        <DirectionElement model="route" id="hub">{(v) => <Node id="hub" label="Hub" v={v} />}</DirectionElement>
        <DirectionElement model="route" id="locker">{(v) => <Node id="locker" label="Locker" v={v} />}</DirectionElement>
        <DirectionElement model="route" id="customer">{(v) => <Node id="customer" label="Customer" v={v} />}</DirectionElement>
        {measures.map((m) => (
          <text key={m.target + m.metric} x={1010} y={440} textAnchor="middle" fontSize={64} fontWeight={900} fill={LATE} opacity={m.progress}>
            {m.label}
          </text>
        ))}
      </svg>
    </AbsoluteFill>
  );
};

// Negative control: the same picture with the final state hard-coded.
const StaticFinalRoute: React.FC<{ caption: string }> = ({ caption }) => {
  const full = { presence: 1, active: true, attrs: { delay: 40 } };
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <div style={{ position: "absolute", left: 120, top: 90, fontSize: 60, fontWeight: 800, color: INK }}>{caption}</div>
      <svg width={1920} height={1080}>
        <Leg from="warehouse" to="hub" v={{ presence: 1, attrs: {} }} />
        <Leg from="hub" to="locker" v={full} />
        {Object.keys(POS).map((id) => <Node key={id} id={id} label={id} v={full} />)}
        <text x={1010} y={440} textAnchor="middle" fontSize={64} fontWeight={900} fill={LATE}>+40 min</text>
      </svg>
    </AbsoluteFill>
  );
};

const Card: React.FC<{ text: string }> = ({ text }) => (
  <AbsoluteFill style={{ background: INK, color: PAPER, justifyContent: "center", alignItems: "center", fontSize: 72, fontWeight: 800 }}>
    {text}
  </AbsoluteFill>
);

export const Scene: React.FC<SceneProps> = ({ visualTimeline, scenes, negativeControl, captions }) => {
  const { fps } = useVideoConfig();
  const win = (id: string) => scenes.find((s) => s.id === id)!;
  const seq = (id: string, node: React.ReactNode) => {
    const w = win(id);
    return (
      <Sequence key={id} from={Math.round(w.start * fps)} durationInFrames={Math.max(1, Math.round((w.end - w.start) * fps))}>
        {node}
      </Sequence>
    );
  };
  const Map = negativeControl === "static_final" ? StaticFinalRoute : RouteMap;
  return (
    <DirectionProvider timeline={visualTimeline}>
      <AbsoluteFill style={{ background: PAPER, fontFamily: "Segoe UI, Arial, sans-serif" }}>
        {seq("sc1", <Card text="A parcel leaves the warehouse at dawn." />)}
        {seq("sc2", <Map caption="Every leg of the trip" />)}
        {seq("sc3", <Map caption="One detour, everyone downstream" />)}
        {seq("sc4", <Card text="One closed road moved the whole promise." />)}
        {/* Captions at the root, outside every Sequence: they run on absolute time. */}
        {captions && captions.length > 0 && <PhraseCaptions words={captions} />}
      </AbsoluteFill>
    </DirectionProvider>
  );
};

export const calculateMetadata: CalculateMetadataFunction<SceneProps> = async ({ props }) => ({
  durationInFrames: Math.round((props.durationSeconds ?? 20) * 30),
  fps: 30,
  width: 1920,
  height: 1080,
});

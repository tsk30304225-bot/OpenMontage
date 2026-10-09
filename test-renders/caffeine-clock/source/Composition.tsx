import React from "react";
import {
  AbsoluteFill,
  CalculateMetadataFunction,
  Easing,
  interpolate,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont as loadHahmlet } from "@remotion/google-fonts/Hahmlet";
import { loadFont as loadNotoSansKR } from "@remotion/google-fonts/NotoSansKR";
// Contract runtime (no look) + the shared narration-caption module (allowed by exact path).
import { DirectionProvider, DirectionTimeline, useDirectionTime, useEventProgress, useModelState } from "../../src/direction";
import { PhraseCaptions } from "../../src/components/PhraseCaptions";

const { fontFamily: SERIF } = loadHahmlet("normal", { weights: ["600", "800"], subsets: ["korean", "latin"] });
const { fontFamily: SANS } = loadNotoSansKR("normal", { weights: ["400", "500", "700"], subsets: ["korean", "latin"] });

// ---- palette (art-direction.md) ---------------------------------------------
const C = {
  espresso: "#120B07",
  roast: "#2A1A10",
  crema: "#E9B872",
  milk: "#F6EDE1",
  amber: "#FF8A3D",
  dusk: "#22304F",
  night: "#0E1424",
};

type Word = { word: string; startMs: number; endMs: number };
type SceneClip = { scene_id: string; src: string; start: number; end: number };

export interface SceneProps {
  visualTimeline?: DirectionTimeline;
  sceneClips?: SceneClip[];
  totalSeconds: number;
  captions: Word[];
  captionMuteWindows: [number, number][];
  scenes: Record<string, [number, number]>;
  footage: Record<string, string>;
}

const FADE = 12; // frames, cross-dissolve through espresso

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const easeIO = Easing.bezier(0.65, 0, 0.35, 1);

/** Scene wrapper: fades in/out at its edges (Sequence-local frames only for the dissolve). */
const SceneFade: React.FC<{ frames: number; children: React.ReactNode; fadeIn?: boolean; fadeOut?: boolean }> = ({
  frames,
  children,
  fadeIn = true,
  fadeOut = true,
}) => {
  const f = useCurrentFrame();
  const a = fadeIn ? interpolate(f, [0, FADE], [0, 1], clamp) : 1;
  const b = fadeOut ? interpolate(f, [frames - FADE, frames], [1, 0], clamp) : 1;
  return <AbsoluteFill style={{ opacity: Math.min(a, b) }}>{children}</AbsoluteFill>;
};

// ---- footage scenes -----------------------------------------------------------

const Grade: React.FC<{ warm: number }> = ({ warm }) => (
  <>
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 45%, rgba(18,11,7,0.78) 100%)`,
      }}
    />
    <AbsoluteFill style={{ background: `rgba(233,184,114,${0.1 * warm})`, mixBlendMode: "soft-light" }} />
  </>
);

const Footage: React.FC<{ src: string; frames: number; warm: number }> = ({ src, frames, warm }) => {
  const f = useCurrentFrame();
  const s = interpolate(f, [0, frames], [1.0, 1.05], clamp);
  return (
    <AbsoluteFill style={{ background: C.espresso, overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${s})` }}>
        <OffthreadVideo src={staticFile(src)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </AbsoluteFill>
      <Grade warm={warm} />
    </AbsoluteFill>
  );
};

/** sc1 — 3 p.m., the pour. A café-menu time stamp settles in the lower-left. */
const OpeningTitle: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const rise = interpolate(t, [0.5, 1.6], [40, 0], { ...clamp, easing: Easing.out(Easing.cubic) });
  const a = interpolate(t, [0.5, 1.4], [0, 1], clamp);
  const rule = interpolate(t, [1.0, 2.2], [0, 1], { ...clamp, easing: easeIO });
  const out = interpolate(t, [5.6, 6.6], [1, 0], clamp);
  return (
    <div style={{ position: "absolute", left: 120, top: 520, opacity: a * out, transform: `translateY(${rise}px)` }}>
      <div style={{ fontFamily: SANS, fontWeight: 500, fontSize: 30, letterSpacing: 8, color: C.crema }}>PM</div>
      <div style={{ fontFamily: SERIF, fontWeight: 800, fontSize: 190, lineHeight: 1, color: C.milk, letterSpacing: -4 }}>
        3:00
      </div>
      <div style={{ width: 360 * rule, height: 3, background: C.crema, margin: "18px 0 16px" }} />
      <div style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 46, color: C.milk }}>커피 한 잔의 시계가 켜진다</div>
    </div>
  );
};

/** sc6 — the cup goes down; the closing line lands after the narration ends. */
const ClosingTitle: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps; // sc6-local; narration ends ~5.9 s into the scene
  const a = interpolate(t, [6.0, 6.8], [0, 1], clamp);
  const y = interpolate(t, [6.0, 7.0], [24, 0], { ...clamp, easing: Easing.out(Easing.cubic) });
  const dim = interpolate(t, [5.6, 7.0], [0, 0.55], clamp);
  const end = interpolate(t, [7.7, 8.3], [0, 1], clamp);
  return (
    <>
      <AbsoluteFill style={{ background: C.espresso, opacity: dim }} />
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: a, transform: `translateY(${y}px)` }}>
        <div style={{ fontFamily: SANS, fontWeight: 500, fontSize: 30, letterSpacing: 6, color: C.crema, marginBottom: 18 }}>
          LAST CUP
        </div>
        <div style={{ fontFamily: SERIF, fontWeight: 800, fontSize: 104, color: C.milk, textAlign: "center", lineHeight: 1.15 }}>
          마지막 잔은,
          <br />
          이른 오후에.
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: C.espresso, opacity: end }} />
    </>
  );
};

// ---- the caffeine clock dial (signature device; implements the rail contract) ----

type RailItem = { id: string; label?: string; planned_start?: number; duration: number; present?: boolean };
type RailState = { items: RailItem[]; deadline?: number; measures: { target: string; metric: string; label?: string | null }[] };

const CX = 1190;
const CY = 330;
const R = 380;
// minutes after midnight -> clockwise degrees from 12 o'clock on a 12-hour face
const deg = (min: number) => ((min / 60) % 12) * 30;
const pt = (d: number, r: number) => {
  const a = ((d - 90) * Math.PI) / 180;
  return [CX + r * Math.cos(a), CY + r * Math.sin(a)];
};
const arcPath = (d0: number, d1: number, r: number) => {
  if (d1 - d0 < 0.05) return "";
  const [x0, y0] = pt(d0, r);
  const [x1, y1] = pt(d1, r);
  return `M ${x0} ${y0} A ${r} ${r} 0 ${d1 - d0 > 180 ? 1 : 0} 1 ${x1} ${y1}`;
};

const DialFace: React.FC<{ nightness: number }> = ({ nightness }) => {
  const ticks = [];
  for (let m = 0; m < 720; m += 15) {
    const d = m / 2;
    const hour = m % 60 === 0;
    const inSpan = d >= 90 && d <= 270;
    const [x0, y0] = pt(d, R + 46);
    const [x1, y1] = pt(d, R + (hour ? 74 : 58));
    ticks.push(
      <line key={m} x1={x0} y1={y0} x2={x1} y2={y1} stroke={C.milk} strokeOpacity={inSpan ? (hour ? 0.9 : 0.35) : 0.12}
        strokeWidth={hour ? 4 : 2} strokeLinecap="round" />,
    );
  }
  const labels = [15, 16, 17, 18, 19, 20, 21].map((h) => {
    const [x, y] = pt(deg(h * 60), R + 118);
    return (
      <text key={h} x={x} y={y + 14} textAnchor="middle" fontFamily={SANS} fontWeight={500} fontSize={34}
        fill={C.milk} fillOpacity={0.85}>
        {`${h}:00`}
      </text>
    );
  });
  const face = interpolate(nightness, [0, 1], [0, 1]);
  return (
    <g>
      <circle cx={CX} cy={CY} r={R + 30} fill={C.roast} fillOpacity={0.55 - 0.25 * face} />
      <circle cx={CX} cy={CY} r={R} fill="none" stroke={C.milk} strokeOpacity={0.12} strokeWidth={56} />
      {ticks}
      {labels}
      <circle cx={CX} cy={CY} r={10} fill={C.milk} fillOpacity={0.7} />
    </g>
  );
};

const itemColor = (id: string) => (id === "absorb" ? C.crema : id === "mask" ? C.amber : "#B9764A");

/** Every rail event is drawn here, each through its own contract progress. */
const CaffeineDial: React.FC<{ nightness: number }> = ({ nightness }) => {
  const { state } = useModelState<RailState>("caffeine_clock");
  const pAbsorb = useEventProgress("ev-b1");
  const pMeasure = useEventProgress("ev-b2");
  const pMask = useEventProgress("ev-b3");
  const pHalf = useEventProgress("ev-b4");
  const pTail = useEventProgress("ev-b5");
  const t = useDirectionTime();
  const pour: Record<string, number> = { absorb: pAbsorb, mask: pMask, tail: pTail };

  const arcs = (state.items ?? [])
    .filter((it) => it.present !== false)
    .map((it) => {
      const start = it.planned_start ?? 900;
      const p = pour[it.id] ?? 1;
      const d0 = deg(start);
      const d1 = d0 + (deg(start + it.duration) - d0) * p;
      const col = itemColor(it.id);
      const [hx, hy] = pt(d1, R);
      const shimmer = 0.5 + 0.5 * Math.sin(t * 3 + d1 / 20);
      return (
        <g key={it.id}>
          <path d={arcPath(d0, d1, R)} stroke={col} strokeOpacity={0.25} strokeWidth={84} fill="none" strokeLinecap="butt" />
          <path d={arcPath(d0, d1, R)} stroke={col} strokeWidth={54} fill="none" strokeLinecap="butt"
            strokeDasharray={it.id === "tail" ? "6 10" : undefined} />
          {p < 1 && p > 0 && <circle cx={hx} cy={hy} r={20 + 6 * shimmer} fill={C.milk} fillOpacity={0.9} />}
        </g>
      );
    });

  // MEASURE ev-b2: a bracket outside the rim around the absorption window + its label.
  const measure = (state.measures ?? []).find((m) => m.target === "absorb");
  let bracket: React.ReactNode = null;
  if (measure) {
    const d0 = deg(900);
    const d1 = d0 + (deg(945) - d0) * pMeasure;
    const [lx, ly] = pt((deg(900) + deg(945)) / 2, R + 190);
    bracket = (
      <g opacity={pMeasure}>
        <path d={arcPath(d0, d1, R + 92)} stroke={C.crema} strokeWidth={5} fill="none" />
        <text x={lx + 30} y={ly} fontFamily={SERIF} fontWeight={800} fontSize={64} fill={C.crema}>
          {measure.label ?? "45분"}
        </text>
      </g>
    );
  }

  // SHIFT ev-b4: the deadline — a clock hand sweeps from 15:00 to the half-life point.
  let hand: React.ReactNode = null;
  if (state.deadline != null) {
    const target = deg(state.deadline);
    const d = deg(900) + (target - deg(900)) * pHalf;
    const [hx, hy] = pt(d, R - 40);
    const [lx, ly] = pt(target + 22, R - 150);
    hand = (
      <g>
        <line x1={CX} y1={CY} x2={hx} y2={hy} stroke={C.milk} strokeWidth={9} strokeLinecap="round" />
        <circle cx={CX} cy={CY} r={18} fill={C.milk} />
        <g opacity={interpolate(pHalf, [0.6, 1], [0, 1], clamp)}>
          <text x={lx} y={ly} textAnchor="middle" fontFamily={SANS} fontWeight={700} fontSize={38} fill={C.milk}>
            밤 8시 · 절반 남음
          </text>
        </g>
      </g>
    );
  }

  return (
    <g>
      <DialFace nightness={nightness} />
      {arcs}
      {bracket}
      {hand}
    </g>
  );
};

/** Camera per model scene: sc2 leans into the 3 o'clock quadrant, sc3 pulls back to the whole rim. */
const cameraAt = (t: number, sc: Record<string, [number, number]>) => {
  const [s3a] = sc.sc3;
  const k = interpolate(t, [s3a - 0.3, s3a + 1.2], [0, 1], { ...clamp, easing: easeIO });
  const [qx, qy] = pt(104, R); // the 15:00-15:45 stretch of the rim
  return {
    zoom: interpolate(k, [0, 1], [1.7, 1.0]),
    fx: interpolate(k, [0, 1], [qx, CX]),
    fy: interpolate(k, [0, 1], [qy, CY]),
    sx: interpolate(k, [0, 1], [1260, CX]),
    sy: interpolate(k, [0, 1], [560, CY]),
  };
};

const LeftColumn: React.FC<{ kicker: string; big: React.ReactNode; note: string; a: number }> = ({ kicker, big, note, a }) => (
  <div style={{ position: "absolute", left: 120, top: 250, width: 640, opacity: a }}>
    <div style={{ fontFamily: SANS, fontWeight: 500, fontSize: 30, letterSpacing: 6, color: C.crema }}>{kicker}</div>
    <div style={{ fontFamily: SERIF, fontWeight: 800, fontSize: 150, lineHeight: 1.05, color: C.milk, marginTop: 10 }}>{big}</div>
    <div style={{ fontFamily: SANS, fontWeight: 400, fontSize: 38, lineHeight: 1.45, color: C.milk, opacity: 0.82, marginTop: 22 }}>
      {note}
    </div>
  </div>
);

const ModelStage: React.FC<{ scenes: Record<string, [number, number]> }> = ({ scenes }) => {
  const t = useDirectionTime();
  const pAbsorb = useEventProgress("ev-b1");
  const pMeasure = useEventProgress("ev-b2");
  const pMask = useEventProgress("ev-b3");
  const pHalf = useEventProgress("ev-b4");
  const pTail = useEventProgress("ev-b5");
  const [s5a] = scenes.sc5;
  const nightness = interpolate(t, [s5a - 0.5, s5a + 2.5], [0, 1], clamp);
  const cam = cameraAt(t, scenes);
  const inSc2 = t < scenes.sc3[0];
  const inSc3 = t >= scenes.sc3[0] && t < scenes.sc4[0];

  const bg = `radial-gradient(circle at 62% 30%, ${nightness > 0 ? C.dusk : C.roast} 0%, ${
    nightness > 0 ? C.night : C.espresso
  } 70%)`;

  // left column content per scene, each the scene's own primary idea
  let left: React.ReactNode = null;
  if (inSc2) {
    const minutes = Math.round(45 * interpolate(pMeasure, [0, 1], [0, 1]));
    left = (
      <LeftColumn
        kicker="ABSORPTION"
        a={interpolate(pAbsorb, [0, 0.6], [0, 1], clamp)}
        big={pMeasure > 0 ? <span style={{ color: C.crema }}>{minutes}분</span> : "흡수 중"}
        note="위와 장을 지나 혈액으로 — 거의 다 들어오기까지"
      />
    );
  } else if (inSc3) {
    const veil = pMask;
    left = (
      <div style={{ position: "absolute", left: 120, top: 250, width: 640 }}>
        <div style={{ fontFamily: SANS, fontWeight: 500, fontSize: 30, letterSpacing: 6, color: C.amber }}>ADENOSINE BLOCKED</div>
        <div style={{ position: "relative", marginTop: 10, height: 190 }}>
          <div style={{ fontFamily: SERIF, fontWeight: 800, fontSize: 170, lineHeight: 1.05, color: C.milk,
            filter: `blur(${14 * veil}px)`, opacity: 1 - 0.45 * veil }}>
            피로
          </div>
          <div style={{ position: "absolute", left: -10, top: 18, height: 170, width: `${330 * veil}px`,
            background: "linear-gradient(90deg, rgba(246,237,225,0.20), rgba(246,237,225,0.06))",
            borderRight: `4px solid ${C.amber}`, backdropFilter: "blur(2px)" }} />
        </div>
        <div style={{ fontFamily: SANS, fontWeight: 400, fontSize: 38, lineHeight: 1.45, color: C.milk, opacity: 0.82, marginTop: 22 }}>
          {veil > 0.5 ? "사라진 게 아니라, 가려졌을 뿐" : "졸음 신호 아데노신"}
        </div>
      </div>
    );
  } else {
    const pct = Math.round(100 - 50 * pHalf);
    left = (
      <LeftColumn
        kicker="HALF-LIFE · 5H"
        a={interpolate(t, [s5a, s5a + 0.6], [0, 1], clamp)}
        big={<span style={{ color: pHalf > 0 ? C.amber : C.milk }}>{pct}%</span>}
        note={pTail > 0.3 ? "밤 8시에도 몸속에 절반이 남아 있다" : "오후 3시에 마신 카페인, 몸에 남은 양"}
      />
    );
  }

  return (
    <AbsoluteFill style={{ background: bg }}>
      <AbsoluteFill>
        <svg width={1920} height={1080} viewBox="0 0 1920 1080">
          <g transform={`translate(${cam.sx} ${cam.sy}) scale(${cam.zoom}) translate(${-cam.fx} ${-cam.fy})`}>
            <CaffeineDial nightness={nightness} />
          </g>
        </svg>
      </AbsoluteFill>
      {left}
    </AbsoluteFill>
  );
};

// ---- root -----------------------------------------------------------------------

const Captions: React.FC<{ words: Word[]; mute: [number, number][] }> = ({ words, mute }) => {
  const kept = words.filter((w) => !mute.some(([a, b]) => w.startMs / 1000 >= a && w.startMs / 1000 < b));
  return (
    <PhraseCaptions words={kept} maxChars={22} holdSeconds={0.5} fontFamily={SANS} fontSize={44} fontWeight={700}
      activeColor={C.milk} dimColor="rgba(246,237,225,0.45)" backgroundColor="rgba(18,11,7,0.72)" position="bottom-center" />
  );
};

export const Scene: React.FC<SceneProps> = (props) => {
  const { fps } = useVideoConfig();
  const { scenes, footage, sceneClips = [], visualTimeline } = props;
  const F = (s: number) => Math.round(s * fps);
  const seq = (id: string) => ({ from: F(scenes[id][0]), durationInFrames: F(scenes[id][1]) - F(scenes[id][0]) });
  const modelFrom = F(scenes.sc2[0]);
  const modelUntilSc4 = F(scenes.sc4[0]) - modelFrom + FADE;

  const body = (
    <AbsoluteFill style={{ background: C.espresso }}>
      <Sequence {...seq("sc1")}>
        <SceneFade frames={seq("sc1").durationInFrames} fadeIn={false}>
          <Footage src={footage.sc1} frames={seq("sc1").durationInFrames} warm={1} />
          <OpeningTitle />
        </SceneFade>
      </Sequence>

      {/* sc2 + sc3: one continuous dial; the camera pulls back across the boundary */}
      <Sequence from={modelFrom} durationInFrames={modelUntilSc4}>
        <SceneFade frames={modelUntilSc4}>
          <ModelStage scenes={scenes} />
        </SceneFade>
      </Sequence>

      {/* sc4: HyperFrames kinetic beat, rendered to a clip by video_compose */}
      {sceneClips.map((clip) => (
        <Sequence key={clip.scene_id} from={F(clip.start)} durationInFrames={F(clip.end) - F(clip.start)}>
          <OffthreadVideo src={staticFile(clip.src)} muted />
        </Sequence>
      ))}

      <Sequence {...seq("sc5")}>
        <SceneFade frames={seq("sc5").durationInFrames}>
          <ModelStage scenes={scenes} />
        </SceneFade>
      </Sequence>

      <Sequence {...seq("sc6")}>
        <SceneFade frames={seq("sc6").durationInFrames} fadeOut={false}>
          <Footage src={footage.sc6} frames={seq("sc6").durationInFrames} warm={0.4} />
          <ClosingTitle />
        </SceneFade>
      </Sequence>

      <Captions words={props.captions} mute={props.captionMuteWindows} />
    </AbsoluteFill>
  );
  // Keep the provider at the root, outside every <Sequence>: it owns absolute time.
  return visualTimeline ? <DirectionProvider timeline={visualTimeline}>{body}</DirectionProvider> : body;
};

export const calculateMetadata: CalculateMetadataFunction<SceneProps> = async ({ props }) => ({
  durationInFrames: Math.round((props.totalSeconds ?? 38) * 30),
  fps: 30,
  width: 1920,
  height: 1080,
});

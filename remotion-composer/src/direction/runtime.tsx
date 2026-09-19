/**
 * Direction runtime for bespoke (atelier) compositions.
 *
 * The visual_direction contract decides WHAT changes and the visual_timeline
 * decides WHEN (resolved from the real narration). A bespoke composition only
 * decides HOW it looks. This module hands it the contract state at the current
 * absolute video time, so the author never re-estimates timing and a model
 * keeps its state across scene boundaries.
 *
 * Mount <DirectionProvider timeline={props.visualTimeline}> once at the
 * composition root (outside every <Sequence>): the root frame is the absolute
 * frame, and every hook below reads time from the provider, never from a
 * Sequence-local useCurrentFrame().
 *
 * The render path and direction_qa trace which events a project implements by
 * reading these calls (useEventProgress("<event id>"), useElement / <DirectionElement>
 * with a model + element id, useModelState / useMeasures / useView with a model id),
 * so keep their ids as string literals.
 */
import React, { createContext, useContext } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import {
  DirectionEvent,
  ElementMeasure,
  ElementModelDef,
  ElementState,
  ModelElement,
  applyElementEvent,
  elementInitialState,
} from "./elementModel";
import { applyRailEvent, initialRailState, RailState, VisualModelDef } from "../components/visual-models/timelineRail";

export type DirectionModel = (ElementModelDef | VisualModelDef) & { id: string; type: string };
export type DirectionTimeline = { models: DirectionModel[]; events: DirectionEvent[] };

const isRail = (m: DirectionModel) => m.type === "timeline_rail";

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/** 0 before the event's anchor, eased 0..1 while it plays, 1 afterwards. */
export const eventProgressAt = (ev: DirectionEvent, t: number): number => {
  if (t < ev.time_seconds) return 0;
  const p = (t - ev.time_seconds) / Math.max(0.001, ev.duration_seconds);
  return p >= 1 ? 1 : easeInOut(p);
};

export const modelInitialState = (m: DirectionModel): ElementState | RailState =>
  isRail(m) ? initialRailState(m as VisualModelDef) : elementInitialState(m as ElementModelDef);

export const applyModelEvent = (m: DirectionModel, state: any, ev: DirectionEvent) =>
  isRail(m) ? applyRailEvent(state as RailState, ev as any) : applyElementEvent(state as ElementState, ev);

/** Contract state after every event of the model with time <= t (deterministic in t). */
export const modelStateAt = (timeline: DirectionTimeline, modelId: string, t: number) => {
  const model = timeline.models.find((m) => m.id === modelId);
  if (!model) throw new Error(`direction: unknown model ${modelId}`);
  let state: any = modelInitialState(model);
  let before: any = state;
  let current: DirectionEvent | null = null;
  for (const ev of timeline.events.filter((e) => e.model_id === modelId).sort((a, b) => a.time_seconds - b.time_seconds)) {
    if (ev.time_seconds > t) break;
    before = state;
    state = applyModelEvent(model, state, ev);
    current = ev;
  }
  return { model, state, before, lastEvent: current };
};

type Ctx = { timeline: DirectionTimeline; time: number };
const DirectionContext = createContext<Ctx | null>(null);

export const DirectionProvider: React.FC<{ timeline: DirectionTimeline; children: React.ReactNode }> = ({ timeline, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!timeline || !Array.isArray(timeline.events)) {
    throw new Error("DirectionProvider needs props.visualTimeline (compiled visual_timeline)");
  }
  return <DirectionContext.Provider value={{ timeline, time: frame / fps }}>{children}</DirectionContext.Provider>;
};

const useCtx = (): Ctx => {
  const ctx = useContext(DirectionContext);
  if (!ctx) throw new Error("direction hooks must be used inside <DirectionProvider> mounted at the composition root");
  return ctx;
};

/** Absolute video time in seconds (not Sequence-local). */
export const useDirectionTime = (): number => useCtx().time;

export const useDirectionEvent = (eventId: string): DirectionEvent => {
  const ev = useCtx().timeline.events.find((e) => e.id === eventId);
  if (!ev) throw new Error(`direction: unknown event ${eventId} (recompile visual_timeline or fix the id)`);
  return ev;
};

/** Eased progress of one event: 0 before its narration anchor, 1 once it has played. */
export const useEventProgress = (eventId: string): number => {
  const { time } = useCtx();
  return eventProgressAt(useDirectionEvent(eventId), time);
};

/** Whole contract state of a model at the current time (for bespoke renderers that draw the full model). */
export const useModelState = <S = any,>(modelId: string): { state: S; before: S; lastEvent: DirectionEvent | null; progress: number } => {
  const { timeline, time } = useCtx();
  const { state, before, lastEvent } = modelStateAt(timeline, modelId, time);
  return { state, before, lastEvent, progress: lastEvent ? eventProgressAt(lastEvent, time) : 1 };
};

export type ElementView = {
  element: ModelElement | null;
  /** 0 = not on screen, 1 = fully present; ramps with the event that revealed / removed it. */
  presence: number;
  /** Progress of the latest event that targeted this element (1 if none yet). */
  progress: number;
  /** Numeric attributes interpolated through the latest EXPAND/SHIFT; others as in the contract. */
  attrs: Record<string, any>;
  active: boolean;
  lastEvent: DirectionEvent | null;
};

const touches = (ev: DirectionEvent, elementId: string) =>
  ev.target === elementId || ((ev.params?.path as string[] | undefined) ?? []).map(String).includes(elementId);

/** One element of an element model, with appearance and attribute changes eased by its own events. */
export const useElement = (modelId: string, elementId: string): ElementView => {
  const { timeline, time } = useCtx();
  const model = timeline.models.find((m) => m.id === modelId);
  if (!model) throw new Error(`direction: unknown model ${modelId}`);
  if (isRail(model)) throw new Error(`direction: ${modelId} is a timeline_rail; use useModelState for rail models`);
  let state = elementInitialState(model as ElementModelDef);
  let prev = state;
  let last: DirectionEvent | null = null;
  for (const ev of timeline.events.filter((e) => e.model_id === modelId).sort((a, b) => a.time_seconds - b.time_seconds)) {
    if (ev.time_seconds > time) break;
    const next = applyElementEvent(state, ev);
    if (touches(ev, elementId)) {
      prev = state;
      last = ev;
    }
    state = next;
  }
  const now = state.elements[elementId] ?? null;
  const was = prev.elements[elementId] ?? null;
  if (!now && !was && !(model as ElementModelDef).initial_state?.elements?.some((e) => e.id === elementId)) {
    const declared = timeline.events.some((e) => e.model_id === modelId && e.target === elementId);
    if (!declared) throw new Error(`direction: model ${modelId} has no element ${elementId}`);
  }
  const progress = last ? eventProgressAt(last, time) : 1;
  const visNow = now?.visible ? 1 : 0;
  const visWas = was?.visible ? 1 : 0;
  const presence = last ? visWas + (visNow - visWas) * progress : visNow;
  const attrs: Record<string, any> = { ...(now?.attrs ?? {}) };
  if (last && was && now) {
    for (const [k, v] of Object.entries(now.attrs)) {
      const from = was.attrs[k];
      if (typeof v === "number" && typeof from === "number") attrs[k] = from + (v - from) * progress;
    }
  }
  return { element: now ?? was, presence, progress, attrs, active: Boolean(now?.attrs?.active), lastEvent: last };
};

/** Render-prop form of useElement; renders nothing while the element is absent. */
export const DirectionElement: React.FC<{
  model: string;
  id: string;
  children: (view: ElementView) => React.ReactNode;
}> = ({ model, id, children }) => {
  const view = useElement(model, id);
  if (view.presence <= 0.001) return null;
  return <>{children(view)}</>;
};

/** Active measurements of a model (MEASURE events), each with its own eased progress. */
export const useMeasures = (modelId: string): (ElementMeasure & { progress: number })[] => {
  const { timeline, time } = useCtx();
  const { state } = modelStateAt(timeline, modelId, time);
  const events = timeline.events.filter((e) => e.model_id === modelId && e.operation === "MEASURE" && e.time_seconds <= time);
  return ((state as ElementState).measures ?? []).map((m) => {
    const ev = [...events].reverse().find((e) => e.target === m.target && (e.params?.metric ?? "value") === m.metric);
    return { ...m, progress: ev ? eventProgressAt(ev, time) : 1 };
  });
};

/** Model-level view attributes set by SHIFT target=view. */
export const useView = (modelId: string): Record<string, any> => {
  const { timeline, time } = useCtx();
  return ((modelStateAt(timeline, modelId, time).state as ElementState).view ?? {}) as Record<string, any>;
};

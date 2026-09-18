/**
 * timeline_rail visual model: state reducer, schedule derivation and layout.
 *
 * Topic-agnostic: items planned on a numeric (or clock) axis above the rail where
 * they actually happen. What items mean, their labels, colours and the queue
 * policy come from the project's visual_direction model definition.
 *
 * Mirrors lib/visual_direction.py (rail_schedule / apply_rail_event). State is
 * a pure function of the absolute video time, so every cut showing the same
 * model renders one continuously evolving graphic.
 */

export type RailItem = {
  id: string;
  label?: string;
  slot?: number;
  planned_start?: number;
  duration: number;
  ready_offset?: number;
  present?: boolean;
};

export type RailMeasure = { target: string; metric: string; label?: string | null };

export type RailPolicy = "independent" | "sequential" | "ready_first";

export type RailState = {
  axis: { start: number; end: number; tick?: number; format?: "number" | "clock"; unit_suffix?: string };
  slot_interval: number;
  deadline?: number;
  resource_available_at?: number;
  items: RailItem[];
  measures: RailMeasure[];
  frozen: Record<string, { actual_start: number; actual_end: number }>;
  show_planned: boolean;
  show_actual: boolean;
  policy: RailPolicy;
};

export type VisualModelDef = {
  id: string;
  type: "timeline_rail";
  title?: string;
  palette?: Partial<Record<"background" | "ink" | "planned" | "delay" | "rule" | "idle", string>>;
  labels?: Record<string, string>;
  queue?: { policy?: RailPolicy };
  initial_state: Partial<RailState> & { axis: RailState["axis"]; items: RailItem[] };
};

export type VisualEvent = {
  id: string;
  model_id: string;
  operation: "ADD" | "REMOVE" | "EXPAND" | "SHIFT" | "PROPAGATE" | "MEASURE";
  target: string;
  params?: Record<string, any>;
  time_seconds: number;
  duration_seconds: number;
};

export type VisualTimeline = { models: VisualModelDef[]; events: VisualEvent[] };

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

export const initialRailState = (model: VisualModelDef): RailState => {
  const s = clone(model.initial_state) as RailState;
  s.slot_interval = s.slot_interval ?? 1;
  s.measures = s.measures ?? [];
  s.frozen = s.frozen ?? {};
  s.show_planned = s.show_planned ?? true;
  s.show_actual = s.show_actual ?? true;
  s.policy = model.queue?.policy ?? "sequential";
  s.items = (s.items ?? []).map((i) => ({ present: true, ready_offset: 0, ...i }));
  return s;
};

const plannedStart = (s: RailState, i: RailItem): number =>
  i.planned_start != null ? i.planned_start : s.axis.start + (i.slot ?? 0) * s.slot_interval;

export type ScheduleRow = {
  id: string;
  planned_start: number;
  ready: number;
  present: boolean;
  actual_start?: number;
  actual_end?: number;
  wait?: number;
  idle_before?: number;
};

// Derive the actual rail under the model's queue policy:
//   independent  each item at its ready time, no shared resource
//   sequential   one shared resource, planned order
//   ready_first  one shared resource that, when free, takes the earliest-planned ready item
export const railSchedule = (s: RailState) => {
  let cursor = s.resource_available_at ?? s.axis.start;
  const out: Record<string, ScheduleRow> = {};
  type Pending = { planned: number; item: RailItem };
  let pending: Pending[] = [];
  for (const item of s.items) {
    const planned = plannedStart(s, item);
    const row: ScheduleRow = { id: item.id, planned_start: planned, ready: planned + (item.ready_offset ?? 0), present: item.present !== false };
    out[item.id] = row;
    if (row.present) pending.push({ planned, item });
  }
  const byPlan = (a: Pending, b: Pending) => a.planned - b.planned || (a.item.id < b.item.id ? -1 : a.item.id > b.item.id ? 1 : 0);
  pending.sort(byPlan);
  const order: string[] = [];
  let lastEnd = cursor;
  while (pending.length) {
    let chosen = pending[0];
    if (s.policy === "ready_first") {
      let ready = pending.filter((p) => out[p.item.id].ready <= cursor + 1e-9);
      if (!ready.length) {
        cursor = Math.min(...pending.map((p) => out[p.item.id].ready));
        ready = pending.filter((p) => out[p.item.id].ready <= cursor + 1e-9);
      }
      chosen = ready.sort(byPlan)[0];
    }
    pending = pending.filter((p) => p !== chosen);
    const row = out[chosen.item.id];
    let start: number;
    let idle = 0;
    if (s.policy === "independent") {
      start = row.ready;
    } else {
      start = Math.max(row.ready, cursor);
      idle = Math.max(0, start - lastEnd);
    }
    const end = start + (chosen.item.duration ?? 0);
    row.actual_start = start;
    row.actual_end = end;
    row.wait = start - row.ready;
    row.idle_before = idle;
    if (s.policy === "independent") {
      lastEnd = Math.max(lastEnd, end);
    } else {
      cursor = lastEnd = end;
    }
    order.push(chosen.item.id);
    const frozen = s.frozen[chosen.item.id];
    if (frozen) {
      row.actual_start = frozen.actual_start;
      row.actual_end = frozen.actual_end;
      row.wait = Math.max(0, frozen.actual_start - row.ready);
      row.idle_before = 0;
    }
  }
  for (const [id, row] of Object.entries(out)) if (!row.present) order.push(id);
  // Measure the end the viewer sees: items held by a deferred EXPAND have not moved yet.
  const ends = Object.values(out).filter((r) => r.present).map((r) => r.actual_end!);
  const visibleEnd = ends.length ? Math.max(...ends) : s.resource_available_at ?? s.axis.start;
  return { rows: out, order, lastEnd: visibleEnd, overrun: s.deadline != null ? Math.max(0, visibleEnd - s.deadline) : 0 };
};

const findItem = (s: RailState, id: string) => s.items.find((i) => String(i.id) === String(id));

export const applyRailEvent = (state: RailState, ev: VisualEvent): RailState => {
  const s = clone(state);
  const params = ev.params ?? {};
  const target = String(ev.target ?? "");
  switch (ev.operation) {
    case "ADD": {
      const item = { id: target, present: true, ready_offset: 0, ...(params.item ?? {}) } as RailItem;
      const existing = findItem(s, item.id);
      if (existing) Object.assign(existing, item);
      else s.items.push(item);
      break;
    }
    case "REMOVE": {
      const item = findItem(s, target);
      if (item) item.present = false;
      delete s.frozen[target];
      break;
    }
    case "EXPAND": {
      const before = railSchedule(s).rows;
      const item = findItem(s, target);
      if (!item) break;
      item.duration = params.to != null ? Number(params.to) : (item.duration ?? 0) + Number(params.by ?? 0);
      if ((params.propagate ?? "immediate") === "deferred") {
        const targetStart = before[target].planned_start;
        for (const [id, row] of Object.entries(before)) {
          if (row.present && row.planned_start > targetStart && !s.frozen[id]) {
            s.frozen[id] = { actual_start: row.actual_start!, actual_end: row.actual_end! };
          }
        }
      }
      break;
    }
    case "SHIFT": {
      if (target === "slot_interval") {
        s.slot_interval = Number(params.interval);
      } else if (target === "view") {
        for (const key of ["start", "end", "tick"] as const) {
          if (key in params) (s.axis as any)[key] = params[key];
        }
        if ("deadline" in params) s.deadline = params.deadline;
        if ("show_planned" in params) s.show_planned = Boolean(params.show_planned);
        if ("show_actual" in params) s.show_actual = Boolean(params.show_actual);
      } else {
        const item = findItem(s, target);
        if (!item) break;
        if (params.ready_by != null) {
          item.ready_offset = (item.ready_offset ?? 0) + Number(params.ready_by);
        } else {
          item.planned_start = plannedStart(s, item) + Number(params.by ?? 0);
        }
      }
      break;
    }
    case "PROPAGATE": {
      if (target === "" || target === "all") {
        s.frozen = {};
      } else {
        const item = findItem(s, target);
        const start = item ? plannedStart(s, item) : -Infinity;
        for (const id of Object.keys(s.frozen)) {
          const other = findItem(s, id);
          if (other && plannedStart(s, other) > start) delete s.frozen[id];
        }
      }
      break;
    }
    case "MEASURE": {
      if (params.clear) {
        s.measures = [];
      } else {
        const metric = params.metric ?? "wait";
        if (params.exclusive) s.measures = [];
        s.measures = s.measures.filter((m) => !(m.target === target && m.metric === metric));
        s.measures.push({ target, metric, label: params.label ?? null });
      }
      break;
    }
  }
  return s;
};

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export type RailElement = {
  key: string;
  kind: "tick" | "rail" | "planned" | "link" | "block" | "wait" | "idle" | "deadline" | "overrun" | "measure" | "railLabel";
  x: number;
  y: number;
  w: number;
  h: number;
  opacity: number;
  label?: string;
  struck?: boolean;
  below?: boolean;
};

export type RailBox = { x: number; y: number; w: number; h: number };

const formatValue = (v: number, axis: RailState["axis"]) => {
  if (axis.format === "clock") {
    const h = Math.floor(v / 60);
    const m = Math.round(v - h * 60);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  }
  const rounded = Math.round(v * 100) / 100;
  return `${rounded}${axis.unit_suffix ?? ""}`;
};

export const railLayout = (s: RailState, box: RailBox, labels: Record<string, string> = {}): RailElement[] => {
  const L = { planned: "Plan", actual: "Actual", wait: "wait", idle: "idle", overrun: "overrun", deadline: "Deadline", duration: "", ...labels };
  const suffix = labels.unit_suffix ?? s.axis.unit_suffix ?? "";
  const amount = (v: number) => `${Math.round(v * 10) / 10}${suffix}`;
  const { start: a0, end: a1 } = s.axis;
  const labelW = Math.min(150, box.w * 0.14);
  const x0 = box.x + labelW;
  const scale = (box.w - labelW) / Math.max(1e-6, a1 - a0);
  const X = (v: number) => x0 + (v - a0) * scale;
  const unit = box.h / 10;
  const yTicks = box.y + unit * 0.3;
  const yPlanned = box.y + unit * 1.5;
  const yActual = box.y + unit * 4.6;
  const yWait = box.y + unit * 6.8;
  const plannedH = unit * 1.15;
  const blockH = unit * 1.6;
  const waitH = unit * 0.42;
  const laneGap = unit * 0.62;
  const charW = unit * 0.62;
  const sched = railSchedule(s);
  const out: RailElement[] = [];
  const showA = s.show_actual ? 1 : 0;
  const showP = s.show_planned ? 1 : 0;

  // Wait bars that overlap in time go on separate lanes.
  const laneEnds: number[] = [];
  const waitLane: Record<string, number> = {};
  for (const id of [...sched.order].sort((a, b) => sched.rows[a].ready - sched.rows[b].ready)) {
    const row = sched.rows[id];
    if (!row.present || (row.wait ?? 0) <= 1e-6) continue;
    let lane = laneEnds.findIndex((end) => end <= row.ready + 1e-6);
    if (lane < 0) {
      lane = laneEnds.length;
      laneEnds.push(0);
    }
    laneEnds[lane] = row.actual_start!;
    waitLane[id] = lane;
  }
  const laneCount = Math.max(1, laneEnds.length);
  const yBelow = yWait + (laneCount - 1) * laneGap + waitH + unit * 0.35;

  let tick = s.axis.tick ?? (a1 - a0) / 6;
  while (tick * scale < unit * 1.25) tick *= 2;
  for (let v = Math.ceil(a0 / tick - 1e-9) * tick; v <= a1 + 1e-6; v += tick) {
    out.push({ key: `tick-${Math.round(v * 1000)}`, kind: "tick", x: X(v), y: yTicks, w: 1, h: yWait + waitH - yTicks, opacity: 1, label: formatValue(v, s.axis) });
  }
  out.push({ key: "rail-planned", kind: "rail", x: x0, y: yPlanned + plannedH / 2, w: box.w - labelW, h: 2, opacity: showP });
  out.push({ key: "rail-actual", kind: "rail", x: x0, y: yActual + blockH / 2, w: box.w - labelW, h: 2, opacity: showA });
  out.push({ key: "label-planned", kind: "railLabel", x: box.x, y: yPlanned, w: labelW - 16, h: plannedH, opacity: showP, label: L.planned });
  out.push({ key: "label-actual", kind: "railLabel", x: box.x, y: yActual, w: labelW - 16, h: blockH, opacity: showA, label: L.actual });

  const plannedStarts = Object.values(sched.rows).map((r) => r.planned_start).sort((a, b) => a - b);
  for (const id of sched.order) {
    const row = sched.rows[id];
    const item = findItem(s, id)!;
    const nextPlanned = plannedStarts.find((v) => v > row.planned_start + 1e-6);
    const own = item.duration > 0 ? item.duration : s.slot_interval;
    const span = Math.min(s.policy === "independent" ? own : s.slot_interval, nextPlanned != null ? nextPlanned - row.planned_start : own);
    out.push({
      key: `planned-${id}`, kind: "planned", x: X(row.planned_start) + 3, y: yPlanned, w: Math.max(6, span * scale - 8), h: plannedH,
      opacity: showP * (row.present ? 1 : 0.35), label: item.label ?? formatValue(row.planned_start, s.axis), struck: !row.present,
    });
    if (!row.present) {
      out.push({ key: `block-${id}`, kind: "block", x: X(row.planned_start), y: yActual, w: 0, h: blockH, opacity: 0 });
      out.push({ key: `wait-${id}`, kind: "wait", x: X(row.ready), y: yWait, w: 0, h: waitH, opacity: 0 });
      out.push({ key: `idle-${id}`, kind: "idle", x: X(row.planned_start), y: yActual, w: 0, h: blockH, opacity: 0 });
      out.push({ key: `link-${id}`, kind: "link", x: X(row.planned_start), y: yPlanned + plannedH, w: 0, h: yActual - yPlanned - plannedH, opacity: 0 });
      continue;
    }
    const start = row.actual_start!;
    const dur = row.actual_end! - start;
    const idle = row.idle_before ?? 0;
    const durLabel = amount(dur);
    out.push({ key: `idle-${id}`, kind: "idle", x: X(start - idle), y: yActual, w: idle * scale, h: blockH, opacity: showA * (idle > 1e-6 ? 1 : 0) });
    out.push({
      key: `block-${id}`, kind: "block", x: X(start), y: yActual, w: dur * scale, h: blockH,
      // Items held by a deferred EXPAND are drawn translucent: they have not moved to their consequence yet.
      opacity: showA * (dur > 0 ? 1 : 0) * (s.frozen[id] ? 0.45 : 1), label: dur * scale > durLabel.length * unit * 0.45 + 12 ? durLabel : undefined,
    });
    out.push({
      key: `link-${id}`, kind: "link", x: X(row.planned_start) + 3, y: yPlanned + plannedH, w: X(start) - X(row.planned_start) - 3,
      h: yActual - yPlanned - plannedH, opacity: showA * showP * 0.6,
    });
    const wait = row.wait ?? 0;
    out.push({
      key: `wait-${id}`, kind: "wait", x: X(row.ready), y: yWait + (waitLane[id] ?? 0) * laneGap, w: Math.max(0, wait * scale), h: waitH,
      opacity: showA * (wait > 1e-6 ? 1 : 0),
    });
  }

  const deadline = s.deadline;
  out.push({ key: "deadline", kind: "deadline", x: deadline != null ? X(deadline) : X(a1), y: yTicks + unit * 0.9, w: 3, h: yBelow - yTicks - unit * 0.9, opacity: deadline != null ? 1 : 0, label: L.deadline });
  const over = sched.overrun;
  out.push({ key: "overrun", kind: "overrun", x: deadline != null ? X(deadline) : X(a1), y: yActual - unit * 0.25, w: over * scale, h: blockH + unit * 0.5, opacity: showA * (over > 1e-6 ? 1 : 0) });

  // Measurements: wait brackets hang below the wait lanes, the rest sit above the
  // actual rail. Labels that would collide step down (below) or up (above).
  const taken: { below: boolean; level: number; x0: number; x1: number }[] = [];
  for (const m of s.measures) {
    const row = sched.rows[m.target];
    let from = 0, to = 0, value = 0, word = "", below = false;
    if (m.metric === "overrun") {
      if (deadline == null) continue;
      from = deadline; to = sched.lastEnd; value = over; word = L.overrun;
    } else if (row && row.present) {
      if (m.metric === "wait") { from = row.ready; to = row.actual_start!; value = row.wait ?? 0; word = L.wait; below = true; }
      else if (m.metric === "idle_before") { from = row.actual_start! - (row.idle_before ?? 0); to = row.actual_start!; value = row.idle_before ?? 0; word = L.idle; }
      else { from = row.actual_start!; to = row.actual_end!; value = to - from; word = L.duration; }
    } else {
      continue;
    }
    const text = m.label ?? `${amount(value)}${word ? ` ${word}` : ""}`;
    const w = Math.max(2, (to - from) * scale);
    const mid = X(from) + w / 2;
    const half = Math.max(w, text.length * charW) / 2 + unit * 0.2;
    let level = 0;
    while (taken.some((t) => t.below === below && t.level === level && t.x0 < mid + half && mid - half < t.x1)) level += 1;
    taken.push({ below, level, x0: mid - half, x1: mid + half });
    const y = below ? yBelow + level * unit * 1.25 : yActual - unit * 0.35 - level * unit * 1.25;
    out.push({ key: `measure-${m.target}-${m.metric}`, kind: "measure", x: X(from), y, w, h: unit * 0.9, opacity: 1, label: text, below });
  }
  return out;
};

// ---------------------------------------------------------------------------
// Time -> layout
// ---------------------------------------------------------------------------

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const blend = (prev: RailElement[], next: RailElement[], t: number): RailElement[] => {
  const byKey = new Map(prev.map((e) => [e.key, e]));
  const out: RailElement[] = [];
  const seen = new Set<string>();
  for (const n of next) {
    const p = byKey.get(n.key);
    seen.add(n.key);
    if (!p) {
      out.push({ ...n, opacity: n.opacity * t });
      continue;
    }
    out.push({
      ...n,
      x: lerp(p.x, n.x, t), y: lerp(p.y, n.y, t), w: lerp(p.w, n.w, t), h: lerp(p.h, n.h, t),
      opacity: lerp(p.opacity, n.opacity, t),
      label: t < 0.5 && p.label !== undefined ? p.label : n.label,
    });
  }
  for (const p of prev) if (!seen.has(p.key)) out.push({ ...p, opacity: p.opacity * (1 - t) });
  return out;
};

export const railLayoutAtTime = (
  model: VisualModelDef,
  events: VisualEvent[],
  timeSeconds: number,
  box: RailBox,
): { elements: RailElement[]; activeEventId: string | null } => {
  const mine = events.filter((e) => e.model_id === model.id).sort((a, b) => a.time_seconds - b.time_seconds);
  let state = initialRailState(model);
  for (const ev of mine) {
    if (ev.time_seconds > timeSeconds) break;
    const next = applyRailEvent(state, ev);
    const progress = (timeSeconds - ev.time_seconds) / Math.max(0.001, ev.duration_seconds);
    if (progress < 1) {
      return {
        elements: blend(railLayout(state, box, model.labels), railLayout(next, box, model.labels), easeInOut(Math.max(0, progress))),
        activeEventId: ev.id,
      };
    }
    state = next;
  }
  return { elements: railLayout(state, box, model.labels), activeEventId: null };
};

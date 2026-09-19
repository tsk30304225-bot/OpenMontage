/**
 * Element models: any visual model type without a dedicated reducer
 * (flow_network, quantity_stack, comparison_split, ...).
 *
 * Mirrors lib/visual_direction.py (element_initial_state / apply_element_event);
 * a parity test runs both. Elements start hidden unless declared visible, so a
 * final state cannot be on screen before the beat that reveals it.
 */

export type DirectionEvent = {
  id: string;
  beat_id?: string;
  scene_id?: string;
  model_id: string;
  operation: "ADD" | "REMOVE" | "REVEAL" | "CONNECT" | "EXPAND" | "SHIFT" | "PROPAGATE" | "MEASURE";
  target: string;
  params?: Record<string, any>;
  time_seconds: number;
  duration_seconds: number;
};

export type ModelElement = {
  id: string;
  kind: string;
  label?: string;
  visible: boolean;
  from?: string;
  to?: string;
  attrs: Record<string, any>;
};

export type ElementMeasure = { target: string; metric: string; label?: string | null; value?: unknown };

export type ElementState = {
  elements: Record<string, ModelElement>;
  order: string[];
  measures: ElementMeasure[];
  active: string[];
  view: Record<string, any>;
};

export type ElementModelDef = {
  id: string;
  type: string;
  renderer?: "generic" | "bespoke";
  initial_state: { elements?: Partial<ModelElement>[]; view?: Record<string, any> };
  [key: string]: unknown;
};

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

export const elementInitialState = (model: ElementModelDef): ElementState => {
  const elements: Record<string, ModelElement> = {};
  const order: string[] = [];
  for (const raw of model.initial_state?.elements ?? []) {
    const el = { kind: "node", visible: false, attrs: {}, ...clone(raw) } as ModelElement;
    el.id = String(el.id);
    elements[el.id] = el;
    order.push(el.id);
  }
  return { elements, order, measures: [], active: [], view: { ...(model.initial_state?.view ?? {}) } };
};

const need = (s: ElementState, id: string): ModelElement => {
  const el = s.elements[id];
  if (!el) throw new Error(`model has no element ${id}`);
  return el;
};

export const applyElementEvent = (state: ElementState, ev: DirectionEvent): ElementState => {
  const s = clone(state);
  const params = ev.params ?? {};
  const target = String(ev.target ?? "");
  switch (ev.operation) {
    case "ADD":
    case "CONNECT": {
      const spec: any = { ...(params.element ?? {}) };
      if (ev.operation === "CONNECT") {
        spec.kind = spec.kind ?? "edge";
        for (const key of ["from", "to", "label"]) if (key in params) spec[key] = params[key];
      }
      spec.id = target;
      spec.kind = spec.kind ?? "node";
      spec.attrs = spec.attrs ?? {};
      spec.visible = spec.visible ?? true;
      if (s.elements[target]) Object.assign(s.elements[target], spec);
      else {
        s.elements[target] = spec as ModelElement;
        s.order.push(target);
      }
      break;
    }
    case "REVEAL": {
      const el = need(s, target);
      el.visible = true;
      Object.assign(el.attrs, params.attrs ?? {});
      break;
    }
    case "REMOVE":
      need(s, target).visible = false;
      break;
    case "EXPAND": {
      const el = need(s, target);
      const attr = params.attr ?? "value";
      const current = Number(el.attrs[attr] ?? 0);
      el.attrs[attr] = params.to != null ? Number(params.to) : current + Number(params.by ?? 0);
      break;
    }
    case "SHIFT":
      if (target === "view") Object.assign(s.view, params);
      else Object.assign(need(s, target).attrs, params.attrs ?? params);
      break;
    case "PROPAGATE": {
      const path = [target, ...((params.path ?? []) as string[]).map(String)];
      for (const id of path) {
        if (!s.elements[id]) continue;
        s.elements[id].attrs.active = true;
        if (!s.active.includes(id)) s.active.push(id);
      }
      break;
    }
    case "MEASURE": {
      if (params.clear) {
        s.measures = [];
      } else {
        const metric = params.metric ?? "value";
        if (params.exclusive) s.measures = [];
        s.measures = s.measures.filter((m) => !(m.target === target && m.metric === metric));
        s.measures.push({ target, metric, label: params.label ?? null, value: params.value ?? null });
      }
      break;
    }
  }
  return s;
};

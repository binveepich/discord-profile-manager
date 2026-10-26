export const DEFAULT_PREFERENCES = {
  theme: "dark",
  reduce_motion: false,
  visible_columns: ["account", "environment", "last_opened"],
};

const STORAGE_KEY = "dpm.ui-preferences.v1";
const THEMES = new Set(["light", "dark"]);
const COLUMNS = new Set(["account", "environment", "last_opened"]);

function normalize(value = {}) {
  const input = value && typeof value === "object" ? value : {};
  const visible = Array.isArray(input.visible_columns)
    ? [...new Set(input.visible_columns.filter((column) => COLUMNS.has(column)))]
    : DEFAULT_PREFERENCES.visible_columns;
  return {
    theme: THEMES.has(input.theme) ? input.theme : DEFAULT_PREFERENCES.theme,
    reduce_motion: Boolean(input.reduce_motion),
    visible_columns: visible,
  };
}

export function readLocalPreferences() {
  try {
    return normalize(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}"));
  } catch {
    return { ...DEFAULT_PREFERENCES, visible_columns: [...DEFAULT_PREFERENCES.visible_columns] };
  }
}

export function readLocalReduceMotionExplicit() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
    if (!stored || typeof stored !== "object") return null;
    if (Object.hasOwn(stored, "reduce_motion_explicit")) {
      return typeof stored.reduce_motion_explicit === "boolean" ? stored.reduce_motion_explicit : null;
    }
    // Older releases always saved `false` by default, so only a legacy `true`
    // is unambiguously an explicit choice.
    return stored.reduce_motion === true ? true : null;
  } catch {
    return null;
  }
}

export function writeLocalPreferences(value, reduceMotionExplicit = readLocalReduceMotionExplicit()) {
  const next = normalize(value);
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
      ...next,
      reduce_motion_explicit: typeof reduceMotionExplicit === "boolean" ? reduceMotionExplicit : null,
    }));
  } catch {
    // The backend preference store remains authoritative when browser storage
    // is disabled by the host webview.
  }
  return next;
}

export function normalizePreferences(value) {
  return normalize(value);
}

// Saved backend preferences over the local copy. A local explicit reduce-motion choice keeps priority over the saved one.
export function mergeSavedPreferences(current, saved, localChoice) {
  return normalize({
    ...current,
    ...saved,
    reduce_motion: localChoice === null && saved.reduce_motion !== true ? current.reduce_motion : saved.reduce_motion,
  });
}

export function resolveReduceMotionPreference(explicitChoice, osPreference) {
  return typeof explicitChoice === "boolean" ? explicitChoice : Boolean(osPreference);
}

export function applyReduceMotionAttribute(root, isReduced) {
  if (!root?.dataset) return;
  const value = Boolean(isReduced);
  root.dataset.reduceMotion = String(value);
  root.dataset.motion = value ? "reduced" : "full";
}

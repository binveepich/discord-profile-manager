export const DEFAULT_PREFERENCES = {
  theme: "system",
  density: "comfortable",
  reduce_motion: false,
  sidebar_collapsed: false,
  visible_columns: ["account", "environment", "status", "last_opened"],
};

const STORAGE_KEY = "dpm.ui-preferences.v1";
const THEMES = new Set(["light", "dark", "system"]);
const DENSITIES = new Set(["comfortable", "compact"]);
const COLUMNS = new Set(["account", "environment", "status", "last_opened"]);

function normalize(value = {}) {
  const input = value && typeof value === "object" ? value : {};
  const visible = Array.isArray(input.visible_columns)
    ? input.visible_columns.filter((column) => COLUMNS.has(column))
    : DEFAULT_PREFERENCES.visible_columns;
  return {
    theme: THEMES.has(input.theme) ? input.theme : DEFAULT_PREFERENCES.theme,
    density: DENSITIES.has(input.density) ? input.density : DEFAULT_PREFERENCES.density,
    reduce_motion: Boolean(input.reduce_motion),
    sidebar_collapsed: Boolean(input.sidebar_collapsed),
    visible_columns: visible.length ? [...new Set(visible)] : DEFAULT_PREFERENCES.visible_columns,
  };
}

export function readLocalPreferences() {
  try {
    return normalize(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}"));
  } catch {
    return { ...DEFAULT_PREFERENCES, visible_columns: [...DEFAULT_PREFERENCES.visible_columns] };
  }
}

export function writeLocalPreferences(value) {
  const next = normalize(value);
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // The backend preference store remains authoritative when browser storage
    // is disabled by the host webview.
  }
  return next;
}

export function resolveTheme(theme) {
  if (theme !== "system") return theme;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function normalizePreferences(value) {
  return normalize(value);
}

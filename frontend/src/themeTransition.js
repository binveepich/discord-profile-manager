import { easings } from "./motion.js";

// Theme switch for a user click. The app root blurs and shrinks, the colors change while it is blurred, then it settles
// back to normal. Only the app root is animated; dialogs and toasts are rendered outside it so their fixed position holds.

export const THEME_SWAP_CLASS = "theme-swap";

export const THEME_SWITCH_TIMING = Object.freeze({
  blurOutMs: 220,
  shrinkMs: 140,
  blurInMs: 240,
  blurPx: 6,
  shrinkScale: 0.96,
  // Extra time past the nominal end before the switch is forced to finish, because hidden windows can stall animations.
  safetyMs: 120,
});

const browserSchedule = {
  setTimeout: (callback, ms) => globalThis.setTimeout(callback, ms),
  clearTimeout: (id) => globalThis.clearTimeout(id),
  requestAnimationFrame: (callback) => globalThis.requestAnimationFrame(callback),
};

// `request` is for user clicks and animates unless reduced motion is on. `sync` is for saved or startup preferences and
// applies at once. `commit(theme)` writes the theme to the document and React state. `flushCommit` runs the swap's write
// synchronously, so React's DOM update lands before the swap class is removed and cannot animate afterwards.
export function createThemeTransition({
  getStage,
  root,
  commit,
  flushCommit = (update) => update(),
  schedule = browserSchedule,
  timing = THEME_SWITCH_TIMING,
  isReducedMotion = () => root?.dataset?.reduceMotion === "true",
}) {
  let applied = null;
  let desired = null;
  let running = null;

  function applyNow(theme) {
    applied = theme;
    commit(theme);
  }

  function swap(token) {
    token.swapped = true;
    applied = token.theme;
    root.classList.add(THEME_SWAP_CLASS);
    flushCommit(() => commit(token.theme));
    // Forcing layout computes the new colors while transitions are off. Removing the class first would let them animate.
    void token.stage.offsetHeight;
    schedule.requestAnimationFrame(() => root.classList.remove(THEME_SWAP_CLASS));
  }

  function settle(token) {
    if (running !== token) return;
    running = null;
    schedule.clearTimeout(token.timer);
    if (!token.swapped) swap(token);
    for (const animation of token.animations) animation.cancel();
    token.stage.style.willChange = "";
    root.classList.remove(THEME_SWAP_CLASS);
    // A click that arrived during this switch was saved as `desired`; it runs now.
    if (desired !== applied) request(desired);
  }

  function advance(token) {
    if (running !== token) return;
    swap(token);
    const inward = token.stage.animate(
      [
        { filter: `blur(${timing.blurPx}px)`, transform: `scale(${timing.shrinkScale})` },
        { filter: "blur(0px)", transform: "scale(1)" },
      ],
      { duration: timing.blurInMs, easing: easings.standard },
    );
    // Phase 1 holds its end values until here. The new animation starts from those same values, so cancelling phase 1
    // after creating it cannot show a frame without the blur.
    for (const animation of token.animations) animation.cancel();
    token.animations = [inward];
    inward.finished.then(() => settle(token), () => {});
  }

  function start(theme, stage) {
    const token = { theme, stage, swapped: false, animations: [], timer: null };
    running = token;
    stage.style.willChange = "filter, transform";
    try {
      token.animations.push(stage.animate(
        [{ filter: "blur(0px)" }, { filter: `blur(${timing.blurPx}px)` }],
        { duration: timing.blurOutMs, easing: easings.exit, fill: "forwards" },
      ));
      token.animations.push(stage.animate(
        [{ transform: "scale(1)" }, { transform: `scale(${timing.shrinkScale})` }],
        { duration: timing.shrinkMs, delay: timing.blurOutMs - timing.shrinkMs, easing: easings.exit, fill: "forwards" },
      ));
    } catch {
      for (const animation of token.animations) animation.cancel();
      stage.style.willChange = "";
      running = null;
      applyNow(theme);
      return;
    }
    token.timer = schedule.setTimeout(() => settle(token), timing.blurOutMs + timing.blurInMs + timing.safetyMs);
    Promise.all(token.animations.map((animation) => animation.finished)).then(() => advance(token), () => {});
  }

  function request(theme) {
    desired = theme;
    if (running || applied === theme) return;
    const stage = getStage();
    if (applied === null || isReducedMotion() || typeof stage?.animate !== "function") {
      applyNow(theme);
      return;
    }
    start(theme, stage);
  }

  function sync(theme) {
    if (running) return;
    desired = theme;
    if (applied !== theme) applyNow(theme);
  }

  return {
    request,
    sync,
    isRunning: () => running !== null,
    appliedTheme: () => applied,
  };
}

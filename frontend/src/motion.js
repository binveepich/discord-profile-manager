export const durations = Object.freeze({
  instant: 80,
  micro: 120,
  fast: 150,
  navigation: 180,
  normal: 220,
  slow: 320,
  stagger: 40,
  spinner: 800,
  skeleton: 1400,
});

export const easings = Object.freeze({
  standard: "cubic-bezier(0.2, 0, 0, 1)",
  emphasized: "cubic-bezier(0.2, 0, 0, 1.2)",
  exit: "cubic-bezier(0.4, 0, 1, 1)",
  linear: "linear",
});

export const delays = Object.freeze({ tooltip: 420 });

export const reduced = Object.freeze({ duration: 0 });

export function exitMotionDuration() {
  return document.documentElement?.dataset.reduceMotion === "true" ? durations.instant : durations.fast;
}

import test from "node:test";
import assert from "node:assert/strict";
import { createThemeTransition, THEME_SWAP_CLASS, THEME_SWITCH_TIMING } from "../src/themeTransition.js";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const TOTAL_MS = THEME_SWITCH_TIMING.blurOutMs + THEME_SWITCH_TIMING.blurInMs;

function fakeRoot() {
  const classes = new Set();
  return {
    dataset: { reduceMotion: "false" },
    style: {},
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

// Mirrors the Web Animations API where it matters here: `cancel()` rejects `finished`, and a cancelled animation holds no value.
function fakeAnimation(keyframes, options) {
  let resolveFinished;
  let rejectFinished;
  const finished = new Promise((resolve, reject) => { resolveFinished = resolve; rejectFinished = reject; });
  finished.catch(() => {});
  return {
    keyframes,
    options,
    finished,
    cancelled: false,
    finish() { resolveFinished(); },
    cancel() {
      if (this.cancelled) return;
      this.cancelled = true;
      rejectFinished(new Error("AbortError"));
    },
  };
}

function fakeStage(root) {
  const stage = {
    style: { filter: "", transform: "", willChange: "" },
    animations: [],
    reflows: [],
    animate(keyframes, options) {
      const animation = fakeAnimation(keyframes, options);
      stage.animations.push(animation);
      return animation;
    },
    // Reading layout records whether the swap class was present, which is what keeps the new colors from animating.
    get offsetHeight() {
      stage.reflows.push(root.classList.contains(THEME_SWAP_CLASS));
      return 0;
    },
  };
  return stage;
}

function fakeSchedule() {
  let now = 0;
  let nextId = 1;
  const timers = new Map();
  const frames = [];
  return {
    setTimeout(callback, ms) {
      const id = nextId;
      nextId += 1;
      timers.set(id, { at: now + ms, callback });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    requestAnimationFrame(callback) { frames.push(callback); return frames.length; },
    runFrame() { frames.splice(0).forEach((callback) => callback()); },
    advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) {
        if (timers.has(id) && timer.at <= now) {
          timers.delete(id);
          timer.callback();
        }
      }
    },
    timerCount: () => timers.size,
  };
}

function setup({ reduceMotion = false, withAnimate = true } = {}) {
  const root = fakeRoot();
  root.dataset.reduceMotion = reduceMotion ? "true" : "false";
  const stage = fakeStage(root);
  if (!withAnimate) delete stage.animate;
  const schedule = fakeSchedule();
  const commits = [];
  const commit = (theme) => {
    commits.push({ theme, swapping: root.classList.contains(THEME_SWAP_CLASS) });
    root.dataset.theme = theme;
  };
  const transition = createThemeTransition({ getStage: () => stage, root, commit, schedule });
  return { root, stage, schedule, commits, transition };
}

// Ends the switch that started most recently: its blur and shrink first, then the reveal that the swap creates.
async function finishSwitch(stage) {
  const started = stage.animations.length;
  stage.animations.slice(started - 2).forEach((animation) => animation.finish());
  await tick();
  stage.animations[stage.animations.length - 1].finish();
  await tick();
}

const themes = (commits) => commits.map(({ theme }) => theme);

test("reduced motion applies the theme at once with no animation, timer, or swap class", () => {
  const { root, stage, schedule, commits, transition } = setup({ reduceMotion: true });
  transition.sync("dark");
  transition.request("light");
  assert.deepEqual(themes(commits), ["dark", "light"]);
  assert.equal(stage.animations.length, 0);
  assert.equal(schedule.timerCount(), 0);
  assert.equal(root.classList.contains(THEME_SWAP_CLASS), false);
  assert.equal(stage.style.willChange, "");
  assert.equal(transition.isRunning(), false);
});

test("turning reduced motion off again animates the next switch", () => {
  const { root, stage, commits, transition } = setup({ reduceMotion: true });
  transition.sync("dark");
  transition.request("light");
  root.dataset.reduceMotion = "false";
  transition.request("dark");
  assert.equal(transition.isRunning(), true);
  assert.equal(stage.animations.length, 2);
  assert.deepEqual(themes(commits), ["dark", "light"]);
});

test("a click starts the blur at once and changes the colors only at the swap point", async () => {
  const { root, stage, schedule, commits, transition } = setup();
  transition.sync("dark");
  transition.request("light");
  assert.equal(transition.isRunning(), true);
  assert.equal(stage.style.willChange, "filter, transform");
  assert.equal(stage.animations.length, 2);
  assert.deepEqual(stage.animations[0].keyframes, [{ filter: "blur(0px)" }, { filter: "blur(6px)" }]);
  assert.equal(stage.animations[0].options.duration, 220);
  assert.deepEqual(stage.animations[1].keyframes, [{ transform: "scale(1)" }, { transform: "scale(0.96)" }]);
  assert.equal(stage.animations[1].options.duration, 140);
  assert.equal(stage.animations[1].options.delay, 80, "the shrink covers the last 140 ms of the 220 ms blur");
  assert.deepEqual(themes(commits), ["dark"], "colors have not changed before the swap point");

  stage.animations[0].finish();
  stage.animations[1].finish();
  await tick();
  assert.deepEqual(themes(commits), ["dark", "light"]);
  assert.equal(commits[1].swapping, true, "the swap class is present while the colors change");
  assert.equal(stage.reflows.at(-1), true, "layout is read with the swap class present");
  assert.equal(root.classList.contains(THEME_SWAP_CLASS), true);
  assert.equal(stage.animations[2].options.duration, 240);
  assert.deepEqual(stage.animations[2].keyframes, [
    { filter: "blur(6px)", transform: "scale(0.96)" },
    { filter: "blur(0px)", transform: "scale(1)" },
  ]);

  schedule.runFrame();
  assert.equal(root.classList.contains(THEME_SWAP_CLASS), false, "the swap class is removed on the next frame");
  assert.equal(transition.appliedTheme(), "light");
});

test("the end state leaves no filter, transform, will-change or animation behind", async () => {
  const { root, stage, schedule, transition } = setup();
  transition.sync("dark");
  transition.request("light");
  await finishSwitch(stage);
  assert.equal(transition.isRunning(), false);
  assert.equal(stage.style.filter, "");
  assert.equal(stage.style.transform, "");
  assert.equal(stage.style.willChange, "");
  assert.ok(stage.animations.every((animation) => animation.cancelled), "every animation is cancelled, so none holds a value");
  assert.equal(schedule.timerCount(), 0, "the fallback timer is cleared");
  schedule.runFrame();
  assert.equal(root.classList.contains(THEME_SWAP_CLASS), false);
});

test("a click during a switch queues one more switch that runs after the current one ends", async () => {
  const { stage, commits, transition } = setup();
  transition.sync("dark");
  transition.request("light");
  transition.request("dark");
  assert.equal(stage.animations.length, 2, "no second switch starts while the first one runs");
  await finishSwitch(stage);
  assert.deepEqual(themes(commits), ["dark", "light"], "the queued switch has not reached its swap point yet");
  assert.equal(transition.isRunning(), true, "the queued switch starts once the first one ends");
  await finishSwitch(stage);
  assert.deepEqual(themes(commits), ["dark", "light", "dark"]);
  assert.equal(transition.isRunning(), false);
  assert.equal(transition.appliedTheme(), "dark");
});

test("several clicks during one switch keep only the latest choice", async () => {
  const { stage, commits, transition } = setup();
  transition.sync("dark");
  transition.request("light");
  transition.request("dark");
  transition.request("light");
  await finishSwitch(stage);
  assert.deepEqual(themes(commits), ["dark", "light"]);
  assert.equal(transition.isRunning(), false);
});

test("asking for the theme already shown does nothing", () => {
  const { stage, commits, transition } = setup();
  transition.sync("dark");
  transition.request("dark");
  assert.equal(stage.animations.length, 0);
  assert.deepEqual(themes(commits), ["dark"]);
});

test("saved preferences apply at once and do not interrupt a running switch", () => {
  const { stage, commits, transition } = setup();
  transition.sync("dark");
  assert.deepEqual(themes(commits), ["dark"]);
  transition.request("light");
  transition.sync("dark");
  assert.equal(commits.length, 1);
  assert.equal(stage.animations.length, 2);
});

test("a stalled switch is forced to finish after the timeout, and late animation events change nothing", async () => {
  const { root, stage, schedule, commits, transition } = setup();
  transition.sync("dark");
  transition.request("light");
  schedule.advance(TOTAL_MS + THEME_SWITCH_TIMING.safetyMs - 1);
  assert.equal(transition.isRunning(), true, "the fallback waits past the nominal end");
  schedule.advance(1);
  assert.deepEqual(themes(commits), ["dark", "light"]);
  assert.equal(transition.isRunning(), false);
  assert.equal(stage.style.willChange, "");
  assert.equal(stage.style.filter, "");
  assert.equal(stage.style.transform, "");
  assert.ok(stage.animations.every((animation) => animation.cancelled));
  assert.equal(root.classList.contains(THEME_SWAP_CLASS), false);
  stage.animations.forEach((animation) => animation.finish());
  await tick();
  assert.deepEqual(themes(commits), ["dark", "light"], "no second commit");
});

test("a stalled reveal is ended by the timeout after the colors have already changed", async () => {
  const { stage, schedule, commits, transition } = setup();
  transition.sync("dark");
  transition.request("light");
  stage.animations[0].finish();
  stage.animations[1].finish();
  await tick();
  assert.deepEqual(themes(commits), ["dark", "light"]);
  schedule.advance(TOTAL_MS + THEME_SWITCH_TIMING.safetyMs);
  assert.equal(transition.isRunning(), false);
  assert.equal(stage.style.willChange, "");
  assert.ok(stage.animations.every((animation) => animation.cancelled));
  assert.deepEqual(themes(commits), ["dark", "light"]);
});

test("browsers without the Web Animations API apply the theme at once", () => {
  const { root, schedule, commits, transition } = setup({ withAnimate: false });
  transition.sync("dark");
  transition.request("light");
  assert.deepEqual(themes(commits), ["dark", "light"]);
  assert.equal(schedule.timerCount(), 0);
  assert.equal(root.classList.contains(THEME_SWAP_CLASS), false);
});

test("an animation that throws falls back to an instant switch and leaves no will-change behind", () => {
  const { stage, commits, transition } = setup();
  stage.animate = () => { throw new Error("unsupported keyframes"); };
  transition.sync("dark");
  transition.request("light");
  assert.deepEqual(themes(commits), ["dark", "light"]);
  assert.equal(transition.isRunning(), false);
  assert.equal(stage.style.willChange, "");
});

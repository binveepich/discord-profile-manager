import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import postcss from "postcss";
import { durations } from "../src/motion.js";

const cssText = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const stylesheet = postcss.parse(cssText);

// Later rules win in the cascade, so the last declaration for each property is the effective value.
function declarations(selector) {
  const values = {};
  stylesheet.walkRules((rule) => {
    if (!rule.selectors.includes(selector)) return;
    rule.walkDecls((decl) => {
      values[decl.prop] = decl.important ? `${decl.value} !important` : decl.value;
    });
  });
  return values;
}

test("table row entrance does not hold its transform after finishing", () => {
  // Holding the final keyframe would override the inline reorder offset written by the FLIP effect.
  const { animation } = declarations(".profile-row-enter");
  assert.match(animation, /\bbackwards\b/);
  assert.doesNotMatch(animation, /\b(both|forwards)\b/);
});

test("progress fill animates transform rather than layout width", () => {
  const { transition } = declarations(".progress-value");
  assert.match(transition, /\btransform\b/);
  assert.doesNotMatch(transition, /\bwidth\b/);
});

test("reduced motion zeroes non-spinner animations and transitions", () => {
  const rule = declarations(':root[data-reduce-motion="true"] *:not(.spin-once)');
  assert.equal(rule["animation-duration"], "0ms !important");
  assert.equal(rule["transition-duration"], "0ms !important");
});

test("JS exit timers match the CSS duration tokens", () => {
  const root = declarations(":root");
  assert.equal(root["--motion-duration-fast"], `${durations.fast}ms`);
  assert.equal(root["--motion-duration-instant"], `${durations.instant}ms`);
  assert.match(declarations(".popup-exit").animation, /var\(--motion-duration-fast\)/);
});

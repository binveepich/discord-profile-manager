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

test("the splash sweep loops only while the app is loading", () => {
  assert.match(declarations('.startup-splash[data-phase="loading"] .startup-sweep').animation, /\binfinite\b/);
  assert.equal(declarations(".startup-sweep").animation, undefined);
});

test("reduced motion removes the sweep, and the static splash from index.html has none to remove", async () => {
  assert.equal(declarations(':root[data-reduce-motion="true"] .startup-sweep').display, "none");
  // index.html renders the placeholder before React sets the reduced-motion attribute, so it must not loop at all.
  const indexHtml = await readFile(new URL("../index.html", import.meta.url), "utf8");
  assert.doesNotMatch(indexHtml, /startup-sweep/);
});

test("the splash fades with the shared normal duration, and the gate waits for the same time", () => {
  assert.match(declarations(".startup-splash").transition, /var\(--motion-duration-normal\)/);
  assert.equal(declarations(":root")["--motion-duration-normal"], `${durations.normal}ms`);
  assert.equal(declarations('.startup-splash[data-phase="leaving"]').opacity, "0");
});

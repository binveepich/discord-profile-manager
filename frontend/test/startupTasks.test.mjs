import test from "node:test";
import assert from "node:assert/strict";
import { createStartupPlan, runStartup, summarizeStartupWarnings } from "../src/startupTasks.js";

// Builds a plan whose tasks record what ran. A spec may hang, throw synchronously, reject, or resolve with a value.
function fakePlan(phases) {
  const ran = [];
  const plan = phases.map((phase) => phase.map((spec) => ({
    id: spec.id,
    label: `label ${spec.id}`,
    critical: spec.critical,
    timeoutMs: spec.timeoutMs ?? 500,
    failure: `failed ${spec.id}`,
    run: () => {
      ran.push(spec.id);
      if (spec.hang) return new Promise(() => {});
      if (spec.throws) throw new Error(spec.throws);
      if (spec.reject) return Promise.reject(new Error(spec.reject));
      return Promise.resolve(spec.value ?? { id: spec.id });
    },
  })));
  return { plan, ran };
}

test("every task runs in phase order and the ready report keeps each value", async () => {
  const { plan, ran } = fakePlan([
    [{ id: "bridge", critical: true }],
    [{ id: "catalog", critical: true }],
    [{ id: "profiles", critical: true, value: [1, 2] }, { id: "preferences", critical: false, value: { theme: "light" } }],
  ]);
  const progress = [];
  const report = await runStartup(plan, { onProgress: (value) => progress.push(value) });

  assert.equal(report.status, "ready");
  assert.equal(report.failure, null);
  assert.deepEqual(ran, ["bridge", "catalog", "profiles", "preferences"]);
  assert.deepEqual(report.data.profiles, [1, 2]);
  assert.deepEqual(report.data.preferences, { theme: "light" });
  assert.deepEqual(report.warnings, []);
  assert.equal(progress.at(-1).completed, 4);
  assert.equal(progress.at(-1).total, 4);
});

test("a failed non-critical task still reaches the app and is reported as a warning", async () => {
  const { plan } = fakePlan([
    [{ id: "bridge", critical: true }],
    [{ id: "catalog", critical: true }],
    [{ id: "profiles", critical: true }, { id: "preferences", critical: false, reject: "preferences unreadable" }],
  ]);
  const issues = [];
  const report = await runStartup(plan, { onIssue: (issue) => issues.push(issue) });

  assert.equal(report.status, "ready");
  assert.equal(report.failure, null);
  assert.equal(report.data.preferences, undefined);
  assert.equal(report.warnings.length, 1);
  assert.equal(report.warnings[0].id, "preferences");
  assert.equal(report.warnings[0].message, "failed preferences");
  assert.equal(report.warnings[0].detail, "preferences unreadable");
  assert.deepEqual(issues.map((issue) => issue.id), ["preferences"]);
});

test("a failed critical task blocks, names the task, and skips the later phases", async () => {
  const { plan, ran } = fakePlan([
    [{ id: "bridge", critical: true }],
    [{ id: "catalog", critical: true, reject: "Cannot read application profile metadata." }],
    [{ id: "profiles", critical: true }],
  ]);
  const report = await runStartup(plan);

  assert.equal(report.status, "blocked");
  assert.equal(report.failure.id, "catalog");
  assert.equal(report.failure.critical, true);
  assert.equal(report.failure.message, "failed catalog");
  assert.equal(report.failure.detail, "Cannot read application profile metadata.");
  assert.equal(report.failure.timedOut, false);
  assert.deepEqual(ran, ["bridge", "catalog"]);
});

test("a critical task that never finishes times out and blocks", async () => {
  const { plan } = fakePlan([[{ id: "catalog", critical: true, hang: true, timeoutMs: 20 }]]);
  const started = Date.now();
  const report = await runStartup(plan);

  assert.equal(report.status, "blocked");
  assert.equal(report.failure.timedOut, true);
  assert.ok(Date.now() - started < 1000, "the timeout, not the hang, ends the step");
});

test("a non-critical task that never finishes is cut off as a warning and does not block", async () => {
  const { plan } = fakePlan([
    [{ id: "catalog", critical: true }],
    [{ id: "profiles", critical: true }, { id: "about", critical: false, hang: true, timeoutMs: 20 }],
  ]);
  const report = await runStartup(plan);

  assert.equal(report.status, "ready");
  assert.equal(report.warnings.length, 1);
  assert.equal(report.warnings[0].id, "about");
  assert.equal(report.warnings[0].timedOut, true);
});

test("a synchronous throw inside a task counts as that task failing", async () => {
  const { plan } = fakePlan([[{ id: "catalog", critical: true, throws: "boom" }]]);
  const report = await runStartup(plan);

  assert.equal(report.status, "blocked");
  assert.equal(report.failure.detail, "boom");
});

test("the overall limit ends the run even when a task still has time on its own timeout", async () => {
  const { plan } = fakePlan([[{ id: "catalog", critical: true, hang: true, timeoutMs: 5000 }]]);
  const started = Date.now();
  const report = await runStartup(plan, { maxMs: 40 });

  assert.equal(report.status, "blocked");
  assert.equal(report.failure.timedOut, true);
  assert.ok(Date.now() - started < 1000);
});

test("an advisory keeps its task successful and adds one warning", async () => {
  const plan = [[{
    id: "runtime",
    label: "label runtime",
    critical: false,
    timeoutMs: 500,
    failure: "failed runtime",
    run: () => ({ browser_available: false }),
    advisory: (value) => (value.browser_available ? null : "Chưa tìm thấy browser/chrome.exe."),
  }]];
  const report = await runStartup(plan);

  assert.equal(report.status, "ready");
  assert.equal(report.data.runtime.browser_available, false);
  assert.equal(report.warnings[0].message, "Chưa tìm thấy browser/chrome.exe.");
});

test("the real plan runs the catalog, table, and side reads in contract order", async () => {
  const calls = [];
  const plan = createStartupPlan({
    invoke: async (method, ...args) => {
      calls.push([method, ...args]);
      return method === "get_runtime_info" ? { browser_available: true } : {};
    },
    awaitBridge: async () => ({}),
  });
  const flat = plan.flat();

  assert.deepEqual(flat.filter((task) => task.critical).map((task) => task.id), ["bridge", "catalog", "profiles"]);
  assert.deepEqual(flat.filter((task) => !task.critical).map((task) => task.id), ["preferences", "runtime", "about"]);
  const report = await runStartup(plan);

  assert.equal(report.status, "ready");
  assert.deepEqual(calls, [
    ["initialize_catalog"],
    ["list_profiles", "", "stt", false],
    ["get_ui_preferences"],
    ["get_runtime_info"],
    ["get_about_info"],
  ]);
});

test("a bridge that never appears blocks on the bridge task", async () => {
  const plan = createStartupPlan({ invoke: async () => ({}), awaitBridge: async () => null });
  const report = await runStartup(plan);

  assert.equal(report.status, "blocked");
  assert.equal(report.failure.id, "bridge");
});

test("warning messages are joined into one line, and none gives null", () => {
  assert.equal(summarizeStartupWarnings([]), null);
  assert.equal(summarizeStartupWarnings([{ message: "A." }, { message: "B." }]), "A. B.");
});

import test from "node:test";
import assert from "node:assert/strict";

const listeners = new Map();
const activeTimers = new Set();
globalThis.window = {
  pywebview: null,
  addEventListener(name, callback, options = {}) {
    const entries = listeners.get(name) || new Map();
    entries.set(callback, { once: Boolean(options.once) });
    listeners.set(name, entries);
  },
  removeEventListener(name, callback) {
    listeners.get(name)?.delete(callback);
  },
  dispatch(name) {
    for (const [callback, options] of [...(listeners.get(name) || [])]) {
      callback();
      if (options.once) listeners.get(name)?.delete(callback);
    }
  },
  setTimeout(callback, delay) {
    const timer = setTimeout(callback, delay);
    activeTimers.add(timer);
    return timer;
  },
  clearTimeout(timer) {
    activeTimers.delete(timer);
    clearTimeout(timer);
  },
};

const bridge = await import("../src/api/bridge.js");

test("call reports bridge-not-ready distinctly before pywebview is attached", async () => {
  await assert.rejects(bridge.call("list_profiles"), {
    name: "BridgeNotReadyError",
    code: "BRIDGE_NOT_READY",
  });
});

test("a readiness event before React subscribes is handled immediately", () => {
  const api = { list_profiles: async () => [] };
  window.pywebview = { api };
  window.dispatch("pywebviewready");

  let received = null;
  bridge.onBridgeReady((readyApi) => { received = readyApi; });
  assert.equal(received, api);
  assert.equal(bridge.hasNativeBridge(), true);
});

test("a bridge becoming ready after subscription resolves once and clears its timer", async () => {
  window.pywebview = null;
  const lateBridge = await import("../src/api/bridge.js?event-after");
  const expectedApi = { list_profiles: async () => [{ profile_id: "profile_0001" }] };
  const readyPromise = lateBridge.waitForBridge(1000);
  assert.equal(activeTimers.size, 1);

  window.pywebview = { api: expectedApi };
  window.dispatch("pywebviewready");

  assert.equal(await readyPromise, expectedApi);
  assert.equal(activeTimers.size, 0);
});

test("backend rejections propagate unchanged through call", async () => {
  const backendError = new Error("fixture backend failure");
  window.pywebview = { api: { list_profiles: () => Promise.reject(backendError) } };
  const errorBridge = await import("../src/api/bridge.js?backend-error");
  await assert.rejects(errorBridge.call("list_profiles"), (error) => error === backendError);
});

test("unsubscribing before readiness prevents callbacks after unmount", async () => {
  window.pywebview = null;
  const cleanupBridge = await import("../src/api/bridge.js?cleanup");
  let calls = 0;
  const unsubscribe = cleanupBridge.onBridgeReady(() => { calls += 1; });
  unsubscribe();

  window.pywebview = { api: {} };
  window.dispatch("pywebviewready");
  assert.equal(calls, 0);
});

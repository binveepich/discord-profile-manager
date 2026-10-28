const waiters = new Set();
let nativeApi = null;

function attach() {
  const api = window.pywebview?.api || null;
  if (!api) return;
  nativeApi = api;
  for (const listener of [...waiters]) {
    waiters.delete(listener);
    listener(nativeApi);
  }
}

export class BridgeNotReadyError extends Error {
  constructor() {
    super("The desktop bridge is not ready yet.");
    this.name = "BridgeNotReadyError";
    this.code = "BRIDGE_NOT_READY";
  }
}

export class BridgeMethodUnavailableError extends Error {
  constructor(method) {
    super(`The desktop backend does not provide ${String(method)}.`);
    this.name = "BridgeMethodUnavailableError";
    this.code = "BRIDGE_METHOD_UNAVAILABLE";
  }
}

// The backend returns an expected refusal, such as a profile whose Chromium is open, as {ok: false, error}.
// Keep its code and profile so the UI can explain it. The message is unchanged, so other errors read as before.
export class ProfileActionError extends Error {
  constructor(failure) {
    super(String(failure?.message || "The desktop backend refused the request."));
    this.name = "ProfileActionError";
    this.code = String(failure?.code || "error");
    this.profile = failure?.profile || null;
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("pywebviewready", attach, { once: true });
  if (window.pywebview?.api) attach();
}

export function hasNativeBridge() {
  return Boolean(nativeApi || window.pywebview?.api);
}

export function waitForBridge(timeout = 2500) {
  if (hasNativeBridge()) return Promise.resolve(nativeApi || window.pywebview.api);
  return new Promise((resolve) => {
    let timer = null;
    let settled = false;
    const finish = (api) => {
      if (settled) return;
      settled = true;
      if (timer !== null) window.clearTimeout(timer);
      waiters.delete(onReady);
      resolve(api);
    };
    const onReady = (api) => finish(api);
    waiters.add(onReady);
    timer = window.setTimeout(() => finish(null), Math.max(0, timeout));
  });
}

export async function call(method, ...args) {
  const api = nativeApi || window.pywebview?.api;
  if (!api) throw new BridgeNotReadyError();
  if (typeof api[method] !== "function") throw new BridgeMethodUnavailableError(method);
  const result = await api[method](...args);
  if (result?.ok === false && result.error) throw new ProfileActionError(result.error);
  return result;
}

export function onBridgeReady(callback) {
  if (hasNativeBridge()) {
    callback(nativeApi || window.pywebview.api);
    return () => {};
  }
  waiters.add(callback);
  return () => waiters.delete(callback);
}

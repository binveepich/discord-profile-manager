const waiters = [];
let nativeApi = null;

function attach() {
  nativeApi = window.pywebview?.api || null;
  waiters.splice(0).forEach((resolve) => resolve(nativeApi));
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
    const timer = window.setTimeout(() => resolve(null), timeout);
    waiters.push((api) => {
      window.clearTimeout(timer);
      resolve(api);
    });
  });
}

export async function call(method, ...args) {
  const api = await waitForBridge();
  if (!api || typeof api[method] !== "function") {
    throw new Error("The desktop bridge is unavailable.");
  }
  return api[method](...args);
}

// Start-up plan for the loading splash. Phases run one after another and the tasks inside a phase run together.
// A failed critical task stops the start-up and blocks the app. A failed non-critical task only adds a warning.
// Every task has its own timeout, and the whole run is also cut off by an overall limit, so the splash always finishes.
import { BridgeNotReadyError, call, waitForBridge } from "./api/bridge.js";

export const STARTUP_MAX_MS = 25000;
const BRIDGE_TIMEOUT_MS = 10000;
const CATALOG_TIMEOUT_MS = 15000;
const SIDE_TIMEOUT_MS = 5000;

class StartupTimeoutError extends Error {
  constructor() {
    super("The start-up step timed out.");
    this.name = "StartupTimeoutError";
  }
}

// `invoke` and `awaitBridge` can be replaced, so the plan can run without the desktop bridge.
export function createStartupPlan({ invoke = call, awaitBridge = waitForBridge } = {}) {
  return [
    [
      {
        id: "bridge",
        label: "Đang kết nối với ứng dụng",
        critical: true,
        timeoutMs: BRIDGE_TIMEOUT_MS,
        failure: "Không kết nối được với phần xử lý phía sau.",
        run: async () => {
          if (!(await awaitBridge(BRIDGE_TIMEOUT_MS))) throw new BridgeNotReadyError();
        },
      },
    ],
    [
      {
        id: "catalog",
        label: "Đang kiểm tra danh sách hồ sơ",
        critical: true,
        timeoutMs: CATALOG_TIMEOUT_MS,
        failure: "Không đọc được danh sách hồ sơ.",
        run: () => invoke("initialize_catalog"),
      },
    ],
    [
      {
        id: "profiles",
        label: "Đang tải bảng hồ sơ",
        critical: true,
        timeoutMs: CATALOG_TIMEOUT_MS,
        failure: "Không tải được bảng hồ sơ.",
        run: () => invoke("list_profiles", "", "stt", false),
      },
      {
        id: "preferences",
        label: "Đang đọc tùy chọn giao diện",
        critical: false,
        timeoutMs: SIDE_TIMEOUT_MS,
        failure: "Không đọc được tùy chọn giao diện đã lưu.",
        run: () => invoke("get_ui_preferences"),
      },
      {
        id: "runtime",
        label: "Đang kiểm tra trình duyệt Chromium",
        critical: false,
        timeoutMs: SIDE_TIMEOUT_MS,
        failure: "Không kiểm tra được trình duyệt Chromium.",
        run: () => invoke("get_runtime_info"),
        advisory: (runtime) => {
          if (runtime?.browser_available) return null;
          return runtime?.browser_download_active
            ? "Đang tải Chromium tự động, có thể mất vài phút. Bạn vẫn có thể quản lý danh sách."
            : "Chưa tìm thấy browser/chrome.exe nên chưa thể mở hồ sơ. Bạn vẫn có thể quản lý danh sách.";
        },
      },
      {
        id: "about",
        label: "Đang chuẩn bị thông tin ứng dụng",
        critical: false,
        timeoutMs: SIDE_TIMEOUT_MS,
        failure: "Không chuẩn bị được thông tin ứng dụng.",
        run: () => invoke("get_about_info"),
      },
    ],
  ];
}

function describeError(error) {
  return String(error?.message || error || "").slice(0, 200);
}

// Resolves with the task's outcome and never rejects, so one task cannot break the others in its phase.
function runTask(task, limitMs) {
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new StartupTimeoutError()), Math.max(0, limitMs));
  });
  return Promise.race([Promise.resolve().then(() => task.run()), timeout])
    .then(
      (value) => ({ ok: true, value }),
      (error) => ({ ok: false, error, timedOut: error instanceof StartupTimeoutError }),
    )
    .finally(() => clearTimeout(timer));
}

// Runs the plan and reports the result. `onProgress` is called before each phase with { completed, total, current }.
// `onIssue` is called for every failed task and every advisory, so the caller can log it.
export async function runStartup(plan, {
  maxMs = STARTUP_MAX_MS,
  now = () => Date.now(),
  onProgress = () => {},
  onIssue = () => {},
} = {}) {
  const started = now();
  const total = plan.reduce((count, phase) => count + phase.length, 0);
  const data = {};
  const warnings = [];
  let completed = 0;
  let failure = null;

  for (const phase of plan) {
    const focus = phase.find((task) => task.critical) || phase[0];
    onProgress({ completed, total, current: focus.label });
    const remaining = maxMs - (now() - started);
    const outcomes = await Promise.all(phase.map((task) => runTask(task, Math.min(task.timeoutMs, remaining))));

    phase.forEach((task, index) => {
      const outcome = outcomes[index];
      completed += 1;
      if (outcome.ok) {
        data[task.id] = outcome.value;
        const advisory = task.advisory?.(outcome.value);
        if (advisory) {
          const issue = { id: task.id, critical: false, timedOut: false, message: advisory, detail: "" };
          warnings.push(issue);
          onIssue(issue);
        }
        return;
      }
      const issue = {
        id: task.id,
        critical: task.critical,
        timedOut: outcome.timedOut,
        message: task.failure,
        detail: outcome.timedOut ? "" : describeError(outcome.error),
      };
      onIssue(issue);
      if (task.critical) failure = failure || issue;
      else warnings.push(issue);
    });
    if (failure) break;
  }

  onProgress({ completed, total, current: "" });
  return { status: failure ? "blocked" : "ready", failure, data, warnings };
}

// One line for the toast that announces soft warnings after the app is shown. Null when there are none.
export function summarizeStartupWarnings(warnings) {
  const messages = warnings.map((issue) => issue.message).filter(Boolean);
  return messages.length ? messages.join(" ") : null;
}

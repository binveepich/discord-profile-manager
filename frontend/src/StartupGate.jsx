import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import App from "./App";
import StartupSplash from "./components/StartupSplash";
import { call, hasNativeBridge } from "./api/bridge";
import { durations } from "./motion";
import { createStartupPlan, runStartup, summarizeStartupWarnings } from "./startupTasks";

// Without the desktop bridge (the Vite dev server in a browser) there is nothing to load, so the demo table opens as before.
const SKIP_STARTUP = import.meta.env.DEV && !hasNativeBridge();
const LOADING = Object.freeze({
  phase: "loading",
  progress: Object.freeze({ completed: 0, total: 0, current: "" }),
  boot: null,
  failure: null,
});

// Every failed task is logged to the console and to the Python log. Reporting never holds up the splash.
function reportIssue(issue) {
  console.warn(`[startup] ${issue.id}: ${issue.message}${issue.detail ? ` (${issue.detail})` : ""}`);
  call("report_startup_warning", issue.id, issue.detail || issue.message).catch(() => {});
}

// Owns the start-up sequence. The app mounts behind the splash, so its first render happens while the splash is still
// shown. The splash fades out after the app reports that it has mounted.
export default function StartupGate() {
  const [state, setState] = useState(() => (SKIP_STARTUP ? { ...LOADING, phase: "app" } : LOADING));
  const [attempt, setAttempt] = useState(0);

  // The static splash from index.html hands over to this one. Both use the same markup, so nothing visibly changes.
  useLayoutEffect(() => {
    document.getElementById("boot-splash")?.remove();
  }, []);

  useEffect(() => {
    if (SKIP_STARTUP) return undefined;
    let active = true;
    runStartup(createStartupPlan(), {
      onProgress: (progress) => {
        if (active) setState((current) => (current.phase === "loading" ? { ...current, progress } : current));
      },
      onIssue: reportIssue,
    }).then((report) => {
      if (!active) return;
      if (report.status === "blocked") {
        setState({ ...LOADING, phase: "blocked", failure: report.failure });
        return;
      }
      setState({
        ...LOADING,
        phase: "mounting",
        boot: {
          profiles: report.data.profiles,
          preferences: report.data.preferences,
          runtime: report.data.runtime,
          about: report.data.about,
          notice: summarizeStartupWarnings(report.warnings),
        },
      });
    });
    return () => { active = false; };
  }, [attempt]);

  const handleMounted = useCallback(() => {
    setState((current) => (current.phase === "mounting" ? { ...current, phase: "leaving" } : current));
  }, []);

  useEffect(() => {
    if (state.phase !== "leaving") return undefined;
    const reduced = document.documentElement.dataset.reduceMotion === "true";
    const timer = window.setTimeout(
      () => setState((current) => ({ ...current, phase: "app" })),
      reduced ? 0 : durations.normal + 40,
    );
    return () => window.clearTimeout(timer);
  }, [state.phase]);

  const retry = useCallback(() => {
    setState(LOADING);
    setAttempt((value) => value + 1);
  }, []);

  const appMounted = state.phase === "mounting" || state.phase === "leaving" || state.phase === "app";
  return <>
    {appMounted && <App boot={state.boot} covered={state.phase === "mounting"} onMounted={handleMounted} />}
    {state.phase !== "app" && <StartupSplash phase={state.phase} progress={state.progress} failure={state.failure} onRetry={retry} />}
  </>;
}

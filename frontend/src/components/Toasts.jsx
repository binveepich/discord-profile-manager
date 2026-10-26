import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, X, XCircle } from "lucide-react";
import { exitMotionDuration } from "../motion";

const TONES = {
  success: { className: "toast-success", Icon: CheckCircle2 },
  error: { className: "toast-error", Icon: XCircle },
  warning: { className: "toast-warning", Icon: AlertTriangle },
};

function ToastItem({ item, onDismiss }) {
  const tone = TONES[item.type] || TONES.success;
  const [phase, setPhase] = useState("enter");
  const onDismissRef = useRef(onDismiss);
  const exitingRef = useRef(false);
  const remaining = useRef(4500);
  const startedAt = useRef(0);
  const dismissTimer = useRef(null);
  const exitTimer = useRef(null);
  onDismissRef.current = onDismiss;

  const beginExit = useCallback(() => {
    if (exitingRef.current) return;
    exitingRef.current = true;
    window.clearTimeout(dismissTimer.current);
    setPhase("exit");
    exitTimer.current = window.setTimeout(() => onDismissRef.current(item.id), exitMotionDuration());
  }, [item.id]);

  const startTimer = useCallback(() => {
    if (exitingRef.current || dismissTimer.current !== null) return;
    startedAt.current = Date.now();
    dismissTimer.current = window.setTimeout(beginExit, remaining.current);
  }, [beginExit]);

  const pauseTimer = useCallback(() => {
    if (dismissTimer.current === null || exitingRef.current) return;
    window.clearTimeout(dismissTimer.current);
    dismissTimer.current = null;
    remaining.current = Math.max(0, remaining.current - (Date.now() - startedAt.current));
  }, []);

  useEffect(() => {
    const enterFrame = window.requestAnimationFrame(() => {
      setPhase((current) => current === "enter" ? "open" : current);
    });
    startTimer();
    return () => {
      window.cancelAnimationFrame(enterFrame);
      window.clearTimeout(dismissTimer.current);
      window.clearTimeout(exitTimer.current);
    };
  }, [startTimer]);

  return <div
    className={`toast ${tone.className} toast-${phase}`}
    key={item.id}
    onMouseEnter={pauseTimer}
    onMouseLeave={startTimer}
  >
    <span className="toast-icon"><tone.Icon className="h-4 w-4" /></span>
    <p>{item.message}</p>
    <button onClick={beginExit} aria-label="Đóng thông báo"><X className="h-4 w-4" /></button>
  </div>;
}

export default function Toasts({ items, onDismiss }) {
  const slots = useRef(new Map());
  const previousTops = useRef(new Map());
  const animationFrames = useRef(new Set());

  // Slide the remaining toasts into their new positions when one is added or removed, instead of letting them jump.
  useLayoutEffect(() => {
    const reduceMotion = document.documentElement.dataset.reduceMotion === "true";
    const tops = new Map();
    const moved = [];
    items.forEach((item) => {
      const element = slots.current.get(item.id);
      if (!element) return;
      const top = element.getBoundingClientRect().top;
      const previousTop = previousTops.current.get(item.id);
      if (!reduceMotion && previousTop !== undefined && Math.abs(previousTop - top) > 1) moved.push({ element, offset: previousTop - top });
      tops.set(item.id, top);
    });
    previousTops.current = tops;
    if (!moved.length) return;
    moved.forEach(({ element, offset }) => {
      element.style.transition = "none";
      element.style.transform = `translateY(${offset}px)`;
    });
    moved[0].element.getBoundingClientRect();
    const frame = window.requestAnimationFrame(() => {
      moved.forEach(({ element }) => {
        element.style.transition = "";
        element.style.transform = "";
      });
      animationFrames.current.delete(frame);
    });
    animationFrames.current.add(frame);
  }, [items]);

  useLayoutEffect(() => () => {
    animationFrames.current.forEach((frame) => window.cancelAnimationFrame(frame));
  }, []);

  return <div className="toast-stack" aria-live="polite">{items.map((item) => <div className="toast-slot" key={item.id} ref={(element) => { if (element) slots.current.set(item.id, element); else slots.current.delete(item.id); }}><ToastItem item={item} onDismiss={onDismiss} /></div>)}</div>;
}

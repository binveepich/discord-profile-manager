import { useEffect, useState } from "react";
import { exitMotionDuration } from "./motion";

// Keeps a popup mounted while its exit animation plays. `closing` is true only during that window.
export default function usePresence(open) {
  const [previousOpen, setPreviousOpen] = useState(open);
  const [exiting, setExiting] = useState(false);

  // Adjusting state during render (not in an effect) means a close or reopen takes effect in the same commit, so nothing waits a frame.
  if (open !== previousOpen) {
    setPreviousOpen(open);
    setExiting(!open);
  }

  useEffect(() => {
    if (!exiting) return undefined;
    const timer = window.setTimeout(() => setExiting(false), exitMotionDuration());
    return () => window.clearTimeout(timer);
  }, [exiting]);

  return { mounted: open || exiting, closing: !open && exiting };
}

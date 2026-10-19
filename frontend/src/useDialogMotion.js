import { useCallback, useEffect, useRef, useState } from "react";
import { exitMotionDuration } from "./motion";

const FOCUSABLE = "button:not(:disabled), input:not(:disabled):not([type=hidden]), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])";

export default function useDialogMotion(onClose) {
  const [phase, setPhase] = useState("enter");
  const closingRef = useRef(false);
  const closeTimer = useRef(null);
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const returnFocusRef = useRef(null);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previousFocus = document.activeElement;
    returnFocusRef.current = previousFocus;
    const dialog = dialogRef.current;
    const firstControl = dialog?.querySelector(FOCUSABLE);
    (firstControl || dialog)?.focus();
    const enterFrame = window.requestAnimationFrame(() => {
      setPhase((current) => current === "enter" ? "open" : current);
    });

    const onKeyDown = (event) => {
      if (closingRef.current) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const controls = [...dialog.querySelectorAll(FOCUSABLE)];
      if (!controls.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.cancelAnimationFrame(enterFrame);
      window.clearTimeout(closeTimer.current);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  const closeDialog = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    setPhase("exit");
    if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
    closeTimer.current = window.setTimeout(() => onCloseRef.current(), exitMotionDuration());
  }, []);

  return {
    closeDialog,
    dialogRef,
    backdropClassName: `modal-backdrop modal-backdrop-${phase}`,
    dialogClassName: `dialog-${phase}`,
  };
}

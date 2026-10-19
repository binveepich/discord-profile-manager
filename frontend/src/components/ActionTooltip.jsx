import { cloneElement, useCallback, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export default function ActionTooltip({ label, children }) {
  const anchorRef = useRef(null);
  const tooltipRef = useRef(null);
  const tooltipId = useId();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [position, setPosition] = useState(null);
  const visible = hovered || focused;

  const updatePosition = useCallback(() => {
    const anchor = anchorRef.current;
    const tooltip = tooltipRef.current;
    if (!anchor || !tooltip) return;

    const rect = anchor.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      setHovered(false);
      setFocused(false);
      return;
    }

    const tooltipRect = tooltip.getBoundingClientRect();
    const margin = 8;
    const halfWidth = tooltipRect.width / 2;
    const left = Math.max(
      margin + halfWidth,
      Math.min(rect.left + rect.width / 2, window.innerWidth - margin - halfWidth),
    );
    let top = rect.bottom + margin;
    let side = "below";
    if (top + tooltipRect.height > window.innerHeight - margin && rect.top - tooltipRect.height - margin >= margin) {
      top = rect.top - tooltipRect.height - margin;
      side = "above";
    }
    top = Math.max(margin, Math.min(top, window.innerHeight - margin - tooltipRect.height));

    setPosition({ left, top, side });
  }, []);

  useLayoutEffect(() => {
    if (!visible) return undefined;
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [updatePosition, visible]);

  const child = cloneElement(children, {
    "aria-describedby": visible ? tooltipId : children.props["aria-describedby"],
  });

  return (
    <>
      <span
        className="action-tooltip-anchor"
        ref={anchorRef}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocusCapture={() => setFocused(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
        }}
      >
        {child}
      </span>
      {visible && createPortal(
        <span
          ref={tooltipRef}
          id={tooltipId}
          className="action-tooltip"
          role="tooltip"
          data-side={position?.side || "below"}
          style={{
            left: position?.left ?? 0,
            top: position?.top ?? 0,
            visibility: position ? "visible" : "hidden",
          }}
        >
          {label}
        </span>,
        document.body,
      )}
    </>
  );
}

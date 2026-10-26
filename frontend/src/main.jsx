import React from "react";
import { createRoot } from "react-dom/client";
import StartupGate from "./StartupGate";
import "./styles.css";
import { applyReduceMotionAttribute, readLocalReduceMotionExplicit, resolveReduceMotionPreference } from "./uiPreferences";

const reduceMotionMedia = window.matchMedia?.("(prefers-reduced-motion: reduce)");
applyReduceMotionAttribute(
  document.documentElement,
  resolveReduceMotionPreference(readLocalReduceMotionExplicit(), reduceMotionMedia?.matches),
);

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <StartupGate />
  </React.StrictMode>,
);

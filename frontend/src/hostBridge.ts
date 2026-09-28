import type { ModuleEvent } from "./types";

export function emitHostEvent(event: ModuleEvent, targetOrigin = "*") {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage(
      { source: "community-prediction", version: 1, ...event },
      targetOrigin,
    );
  }
  window.dispatchEvent(new CustomEvent("community-prediction:event", { detail: event }));
}


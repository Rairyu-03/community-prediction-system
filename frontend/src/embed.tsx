import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { CommunityPredictionModule, type CommunityPredictionModuleProps } from "./App";
import "./styles.css";

export { CommunityPredictionModule } from "./App";
export type { CommunityPredictionModuleProps } from "./App";

export function mountCommunityPredictionModule(
  element: HTMLElement,
  options: CommunityPredictionModuleProps = {},
): () => void {
  const root: Root = createRoot(element);
  root.render(<CommunityPredictionModule {...options} mode={options.mode || "embedded"} />);
  return () => root.unmount();
}


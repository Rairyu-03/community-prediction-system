import React from "react";
import ReactDOM from "react-dom/client";
import { CommunityPredictionModule } from "./App";

type StartupBoundaryState = { error: Error | null };

class StartupBoundary extends React.Component<{ children?: React.ReactNode }, StartupBoundaryState> {
  state: StartupBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): StartupBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    void fetch("/api/client-errors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: error.message, stack: `${error.stack || ""}\n${info.componentStack || ""}`, url: window.location.href }),
    }).catch(() => undefined);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <main style={{maxWidth:720,margin:"12vh auto",padding:32,fontFamily:"system-ui",border:"1px solid #cfe0e8",borderRadius:16,background:"#fff",color:"#12344d"}}>
      <h1>系统界面加载失败</h1><p>{this.state.error.message}</p>
      <button onClick={() => window.location.replace(`${window.location.pathname}?refresh=${Date.now()}`)}>重新加载</button>
    </main>;
  }
}

const query = new URLSearchParams(window.location.search);
const projectId = query.get("projectId") ? Number(query.get("projectId")) : undefined;
const apiBase = query.get("apiBase") || undefined;
const token = query.get("token") || undefined;
const hostOrigin = query.get("hostOrigin") || "*";

const startupWindow = window as typeof window & { __communityStartupTimer?: number };
if (startupWindow.__communityStartupTimer) window.clearTimeout(startupWindow.__communityStartupTimer);
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <StartupBoundary>
      <CommunityPredictionModule
        mode="embedded"
        projectId={projectId}
        apiBase={apiBase}
        token={token}
        hostOrigin={hostOrigin}
      />
    </StartupBoundary>
  </React.StrictMode>,
);

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Use one self-contained classic script for the Windows desktop package.
// This also works in managed browsers that suppress localhost ES modules.
export default defineConfig({
  plugins: [react()],
  // Library-mode builds do not always replace React's CommonJS environment
  // guard. Leaving it in the browser bundle crashes on machines that do not
  // happen to expose a Node-style `process` global.
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    target: "es2015",
    cssCodeSplit: false,
    lib: {
      entry: resolve(import.meta.dirname, "src/main.tsx"),
      name: "CommunityPredictionStandalone",
      formats: ["iife"],
      fileName: () => "assets/community-prediction-standalone.js",
      cssFileName: "community-prediction-standalone",
    },
    rollupOptions: {
      output: {
        assetFileNames: (assetInfo) =>
          assetInfo.name?.endsWith(".css")
            ? "assets/community-prediction-standalone.css"
            : "assets/[name]-[hash][extname]",
      },
    },
  },
});

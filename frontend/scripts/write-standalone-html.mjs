import { readFile, rename, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createHash } from "node:crypto";

const root = resolve(import.meta.dirname, "..");
const sourcePath = resolve(root, "index.html");
const outputPath = resolve(root, "dist", "index.html");
const assetRoot = resolve(root, "dist", "assets");
const sourceScript = resolve(assetRoot, "community-prediction-standalone.js");
const sourceStyle = resolve(assetRoot, "community-prediction-standalone.css");

async function versionAsset(sourcePath, extension) {
  const content = await readFile(sourcePath);
  const digest = createHash("sha256").update(content).digest("hex").slice(0, 12);
  const filename = `community-prediction-standalone.${digest}.${extension}`;
  await rename(sourcePath, resolve(assetRoot, filename));
  return filename;
}

// The desktop service uses a stable localhost address. Content-addressed names
// Prevent a browser from reusing JavaScript/CSS from an older deployment.
const scriptName = await versionAsset(sourceScript, "js");
const styleName = await versionAsset(sourceStyle, "css");

let html = await readFile(sourcePath, "utf8");
html = html
  .replace(/\s*<link rel="icon"[^>]*>\s*/u, "\n")
  .replace(
    /\s*<script type="module" src="\/src\/main\.tsx"><\/script>\s*/u,
    `\n    <link rel="stylesheet" href="./assets/${styleName}" />\n    <script defer src="./assets/${scriptName}"></script>\n`,
  );

if (html.includes('type="module"') || !html.includes(scriptName)) {
  throw new Error("未能生成经典脚本版 index.html");
}

await writeFile(outputPath, html, "utf8");

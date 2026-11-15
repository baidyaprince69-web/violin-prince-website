import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packagePath = resolve(projectRoot, "node_modules/motion/package.json");
if (!existsSync(packagePath)) {
  throw new Error("Motion is not installed. Run npm install before preparing the browser import map.");
}

const manifest = JSON.parse(readFileSync(packagePath, "utf8"));
const importEntry = manifest.exports?.["."]?.import ?? manifest.module;
if (typeof importEntry !== "string" || !importEntry.startsWith("./")) {
  throw new Error("The installed Motion package does not expose a local ESM entry.");
}

const moduleFile = resolve(dirname(packagePath), importEntry);
if (!existsSync(moduleFile)) {
  throw new Error("Motion ESM entry does not exist: " + moduleFile);
}

const relativeEntry = "./node_modules/motion/" + importEntry.replace(/^\.\//, "");
const htmlPath = resolve(projectRoot, "index.html");
let html = readFileSync(htmlPath, "utf8");
const importMapPattern = /(<script type="importmap" id="motion-importmap">)[\s\S]*?(<\/script>)/;
if (!importMapPattern.test(html)) {
  throw new Error("The Motion import map placeholder is missing from index.html.");
}

const importMap = JSON.stringify({ imports: { motion: relativeEntry } });
html = html.replace(importMapPattern, "$1\n    " + importMap + "\n  $2");
writeFileSync(htmlPath, html, "utf8");

console.log(JSON.stringify({
  status: "prepared",
  motion_version: manifest.version,
  module_entry: relativeEntry,
  bundled_into_composition: false
}, null, 2));

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function resolvePackageImport(packageName, exportPath = ".") {
  const packagePath = resolve(projectRoot, "node_modules", packageName, "package.json");
  if (!existsSync(packagePath)) {
    throw new Error("Required local Motion dependency is not installed: " + packageName);
  }
  const manifest = JSON.parse(readFileSync(packagePath, "utf8"));
  const exported = manifest.exports?.[exportPath];
  const importEntry = (typeof exported === "string" ? exported : exported?.import) ?? manifest.module;
  if (typeof importEntry !== "string" || !importEntry.startsWith("./")) {
    throw new Error("No local ESM export found for " + packageName + exportPath);
  }
  const moduleFile = resolve(dirname(packagePath), importEntry);
  if (!existsSync(moduleFile)) {
    throw new Error("Local ESM entry does not exist for " + packageName + ": " + moduleFile);
  }
  return "./node_modules/" + packageName + "/" + importEntry.replace(/^\.\//, "");
}

const imports = {
  "motion": resolvePackageImport("motion"),
  "framer-motion/dom": resolvePackageImport("framer-motion", "./dom"),
  "motion-dom": resolvePackageImport("motion-dom"),
  "motion-utils": resolvePackageImport("motion-utils")
};

const htmlPath = resolve(projectRoot, "index.html");
let html = readFileSync(htmlPath, "utf8");
const importMapPattern = /(<script type="importmap" id="motion-importmap">)[\s\S]*?(<\/script>)/;
if (!importMapPattern.test(html)) {
  throw new Error("The Motion import map placeholder is missing from index.html.");
}

html = html.replace(importMapPattern, "$1\n    " + JSON.stringify({ imports }) + "\n  $2");
writeFileSync(htmlPath, html, "utf8");

const motionManifest = JSON.parse(
  readFileSync(resolve(projectRoot, "node_modules/motion/package.json"), "utf8")
);
console.log(JSON.stringify({
  status: "prepared",
  motion_version: motionManifest.version,
  imports,
  bundled_into_composition: false
}, null, 2));

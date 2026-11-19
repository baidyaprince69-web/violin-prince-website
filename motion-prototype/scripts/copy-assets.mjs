import { cpSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const sourceDirectory = new URL("../../autopilot/engine/assets/fonts/", import.meta.url);
const destinationDirectory = new URL("../assets/fonts/", import.meta.url);

mkdirSync(fileURLToPath(destinationDirectory), { recursive: true });

const bundledFontFiles = [
  "DMSans.woff2",
  "DMSerifDisplay-Regular.woff2",
  "DM-Sans-OFL.txt",
  "DM-Serif-Display-OFL.txt"
];

for (const fileName of bundledFontFiles) {
  const source = fileURLToPath(new URL(fileName, sourceDirectory));
  const destination = fileURLToPath(new URL(fileName, destinationDirectory));
  cpSync(source, destination);
}

console.log("Bundled the existing DM Sans / DM Serif Display fonts and OFL notices.");

// Generates every logo variant from one geometry, so the mark can't drift between files.
import { mkdirSync, writeFileSync } from "node:fs";

const INK = "#000000";
const PAPER = "#FFFFFF";
const RING = "#3A3A3A";
const OUT = "public/brand";

// The dot is a fixed share of the disc. Small sizes enlarge it so it survives rasterizing.
const mark = ({ cx, cy, r, ring, dot = 0.21 }) =>
  `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${INK}"${ring ? ` stroke="${RING}" stroke-width="${(r * 0.03).toFixed(2)}"` : ""}/>` +
  `<circle cx="${cx}" cy="${cy}" r="${(r * dot).toFixed(2)}" fill="${PAPER}"/>`;

const wordmark = (x, y, scale, color) => {
  const letters = "M0 24V0L18 24V0M36 0V15a9.5 9.5 0 0 0 19 0V0M73 0V24H87M105 0V24H119";
  return `<path transform="translate(${x} ${y}) scale(${scale})" d="${letters}" fill="none" stroke="${color}" stroke-width="2.7" stroke-linecap="square" stroke-linejoin="miter"/>`;
};

const svg = (w, h, body) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" fill="none" role="img" aria-label="NULL">${body}</svg>\n`;

const files = {
  "logo-horizontal-dark.svg": svg(240, 64, mark({ cx: 32, cy: 32, r: 31, ring: true }) + wordmark(84, 18, 1.17, PAPER)),
  "logo-horizontal-light.svg": svg(240, 64, mark({ cx: 32, cy: 32, r: 31 }) + wordmark(84, 18, 1.17, INK)),
  "logo-compact-dark.svg": svg(112, 28, mark({ cx: 14, cy: 14, r: 13.5, ring: true }) + wordmark(38, 8, 0.5, PAPER)),
  "logo-compact-light.svg": svg(112, 28, mark({ cx: 14, cy: 14, r: 13.5 }) + wordmark(38, 8, 0.5, INK)),
  "symbol-dark.svg": svg(128, 128, mark({ cx: 64, cy: 64, r: 62, ring: true })),
  "symbol-light.svg": svg(128, 128, mark({ cx: 64, cy: 64, r: 63 })),
  "favicon.svg": svg(32, 32, mark({ cx: 16, cy: 16, r: 15.5, ring: true, dot: 0.3 })),
  "app-icon.svg": svg(
    512,
    512,
    `<rect width="512" height="512" rx="112" fill="#161616"/>` + mark({ cx: 256, cy: 256, r: 150, dot: 0.24 }),
  ),
};

mkdirSync(OUT, { recursive: true });
for (const [name, content] of Object.entries(files)) writeFileSync(`${OUT}/${name}`, content);
writeFileSync("src/app/icon.svg", files["favicon.svg"]);
console.log(`Wrote ${Object.keys(files).length} logo files`);

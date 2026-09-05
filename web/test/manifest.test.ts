/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import manifestRaw from "../public/site.webmanifest?raw";

// The pattern is rooted at "/", which Vite resolves against the project root (web/),
// so this sees the same public/ that Vitest's own working directory does.
const publicFiles = import.meta.glob("/public/*", { eager: true });

const manifest = JSON.parse(manifestRaw) as { icons: { src: string }[] };

describe("site.webmanifest", () => {
  it("names an icon src that resolves under web/public/", () => {
    for (const icon of manifest.icons) {
      expect(publicFiles).toHaveProperty(`/public${icon.src}`);
    }
  });

  it("ships favicon.ico, favicon.svg and apple-touch-icon.png alongside it", () => {
    for (const file of ["favicon.ico", "favicon.svg", "apple-touch-icon.png"]) {
      expect(publicFiles).toHaveProperty(`/public/${file}`);
    }
  });
});

/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

// The lockstep release (root VERSION -> app/package.json via tools/version_sync.py), baked in
// so no screen hardcodes a version string again (the sidebar said v0.2.0 and Settings 0.1.0).
const APP_VERSION = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")).version;

// jsdom, not a browser: these tests assert what the DOM contains after a render
// — in particular that the decide controls are ABSENT when signed out, which is
// a claim about the tree, not about pixels.
export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(APP_VERSION) },
  test: { environment: "jsdom", include: ["src/**/*.test.tsx"] },
});

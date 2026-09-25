/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// jsdom, not a browser: these tests assert what the DOM contains after a render
// — in particular that the decide controls are ABSENT when signed out, which is
// a claim about the tree, not about pixels.
export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", include: ["src/**/*.test.tsx"] },
});

/// <reference types="vitest/config" />
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `vite build`             -> dist/app  standalone SPA (index.html)
// `vite build --mode lib`  -> dist/lib  ES module library exporting <LearningSection> for the portal
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    port: 5173,
    // The local Search API (python -m minicode.api serve) - same-origin in dev, so no CORS needed.
    proxy: { "/api": { target: process.env.MINICODE_API_PROXY ?? "http://localhost:7071", changeOrigin: true } },
  },
  build:
    mode === "lib"
      ? {
          outDir: "dist/lib",
          emptyOutDir: true,
          copyPublicDir: false,
          sourcemap: true,
          lib: {
            entry: resolve(import.meta.dirname, "src/lib.ts"),
            formats: ["es"],
            fileName: () => "learning-section.js",
            cssFileName: "learning-section",
          },
          rollupOptions: {
            external: [
              "react",
              "react-dom",
              "react/jsx-runtime",
              "react-router",
              "@azure/msal-browser",
              "@azure/msal-react",
            ],
          },
        }
      : // MSAL alone is ~300 kB; the standalone app is a single small route set, so no code splitting
        { outDir: "dist/app", emptyOutDir: true, sourcemap: true, chunkSizeWarningLimit: 800 },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
}));

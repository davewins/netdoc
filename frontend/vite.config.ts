import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8123",
    },
  },
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
    // "assets" collides with the app's own /assets/:id route (asset
    // detail pages), which the SPA-fallback route in main.py needs to
    // resolve to index.html rather than the static file mount.
    assetsDir: "app-assets",
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build emits into the package static dir so `driverdna ui` needs Python
// alone at runtime (UI-SPEC decision 8). Dev proxies /api to a running
// `driverdna ui` instance.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/driverdna/ui/static",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8710" },
  },
});

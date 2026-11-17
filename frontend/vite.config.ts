import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base keeps GitHub Pages project sites, custom domains and local
// previews working from the same build.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
});

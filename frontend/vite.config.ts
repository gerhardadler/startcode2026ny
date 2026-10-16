import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  // APP_BASE=/oppdatert builds the copy that galak.se/oppdatert proxies to (see src/base.ts).
  base: `${loadEnv(mode, ".", "APP_").APP_BASE?.replace(/\/$/, "") ?? ""}/`,
  plugins: [react()],
  server: {
    proxy: {
      // API_TARGET lets a second dev setup run next to the usual one.
      "/api": loadEnv(mode, ".", "API_").API_TARGET || "http://localhost:8000",
    },
  },
}));

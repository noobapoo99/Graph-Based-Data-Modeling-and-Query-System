import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Builds the Vite configuration because local development still benefits from proxying API calls to the backend.
export default defineConfig(function createViteConfig({ mode }) {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});

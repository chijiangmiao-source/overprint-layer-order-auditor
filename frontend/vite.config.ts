import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev the browser hits Vite (5173); API calls are proxied to the API
// service. In the production image the built assets are served by nginx,
// which proxies /api to the API container (see web/nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

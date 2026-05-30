import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During dev, Vite serves the UI on its own port and proxies /api to the
// backend daemon (FastAPI on 127.0.0.1:7823, see config.json `port`). This
// keeps image URLs like /api/screenshots/{id}/image working without CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:7823",
        changeOrigin: true,
      },
    },
  },
});

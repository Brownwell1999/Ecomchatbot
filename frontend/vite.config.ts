import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /graphql is proxied to the gateway so the browser sees a single origin
// (same as production, where nginx does the proxying).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/graphql": "http://localhost:8000",
    },
  },
});

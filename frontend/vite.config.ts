import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // The container's filesystem events don't reach the host bind mount reliably.
    watch: { usePolling: true },
  },
});

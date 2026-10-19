import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Проксирование API на локальный «Полилог» (doc 01 §4.2)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

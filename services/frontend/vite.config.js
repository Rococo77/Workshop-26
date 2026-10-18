import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Servi derrière le WAF ; on autorise tous les hosts (reverse proxy) et on
// fixe le port HMR sur l'interface publiée (8080) pour le rechargement.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
    hmr: { clientPort: 8080 },
  },
});

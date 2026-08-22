/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// No @types/node dependency here, so declare the one shape this file reads from it.
declare const process: { env: Record<string, string | undefined> };

// Defaults are what a laptop run outside the devcontainer wants. The devcontainer sets
// only WEB_HOST and WEB_PUBLIC_PORT, because each service keeps its conventional port
// inside and only the host-side mapping shifts.
const webHost = process.env.WEB_HOST ?? "localhost";
const webPort = Number(process.env.WEB_PORT ?? 5173);
const apiPort = Number(process.env.API_PORT ?? 8000);

// The HMR websocket defaults to the port this server listens on, which is not the one
// the page was loaded from when a mapping shifts it, and not published either. Left
// unset the page loads and never hot-reloads, silently.
const webPublicPort = process.env.WEB_PUBLIC_PORT
  ? Number(process.env.WEB_PUBLIC_PORT)
  : undefined;

export default defineConfig({
  plugins: [react()],
  server: {
    host: webHost,
    port: webPort,
    strictPort: true,
    proxy: {
      "/api": `http://localhost:${apiPort}`,
    },
    ...(webPublicPort ? { hmr: { clientPort: webPublicPort } } : {}),
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});

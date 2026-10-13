import { defineConfig } from "vite";

export default defineConfig({
  // host: true binds both 127.0.0.1 and ::1 — found live: with no host set,
  // Vite bound only ::1 (IPv6), but "localhost" resolves to 127.0.0.1 first
  // on this machine, so the dev server looked "ready" yet was unreachable.
  server: { port: 5173, host: true },
});

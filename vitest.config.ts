import { defineConfig } from "vitest/config";

// Pure modules only (src/lib), in node: nothing here needs a DOM or Steam.
// probes/ has its own tooling and is never collected.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    exclude: ["node_modules/**", "dist/**", "out/**", "probes/**"],
  },
});

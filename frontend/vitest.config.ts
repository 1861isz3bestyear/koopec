import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    environment: "jsdom",
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      exclude: ["src/**/*.test.ts"],
      thresholds: {
        statements: 95.01,
        branches: 95.01,
        functions: 95.01,
        lines: 95.01,
      },
    },
  },
});

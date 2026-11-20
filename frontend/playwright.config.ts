import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "cargo run --manifest-path ../backend/Cargo.toml -p http-api",
      url: "http://127.0.0.1:8000/v1/health",
      timeout: 180_000,
      reuseExistingServer: false,
    },
    {
      command: "corepack pnpm dev --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      timeout: 30_000,
      reuseExistingServer: false,
    },
  ],
});

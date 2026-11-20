import { expect, test } from "@playwright/test";

test("imports candles and calculates exposure through the backend", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByText("Backend connected")).toBeVisible();
  await page.locator("#file").setInputFiles({
    name: "candles.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "time,open,high,low,close\n1700000000,100,110,90,105\n",
    ),
  });
  await expect(page.locator("#chart-message")).toHaveText("Loaded candles.csv");
  await expect(page.locator("#chart canvas").first()).toBeVisible();
  await page.getByLabel("Snapshot JSON").fill(
    JSON.stringify({
      observed_at: 0,
      available_at: 0,
      valued_at: 0,
      spot: 100,
      contracts: [
        {
          id: "call",
          kind: "call",
          strike: 100,
          expiry: 31536000,
          iv: 0.5,
          open_interest: 10,
          multiplier: 2,
        },
      ],
    }),
  );
  await page.getByRole("button", { name: "Calculate exposure" }).click();
  await expect(page.locator("#result")).toContainText('"signed"');
  expect(errors).toEqual([]);
});

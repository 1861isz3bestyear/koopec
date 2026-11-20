import { beforeEach, expect, it, vi } from "vitest";

const chartMocks = vi.hoisted(() => ({
    fitContent: vi.fn(),
    setData: vi.fn(),
  })),
  choose = (file?: { name: string; text: () => Promise<string> }): void => {
    const files: { name: string; text: () => Promise<string> }[] = [],
      input = document.querySelector<HTMLInputElement>("#file");
    if (!input) {
      throw new Error("File input is missing");
    }
    if (file) {
      files.push(file);
    }
    Object.defineProperty(input, "files", { configurable: true, value: files });
    input.dispatchEvent(new Event("change"));
  },
  delay = 0,
  expectChartLoaded = (): void => {
    expect(chartMocks.setData).toHaveBeenCalledOnce();
    expect(chartMocks.fitContent).toHaveBeenCalledOnce();
    expect(document.querySelector("#chart-message")?.textContent).toContain(
      "candles.csv",
    );
  },
  flush = async (): Promise<void> => {
    await new Promise<void>((resolve) => {
      setTimeout(resolve, delay);
    });
  },
  start = async (fetcher: ReturnType<typeof vi.fn>): Promise<void> => {
    vi.resetModules();
    document.body.innerHTML = '<div id="app"></div>';
    vi.stubGlobal("fetch", fetcher);
    await import("./main");
    await flush();
  },
  submit = (text: string): void => {
    const input = document.querySelector<HTMLTextAreaElement>("#snapshot");
    if (!input) {
      throw new Error("Snapshot input is missing");
    }
    input.value = text;
    document
      .querySelector("form")
      ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  };
vi.mock("lightweight-charts", () => ({
  CandlestickSeries: {},
  createChart: () => ({
    addSeries: () => ({ setData: chartMocks.setData }),
    timeScale: () => ({ fitContent: chartMocks.fitContent }),
  }),
}));
beforeEach(() => {
  vi.clearAllMocks();
});
it("loads valid CSV and submits a valid options calculation", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce({ ok: true })
    .mockResolvedValueOnce({
      json: () => Promise.resolve({ absolute: 0, signed: 0, strikes: [] }),
      ok: true,
    });
  await start(fetcher);
  expect(document.querySelector("#status")?.textContent).toBe(
    "Backend connected",
  );
  choose();
  choose({
    name: "candles.csv",
    text: () => Promise.resolve("time,open,high,low,close\n1700000000,1,2,1,2"),
  });
  await flush();
  expectChartLoaded();
  submit("{}");
  await flush();
  expect(document.querySelector("#result")?.textContent).toContain(
    '"signed": 0',
  );
});
it("reports invalid CSV and backend errors", async () => {
  await start(
    vi
      .fn()
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: false, status: 422 }),
  );
  expect(document.querySelector("#status")?.textContent).toBe(
    "Backend unavailable",
  );
  choose({ name: "bad.csv", text: () => Promise.resolve("bad") });
  await flush();
  expect(document.querySelector("#chart-message")?.textContent).toContain(
    "CSV columns",
  );
  submit("{}");
  await flush();
  expect(document.querySelector("#result")?.textContent).toContain("422");
});
it("handles unavailable backend, invalid JSON and invalid response", async () => {
  await start(
    vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ wrong: true }),
        ok: true,
      }),
  );
  expect(document.querySelector("#status")?.textContent).toBe(
    "Backend unavailable",
  );
  submit("{");
  await flush();
  expect(document.querySelector("#result")?.textContent).not.toContain(
    "Results will appear",
  );
  submit("{}");
  await flush();
  expect(document.querySelector("#result")?.textContent).toContain(
    "unexpected response",
  );
});
it("handles non-Error failures", async () => {
  await start(
    vi
      .fn()
      .mockResolvedValueOnce({ ok: true })
      .mockRejectedValueOnce("offline"),
  );
  choose({
    name: "bad",
    text: vi.fn<() => Promise<string>>().mockRejectedValue("bad"),
  });
  await flush();
  expect(document.querySelector("#chart-message")?.textContent).toBe(
    "Unable to read CSV.",
  );
  submit("{}");
  await flush();
  expect(document.querySelector("#result")?.textContent).toBe(
    "Calculation failed.",
  );
});
it("rejects a missing application root", async () => {
  vi.resetModules();
  document.body.innerHTML = "";
  await expect(import("./main")).rejects.toThrow("Application root is missing");
});

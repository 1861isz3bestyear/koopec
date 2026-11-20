import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ setData: vi.fn(), fitContent: vi.fn() }));
vi.mock("lightweight-charts", () => ({
  CandlestickSeries: {},
  createChart: () => ({
    addSeries: () => ({ setData: mocks.setData }),
    timeScale: () => ({ fitContent: mocks.fitContent }),
  }),
}));
const flush = async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};
async function start(fetcher: ReturnType<typeof vi.fn>) {
  vi.resetModules();
  document.body.innerHTML = '<div id="app"></div>';
  vi.stubGlobal("fetch", fetcher);
  await import("./main");
  await flush();
}
function submit(text: string) {
  (document.querySelector("#snapshot") as HTMLTextAreaElement).value = text;
  document
    .querySelector("form")
    ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}
function choose(file?: { name: string; text: () => Promise<string> }) {
  const input = document.querySelector<HTMLInputElement>("#file")!;
  Object.defineProperty(input, "files", {
    configurable: true,
    value: file ? [file] : [],
  });
  input.dispatchEvent(new Event("change"));
}
beforeEach(() => {
  vi.clearAllMocks();
});
describe("market workspace", () => {
  it("loads valid CSV and submits a valid options calculation", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ signed: 0, absolute: 0, strikes: [] }),
      });
    await start(fetcher);
    expect(document.querySelector("#status")?.textContent).toBe(
      "Backend connected",
    );
    choose();
    choose({
      name: "candles.csv",
      text: async () => "time,open,high,low,close\n1700000000,1,2,1,2",
    });
    await flush();
    expect(mocks.setData).toHaveBeenCalledOnce();
    expect(mocks.fitContent).toHaveBeenCalledOnce();
    expect(document.querySelector("#chart-message")?.textContent).toContain(
      "candles.csv",
    );
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
    choose({ name: "bad.csv", text: async () => "bad" });
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
          ok: true,
          json: async () => ({ wrong: true }),
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
      text: async () => {
        throw "bad";
      },
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
    await expect(import("./main")).rejects.toThrow(
      "Application root is missing",
    );
  });
});

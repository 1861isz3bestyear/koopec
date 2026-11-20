import { createChart, CandlestickSeries } from "lightweight-charts";
import { isExposureResponse, parseCandles } from "./data";
import "./style.css";

const root = document.querySelector<HTMLDivElement>("#app");
if (!root) throw new Error("Application root is missing");
root.innerHTML = `
  <main>
    <header>
      <div>
        <span class="eyebrow">KOOPEC / WORKSPACE</span>
        <h1>Market overview</h1>
        <p>Explore candles and calculate options exposure.</p>
      </div>
      <span class="badge" id="status">Checking backend</span>
    </header>
    <section class="panel">
      <div class="heading">
        <div><span class="eyebrow">PRICE ACTION</span><h2>Candlestick chart</h2></div>
        <label class="upload">Import CSV<input id="file" type="file" accept=".csv,text/csv"></label>
      </div>
      <p class="hint">CSV: time, open, high, low, close. Time is Unix seconds or ISO 8601.</p>
      <div id="chart" aria-label="Candlestick chart"></div>
      <p id="chart-message" class="message" role="status">Import a CSV to display candles.</p>
      <small>Charts by <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a></small>
    </section>
    <section class="panel">
      <div class="heading"><div><span class="eyebrow">CALCULUS</span><h2>Options exposure</h2></div></div>
      <p class="hint">Send an options snapshot as JSON to the Rust backend.</p>
      <form id="form">
        <label for="snapshot">Snapshot JSON</label>
        <textarea id="snapshot" rows="7" spellcheck="false" placeholder='{"observed_at": 0, "available_at": 0, "valued_at": 0, "spot": 100, "contracts": []}'></textarea>
        <button type="submit">Calculate exposure</button>
      </form>
      <pre id="result" aria-live="polite">Results will appear here.</pre>
    </section>
    <footer>Rust backend · Lightweight Charts</footer>
  </main>
`;
const element = <T extends HTMLElement>(selector: string): T =>
  document.querySelector<T>(selector)!;
const container = element<HTMLDivElement>("#chart");
const chart = createChart(container, {
  autoSize: true,
  height: 360,
  layout: { background: { color: "#111b25" }, textColor: "#a4b4c2" },
  grid: { vertLines: { color: "#1c2b37" }, horzLines: { color: "#1c2b37" } },
  rightPriceScale: { borderColor: "#263948" },
  timeScale: { borderColor: "#263948" },
});
const candles = chart.addSeries(CandlestickSeries, {
  upColor: "#47d3a0",
  downColor: "#f4827e",
  borderVisible: false,
  wickUpColor: "#47d3a0",
  wickDownColor: "#f4827e",
});
element<HTMLInputElement>("#file").addEventListener("change", async (event) => {
  const file = (event.currentTarget as HTMLInputElement).files?.[0];
  if (!file) return;
  try {
    candles.setData(parseCandles(await file.text()));
    chart.timeScale().fitContent();
    element("#chart-message").textContent = `Loaded ${file.name}`;
  } catch (error) {
    element("#chart-message").textContent =
      error instanceof Error ? error.message : "Unable to read CSV.";
  }
});
element<HTMLFormElement>("#form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = element("#result");
  try {
    const input: unknown = JSON.parse(
      element<HTMLTextAreaElement>("#snapshot").value,
    );
    const response = await fetch("/v1/options/exposure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!response.ok)
      throw new Error(
        `Calculation failed (${response.status}). Check your snapshot.`,
      );
    const value: unknown = await response.json();
    if (!isExposureResponse(value))
      throw new Error("The backend returned an unexpected response.");
    result.textContent = JSON.stringify(value, null, 2);
  } catch (error) {
    result.textContent =
      error instanceof Error ? error.message : "Calculation failed.";
  }
});
fetch("/v1/health")
  .then((response) => {
    element("#status").textContent = response.ok
      ? "Backend connected"
      : "Backend unavailable";
  })
  .catch(() => {
    element("#status").textContent = "Backend unavailable";
  });

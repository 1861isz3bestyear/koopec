import "./style.css";
import { CandlestickSeries, createChart } from "lightweight-charts";
import { isExposureResponse, parseCandles } from "./data";

const root = document.querySelector<HTMLDivElement>("#app");
if (!root) {
  throw new Error("Application root is missing");
}
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
{
  const assertElement = (selector: string): HTMLElement => {
      const found = document.querySelector<HTMLElement>(selector);
      if (!found) {
        throw new Error(`Missing element: ${selector}`);
      }
      return found;
    },
    chart = createChart(assertElement("#chart"), {
      autoSize: true,
      grid: {
        horzLines: { color: "#1c2b37" },
        vertLines: { color: "#1c2b37" },
      },
      height: 360,
      layout: { background: { color: "#111b25" }, textColor: "#a4b4c2" },
      rightPriceScale: { borderColor: "#263948" },
      timeScale: { borderColor: "#263948" },
    }),
    chartCandles = chart.addSeries(CandlestickSeries, {
      borderVisible: false,
      downColor: "#f4827e",
      upColor: "#47d3a0",
      wickDownColor: "#f4827e",
      wickUpColor: "#47d3a0",
    }),
    fileIndex = 0,
    indentation = 2,
    message = (error: unknown, fallback: string): string => {
      if (error instanceof Error) {
        return error.message;
      }
      return fallback;
    },
    parseExposure = async (response: Response): Promise<string> => {
      const value: unknown = await response.json();
      if (!isExposureResponse(value)) {
        throw new Error("The backend returned an unexpected response.");
      }
      return JSON.stringify(value, null, indentation);
    },
    readFile = async (event: Event): Promise<void> => {
      const file = (event.currentTarget as HTMLInputElement).files?.[fileIndex];
      if (!file) {
        return;
      }
      try {
        chartCandles.setData(parseCandles(await file.text()));
        chart.timeScale().fitContent();
        assertElement("#chart-message").textContent = `Loaded ${file.name}`;
      } catch (error) {
        assertElement("#chart-message").textContent = message(
          error,
          "Unable to read CSV.",
        );
      }
    },
    requestExposure = async (): Promise<string> => {
      const input: unknown = JSON.parse(
          (assertElement("#snapshot") as HTMLTextAreaElement).value,
        ),
        response = await fetch("/v1/options/exposure", {
          body: JSON.stringify(input),
          headers: { "Content-Type": "application/json" },
          method: "POST",
        });
      if (!response.ok) {
        throw new Error(
          `Calculation failed (${String(response.status)}). Check your snapshot.`,
        );
      }
      return parseExposure(response);
    },
    submitForm = async (): Promise<void> => {
      try {
        assertElement("#result").textContent = await requestExposure();
      } catch (error) {
        assertElement("#result").textContent = message(
          error,
          "Calculation failed.",
        );
      }
    };
  assertElement("#file").addEventListener("change", (event) => {
    readFile(event).catch((error: unknown) => {
      throw error;
    });
  });
  assertElement("#form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitForm().catch((error: unknown) => {
      throw error;
    });
  });
  fetch("/v1/health")
    .then((response) => {
      if (response.ok) {
        assertElement("#status").textContent = "Backend connected";
      } else {
        assertElement("#status").textContent = "Backend unavailable";
      }
    })
    .catch(() => {
      assertElement("#status").textContent = "Backend unavailable";
    });
}

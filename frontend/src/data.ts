import type { ExposureResponse } from "./api-types";
import type { CandlestickData, UTCTimestamp } from "lightweight-charts";

export function parseCandles(text: string): CandlestickData<UTCTimestamp>[] {
  const lines = text.trim().split(/\r?\n/);
  const header = lines
    .shift()
    ?.split(",")
    .map((x) => x.trim().toLowerCase());
  if (!header || header.join(",") !== "time,open,high,low,close")
    throw new Error("CSV columns must be time,open,high,low,close.");
  if (lines.length === 0 || lines.every((line) => !line.trim()))
    throw new Error("The CSV contains no candles.");
  const result: CandlestickData<UTCTimestamp>[] = [];
  for (const [index, line] of lines.entries()) {
    const fields = line.split(",").map((x) => x.trim());
    if (fields.length !== 5 || fields.some((x) => x === ""))
      throw new Error(`Invalid row ${index + 2}.`);
    const [rawTime, rawOpen, rawHigh, rawLow, rawClose] = fields;
    const timestamp = /^\d+$/.test(rawTime ?? "")
      ? Number(rawTime)
      : Date.parse(rawTime ?? "") / 1000;
    const [open, high, low, close] = [rawOpen, rawHigh, rawLow, rawClose].map(
      Number,
    );
    if (
      !Number.isSafeInteger(timestamp) ||
      timestamp <= 0 ||
      open === undefined ||
      high === undefined ||
      low === undefined ||
      close === undefined ||
      ![open, high, low, close].every((x) => Number.isFinite(x) && x > 0) ||
      low > Math.min(open, close) ||
      high < Math.max(open, close) ||
      low > high ||
      (result.length > 0 && timestamp <= (result[result.length - 1]?.time ?? 0))
    )
      throw new Error(
        `Invalid OHLC or chronological order on row ${index + 2}.`,
      );
    result.push({ time: timestamp as UTCTimestamp, open, high, low, close });
  }
  return result;
}

export function isExposureResponse(value: unknown): value is ExposureResponse {
  if (typeof value !== "object" || value === null) return false;
  const data = value as Record<string, unknown>;
  return (
    typeof data.signed === "number" &&
    Number.isFinite(data.signed) &&
    typeof data.absolute === "number" &&
    Number.isFinite(data.absolute) &&
    Array.isArray(data.strikes) &&
    data.strikes.every(
      (x: unknown) =>
        typeof x === "object" &&
        x !== null &&
        ["strike", "call", "put"].every(
          (key) =>
            typeof (x as Record<string, unknown>)[key] === "number" &&
            Number.isFinite((x as Record<string, number>)[key]),
        ),
    )
  );
}

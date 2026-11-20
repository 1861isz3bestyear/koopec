import type { CandlestickData, UTCTimestamp } from "lightweight-charts";
import type { ExposureResponse } from "./api-types";
const candleFields = 5,
  csvHeader = "time,open,high,low,close",
  emptyCount = 0,
  firstDataRow = 2,
  isExposureResponse = (value: unknown): value is ExposureResponse => {
    if (typeof value !== "object" || value === null) {
      return false;
    }
    const data = value as Record<string, unknown>;
    return (
      typeof data.signed === "number" &&
      Number.isFinite(data.signed) &&
      typeof data.absolute === "number" &&
      Number.isFinite(data.absolute) &&
      Array.isArray(data.strikes) &&
      data.strikes.every(
        (strike: unknown) =>
          typeof strike === "object" &&
          strike !== null &&
          ["strike", "call", "put"].every(
            (key) =>
              typeof (strike as Record<string, unknown>)[key] === "number" &&
              Number.isFinite((strike as Record<string, number>)[key]),
          ),
      )
    );
  },
  lastIndexOffset = 1,
  millisecondsPerSecond = 1000,
  parseCandleRow = (() => {
    const decodeTime = (raw: string): number => {
        if (/^\d+$/u.test(raw)) {
          return Number(raw);
        }
        return Date.parse(raw) / millisecondsPerSecond;
      },
      isValidCandle = (values: {
        close: number;
        high: number;
        low: number;
        open: number;
        previous: number;
        timestamp: number;
      }): boolean => {
        const { close, high, low, open, previous, timestamp } = values;
        return (
          Number.isSafeInteger(timestamp) &&
          timestamp > emptyCount &&
          timestamp > previous &&
          [open, high, low, close].every(
            (price) => Number.isFinite(price) && price > emptyCount,
          ) &&
          low <= Math.min(open, close) &&
          high >= Math.max(open, close) &&
          low <= high
        );
      },
      parseRow = (
        line: string,
        index: number,
        previous: number,
      ): CandlestickData<UTCTimestamp> => {
        const fields = line.split(",").map((field) => field.trim()),
          [rawTime, rawOpen, rawHigh, rawLow, rawClose] = fields,
          priceClose = Number(rawClose),
          priceHigh = Number(rawHigh),
          priceLow = Number(rawLow),
          priceOpen = Number(rawOpen),
          timestamp = decodeTime(rawTime ?? ""),
          values = {
            close: priceClose,
            high: priceHigh,
            low: priceLow,
            open: priceOpen,
            previous,
            timestamp,
          };
        if (
          fields.length !== candleFields ||
          fields.some((field) => field === "")
        ) {
          throw new Error(`Invalid row ${String(index + firstDataRow)}.`);
        }
        if (!isValidCandle(values)) {
          throw new Error(
            `Invalid OHLC or chronological order on row ${String(index + firstDataRow)}.`,
          );
        }
        return {
          close: values.close,
          high: values.high,
          low: values.low,
          open: values.open,
          time: timestamp as UTCTimestamp,
        };
      };
    return parseRow;
  })(),
  parseCandles = (text: string): CandlestickData<UTCTimestamp>[] => {
    const lines = text.trim().split(/\r?\n/u);
    if (
      lines
        .shift()
        ?.split(",")
        .map((field) => field.trim().toLowerCase())
        .join(",") !== csvHeader
    ) {
      throw new Error("CSV columns must be time,open,high,low,close.");
    }
    if (lines.length === emptyCount || lines.every((line) => !line.trim())) {
      throw new Error("The CSV contains no candles.");
    }
    return lines.reduce<CandlestickData<UTCTimestamp>[]>(
      (result, line, index) => {
        result.push(
          parseCandleRow(
            line,
            index,
            result.at(-lastIndexOffset)?.time ?? emptyCount,
          ),
        );
        return result;
      },
      [],
    );
  };
export { isExposureResponse, parseCandles };

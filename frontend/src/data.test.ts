import { describe, expect, it } from "vitest";
import { isExposureResponse, parseCandles } from "./data";
const firstIndex = 0,
  header = "time,open,high,low,close\n",
  isoTimestamp = 1704067200,
  oneCandle = 1;
describe("candle CSV", () => {
  it("accepts chronological OHLC values", () => {
    const candles = parseCandles(`${header}1700000000,10,12,9,11`);
    expect(candles).toHaveLength(oneCandle);
  });
  it("accepts an ISO timestamp and a case-insensitive header", () => {
    const candles = parseCandles(
      " TIME,OPEN,HIGH,LOW,CLOSE\n2024-01-01T00:00:00Z,10,12,9,11",
    );
    expect(candles[firstIndex]?.time).toBe(isoTimestamp);
  });
  it.each([
    { input: "", name: "an empty file" },
    { input: "bad,header", name: "an invalid header" },
    { input: header, name: "a header without observations" },
    { input: `${header}0,1,1,1,1`, name: "a zero timestamp" },
    { input: `${header}invalid,1,1,1,1`, name: "an invalid timestamp" },
    { input: `${header}1700000000,1,1,1`, name: "a missing field" },
    { input: `${header}1700000000,,12,9,11`, name: "an empty field" },
    { input: `${header}1700000000,-1,1,1,1`, name: "a negative price" },
    { input: `${header}1700000000,2,2,3,2`, name: "a low above the open" },
    { input: `${header}1700000000,10,9,8,11`, name: "a high below the close" },
    { input: `${header}1700000000,2,1,1,2`, name: "a high below the open" },
    { input: `${header}1700000000,NaN,2,1,2`, name: "a nonnumeric price" },
    { input: `${header}1700000000,1,Infinity,1,1`, name: "an infinite price" },
    { input: `${header}1700000000,1,1,2,1`, name: "a reversed range" },
    {
      input: `${header}1700000000,10,12,9,11\n1700000000,10,12,9,11`,
      name: "duplicate times",
    },
    {
      input: `${header}1700000000,1,2,1,1\n1699999999,1,2,1,1`,
      name: "decreasing times",
    },
  ])("rejects $name", ({ input }) => {
    expect(() => parseCandles(input)).toThrow();
  });
});
describe("exposure response validation", () => {
  it("accepts finite totals and strike exposures", () => {
    const response = {
      absolute: 1,
      signed: 0,
      strikes: [{ call: 1, put: 0, strike: 1 }],
    };
    expect(isExposureResponse(response)).toBe(true);
  });
});
describe("invalid exposure responses", () => {
  it.each([
    { name: "undefined", value: ([] as unknown[]).at(firstIndex) },
    { name: "null", value: null },
    { name: "a number", value: 1 },
    { name: "missing fields", value: {} },
    {
      name: "a string total",
      value: { absolute: 1, signed: "0", strikes: [] },
    },
    { name: "a NaN total", value: { absolute: 1, signed: NaN, strikes: [] } },
    {
      name: "a string absolute total",
      value: { absolute: "1", signed: 0, strikes: [] },
    },
    {
      name: "an infinite absolute total",
      value: { absolute: Infinity, signed: 0, strikes: [] },
    },
    {
      name: "a null strike",
      value: { absolute: 1, signed: 0, strikes: [null] },
    },
    {
      name: "an infinite call",
      value: {
        absolute: 1,
        signed: 0,
        strikes: [{ call: Infinity, put: 0, strike: 1 }],
      },
    },
    {
      name: "a string put",
      value: {
        absolute: 1,
        signed: 0,
        strikes: [{ call: 0, put: "0", strike: 1 }],
      },
    },
    {
      name: "a non-array strikes value",
      value: { absolute: 1, signed: 0, strikes: {} },
    },
  ])("rejects $name", ({ value }) => {
    expect(isExposureResponse(value)).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { isExposureResponse, parseCandles } from "./data";

const header = "time,open,high,low,close\n";

describe("candle CSV", () => {
  it("accepts chronological OHLC values", () => {
    const candles = parseCandles(`${header}1700000000,10,12,9,11`);
    expect(candles).toHaveLength(1);
  });

  it("accepts an ISO timestamp and a case-insensitive header", () => {
    const candles = parseCandles(
      " TIME,OPEN,HIGH,LOW,CLOSE\n2024-01-01T00:00:00Z,10,12,9,11",
    );
    expect(candles[0]?.time).toBe(1704067200);
  });

  it.each([
    { name: "an empty file", input: "" },
    { name: "an invalid header", input: "bad,header" },
    { name: "a header without observations", input: header },
    { name: "a zero timestamp", input: `${header}0,1,1,1,1` },
    { name: "an invalid timestamp", input: `${header}invalid,1,1,1,1` },
    { name: "a missing field", input: `${header}1700000000,1,1,1` },
    { name: "an empty field", input: `${header}1700000000,,12,9,11` },
    { name: "a negative price", input: `${header}1700000000,-1,1,1,1` },
    { name: "a low above the open", input: `${header}1700000000,2,2,3,2` },
    { name: "a high below the close", input: `${header}1700000000,10,9,8,11` },
    { name: "a high below the open", input: `${header}1700000000,2,1,1,2` },
    { name: "a nonnumeric price", input: `${header}1700000000,NaN,2,1,2` },
    { name: "an infinite price", input: `${header}1700000000,1,Infinity,1,1` },
    { name: "a reversed range", input: `${header}1700000000,1,1,2,1` },
    {
      name: "duplicate times",
      input: `${header}1700000000,10,12,9,11\n1700000000,10,12,9,11`,
    },
    {
      name: "decreasing times",
      input: `${header}1700000000,1,2,1,1\n1699999999,1,2,1,1`,
    },
  ])("rejects $name", ({ input }) => {
    expect(() => parseCandles(input)).toThrow();
  });
});

describe("exposure response validation", () => {
  it("accepts finite totals and strike exposures", () => {
    const response = {
      signed: 0,
      absolute: 1,
      strikes: [{ strike: 1, call: 1, put: 0 }],
    };
    expect(isExposureResponse(response)).toBe(true);
  });

  it.each([
    { name: "undefined", value: undefined },
    { name: "null", value: null },
    { name: "a number", value: 1 },
    { name: "missing fields", value: {} },
    {
      name: "a string total",
      value: { signed: "0", absolute: 1, strikes: [] },
    },
    { name: "a NaN total", value: { signed: NaN, absolute: 1, strikes: [] } },
    {
      name: "a string absolute total",
      value: { signed: 0, absolute: "1", strikes: [] },
    },
    {
      name: "an infinite absolute total",
      value: { signed: 0, absolute: Infinity, strikes: [] },
    },
    {
      name: "a null strike",
      value: { signed: 0, absolute: 1, strikes: [null] },
    },
    {
      name: "an infinite call",
      value: {
        signed: 0,
        absolute: 1,
        strikes: [{ strike: 1, call: Infinity, put: 0 }],
      },
    },
    {
      name: "a string put",
      value: {
        signed: 0,
        absolute: 1,
        strikes: [{ strike: 1, call: 0, put: "0" }],
      },
    },
    {
      name: "a non-array strikes value",
      value: { signed: 0, absolute: 1, strikes: {} },
    },
  ])("rejects $name", ({ value }) => {
    expect(isExposureResponse(value)).toBe(false);
  });
});

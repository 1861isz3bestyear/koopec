import { beforeAll, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const aaContrast = 4.5,
  blueWeight = 0.0722,
  channelCount = 3,
  channelThreshold = 0.04045,
  emptyTotal = 0,
  exponent = 2.4,
  greenWeight = 0.7152,
  linearDivisor = 12.92,
  maximumChannel = 255,
  nonlinearDivisor = 1.055,
  nonlinearOffset = 0.055,
  offset = 0.05,
  redWeight = 0.2126,
  relativeLuminance = (color: string): number => {
    const match = color.match(/\d+(?:\.\d+)?/gu);
    if (!match || match.length < channelCount) {
      throw new Error(`Unsupported color: ${color}`);
    }
    return match
      .slice(emptyTotal, channelCount)
      .reduce((total, value, index) => {
        const channel = Number(value) / maximumChannel,
          weight = [redWeight, greenWeight, blueWeight].at(index);
        if (typeof weight !== "number") {
          throw new Error("Missing luminance weight");
        }
        if (channel <= channelThreshold) {
          return total + (weight * channel) / linearDivisor;
        }
        return (
          total +
          weight * ((channel + nonlinearOffset) / nonlinearDivisor) ** exponent
        );
      }, emptyTotal);
  },
  styleOf = (selector: string): CSSStyleDeclaration => {
    const element = document.querySelector(selector);
    if (!element) {
      throw new Error(`Missing element: ${selector}`);
    }
    return getComputedStyle(element);
  },
  textContrast = (foreground: string, background: string): number => {
    const first = relativeLuminance(foreground),
      second = relativeLuminance(background);
    return (
      (Math.max(first, second) + offset) / (Math.min(first, second) + offset)
    );
  };
beforeAll(() => {
  const style = document.createElement("style");
  style.textContent = readFileSync("src/style.css", "utf8");
  document.head.append(style);
  document.body.innerHTML =
    '<main><header><p>Text</p><span class="badge">Status</span></header><section class="panel"><span class="eyebrow">Label</span><p class="hint">Hint</p><button>Button</button><textarea>Input</textarea><pre>Output</pre><small>Caption</small></section><footer>Footer</footer></main>';
});
it("enforces at least WCAG AA 4.5:1 for UI text against its effective background", () => {
  const panel = styleOf(".panel"),
    root = getComputedStyle(document.documentElement);
  for (const [selector, background] of [
    ["header p", root.backgroundColor],
    [".badge", root.backgroundColor],
    [".eyebrow", panel.backgroundColor],
    [".hint", panel.backgroundColor],
    ["button", styleOf("button").backgroundColor],
    ["textarea", styleOf("textarea").backgroundColor],
    ["pre", styleOf("pre").backgroundColor],
    ["small", panel.backgroundColor],
    ["footer", root.backgroundColor],
  ] as const) {
    expect(
      textContrast(styleOf(selector).color, background),
      selector,
    ).toBeGreaterThanOrEqual(aaContrast);
  }
});
it("rejects a low contrast combination", () => {
  expect(textContrast("rgb(128,128,128)", "rgb(130,130,130)")).toBeLessThan(
    aaContrast,
  );
});

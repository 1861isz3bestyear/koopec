import { readFileSync } from "node:fs";
import { beforeAll, expect, it } from "vitest";

function luminance(color: string): number {
  const match = color.match(/\d+(?:\.\d+)?/g);
  if (!match || match.length < 3)
    throw new Error(`Unsupported color: ${color}`);
  const channels = match
    .slice(0, 3)
    .map(Number)
    .map((value) => {
      const channel = value / 255;
      return channel <= 0.04045
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4;
    });
  return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
}
function contrast(foreground: string, background: string): number {
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort(
    (a, b) => b - a,
  );
  return (lighter! + 0.05) / (darker! + 0.05);
}
beforeAll(() => {
  const style = document.createElement("style");
  style.textContent = readFileSync("src/style.css", "utf8");
  document.head.append(style);
  document.body.innerHTML =
    '<main><header><p>Text</p><span class="badge">Status</span></header><section class="panel"><span class="eyebrow">Label</span><p class="hint">Hint</p><button>Button</button><textarea>Input</textarea><pre>Output</pre><small>Caption</small></section><footer>Footer</footer></main>';
});
it("enforces at least WCAG AA 4.5:1 for UI text against its effective background", () => {
  const root = getComputedStyle(document.documentElement);
  const panel = getComputedStyle(document.querySelector(".panel")!);
  for (const [selector, background] of [
    ["header p", root.backgroundColor],
    [".badge", root.backgroundColor],
    [".eyebrow", panel.backgroundColor],
    [".hint", panel.backgroundColor],
    [
      "button",
      getComputedStyle(document.querySelector("button")!).backgroundColor,
    ],
    [
      "textarea",
      getComputedStyle(document.querySelector("textarea")!).backgroundColor,
    ],
    ["pre", getComputedStyle(document.querySelector("pre")!).backgroundColor],
    ["small", panel.backgroundColor],
    ["footer", root.backgroundColor],
  ] as const) {
    expect(
      contrast(
        getComputedStyle(document.querySelector(selector)!).color,
        background,
      ),
      selector,
    ).toBeGreaterThanOrEqual(4.5);
  }
});
it("rejects a low contrast combination", () =>
  expect(contrast("rgb(128,128,128)", "rgb(130,130,130)")).toBeLessThan(4.5));

// Record colors used by the actual renderer before text alters the pixels.
window.canvasTextSamples = [];
const originalFillText = CanvasRenderingContext2D.prototype.fillText;
CanvasRenderingContext2D.prototype.fillText = function(text, x, y, ...rest) {
  if (this.canvas.id === 'chart') {
    const transform = this.getTransform();
    const point = new DOMPoint(x, y - 2).matrixTransform(transform);
    const px = Math.max(0, Math.min(this.canvas.width - 1, Math.floor(point.x)));
    const py = Math.max(0, Math.min(this.canvas.height - 1, Math.floor(point.y)));
    const pixel = this.getImageData(px, py, 1, 1).data;
    const alpha = pixel[3] / 255;
    const background = Array.from(pixel.slice(0, 3), value => value * alpha + 255 * (1 - alpha));
    const color = this.fillStyle;
    const foreground = /^#[0-9a-f]{6}$/i.test(color)
      ? [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16)) : null;
    window.canvasTextSamples.push({text, foreground, background});
  }
  return originalFillText.call(this, text, x, y, ...rest);
};
void 0;

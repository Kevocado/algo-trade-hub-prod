import "@testing-library/jest-dom";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});

// recharts' `ResponsiveContainer` measures its parent with a ResizeObserver, which jsdom does not
// implement. Without this, any test that renders a chart throws `ResizeObserver is not defined` --
// which is why the two existing chart pages had no rendered-output tests at all. A no-op observer is
// the standard jsdom stand-in: it reports no size, so charts render at their container's fallback
// dimensions and their contents stay assertable.
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// A no-op observer leaves every element 0x0, and recharts' `ResponsiveContainer` renders NOTHING at
// 0x0 -- so chart output was unassertable and assertions about it would have been about the mock.
// Giving elements a size makes the SVG real, which is what let the numeric-x-axis test check the axis
// rather than the absence of an exception.
Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 640 });
Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 320 });
Element.prototype.getBoundingClientRect = function () {
  return { width: 640, height: 320, top: 0, left: 0, right: 640, bottom: 320, x: 0, y: 0,
           toJSON: () => ({}) } as DOMRect;
};

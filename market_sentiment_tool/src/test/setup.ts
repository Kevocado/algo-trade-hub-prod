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

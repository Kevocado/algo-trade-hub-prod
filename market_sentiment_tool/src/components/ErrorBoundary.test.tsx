import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ErrorBoundary } from "@/components/ErrorBoundary";

function Boom(): never {
  throw new Error("points is undefined");
}

describe("ErrorBoundary", () => {
  it("shows what failed instead of a blank page, and leaves its siblings alone", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<div><nav>menu</nav><ErrorBoundary><Boom /></ErrorBoundary></div>);
    expect(screen.getByRole("alert")).toHaveTextContent("points is undefined");
    expect(screen.getByText("menu")).toBeInTheDocument();
  });

  it("clears when the route changes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(<ErrorBoundary resetKey="/journal"><Boom /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(<ErrorBoundary resetKey="/health"><p>fine</p></ErrorBoundary>);
    expect(screen.getByText("fine")).toBeInTheDocument();
  });
});

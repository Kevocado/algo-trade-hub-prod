import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ReportDumbbells, closer } from "@/components/ReportDumbbells";

const fmt = (v: number) => `${v}k`;

describe("ReportDumbbells", () => {
  it("says who was closer to the first reported figure, and says nothing when a figure is missing", () => {
    expect(closer({ month: "m", nowcast: 100, kalshi: 60, firstPrint: 90 })).toBe("ours");
    expect(closer({ month: "m", nowcast: 100, kalshi: 95, firstPrint: 90 })).toBe("kalshi");
    expect(closer({ month: "m", nowcast: 80, kalshi: 100, firstPrint: 90 })).toBe("tie");
    expect(closer({ month: "m", nowcast: null, kalshi: 95, firstPrint: 90 })).toBeNull();
  });

  it("draws latest first, rings only the closer estimate, and never draws a missing figure", () => {
    render(<ReportDumbbells fmt={fmt} points={[
      { month: "2026-06", nowcast: 173, kalshi: 119, firstPrint: 57 },
      { month: "2026-08", nowcast: 78, kalshi: 39, firstPrint: 162 },
      { month: "2026-07", nowcast: null, kalshi: 67, firstPrint: -23 },
    ]} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.textContent?.slice(0, 7))).toEqual(["2026-08", "2026-07", "2026-06"]);
    expect(rows[0].querySelector('[data-mark="ours"]')?.getAttribute("data-closer")).toBe("true");     // 84 away vs Kalshi's 123
    expect(rows[0].querySelector('[data-mark="kalshi"]')?.getAttribute("data-closer")).toBe("false");
    expect(rows[2].querySelector('[data-mark="kalshi"]')?.getAttribute("data-closer")).toBe("true");
    expect(rows[1].querySelector('[data-mark="ours"]')).toBeNull();
    expect(rows[1]).toHaveTextContent("not scored");
  });

  it("says so when there are no reports", () => {
    render(<ReportDumbbells fmt={fmt} points={[]} />);
    expect(screen.getByText("No reports yet.")).toBeInTheDocument();
  });
});

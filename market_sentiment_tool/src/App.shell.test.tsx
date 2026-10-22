import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Link, MemoryRouter } from "react-router-dom";

import { AppShell } from "@/App";

// `src/lib/supabase.ts` builds a real client at import time and THROWS when the publishable key is
// absent, so importing `App` -- which pulls in every page -- fails before a single assertion runs.
// The stub is a stand-in for a credential this test does not need.
vi.mock("@/lib/supabase", () => ({ supabase: {} }));

// The rail reads the portfolio on every route. That read is not what this file is about, and it
// is a real request that lands after the assertions, so it is stubbed at the hook: the shell
// renders its nav either way.
vi.mock("@/hooks/usePortfolio", () => ({
  usePortfolio: () => ({ portfolio: null, positions: [], loading: false, error: null }),
}));

/**
 * The shell on a phone.
 *
 * The rail is 256px wide and `sticky`, so on a 375px phone it took two thirds of the screen and
 * every page was squeezed into what was left. Below 768px the rail is hidden and a menu button
 * opens the same nav as an overlay; from 768px up nothing changes.
 *
 * The breakpoint is CSS, not JavaScript: there is no width check in the component to fall out of
 * step with the stylesheet, and jsdom has no layout to measure. So these tests assert the two
 * things that ARE observable here -- the classes that carry the breakpoint, and the state the
 * button and the overlay expose -- and the browser run in the PR is what shows the pixels.
 */
function renderShell() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <AppShell>
        <Link to="/journal">go to the journal</Link>
      </AppShell>
    </MemoryRouter>,
  );
}

/** The one control that opens and closes the menu. Its name says which it does right now. */
function menuButton(): HTMLElement {
  return screen.getByRole("button", { name: /menu/i });
}

beforeEach(() => {
  // The viewport the tests are about. jsdom has no layout, so this states the case rather than
  // driving it: the classes below are what make it true.
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 375 });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("the shell on a phone", () => {
  it("has a menu button, and it says whether the menu is open", () => {
    renderShell();

    const button = menuButton();
    expect(button.tagName).toBe("BUTTON"); // a real button: reachable by keyboard, no role needed
    expect(button).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(button);
    expect(menuButton()).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps the nav out of the way until the menu is opened", () => {
    renderShell();

    // The rail is display:none below Tailwind's md breakpoint (768px) and display:flex from
    // there up, so a phone never pays for it. These two classes ARE the behaviour.
    const rail = screen.getByTestId("sidebar-rail");
    expect(rail.className).toContain("hidden");
    expect(rail.className).toContain("md:flex");

    // And the overlay that replaces it is not in the tree at all until it is opened, so there is
    // no second copy of the nav for a screen reader to walk.
    expect(screen.queryByTestId("sidebar-overlay")).toBeNull();
  });

  it("opens the nav as an overlay, and closes it again", () => {
    renderShell();

    fireEvent.click(menuButton());

    const overlay = screen.getByTestId("sidebar-overlay");
    // The overlay is the nav, not a copy of its title: the links are the ones the rail has.
    expect(within(overlay).getByRole("link", { name: /journal/i })).toHaveAttribute("href", "/journal");
    // And it is an overlay: fixed to the viewport, over a backdrop, and never at 768px and up.
    expect(overlay.className).toContain("fixed");
    expect(overlay.className).toContain("md:hidden");
    expect(screen.getByTestId("sidebar-backdrop")).toBeInTheDocument();

    fireEvent.click(menuButton());
    expect(screen.queryByTestId("sidebar-overlay")).toBeNull();
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on Escape and gives the keyboard its focus back", () => {
    renderShell();

    fireEvent.click(menuButton());
    expect(screen.getByTestId("sidebar-overlay")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("sidebar-overlay")).toBeNull();
    // Focus goes back to the button that opened it, so a keyboard user is not dropped on the
    // body of the page.
    expect(document.activeElement).toBe(menuButton());
  });

  it("closes when the backdrop is clicked", () => {
    renderShell();

    fireEvent.click(menuButton());
    fireEvent.click(screen.getByTestId("sidebar-backdrop"));
    expect(screen.queryByTestId("sidebar-overlay")).toBeNull();
  });

  it("closes when the route changes, so the new page is not read through the overlay", () => {
    renderShell();

    fireEvent.click(menuButton());
    expect(screen.getByTestId("sidebar-overlay")).toBeInTheDocument();

    // A link OUTSIDE the overlay: so what closes the menu is the route change itself and not
    // the overlay's own click handler.
    fireEvent.click(screen.getByRole("link", { name: /go to the journal/i }));
    expect(screen.queryByTestId("sidebar-overlay")).toBeNull();
  });

  it("moves focus into the overlay when it opens", () => {
    renderShell();

    fireEvent.click(menuButton());
    // The panel itself takes focus, so the next Tab lands on the first link inside it.
    expect(document.activeElement).toBe(screen.getByTestId("sidebar-overlay"));
  });
});

describe("the shell from 768px up", () => {
  it("keeps the rail, and never shows the overlay there", () => {
    renderShell();

    const rail = screen.getByTestId("sidebar-rail");
    expect(rail.className).toContain("md:flex");
    expect(rail.className).not.toContain("md:hidden");

    // The overlay is md:hidden, so it cannot appear on a wide screen even if the state says open.
    fireEvent.click(menuButton());
    expect(screen.getByTestId("sidebar-overlay").className).toContain("md:hidden");
    expect(screen.getByTestId("sidebar-backdrop").className).toContain("md:hidden");
  });
});

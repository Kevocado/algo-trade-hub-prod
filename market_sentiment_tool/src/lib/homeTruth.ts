/**
 * The front page's "what we found": wire types, words and formatting.
 *
 * Every number here arrives computed from the server (`tradehub/journal/standings.py`). This module
 * decides words, chips and layout only; it never compares a gap against its standard error, because
 * that judgement about whether a result is real belongs in exactly one place. A second
 * implementation is a second place to be wrong, and this is the page a reader lands on first.
 *
 * The rules that keep it honest, each of them enforced by a test in `homeTruth.test.ts`:
 * a missing gap or interval renders as a dash and never as 0; a verdict is a one- or two-word chip
 * pinned by test, so "Loses to" cannot quietly become "Underperforming"; and no percentage appears
 * that is neither a count nor a measured gap.
 */

import { forecasterLabel } from "@/lib/forecasterLabels";

export interface StandingEntry {
  forecaster: string;
  version: string;
  baseline: "market" | "climatology" | "none";
  cadence: string;
  /** Our mean squared error minus the baseline's. Negative is better. `null` = not measured. */
  gap: number | null;
  /** Standard error of that gap. `null` = no interval was recorded, so nothing can be concluded. */
  se: number | null;
  /** Replayed sessions the gap was measured over. */
  n: number | null;
  n_settled: number | null;
  bss: number | null;
  verdict: "beats" | "loses to" | "indistinguishable" | "no difference" | "unknown";
  date_from: string | null;
  date_to: string | null;
}

export interface Standings {
  best: StandingEntry | null;
  worst: StandingEntry | null;
  n_settled: number;
  n_replayed: number;
  forecasters: number;
  market_linked: string[];
  distinct_se: number;
  /** Assembled from the numbers on the server. Never typed here. */
  verdict: string;
}

export interface Chip {
  label: string;
  tone: "ok" | "warn" | "bad" | "flat";
}

/** Lede. Kept under the word budget and asserted by test. */
export const HOME_INTRO =
  "What we found, measured against the Kalshi price. Every figure carries its own error bar.";

/**
 * One- or two-word verdict chips, pinned exactly by test. "No signal" rather than "Inconclusive",
 * and "No interval" for the case where we know the sign but never measured whether it clears noise:
 * an unreported interval must not read as a weak result, because it is not one.
 */
export function verdictChip(verdict: StandingEntry["verdict"] | string): Chip {
  switch (verdict) {
    case "beats":
      return { label: "Beats", tone: "ok" };
    case "loses to":
      return { label: "Loses to", tone: "bad" };
    case "indistinguishable":
      return { label: "No signal", tone: "flat" };
    case "no difference":
      return { label: "Even", tone: "flat" };
    case "unknown":
      return { label: "No interval", tone: "warn" };
    default:
      return { label: "—", tone: "flat" };
  }
}

const signed = (value: number, places = 3) => `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(places)}`;

/**
 * "−0.030 ± 0.005" when both are measured, and a dash when either is not.
 *
 * A dash, never 0.00: without an interval there is no bar for the gap to clear, and rendering the
 * missing half as a zero-width bar would print "−0.030 ± 0.000", which reads as a precise result.
 * A zero-width bar for a gap of exactly zero is a real measurement and is rendered as such.
 */
export function gapText(gap: number | null, se: number | null): string {
  if (gap === null || gap === undefined) return "—";
  if (se === null || se === undefined) return "—";
  return `${signed(gap)} ± ${se.toFixed(3)}`;
}

export function plainName(forecaster: string): string {
  return forecasterLabel(forecaster) ?? forecaster;
}

export interface HomeStat {
  settled: number;
  forecasters: number;
  replayed: number;
  bestName: string;
  bestGap: string;
  bestSe: string | null;
  worstName: string;
  worstGap: string;
  worstSe: string | null;
}

/** The big numbers, and the names of each end. Formatting only; no score is derived here. */
export function headlineStats(s: Standings): HomeStat {
  const se = (v: number | null) => (v === null || v === undefined ? null : v.toFixed(3));
  return {
    settled: s.n_settled,
    forecasters: s.forecasters,
    replayed: s.n_replayed,
    bestName: s.best ? plainName(s.best.forecaster) : "—",
    bestGap: s.best ? gapText(s.best.gap, s.best.se) : "—",
    bestSe: s.best ? se(s.best.se) : null,
    worstName: s.worst ? plainName(s.worst.forecaster) : "—",
    worstGap: s.worst ? gapText(s.worst.gap, s.worst.se) : "—",
    worstSe: s.worst ? se(s.worst.se) : null,
  };
}

/**
 * Where to go next. Only routes that exist: the weather page and the order-book study are not built
 * yet, and a link to a route that 404s is a broken promise on the landing page.
 */
export const homeLinks: { to: string; label: string; blurb: string }[] = [
  { to: "/journal", label: "Journal", blurb: "Every frozen forecast and what it scored" },
  { to: "/models", label: "Models", blurb: "Which forecasters exist and what each claims" },
  { to: "/sports", label: "Sports", blurb: "NFL and college football, winners and spreads" },
  { to: "/health", label: "Health", blurb: "Whether the jobs are actually running" },
];
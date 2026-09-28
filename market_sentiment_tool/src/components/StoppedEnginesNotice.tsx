import { AlertOctagon, FlaskConical } from "lucide-react";

import {
  QUARANTINED_WORD,
  STOPPED_WORD,
  edgeTypesText,
  opportunitiesFoundReason,
  opportunitiesFoundText,
  quarantineSinkOf,
  type EngineHealthResponse,
} from "@/lib/engineHealth";
import { NOT_MEASURED } from "@/lib/edgeFigures";

/**
 * The half of the stopped-engine ruling that only a page can close.
 *
 * `/api/engine-health` knows which engines cannot run, and -- since 2026-09-28 -- which are
 * quarantined. Knowing it is not the same as having said it, and the reason this component exists is
 * the same reason `WithheldEdgesNotice` exists: a fact that is held but not rendered is, to a reader,
 * indistinguishable from the fact not being true.
 *
 * The specific lie this removes is the EMPTY TAB. "No high-confidence edges detected in weather"
 * is a finding. It was being printed for an engine that had not looked at anything, because
 * `WeatherEngine` prices every market off `yes_ask`, Kalshi stopped sending that key, and the `0`
 * default made every market look unpriceable -- so the engine skipped all of them and published
 * nothing without raising anything. Failing closed is why nothing wrong reached the ledger; it is
 * also why nothing reached the reader.
 *
 * **The panel now carries two states and they are not interchangeable.** `could_not_run` is the
 * broken case above. `quarantined` is a REPAIRED engine that runs, measured 295 rows on 2026-09-28,
 * and had them withheld on purpose; those rows are on `/api/quarantine` and in
 * `QuarantineNotice`. Rendering them with the same words would say "not running" about an engine
 * that runs, which is false, and would send a reader to fix something already fixed. So the heading
 * counts them separately and each block says which of the two it is.
 *
 * Rendered UNCONDITIONALLY when the ruling names an engine, and not only when the tab happens to be
 * empty. That is deliberate and it is the one thing worth being strict about here: a MACRO tab with
 * rows on it is fed by `labor_nowcast` and a WEATHER tab with rows on it can be fed by the measured
 * `weather` engine, so a stopped engine's tab can look perfectly healthy. "The tab is empty,
 * therefore something is wrong" is not a rule that survives contact with this product. The engine's
 * state is the fact, and the tab is only where the absence shows up.
 *
 * Deliberately NOT rendered: the engine's opportunity count, on either state. Neither has one *here*,
 * and the figure is drawn as a dash with a reason rather than a zero, because `0` is the one value
 * that would read as a search that ran and found nothing. For a quarantined engine the count EXISTS
 * and is on the quarantine surface, with the split between real opportunities and artefacts -- a
 * bare total on this panel would throw away the only part of the number anybody could act on.
 */
export interface StoppedEnginesNoticeProps {
  health: EngineHealthResponse | null;
  /** A failed read of the ruling. When set, nothing is claimed about which engines are stopped. */
  readError?: string | null;
  className?: string;
}

export function StoppedEnginesNotice({ health, readError = null, className = "" }: StoppedEnginesNoticeProps) {
  // A failed read outranks everything, including a non-empty bucket. Claim nothing rather than
  // claim from a read that did not complete: the ruling is a list, and an empty list from a
  // failure is indistinguishable from a product with nothing stopped.
  if (readError) {
    return (
      <section
        aria-label="Engine states could not be read"
        data-testid="engine-health-read-failure"
        className={`rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 ${className}`}
      >
        <div className="flex items-center gap-2">
          <AlertOctagon className="h-4 w-4 text-rose-400" aria-hidden="true" />
          <h2 className="text-sm font-bold uppercase tracking-widest text-rose-200">
            Could not read which engines are running
          </h2>
        </div>
        <p className="mt-1 text-xs text-rose-100/80">{readError}</p>
        <p className="mt-1 text-xs text-rose-100/70">
          This is a failed read, not an empty one. Nothing is claimed here: not that engines are
          stopped, and not that none are. An empty board on this page is therefore not established
          as a finding about the market.
        </p>
      </section>
    );
  }

  // Two buckets, kept apart because they are different facts. `stopped` is a broken engine and
  // nothing was measured. `quarantined` is a repaired engine that measured and had the measurement
  // withheld. The filter is on the server's own `state` and is a lookup, not a rule.
  const stopped = (health?.edge_types ?? []).filter((entry) => entry.state === "could_not_run");
  const quarantined = (health?.edge_types ?? []).filter((entry) => entry.state === "quarantined");
  // An empty bucket renders nothing at all. There is no "0 stopped engines" line: a placeholder for
  // an absence is the same noise this component exists to remove, and the count that matters is
  // non-zero by definition. A missing ruling is not an absence though -- it is a fault -- and it
  // gets said, because a page that says nothing about which engines run is the defect.
  if (!health) {
    return (
      <section
        aria-label="Engine states did not arrive"
        data-testid="engine-health-missing"
        className={`rounded-xl border border-amber-900/50 bg-amber-950/20 p-4 ${className}`}
      >
        <p className="text-sm font-bold uppercase tracking-widest text-amber-200">
          Engine states did not arrive
        </p>
        <p className="mt-1 text-xs text-amber-100/70">
          Nothing is claimed about which engines are running. An empty board above is not
          established as a finding until the ruling arrives.
        </p>
      </section>
    );
  }
  if (stopped.length === 0 && quarantined.length === 0) return null;

  // The frame is the WORSE of the two states, never the better one. A page with one quarantined
  // board and one broken board is in the broken state, and colouring it amber would tell a reader
  // the product is in better shape than it is -- a quarantined board has a question open, a broken
  // one has no data at all.
  const broken = stopped.length > 0;
  const shell = broken
    ? "border-rose-900/60 bg-rose-950/20"
    : "border-amber-600/50 bg-amber-950/20";
  const heading = broken ? "text-rose-200" : "text-amber-200";

  return (
    <section
      aria-label={broken ? "Engines that could not run" : "Engines that are quarantined"}
      data-testid={broken ? "stopped-engines" : "quarantined-engines"}
      className={`rounded-xl border ${shell} p-4 ${className}`}
    >
      <div className="flex items-center gap-2">
        {broken ? (
          <AlertOctagon className="h-4 w-4 text-rose-400" aria-hidden="true" />
        ) : (
          <FlaskConical className="h-4 w-4 text-amber-400" aria-hidden="true" />
        )}
        {/* Both counts are the SERVER's, and they are printed separately rather than summed.
            Summing them would produce a number nobody could act on: "2 of 5 boards are not
            working" is true and useless when one of the two is working perfectly well and has simply
            had its output withheld. */}
        <h2 className={`text-sm font-bold uppercase tracking-widest ${heading}`}>
          {health.edge_types_could_not_run} of {health.edge_types_total} boards are fed by an engine
          that is {STOPPED_WORD}
        </h2>
      </div>

      {/* The quarantined count on its OWN line, not folded into the heading above it. A reader who
          has to pick a count out of a sentence carrying two of them will read the wrong one, and
          the wrong one here is "0 of 5 boards are not working" -- the healthy-looking summary this
          panel was built to stop showing. */}
      {health.edge_types_quarantined > 0 && (
        <p className="mt-1 text-[10px] uppercase tracking-wider text-amber-300/80">
          {health.edge_types_quarantined} of {health.edge_types_total} boards are {QUARANTINED_WORD} —
          they ran, and their output is withheld rather than published
        </p>
      )}

      <p className="mt-1 text-xs text-rose-100/70">{health.note}</p>
      <p className="mt-1 text-[10px] uppercase tracking-wider text-rose-200/60">
        {edgeTypesText(health)}
      </p>

      {[...stopped, ...quarantined].map((entry) => {
        const wired = entry.stopped_sites.filter((site) => site.wired_to_a_scanner);
        const unwired = entry.stopped_sites.filter((site) => !site.wired_to_a_scanner);
        return (
          <div key={entry.edge_type} className="mt-3 border-t border-rose-900/40 pt-3">
            {/* The state word is the server's decision, read from the entry rather than re-derived,
                and it is what keeps the two buckets from being read as one. A quarantined engine
                saying "not running" here would be a false claim about an engine that measured 295
                rows. */}
            <p className="font-mono text-xs font-bold text-rose-300">
              {entry.edge_type} · {entry.label} ·{" "}
              {entry.state === "quarantined" ? QUARANTINED_WORD : STOPPED_WORD}
            </p>
            {/* The reason, in the words a reader actually reads. A bare state is jargon, and the
                mechanism is the finding: this is a broken reader of a moved API, not a market with
                no opportunity in it. */}
            <p className="mt-1 text-xs leading-relaxed text-rose-100/90">{entry.reason}</p>
            <p className="mt-2 text-[10px] uppercase tracking-wider text-rose-200/60">
              Opportunities found:{" "}
              <span className="font-mono" title={opportunitiesFoundReason(entry) ?? undefined}>
                {opportunitiesFoundText(entry)}
              </span>{" "}
              — {opportunitiesFoundReason(entry)}
            </p>
            {/* Where the measurement lives, for a quarantined engine. The count is not on this panel
                and this is the pointer to it -- 26 independent opportunities, with the split
                between real ones and units artefacts, on /api/quarantine. Repeating the number here
                would put two counts of one fact on two screens and this one would have lost the
                split on the way. */}
            {quarantineSinkOf(entry) && (
              <p className="mt-1 text-[10px] uppercase tracking-wider text-amber-300/70">
                Measured output: {quarantineSinkOf(entry)} (shown on /api/quarantine)
              </p>
            )}
            <ul className="mt-2 space-y-1">
              {wired.map((site) => (
                <li key={site.site} className="text-xs text-rose-100/80">
                  <span className="font-mono font-bold">{site.name}</span>
                  <span className="text-rose-100/50">
                    {" "}
                    · on the scan path · {site.site}
                  </span>
                  {/* The disposition, on the same line as the site. This list holds a repaired
                      engine and two unrepaired helpers now, and a site with no disposition on screen
                      reads as a live defect -- which is the defect this panel was built to remove,
                      reintroduced in the panel itself. */}
                  <span className={site.disposition === "repaired_quarantined" ? "text-amber-300/70" : "text-rose-300/60"}>
                    {" "}
                    · {site.disposition === "repaired_quarantined" ? "repaired, output quarantined" : "not repaired"}
                  </span>
                </li>
              ))}
              {/* Unwired sites are listed too, and kept separate. They are real defects a maintainer
                  has to see, and they are NOT the reason this board is empty -- nothing calls
                  them. Saying so next to each one is what stops the list being read as a cause. */}
              {unwired.map((site) => (
                <li key={site.site} className="text-xs text-rose-100/60">
                  <span className="font-mono font-bold">{site.name}</span>
                  <span className="text-rose-100/40">
                    {" "}
                    · not wired to any scanner, so not a cause of an empty board · {site.site}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

export { NOT_MEASURED };
export default StoppedEnginesNotice;

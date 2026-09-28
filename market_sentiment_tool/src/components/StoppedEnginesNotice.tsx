import { AlertOctagon } from "lucide-react";

import {
  STOPPED_WORD,
  edgeTypesText,
  opportunitiesFoundReason,
  opportunitiesFoundText,
  type EngineHealthResponse,
} from "@/lib/engineHealth";
import { NOT_MEASURED } from "@/lib/edgeFigures";

/**
 * The half of the stopped-engine ruling that only a page can close.
 *
 * `/api/engine-health` knows which engines cannot run. Knowing it is not the same as having said
 * it, and the reason this component exists is the same reason `WithheldEdgesNotice` exists: a fact
 * that is held but not rendered is, to a reader, indistinguishable from the fact not being true.
 *
 * The specific lie this removes is the EMPTY TAB. "No high-confidence edges detected in weather"
 * is a finding. It was being printed for an engine that had not looked at anything, because
 * `WeatherEngine` prices every market off `yes_ask`, Kalshi stopped sending that key, and the `0`
 * default made every market look unpriceable -- so the engine skipped all of them and published
 * nothing without raising anything. Failing closed is why nothing wrong reached the ledger; it is
 * also why nothing reached the reader.
 *
 * Rendered UNCONDITIONALLY when the ruling says an engine is stopped, and not only when the tab
 * happens to be empty. That is deliberate and it is the one thing worth being strict about here: a
 * MACRO tab with rows on it is fed by `labor_nowcast` and a WEATHER tab with rows on it can be fed
 * by the measured `weather` engine, so a stopped engine's tab can look perfectly healthy. "The tab
 * is empty, therefore something is wrong" is not a rule that survives contact with this product.
 * The engine's state is the fact, and the tab is only where the absence shows up.
 *
 * Deliberately NOT rendered: the stopped engine's opportunity count. It does not have one, and the
 * figure is drawn as a dash with a reason rather than a zero, because `0` is the one value that
 * would read as a search that ran and found nothing.
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

  const stopped = (health?.edge_types ?? []).filter((entry) => entry.state === "could_not_run");
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
  if (stopped.length === 0) return null;

  return (
    <section
      aria-label="Engines that could not run"
      data-testid="stopped-engines"
      className={`rounded-xl border border-rose-900/60 bg-rose-950/20 p-4 ${className}`}
    >
      <div className="flex items-center gap-2">
        <AlertOctagon className="h-4 w-4 text-rose-400" aria-hidden="true" />
        {/* The count is the SERVER's. Counting the filtered list here would be a second copy of a
            number the response already resolved, and this is the page whose whole job is that one
            number exists once. */}
        <h2 className="text-sm font-bold uppercase tracking-widest text-rose-200">
          {health.edge_types_could_not_run} of {health.edge_types_total} boards are fed by an
          engine that is {STOPPED_WORD}
        </h2>
      </div>

      <p className="mt-1 text-xs text-rose-100/70">{health.note}</p>
      <p className="mt-1 text-[10px] uppercase tracking-wider text-rose-200/60">
        {edgeTypesText(health)}
      </p>

      {stopped.map((entry) => {
        const wired = entry.stopped_sites.filter((site) => site.wired_to_a_scanner);
        const unwired = entry.stopped_sites.filter((site) => !site.wired_to_a_scanner);
        return (
          <div key={entry.edge_type} className="mt-3 border-t border-rose-900/40 pt-3">
            <p className="font-mono text-xs font-bold text-rose-300">
              {entry.edge_type} · {entry.label} · {STOPPED_WORD}
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
            <ul className="mt-2 space-y-1">
              {wired.map((site) => (
                <li key={site.site} className="text-xs text-rose-100/80">
                  <span className="font-mono font-bold">{site.name}</span>
                  <span className="text-rose-100/50">
                    {" "}
                    · on the scan path · {site.site}
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

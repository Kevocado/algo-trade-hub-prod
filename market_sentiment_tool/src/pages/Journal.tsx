import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import { GateBadge } from "@/components/GateBadge";
import { QuarantineNotice } from "@/components/QuarantineNotice";
import { useQuarantine } from "@/hooks/useQuarantine";
import {
  EXPERIMENTAL,
  biasReadout,
  brierText,
  key,
  pct,
  settledText,
  skillText,
  tiles,
  type JournalFeed,
  type JournalResponse,
  type JournalScore,
} from "@/lib/journal";

/**
 * /journal, the flagship (v2 spec §11): every forecaster's frozen, settled, scored record.
 *
 * Three blocks: the ledger hero (server headline, calibrated forecasters only), one tile per
 * forecaster with its Kalshi pseudo-forecaster beneath it in the same units, and the quarantine
 * section. A forecaster appears from its first frozen row (display gate); nothing here filters,
 * sorts by skill, or hides a losing forecaster, and nothing here computes a score.
 */

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(buildApiUrl(path));
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
  return payload as T;
}

function ScoreLines({ score, label }: { score: JournalScore; label?: string }) {
  return (
    <div className="space-y-1 text-sm">
      {label && <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>}
      <p className="font-mono text-2xl text-white" aria-label={`Brier ${key(score)}`}>
        {brierText(score.brier)}
      </p>
      <p className="text-slate-300">{skillText(score)}</p>
      <p className="text-slate-500">{settledText(score)}</p>
    </div>
  );
}

function Calibration({ score }: { score: JournalScore }) {
  if (!score.reliability.length) return <p className="text-xs text-slate-500">No settled targets yet.</p>;
  const bias = biasReadout(score.reliability);
  return (
    <div className="mt-3">
      <table className="w-full text-xs text-slate-300" aria-label={`Calibration ${key(score)}`}>
        <thead className="text-slate-500">
          <tr>
            <th className="text-left font-normal">Confidence</th>
            <th className="text-right font-normal">n</th>
            <th className="text-right font-normal">Predicted</th>
            <th className="text-right font-normal">Observed</th>
          </tr>
        </thead>
        <tbody>
          {score.reliability.map((b) => (
            <tr key={b.bucket}>
              <td>{b.bucket}%</td>
              <td className="text-right">{b.n}</td>
              <td className="text-right">{pct(b.predicted)}</td>
              <td className="text-right">{pct(b.observed)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {bias && <p className="mt-1 text-xs text-slate-400">{bias}</p>}
    </div>
  );
}

function Feed({ score }: { score: JournalScore }) {
  const [feed, setFeed] = useState<JournalFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const q = new URLSearchParams({ forecaster: score.forecaster, version: score.forecaster_version, limit: "20" });
    getJson<JournalFeed>(`/api/journal/feed?${q}`).then(setFeed).catch((e: Error) => setError(e.message));
  }, [score.forecaster, score.forecaster_version]);
  if (error) return <p className="text-xs text-rose-300">Frozen forecasts unavailable: {error}</p>;
  if (!feed) return <p className="text-xs text-slate-500">Loading frozen forecasts…</p>;
  return (
    <table className="mt-3 w-full text-xs text-slate-300" aria-label={`Frozen forecasts ${key(score)}`}>
      <thead className="text-slate-500">
        <tr>
          <th className="text-left font-normal">Target</th>
          <th className="text-right font-normal">Model</th>
          <th className="text-right font-normal">Market</th>
          <th className="text-right font-normal">Frozen</th>
        </tr>
      </thead>
      <tbody>
        {feed.forecasts.map((f) => (
          <tr key={f.target} className={f.rebuilt ? "line-through text-slate-600" : ""}>
            <td className="font-mono">{f.target}</td>
            <td className="text-right">{pct(f.probability)}</td>
            <td className="text-right">{pct(f.market_prob)}</td>
            <td className="text-right">{f.frozen_at.slice(0, 16).replace("T", " ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Journal() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const { data: quarantine, error: quarantineError } = useQuarantine();

  useEffect(() => {
    getJson<JournalResponse>("/api/journal").then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
          <p className="font-semibold">Journal unavailable</p>
          <p className="mt-1 text-rose-300/80">{error}</p>
        </div>
      </div>
    );
  }
  if (!data) return <div className="p-8 text-slate-400">Loading journal…</div>;

  const h = data.headline;
  return (
    <div className="space-y-8 p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Prediction Journal</h1>
        <p className="mt-2 max-w-3xl text-slate-400">
          Every forecast is frozen before its cutoff, settled against a public source, and scored against the
          market where one exists (climatology where not). Nothing is backfilled.
        </p>
        <p className="mt-4 text-slate-200" aria-label="Headline">
          {h.calibrated} of {h.forecasters} forecasters calibrated · {h.settled_calibrated} settled targets across
          calibrated forecasters · {h.promoted} promoted
        </p>
      </header>

      {data.forecasters.length === 0 ? (
        <p className="text-slate-400">No forecaster has frozen a forecast yet.</p>
      ) : (
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Forecasters">
          {tiles(data.forecasters).map(({ model, market }) => (
            <article key={key(model)} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 className="font-mono text-sm text-slate-100">{key(model)}</h2>
                <div className="flex items-center gap-2">
                  {EXPERIMENTAL.has(model.forecaster) && (
                    <span className="text-[10px] uppercase tracking-wider text-amber-300">experimental</span>
                  )}
                  {!model.calibration_ready && (
                    <span className="text-[10px] uppercase tracking-wider text-slate-400">provisional</span>
                  )}
                  <GateBadge edge={{ gate_status: model.gate_status }} />
                </div>
              </div>
              <ScoreLines score={model} />
              {market && (
                <div className="mt-3 border-t border-slate-800 pt-3">
                  <ScoreLines score={market} label={`Kalshi-implied (${key(market)})`} />
                </div>
              )}
              {model.gate_reasons.length > 0 && (
                <ul className="mt-3 list-disc pl-4 text-xs text-slate-500">
                  {model.gate_reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
              <Calibration score={model} />
              <button
                type="button"
                className="mt-3 text-xs text-sky-300 underline"
                onClick={() => setOpen(open === key(model) ? null : key(model))}
              >
                {open === key(model) ? "Hide frozen forecasts" : "Show frozen forecasts"}
              </button>
              {open === key(model) && <Feed score={model} />}
            </article>
          ))}
        </section>
      )}

      <section aria-label="Quarantine">
        <h2 className="mb-2 text-lg font-semibold text-slate-200">Quarantine</h2>
        <p className="mb-2 text-sm text-slate-500">Scored in public, excluded from every headline number above.</p>
        <QuarantineNotice payload={quarantine} readError={quarantineError} />
      </section>
    </div>
  );
}

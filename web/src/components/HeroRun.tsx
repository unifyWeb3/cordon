"use client";

import { useEffect, useRef, useState } from "react";
import sample from "@/lib/sample-run.json";
import { LIFECYCLE_ORDER } from "@/lib/genlayer";
import { verdictBlurb } from "@/lib/content";

/**
 * The hero vignette, replayed as a loop. Follows the HeroLive pattern: a real recorded run
 * played back in order, with real durations compressed so it fits in a glance.
 *
 * The server renders the FINISHED state. The loop only starts after hydration, so a visitor with
 * JS disabled, a crawler, or a screenshot tool sees the complete story rather than a blank frame.
 * That is also why nothing here is required to understand the page -- it is the evidence, not the
 * explanation.
 *
 * Every figure on screen is the run's own. The loop decides only when each step comes into view.
 */

type Segment = { state: string; startedAt: number; endedAt: number };
type Case = {
  id: string;
  targetChainTx: string;
  verdict: string;
  rationale: string;
  states: string[];
  trail: Segment[];
  evidence: Record<string, string | boolean | null>;
  timing: { toAcceptedMs: number | null; toFinalizedMs: number | null; consensus: string | null };
};

const CASES = sample.cases as unknown as Case[];
const LEAD = CASES.find((c) => c.id === "live-real-tx-run2") ?? CASES[0];

// The recorded run took 63.0s. Played at this scale it runs about 14s, which is long enough to
// read and short enough that a visitor does not decide it is broken.
const SCALE = 0.22;
const HOLD_MS = 3600;
const RESET_MS = 520;
const MIN_SEGMENT_MS = 420;

const ENDS = LEAD.trail.reduce<number[]>((acc, seg) => {
  const prev = acc[acc.length - 1] ?? 0;
  acc.push(prev + Math.max(MIN_SEGMENT_MS, (seg.endedAt - seg.startedAt) * SCALE));
  return acc;
}, []);
const LAST = ENDS[ENDS.length - 1] ?? 0;
const CYCLE = LAST + HOLD_MS + RESET_MS;

const BEATS: { key: string; label: string; detail: string }[] = [
  { key: "submitted", label: "Proof submitted", detail: "Anyone can propose a freeze" },
  { key: "reading", label: "Reading chain state", detail: "One batched JSON-RPC call" },
  { key: "comparing", label: "Validators re-run and compare", detail: "Verdict enum only" },
  { key: "verdict", label: "Verdict arrives", detail: "" },
];

function verdictColour(v: string): { fg: string; bg: string } {
  if (v === "CONFIRMED_EXPLOIT") return { fg: "var(--v-confirmed)", bg: "var(--v-confirmed-bg)" };
  if (v === "FALSE_REPORT") return { fg: "var(--v-false)", bg: "var(--v-false-bg)" };
  return { fg: "var(--v-insufficient)", bg: "var(--v-insufficient-bg)" };
}

export function HeroRun() {
  // Finished first, on purpose. See the note above.
  const [step, setStep] = useState<number>(BEATS.length);
  const [resetting, setResetting] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let raf = 0;
    const t0 = performance.now() + 900 - (LAST + HOLD_MS);
    const tick = (now: number) => {
      const t = ((now - t0) % CYCLE + CYCLE) % CYCLE;
      if (t >= LAST + HOLD_MS) {
        setStep(BEATS.length);
        setResetting(true);
      } else {
        let done = 0;
        while (done < ENDS.length && ENDS[done] <= t) done += 1;
        setStep((prev) => (prev === done ? prev : done));
        setResetting(false);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const reached = (n: number) => step >= n;
  const lc = verdictColour(LEAD.verdict);
  const acc = LEAD.timing.toAcceptedMs;
  const fin = LEAD.timing.toFinalizedMs;

  return (
    <section
      className="card"
      style={{ opacity: resetting ? 0.35 : 1, transition: "opacity 220ms ease" }}
      aria-label="Replay of a real recorded adjudication"
    >
      <div className="eyebrow" style={{ marginBottom: 14 }}>Fig. 1 — one real adjudication</div>

      <div className="grid-2" style={{ alignItems: "start" }}>
        {/* beats */}
        <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 10 }}>
          {BEATS.map((b, i) => {
            const on = reached(i);
            const active = step === i;
            return (
              <li
                key={b.key}
                style={{
                  display: "grid",
                  gridTemplateColumns: "26px 1fr",
                  gap: 12,
                  opacity: on ? 1 : 0.32,
                  transition: "opacity 200ms ease",
                }}
              >
                <span
                  className="mono"
                  style={{
                    color: active ? "var(--accent)" : "var(--muted)",
                    fontWeight: 700,
                    paddingTop: 1,
                  }}
                >
                  {i + 1}
                </span>
                <span>
                  <span style={{ display: "block", fontWeight: 600, fontSize: "var(--t-sm)" }}>
                    {b.label}
                  </span>
                  <span className="sub" style={{ display: "block", fontSize: "var(--t-xs)" }}>
                    {b.detail || verdictBlurb[LEAD.verdict]}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>

        {/* lifecycle + verdict */}
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div className="sub" style={{ fontSize: "var(--t-xs)", marginBottom: 6 }}>
              Lifecycle
            </div>
            <div className="stage">
              {LIFECYCLE_ORDER.map((st) => {
                const seen = LEAD.states.includes(st);
                const idx = LIFECYCLE_ORDER.indexOf(st);
                const done = reached(3) ? true : idx < Math.min(step, 3);
                const active = step >= 2 && idx === Math.min(step, 3) && step < 3;
                return (
                  <span
                    key={st}
                    className={`stage-step${done && seen ? " done" : ""}${active && seen ? " active" : ""}`}
                    style={seen ? undefined : { opacity: 0.3 }}
                  >
                    {st}
                  </span>
                );
              })}
            </div>
          </div>

          <div
            className="card-quiet"
            style={{
              borderColor: reached(3) ? lc.fg : "var(--line-soft)",
              background: reached(3) ? lc.bg : "var(--panel-2)",
              transition: "background 260ms ease, border-color 260ms ease",
            }}
          >
            <div className="sub" style={{ fontSize: "var(--t-xs)" }}>Verdict</div>
            <div
              className="mono"
              style={{
                color: reached(3) ? lc.fg : "var(--muted)",
                fontWeight: 700,
                fontSize: "var(--t-base)",
                marginTop: 2,
              }}
            >
              {reached(3) ? LEAD.verdict : "—"}
            </div>
            <div className="sub" style={{ fontSize: "var(--t-xs)", marginTop: 8 }}>
              {verdictBlurb[LEAD.verdict]}
            </div>
          </div>

          <dl className="kv">
            <dt>Accepted after</dt>
            <dd className="tnum">{acc !== null ? `${(acc / 1000).toFixed(1)} s` : "—"}</dd>
            <dt>Finalized after</dt>
            <dd className="tnum">{fin !== null ? `${(fin / 1000).toFixed(1)} s` : "—"}</dd>
            <dt>Consensus</dt>
            <dd>{LEAD.timing.consensus ?? "—"}</dd>
            <dt>Evidence</dt>
            <dd className="mono">
              value={String(LEAD.evidence.valueBand)} · logs={String(LEAD.evidence.logBand)}
            </dd>
          </dl>
        </div>
      </div>

      <hr className="rule" style={{ margin: "18px 0 12px" }} />

      <p className="sub" style={{ fontSize: "var(--t-xs)", lineHeight: 1.7 }}>
        A real adjudication on {sample.provenance.network} (chain {sample.provenance.chainId}),
        contract <span className="mono">{sample.provenance.contract}</span>, recorded{" "}
        {sample.provenance.recordedAt.slice(0, 10)}. Every figure above is the run&apos;s own; the
        loop only decides when each step comes into view, and the {LEAD.timing.toFinalizedMs
          ? `${(LEAD.timing.toFinalizedMs / 1000).toFixed(1)} s`
          : "—"}
        {" "}run is played at {SCALE}× speed.
      </p>
    </section>
  );
}

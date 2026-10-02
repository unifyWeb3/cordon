import sample from "@/lib/sample-run.json";
import { pivot } from "@/lib/content";

/**
 * The strongest argument the product has, told with its real numbers and its real outcome:
 * a drain-shaped transaction the committee would not confirm.
 */
export function Pivot() {
  const drain = sample.cases.find((c) => c.id === "live-drain-run2");
  const others = sample.cases.filter((c) => c.id !== "live-drain-run2");

  return (
    <section className="card">
      <div className="eyebrow">The case that matters most</div>
      <h2 style={{ fontSize: "var(--t-xl)", marginTop: 10, maxWidth: 720 }}>{pivot.headline}</h2>
      <p className="sub" style={{ marginTop: 12, maxWidth: 760, color: "var(--text-2)" }}>
        {pivot.body}
      </p>

      {drain ? (
        <div className="card-quiet" style={{ marginTop: 18 }}>
          <div className="grid-2">
            <dl className="kv">
              <dt>Repeated events</dt>
              <dd className="mono">14 × Transfer (0xddf252ad…)</dd>
              <dt>Log band</dt>
              <dd className="mono">{String(drain.evidence.logBand)}</dd>
              <dt>Value band</dt>
              <dd className="mono">{String(drain.evidence.valueBand)}</dd>
              <dt>Selector</dt>
              <dd className="mono">{String(drain.evidence.inputSelector)}</dd>
            </dl>
            <dl className="kv">
              <dt>Leader rotations</dt>
              <dd className="tnum">
                {Math.max(0, drain.states.filter((s) => s === "PROPOSING").length - 1)}
              </dd>
              <dt>Accepted after</dt>
              <dd className="tnum">
                {drain.timing.toAcceptedMs !== null
                  ? `${(drain.timing.toAcceptedMs / 1000).toFixed(1)} s`
                  : "—"}
              </dd>
              <dt>Finalized after</dt>
              <dd className="tnum">
                {drain.timing.toFinalizedMs !== null
                  ? `${(drain.timing.toFinalizedMs / 1000).toFixed(1)} s`
                  : "—"}
              </dd>
              <dt>Verdict</dt>
              <dd className="mono" style={{ color: "var(--v-insufficient)" }}>{drain.verdict}</dd>
            </dl>
          </div>
          <p className="sub" style={{ marginTop: 12, fontSize: "var(--t-xs)" }}>
            <span style={{ color: "var(--text-2)" }}>Rationale:</span> {drain.rationale}
          </p>
        </div>
      ) : null}

      <div className="grid-3" style={{ marginTop: 16 }}>
        {others.map((c) => (
          <div key={c.id} className="card-quiet">
            <span
              className="pill"
              style={{
                background:
                  c.verdict === "FALSE_REPORT" ? "var(--v-false-bg)" : "var(--v-insufficient-bg)",
                color: c.verdict === "FALSE_REPORT" ? "var(--v-false)" : "var(--v-insufficient)",
              }}
            >
              {c.verdict}
            </span>
            <p className="sub" style={{ marginTop: 8, fontSize: "var(--t-xs)" }}>
              {c.verdict === "FALSE_REPORT"
                ? "A fabricated claim against a real transaction. The measured evidence contradicted it."
                : "A transaction hash that is not on the chain. Nothing to judge, so nothing was done."}
            </p>
            <div className="mono sub" style={{ marginTop: 6, fontSize: "var(--t-xs)" }}>
              accepted {(c.timing.toAcceptedMs ?? 0) / 1000}s · finalized{" "}
              {(c.timing.toFinalizedMs ?? 0) / 1000}s
            </div>
          </div>
        ))}
      </div>

      <p className="sub" style={{ marginTop: 16, color: "var(--text-2)" }}>{pivot.note}</p>
    </section>
  );
}

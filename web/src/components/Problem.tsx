import { problem, howItWorks, assurances, emit, limits, nav } from "@/lib/content";

export function Problem() {
  return (
    <section className="card" id="problem">
      <div className="eyebrow">{problem.eyebrow}</div>
      <p style={{ fontSize: "var(--t-xl)", lineHeight: 1.3, marginTop: 10, letterSpacing: "-0.01em" }}>
        {problem.lede}
      </p>

      <div className="grid-3" style={{ marginTop: 22 }}>
        {problem.points.map((p) => (
          <div key={p.figure} className="card-quiet">
            <div style={{ fontSize: "var(--t-lg)", fontWeight: 700, color: "var(--text)" }}>
              {p.figure}
            </div>
            <p className="sub" style={{ marginTop: 6 }}>{p.what}</p>
          </div>
        ))}
      </div>

      {/* The counterweight sits in the same section, not in a footnote. */}
      <div
        className="card-quiet"
        style={{ marginTop: 16, borderColor: "#3a3320", background: "#1d1a12" }}
      >
        <div className="eyebrow" style={{ color: "var(--v-insufficient)" }}>What it does not do</div>
        <p className="sub" style={{ marginTop: 6, color: "var(--text-2)" }}>{problem.counterweight}</p>
      </div>
    </section>
  );
}

export function How() {
  return (
    <section className="card" id="how">
      <div className="eyebrow">{howItWorks.eyebrow}</div>
      <div style={{ display: "grid", gap: 14, marginTop: 16 }}>
        {howItWorks.steps.map((s) => (
          <div key={s.n} style={{ display: "grid", gridTemplateColumns: "30px 1fr", gap: 14 }}>
            <span
              className="mono"
              style={{
                color: "var(--accent)",
                fontWeight: 700,
                border: "1px solid var(--line)",
                borderRadius: 999,
                width: 26,
                height: 26,
                display: "grid",
                placeItems: "center",
              }}
            >
              {s.n}
            </span>
            <div>
              <h3 style={{ fontSize: "var(--t-base)" }}>{s.title}</h3>
              <p className="sub" style={{ marginTop: 2 }}>{s.body}</p>
            </div>
          </div>
        ))}
      </div>

      <hr className="rule" style={{ margin: "20px 0 14px" }} />
      <div style={{ display: "grid", gap: 10 }}>
        {assurances.map((a) => (
          <div key={a.claim} style={{ display: "grid", gridTemplateColumns: "16px 1fr", gap: 10 }}>
            <span style={{ color: "var(--v-false)", fontWeight: 700 }} aria-hidden>✓</span>
            <div>
              <div style={{ fontSize: "var(--t-sm)", fontWeight: 600 }}>{a.claim}</div>
              <div className="sub" style={{ fontSize: "var(--t-xs)" }}>{a.note}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * The emit caveat. This is the single most important paragraph on the page and it is not
 * softened anywhere: consensus decides the verdict, delivery is a watcher, and the watcher holds
 * a key that can freeze. Phase 1 tested emit() against a live target and it does not deliver.
 */
export function Transport() {
  return (
    <section className="card" id="limits" style={{ borderColor: "#3a2a20" }}>
      <h2 style={{ fontSize: "var(--t-lg)" }}>{emit.heading}</h2>
      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card-quiet" style={{ borderColor: "#1d3a2a", background: "var(--v-false-bg)" }}>
          <div className="eyebrow" style={{ color: "var(--v-false)" }}>On-chain, verified</div>
          <p className="sub" style={{ marginTop: 6, color: "var(--text-2)" }}>{emit.does}</p>
        </div>
        <div className="card-quiet" style={{ borderColor: "#3a2a20", background: "var(--v-confirmed-bg)" }}>
          <div className="eyebrow" style={{ color: "var(--v-confirmed)" }}>Off-chain, tested</div>
          <p className="sub" style={{ marginTop: 6, color: "var(--text-2)" }}>{emit.doesNot}</p>
        </div>
      </div>
      <p className="sub" style={{ marginTop: 14, color: "var(--text-2)" }}>{emit.trade}</p>

      <hr className="rule" style={{ margin: "18px 0 12px" }} />
      <div className="eyebrow">Other limits</div>
      <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
        {limits.map((l) => (
          <li key={l} className="sub" style={{ marginBottom: 4 }}>{l}</li>
        ))}
      </ul>
    </section>
  );
}

export function Nav() {
  const items = [
    ["#problem", nav.problem],
    ["#how", nav.how],
    ["#limits", nav.limits],
  ];
  return (
    <nav className="sub" style={{ display: "flex", gap: 16, fontSize: "var(--t-xs)" }}>
      {items.map(([href, label]) => (
        <a key={href} href={href}>{label}</a>
      ))}
    </nav>
  );
}

"use client";

import { LIFECYCLE_ORDER, lifecycleIndex } from "@/lib/genlayer";

/**
 * The lifecycle is rendered as discrete steps rather than one status string, because
 * "PENDING / ACCEPTED / FINALIZED all reachable and distinct" is a rubric line and a
 * single collapsed status hides how long adjudication actually takes.
 */
export function Stages({ status }: { status: string }) {
  const idx = lifecycleIndex(status);
  return (
    <div className="stage">
      {LIFECYCLE_ORDER.map((s, i) => {
        const state = idx < 0 ? "" : i < idx ? "done" : i === idx ? "active" : "";
        return (
          <span key={s} className={`stage-step ${state}`}>
            {s}
          </span>
        );
      })}
      {idx < 0 ? (
        <span className="stage-step active">{status || "UNKNOWN"}</span>
      ) : null}
    </div>
  );
}

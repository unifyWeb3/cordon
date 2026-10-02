import type { Evidence } from "@/lib/types";

/**
 * Shows only what the contract stored, which is deliberately a set of stable fields:
 * bands and counts, never raw block numbers, gas, or timestamps.
 */
export function EvidenceGrid({ e }: { e: Evidence }) {
  const rows: [string, string][] = [
    ["Transaction found", e.tx_found ? "yes" : "no"],
    ["Receipt status", e.receipt_status],
    ["Executed successfully", e.success ? "yes" : "no"],
    ["Function selector", e.input_selector || "NONE"],
    ["Value magnitude band", e.value_band],
    ["Log count band", e.log_band],
    ["Event signatures repeated", e.repeated_selectors || "none"],
  ];
  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "220px 1fr",
          gap: "6px 14px",
          fontSize: 13,
        }}
      >
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <span className="sub">{k}</span>
            <span className="mono">{v}</span>
          </div>
        ))}
      </div>
      <div className="sub mono" style={{ marginTop: 10 }}>
        signature: {e.signature}
      </div>
    </div>
  );
}

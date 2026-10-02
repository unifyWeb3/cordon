import { notFound } from "next/navigation";
import { CONTRACT_ADDRESS, TARGET_CHAIN_EXPLORER, readClient } from "@/lib/genlayer";
import type { Proof } from "@/lib/types";

/**
 * A shareable per-case artefact: one link that shows a single verdict with its evidence.
 *
 * force-dynamic is required. Without it Next prerenders this route at build time, which means a
 * network call during the build -- the build then fails whenever the RPC is slow or down, for a
 * page whose whole purpose is to show live chain state.
 */
export const dynamic = "force-dynamic";

export default async function CasePage({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = await params;

  let proof: Proof;
  try {
    proof = (await readClient().readContract({
      address: CONTRACT_ADDRESS,
      functionName: "get_evidence",
      args: [caseId],
    })) as unknown as Proof;
  } catch {
    notFound();
  }

  const e = proof.evidence;
  const colour =
    proof.verdict === "CONFIRMED_EXPLOIT"
      ? ["var(--v-confirmed)", "var(--v-confirmed-bg)"]
      : proof.verdict === "FALSE_REPORT"
        ? ["var(--v-false)", "var(--v-false-bg)"]
        : ["var(--v-insufficient)", "var(--v-insufficient-bg)"];

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
    <main>
      <a href="/" className="sub" style={{ fontSize: "var(--t-xs)" }}>&#8592; all cases</a>

      <header style={{ marginTop: 18 }}>
        <div className="eyebrow">Cordon &#183; adjudicated freeze</div>
        <h1 style={{ fontSize: "var(--t-2xl)", marginTop: 10 }} className="mono">
          {proof.case_id}
        </h1>
        <span
          className="pill"
          style={{ background: colour[1], color: colour[0], marginTop: 14 }}
        >
          {proof.verdict}
        </span>
      </header>

      <section className="card" style={{ marginTop: 22 }}>
        <div className="eyebrow">Rationale &#8212; stored, never compared across models</div>
        <p style={{ marginTop: 8 }}>{proof.rationale || "(none)"}</p>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="eyebrow">Evidence &#8212; stable fields only</div>
        <dl className="kv" style={{ marginTop: 12 }}>
          {rows.map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt>{k}</dt>
              <dd className="mono">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="mono sub" style={{ marginTop: 14, fontSize: "var(--t-xs)" }}>
          signature: {e.signature}
        </div>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="eyebrow">Freeze</div>
        <dl className="kv" style={{ marginTop: 12 }}>
          <dt>Frozen</dt>
          <dd>{proof.frozen ? "yes" : "no"}</dd>
          <dt>expires_at</dt>
          <dd className="mono">{proof.expires_at || "&#8212;"}</dd>
          <dt>unfrozen_at</dt>
          <dd className="mono">{proof.unfrozen_at || "&#8212;"}</dd>
          <dt>Validator agreed</dt>
          <dd>{String(proof.validator_agreed)}</dd>
          <dt>Submitted</dt>
          <dd className="mono">{proof.submitted_at}</dd>
          <dt>Submitter</dt>
          <dd className="mono">{proof.submitter}</dd>
          <dt>Evidence mode</dt>
          <dd className="mono">{proof.evidence_mode}</dd>
        </dl>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="eyebrow">Artefacts</div>
        <div className="mono" style={{ marginTop: 10 }}>
          <div>target: {proof.target}</div>
          <div>
            evidence tx:{" "}
            <a href={`${TARGET_CHAIN_EXPLORER}/tx/${proof.tx_hash}`} target="_blank" rel="noreferrer">
              {proof.tx_hash} &#8599;
            </a>
          </div>
          <div>contract: {CONTRACT_ADDRESS}</div>
        </div>
        <p className="sub" style={{ fontSize: "var(--t-xs)", marginTop: 14 }}>
          Submitted claim &#8212; untrusted text, weighed as data: {proof.claim}
        </p>
      </section>
    </main>
  );
}

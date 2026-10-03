import Link from "next/link";
import { notFound } from "next/navigation";
import { CONTRACT_ADDRESS, TARGET_CHAIN_EXPLORER } from "@/lib/genlayer";
import { readCase } from "@/lib/chain";
import type { Proof } from "@/lib/types";

/**
 * A shareable per-case artefact: one link that shows a single verdict with its evidence.
 *
 * force-dynamic, so the build never makes a network call — a build-time RPC call fails the whole
 * build whenever the endpoint is slow or rate limiting, which is not a build's problem to have.
 * Caching and retry live in readCase() instead.
 */
export const dynamic = "force-dynamic";

function VerdictPill({ verdict }: { verdict: string }) {
  const colour =
    verdict === "CONFIRMED_EXPLOIT"
      ? ["var(--v-confirmed)", "var(--v-confirmed-bg)"]
      : verdict === "FALSE_REPORT"
        ? ["var(--v-false)", "var(--v-false-bg)"]
        : ["var(--v-insufficient)", "var(--v-insufficient-bg)"];
  return (
    <span className="pill" style={{ background: colour[1], color: colour[0] }}>
      {verdict}
    </span>
  );
}

/**
 * A read that failed for a reason other than "no such case".
 *
 * Rendering 404 here would be a lie: the case may well exist, the endpoint is just refusing to
 * answer right now. Saying so is more useful than a dead end, and it keeps a shared-endpoint
 * outage from masquerading as a broken product.
 */
function Unreachable({ kind, message }: { kind: string; message: string }) {
  return (
    <main>
      <Link href="/" className="sub" style={{ fontSize: "var(--t-xs)" }}>
        &larr; all cases
      </Link>
      <section className="card" style={{ marginTop: 22, borderColor: "#3a3320" }}>
        <div className="eyebrow" style={{ color: "var(--v-insufficient)" }}>
          {kind === "rate-limited" ? "Chain endpoint rate limited" : "Could not reach the chain"}
        </div>
        <h1 style={{ fontSize: "var(--t-xl)", marginTop: 10 }}>
          This case exists, we just could not fetch it.
        </h1>
        <p className="sub" style={{ marginTop: 12, maxWidth: 640, color: "var(--text-2)" }}>
          {kind === "rate-limited"
            ? "studio.genlayer.com limits requests per minute and is shared between everyone. This is not a missing case — reload in a few seconds."
            : "The read did not complete. Reload, or read the same record directly from the contract."}
        </p>
        <p className="mono sub" style={{ marginTop: 14, fontSize: "var(--t-xs)" }}>
          contract {CONTRACT_ADDRESS}
        </p>
        <p className="mono sub" style={{ fontSize: "var(--t-xs)" }}>
          detail: {message.slice(0, 200)}
        </p>
      </section>
    </main>
  );
}

export default async function CasePage({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = await params;
  const res = await readCase(caseId);

  if (!res.ok) {
    // A real 404, with a real HTTP status. This is the only path allowed to claim absence.
    if (res.kind === "unknown-case") notFound();
    // Everything else renders. Telling someone a case does not exist when it does is the one
    // failure a shareable link cannot recover from.
    return <Unreachable kind={res.kind} message={res.message} />;
  }

  const proof = res.value as Proof;
  const e = proof.evidence;

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
      <Link href="/" className="sub" style={{ fontSize: "var(--t-xs)" }}>
        &larr; all cases
      </Link>

      <header style={{ marginTop: 18 }}>
        <div className="eyebrow">Cordon &#183; adjudicated freeze</div>
        <h1 className="mono" style={{ fontSize: "var(--t-2xl)", marginTop: 10 }}>
          {proof.case_id}
        </h1>
        <span style={{ display: "inline-block", marginTop: 14 }}>
          <VerdictPill verdict={proof.verdict} />
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

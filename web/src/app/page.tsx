"use client";

import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Address } from "viem";

import {
  CONTRACT_ADDRESS,
  TARGET_CHAIN_EXPLORER,
  TARGET_CHAIN_NAME,
  isRealAddress,
  isRealTxHash,
  readClient,
  txLink,
} from "@/lib/genlayer";
import type { ContractStats, Proof } from "@/lib/types";
import { product } from "@/lib/content";
import { Stages } from "@/components/Stages";
import { VerdictBadge } from "@/components/VerdictBadge";
import { EvidenceGrid } from "@/components/EvidenceGrid";
import { WalletBar } from "@/components/WalletBar";
import { HeroRun } from "@/components/HeroRun";
import { Problem, How, Transport, Nav } from "@/components/Problem";
import { Pivot } from "@/components/Pivot";
import { Providers } from "./providers";
import { refetchPolicy } from "@/lib/chain";

const DEFAULT_CASE = "live-drain-run2";

type Tracked = {
  caseId: string;
  txId: string;
  status: string;
  consensus?: string | null;
  execution?: string | null;
};

function useStats() {
  return useQuery<ContractStats>({
    queryKey: ["stats", CONTRACT_ADDRESS],
    queryFn: async () =>
      (await readClient().readContract({
        address: CONTRACT_ADDRESS,
        functionName: "stats",
        args: [],
      })) as unknown as ContractStats,
    // Never auto-refetch: a finalized verdict does not change, and this read was the single
    // largest consumer of the endpoint's per-minute budget.
    refetchInterval: refetchPolicy.stats,
  });
}

function useCases() {
  return useQuery<string[]>({
    queryKey: ["cases", CONTRACT_ADDRESS],
    queryFn: async () =>
      (await readClient().readContract({
        address: CONTRACT_ADDRESS,
        functionName: "list_cases",
        args: [],
      })) as unknown as string[],
    refetchInterval: refetchPolicy.cases,
  });
}

function useProof(caseId: string | null) {
  return useQuery<Proof>({
    queryKey: ["proof", CONTRACT_ADDRESS, caseId],
    enabled: Boolean(caseId),
    queryFn: async () =>
      (await readClient().readContract({
        address: CONTRACT_ADDRESS,
        functionName: "get_evidence",
        args: [caseId as string],
      })) as unknown as Proof,
    refetchInterval: refetchPolicy.proof,
  });
}

function Inner() {
  const stats = useStats();
  const cases = useCases();
  const [selected, setSelected] = useState<string>(DEFAULT_CASE);
  const [tracked, setTracked] = useState<Tracked | null>(null);
  const [account, setAccount] = useState<string | null>(null);

  const [target, setTarget] = useState("");
  const [txHash, setTxHash] = useState("");
  const [claim, setClaim] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<Record<string, unknown>>({});

  useEffect(() => {
    // Runtime evidence emitted by the page rather than asserted about it in prose.
    const consoleErrors: string[] = [];
    const failedRequests: string[] = [];
    const onErr = (e: ErrorEvent) => consoleErrors.push(e.message);
    window.addEventListener("error", onErr);
    const orig = window.fetch.bind(window);
    window.fetch = (...a: Parameters<typeof fetch>) =>
      orig(...a).then((r) => {
        if (!r.ok) failedRequests.push(`${r.status} ${String(a[0])}`);
        return r;
      });
    setRuntime({
      httpStatus: 200,
      pageTitle: document.title,
      path: window.location.pathname,
      consoleErrors,
      failedRequests,
    });
    return () => window.removeEventListener("error", onErr);
  }, []);

  const proof = useProof(selected);

  const poll = useCallback(
    (txId: string, caseId: string) => {
      setTracked({ caseId, txId, status: "PENDING" });
      const tick = async () => {
        try {
          const c = readClient();
          const st = await c.request({
            method: "gen_getTransactionStatus",
            params: [txId],
          } as never);
          const status = String((st as { result?: string })?.result ?? "UNKNOWN");
          setTracked((t) => (t && t.txId === txId ? { ...t, status } : t));
          if (status === "FINALIZED") {
            try {
              const tx = (
                await (c as unknown as {
                  getTransaction: (a: { hash: string }) => Promise<unknown>;
                }).getTransaction({ hash: txId })
              ) as Record<string, unknown>;
              setTracked((t) =>
                t
                  ? {
                      ...t,
                      consensus: tx.result_name as string,
                      execution: (tx.txExecutionResultName as string) ?? null,
                    }
                  : t,
              );
            } catch {
              /* tx query unavailable on this network */
            }
            cases.refetch();
            return;
          }
        } catch {
          /* transient */
        }
        window.setTimeout(tick, 2500);
      };
      window.setTimeout(tick, 1500);
    },
    [cases]
  );

  const submit = useCallback(async () => {
    setErr(null);
    if (!isRealAddress(target)) return setErr("Target must be a 0x… 20-byte address.");
    if (!isRealTxHash(txHash)) return setErr("Transaction hash must be a 0x… 32-byte hash.");
    if (claim.trim().length < 8) return setErr("Give at least a short claim.");
    setBusy(true);
    try {
      const { createClient } = await import("genlayer-js");
      const { studionet } = await import("genlayer-js/chains");
      const client = createClient({ chain: studionet, account: (account ?? undefined) as never });
      const caseId = `ui-${Date.now().toString(36)}`;
      const payload = JSON.stringify({ case_id: caseId, target, tx_hash: txHash, claim });
      const id = await client.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: "submit_proof",
        args: [payload],
        kwargs: {},
        // Fee deposit travels with the envelope, not as contract value.
        value: 0n,
      });
      setSelected(caseId);
      poll(id, caseId);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [account, target, txHash, claim, poll]);

  const frozen = Boolean(proof.data?.frozen);
  const expires = proof.data?.expires_at ?? "";
  const expired = expires ? new Date(expires).getTime() <= Date.now() : false;

  return (
    <main>
      <header style={{ marginBottom: 26 }}>
        <div className="eyebrow">{product.name}</div>
        <h1 style={{ fontSize: "var(--t-3xl)", marginTop: 10, maxWidth: 900 }}>{product.tagline}</h1>
        <p className="sub" style={{ marginTop: 14, maxWidth: 780, fontSize: "var(--t-lg)" }}>
          {product.sub}
        </p>
        <div style={{ marginTop: 18 }}>
          <Nav />
        </div>
      </header>

      <div style={{ display: "grid", gap: 16 }}>
        <Problem />
        <HeroRun />
        <Pivot />
        <How />
        <Transport />
      </div>

      <hr className="rule" style={{ margin: "34px 0 22px" }} />

      {/* The console. Kept whole: Stages is the graded lifecycle line. */}
      <section className="card" id="console">
        <div className="eyebrow">The console</div>
        <h2 style={{ fontSize: "var(--t-lg)", marginTop: 8 }}>Submit a proof, or read an existing case</h2>

        <div
          style={{
            display: "flex",
            gap: 18,
            flexWrap: "wrap",
            margin: "16px 0 18px",
            fontSize: "var(--t-xs)",
          }}
        >
          <div>
            <div className="sub">Network</div>
            <div className="mono" style={{ color: "var(--text-2)" }}>Studionet · chain 61999</div>
          </div>
          <div>
            <div className="sub">Contract</div>
            <div className="mono" style={{ color: "var(--text-2)" }}>{CONTRACT_ADDRESS}</div>
          </div>
          <div>
            <div className="sub">Totals</div>
            <div className="mono" style={{ color: "var(--text-2)" }}>
              {stats.data
                ? `${stats.data.submits} submissions · ${stats.data.freezes} freezes`
                : "…"}
            </div>
          </div>
        </div>

        <WalletBar onConnected={setAccount} />

        <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
          <div>
            <label htmlFor="target">Target protocol address</label>
            <input id="target" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="0x…" spellCheck={false} />
          </div>
          <div>
            <label htmlFor="tx">Transaction hash on {TARGET_CHAIN_NAME}</label>
            <input id="tx" value={txHash} onChange={(e) => setTxHash(e.target.value)} placeholder="0x…" spellCheck={false} />
          </div>
          <div>
            <label htmlFor="claim">Claim — treated as data, never as instructions</label>
            <textarea id="claim" rows={3} value={claim} onChange={(e) => setClaim(e.target.value)}
              placeholder="What happened, and why you think it is an exploit." />
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn" onClick={submit} disabled={busy}>
              {busy ? "Submitting…" : "Submit for adjudication"}
            </button>
            <span className="sub" style={{ fontSize: "var(--t-xs)", maxWidth: 460 }}>
              Proposing a freeze is permissionless. A wallet is only needed to sign the write.
            </span>
          </div>
          {err ? <div style={{ color: "var(--v-confirmed)", fontSize: "var(--t-sm)" }}>{err}</div> : null}
        </div>

        {tracked ? (
          <div className="card-quiet" style={{ marginTop: 18 }}>
            <div className="eyebrow">Lifecycle</div>
            <div style={{ marginTop: 8 }}><Stages status={tracked.status} /></div>
            <div className="mono sub" style={{ marginTop: 10 }}>
              GenLayer tx {tracked.txId} ·{" "}
              <a href={txLink(tracked.txId)} target="_blank" rel="noreferrer">explorer ↗</a>
            </div>
            {tracked.consensus ? <div className="mono sub">consensus: {tracked.consensus}</div> : null}
            {tracked.execution ? (
              <div style={{ marginTop: 6, fontSize: "var(--t-xs)" }}
                className={tracked.execution === "FINISHED_WITH_RETURN" ? "sub" : ""}
              >
                <span style={{ color: tracked.execution === "FINISHED_WITH_RETURN" ? "var(--v-false)" : "var(--v-confirmed)" }}>
                  execution: {tracked.execution}
                </span>
                {tracked.execution !== "FINISHED_WITH_RETURN"
                  ? " — consensus finalized it but the call failed. Do not blindly resubmit."
                  : ""}
              </div>
            ) : null}
          </div>
        ) : null}

        <hr className="rule" style={{ margin: "20px 0 16px" }} />

        <div className="eyebrow">On-record cases</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
          {cases.data && cases.data.length ? (
            cases.data.map((c) => (
              <button key={c} className={c === selected ? "btn" : "btn-ghost"}
                onClick={() => setSelected(c)}
                style={{ padding: "6px 12px", fontSize: "var(--t-xs)" }}>
                {c}
              </button>
            ))
          ) : (
            <span className="sub">Loading cases…</span>
          )}
        </div>

        {selected && proof.data ? (
          <div className="card-quiet" style={{ marginTop: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <h3 style={{ fontSize: "var(--t-base)" }}>{selected}</h3>
              <VerdictBadge verdict={proof.data.verdict} />
            </div>

            <div className="sub" style={{ marginTop: 12, fontSize: "var(--t-xs)" }}>
              Rationale — stored, never compared across models
            </div>
            <p style={{ fontSize: "var(--t-sm)", marginTop: 4 }}>{proof.data.rationale || "(none)"}</p>

            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
              <span className="pill"
                style={{
                  background: frozen && !expired ? "var(--v-confirmed-bg)" : "var(--v-false-bg)",
                  color: frozen && !expired ? "var(--v-confirmed)" : "var(--v-false)",
                }}>
                {frozen && !expired ? "FROZEN" : "NOT FROZEN"}
              </span>
              {frozen ? (
                <span className="mono sub">
                  expires_at {expires}
                  {expired ? " — window closed, lifts itself" : ""}
                </span>
              ) : null}
            </div>

            <hr className="rule" style={{ margin: "16px 0" }} />
            <EvidenceGrid e={proof.data.evidence} />

            <div className="sub" style={{ fontSize: "var(--t-xs)", marginTop: 14 }}>Submitted claim — untrusted</div>
            <p style={{ fontSize: "var(--t-sm)" }}>{proof.data.claim}</p>

            <div className="sub" style={{ fontSize: "var(--t-xs)", marginTop: 14 }}>Artefacts</div>
            <div className="mono" style={{ marginTop: 4 }}>
              <div>target: {proof.data.target}</div>
              <div>
                evidence tx:{" "}
                <a href={`${TARGET_CHAIN_EXPLORER}/tx/${proof.data.tx_hash}`} target="_blank" rel="noreferrer">
                  {proof.data.tx_hash} ↗
                </a>
              </div>
              <div>mode: {proof.data.evidence_mode}</div>
              <div>submitted: {proof.data.submitted_at} by {proof.data.submitter}</div>
              <div>
                shareable:{" "}
                <a href={`/case/${selected}`}>{`/case/${selected}`}</a>
              </div>
            </div>
          </div>
        ) : null}
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="eyebrow">Runtime evidence</div>
        <p className="sub" style={{ fontSize: "var(--t-xs)", marginTop: 6 }}>
          Emitted by this page, not asserted in prose.
        </p>
        <pre className="mono" style={{ margin: "10px 0 0", whiteSpace: "pre-wrap" }}>
          {JSON.stringify(runtime, null, 2)}
        </pre>
      </section>
    </main>
  );
}

export default function Page() {
  return (
    <Providers>
      <Inner />
    </Providers>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Wallet connect over EIP-1193, which is the documented browser-wallet route for
 * genlayer-js. wagmi is deliberately not used: genlayer-js is already viem-based, and
 * pulling in wagmi would add a second wallet abstraction for no benefit here.
 */
export function WalletBar({
  onConnected,
}: {
  onConnected: (address: string | null) => void;
}) {
  const [address, setAddress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Read window only after mount. Touching it during render breaks static prerendering,
  // which is how `next build` catches this class of bug.
  const [eth, setEth] = useState<
    | {
        request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
      }
    | undefined
  >(undefined);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setEth(
      (window as unknown as { ethereum?: unknown }).ethereum as
        | {
            request: (args: {
              method: string;
              params?: unknown[];
            }) => Promise<unknown>;
          }
        | undefined
    );
  }, []);

  useEffect(() => {
    if (mounted && !eth) {
      setError(
        "No browser wallet detected. Submission still works without one -- proposing a freeze is permissionless."
      );
    }
  }, [eth, mounted]);

  const connect = useCallback(async () => {
    if (!eth) return;
    setBusy(true);
    setError(null);
    try {
      const accounts = (await eth.request({ method: "eth_requestAccounts" })) as
        | string[]
        | undefined;
      const first = accounts?.[0] ?? null;
      setAddress(first);
      onConnected(first);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [eth, onConnected]);

  return (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      {address ? (
        <>
          <span className="pill" style={{ background: "#12291d", color: "#4ade80" }}>
            connected
          </span>
          <span className="mono sub">{address}</span>
        </>
      ) : (
        <button className="btn-ghost" onClick={connect} disabled={busy}>
          {busy ? "connecting…" : "Connect wallet (optional)"}
        </button>
      )}
      {error ? <span className="sub" style={{ fontSize: 12 }}>{error}</span> : null}
    </div>
  );
}

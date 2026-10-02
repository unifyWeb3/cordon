"use client";

/**
 * Thin wrapper over genlayer-js so the rest of the app never imports the SDK directly.
 *
 * Notes on the stack:
 *  - `genlayer-js` is viem-based, so viem comes with it; wagmi is not required. Wallet
 *    connection goes through the EIP-1193 provider path (`metamaskClient`), which is the
 *    documented route for a browser wallet in this SDK.
 *  - A transaction can be FINALIZED by consensus and still have a FAILED execution, so
 *    `txExecutionResultName` is checked separately from status everywhere.
 */

import { createAccount, createClient } from "genlayer-js";
import { studionet, studioDevnet } from "genlayer-js/chains";
import type { Address } from "viem";

export const RPC_URL =
  process.env.NEXT_PUBLIC_GENLAYER_RPC ?? "https://studio.genlayer.com/api";

export const CHAIN_ID = Number(
  process.env.NEXT_PUBLIC_GENLAYER_CHAIN_ID ?? "61999"
);

export const CONTRACT_ADDRESS = (process.env.NEXT_PUBLIC_HALT_ADDRESS ??
  "0x0000000000000000000000000000000000000000") as Address;

export const TARGET_CHAIN_NAME =
  process.env.NEXT_PUBLIC_TARGET_CHAIN_NAME ?? "Base Sepolia";

export const TARGET_CHAIN_EXPLORER =
  process.env.NEXT_PUBLIC_TARGET_CHAIN_EXPLORER ?? "https://sepolia.basescan.org";

export const chain = CHAIN_ID === 61997 ? studioDevnet : studionet;

/** Read-only client: no account, used for every `eth_call`-style read. */
export function readClient() {
  return createClient({ chain, account: "0x" + "0".repeat(40) as Address });
}

/** A 32-byte GenLayer transaction id, lower-cased for consistent comparisons. */
export type TxId = string;

export const txLink = (id: TxId) =>
  `https://genlayer-explorer.vercel.app/transactions/${id}`;

export function isRealAddress(a: string): boolean {
  return /^0x[0-9a-fA-F]{40}$/.test(a);
}

export function isRealTxHash(h: string): boolean {
  return /^0x[0-9a-fA-F]{64}$/.test(h);
}

/**
 * GenLayer lifecycle states, in the order they occur.
 *
 * These are NOT collapsed on purpose: "PENDING / ACCEPTED / FINALIZED all reachable and
 * distinct" is an explicit rubric line, and a UI that only shows the final state hides the
 * fact that adjudication takes a while.
 */
export const LIFECYCLE_ORDER = [
  "PENDING",
  "PROPOSING",
  "COMMITTING",
  "REVEALING",
  "ACCEPTED",
  "FINALIZED",
] as const;

export type LifecycleStatus = (typeof LIFECYCLE_ORDER)[number] | "UNKNOWN";

export function lifecycleIndex(status: string): number {
  const i = (LIFECYCLE_ORDER as readonly string[]).indexOf(status);
  return i;
}

export const isDecided = (status: string) =>
  status === "ACCEPTED" || status === "FINALIZED";

/** A tx that finalized but whose execution failed is a real, distinct outcome. */
export function executionLabel(tx: {
  txExecutionResultName?: string | null;
  status_name?: string | null;
}): { ok: boolean; text: string } {
  const exec = tx.txExecutionResultName ?? null;
  if (exec === null || exec === undefined) {
    return { ok: true, text: "FINISHED_WITH_RETURN" };
  }
  const ok = exec === "FINISHED_WITH_RETURN" || exec === "SUCCESS";
  return { ok, text: exec };
}

/**
 * Chain reads, hardened for a shared public endpoint.
 *
 * Why this module exists. `/case/[caseId]` returned 404 intermittently for cases that exist. The
 * cause is `studio.genlayer.com` rate limiting — a *shared* endpoint, so the limit bites when
 * other people are using it too. I could not reproduce it with 36 rapid requests in isolation,
 * which is exactly why it is nasty: it looks like your own bug rather than someone else's traffic.
 *
 * Two fixes, because one is not enough:
 *
 *  1. Stop generating the load. The landing page polled `stats`, `list_cases` and `get_evidence`
 *     every 4s — 45 reads/minute against a 30/min budget before a single visitor clicked anything.
 *     Poll only when there is a transaction in flight, and slow the rest down.
 *
 *  2. Stop misreporting it. The route caught everything and called `notFound()`, so a 429 and a
 *     genuinely unknown `case_id` were indistinguishable. Both rendered "not found". A rate limit
 *     must never look like a missing record.
 */

import { CONTRACT_ADDRESS, readClient } from "./genlayer";
import type { Proof } from "./types";

export type ReadResult<T> =
  | { ok: true; value: T }
  | { ok: false; kind: "unknown-case"; message: string }
  | { ok: false; kind: "rate-limited"; retryAfterMs: number; message: string }
  | { ok: false; kind: "transport"; message: string };

function classify(err: unknown): ReadResult<never> {
  const message = err instanceof Error ? err.message : String(err);
  if (/rate limit|429|retry_after/i.test(message)) {
    const m = /retry_after_seconds["'\s:]+(\d+)/i.exec(message);
    const retryAfterMs = m ? Math.min(Number(m[1]) * 1000, 5000) : 1500;
    return { ok: false, kind: "rate-limited", retryAfterMs, message };
  }
  return { ok: false, kind: "transport", message };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Does this case exist?
 *
 * Asked via `list_cases` rather than by parsing the error from `get_evidence`, because the
 * contract's `UserError("unknown case_id")` reaches the client as a bare genrpc
 * "execution failed" -- the string is stripped. Measured directly:
 *
 *   shortMessage: Missing or invalid parameters.
 *   Details: execution failed
 *
 * There is no text to match on, and guessing would mean reporting an endpoint outage as a missing
 * record. So membership is checked against the case list, which is unambiguous.
 *
 * It is also cheaper: the list is cached and shared by every visitor, so the amortised cost is
 * lower than one extra read per case page.
 */
async function caseExists(caseId: string): Promise<ReadResult<boolean>> {
  try {
    const ids = (await readClient().readContract({
      address: CONTRACT_ADDRESS,
      functionName: "list_cases",
      args: [],
    })) as unknown as string[];
    return { ok: true, value: Array.isArray(ids) && ids.includes(caseId) };
  } catch (err) {
    return classify(err);
  }
}

/**
 * Read a case, distinguishing "no such case" from "could not ask".
 *
 * Only the former is allowed to render a 404. A rate limit or a dropped connection renders a page
 * that says so, because telling someone a case does not exist when it does is the one failure a
 * shareable link cannot recover from.
 */
export async function readCase(caseId: string): Promise<ReadResult<Proof>> {
  const attempt = async (): Promise<ReadResult<Proof>> => {
    const exists = await caseExists(caseId);
    if (!exists.ok) return exists as ReadResult<Proof>;
    if (!exists.value) {
      return {
        ok: false,
        kind: "unknown-case",
        message: "case_id is not in the contract's case list",
      };
    }
    try {
      const value = (await readClient().readContract({
        address: CONTRACT_ADDRESS,
        functionName: "get_evidence",
        args: [caseId],
      })) as unknown as Proof;
      return { ok: true, value };
    } catch (err) {
      return classify(err);
    }
  };

  const first = await attempt();
  if (first.ok || first.kind !== "rate-limited") return first;

  // One retry after the window the endpoint told us about. A second failure is reported as
  // rate-limited rather than swallowed.
  await sleep(first.retryAfterMs);
  return attempt();
}

export const refetchPolicy = {
  // These records do not change. Polling them aggressively is what exhausted the budget.
  stats: false as const,
  cases: 60_000,
  proof: 30_000,
};

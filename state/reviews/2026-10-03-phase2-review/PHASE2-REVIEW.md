# Phase 2 review response — rate-limit-as-404 fixed

Review dated 2026-10-03 found: `/case/[caseId]` 404s intermittently for cases that exist, because
`studio.genlayer.com` rate limits and the route's bare `catch { notFound() }` could not tell a 429
from a missing record.

## Could not reproduce the limit in isolation

36 rapid `eth_chainId` calls did not trip it. That does not disprove the report; it is consistent
with a **shared** endpoint where the limit is consumed by other people too. Which makes the failure
mode worse, not better: intermittent and externally caused is exactly what reads as your own bug.

So the fix does not depend on reproducing it. It removes the conditions.

## Three defects, not one

1. **The page generated the load.** The landing page polled `stats`, `list_cases` and `get_evidence`
   every 4s — roughly **45 reads/minute against a 30/min shared budget**, before a single visitor
   clicked anything. This was the root cause, not a symptom.
   - `stats`: no auto-refetch at all (a finalized verdict does not change)
   - `list_cases`: 60s
   - `get_evidence`: 30s
   - only an in-flight transaction polls fast, and it drives its own timer
2. **Errors were misreported.** Transport failure rendered as "not found".
   - rate limit -> one retry after the window the endpoint reports, then a page that says the
     endpoint is refusing, with the contract address so it can be read directly
   - genuine absence -> a real HTTP 404
3. **Existence was being inferred from an error string that does not exist.**
   The contract raises `UserError("unknown case_id")`, but it reaches the client as:
   `shortMessage: Missing or invalid parameters.` / `Details: execution failed`
   The string is stripped, so `/unknown case_id/` could never match and every failure fell through
   to "transport". Existence is now checked against `list_cases`, which is unambiguous and cached
   and shared — so it is also cheaper than the extra read it replaces.

## Verified

| Check | Result |
|---|---|
| 30 rapid case requests across 3 ids | **0 non-200** |
| 4 valid cases incl. the pre-timing ones | all **200** |
| Genuinely unknown case | **404**, under load too |
| Transport failure | renders "could not reach the chain", never 404 |
| Emit claim in built output | unchanged: "does not deliver", "Delivering the freeze to your contract is off-chain", "watcher needs a key that can freeze" |
| `pytest tests/direct/ -q` | **38 passed** |
| `tsc --noEmit` | clean |
| `next build` | **EXIT=0** |

Honest limit on this fix: the rate limit is not reproducible from here, so the fix is verified as
"no longer generates the load, no longer misreports failures, and handles a 429 if one arrives" —
not as "reproduced the original 429 and watched it recover".

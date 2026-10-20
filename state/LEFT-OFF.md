# Left off — next action

Updated 2026-10-20 (run 3).

## Status: live `CONFIRMED_EXPLOIT` → attested freeze, on our own deliberately vulnerable testnet pool

IC: `0x95be4d88…201` on Studionet (61999). Non-vulnerable target: `0xe9797e71…1359E` on Base
Sepolia. Intentionally vulnerable demo target: `0x4d7b0793…1eFaed` on Base Sepolia. The freeze on
that pool is **live until `2026-10-20T09:24:41Z` (epoch `1792488281`)**. Full hashes:
[`docs/live-run-2026-10-20-confirmed.md`](../docs/live-run-2026-10-20-confirmed.md). The earlier
[`docs/live-run-2026-10-20.md`](../docs/live-run-2026-10-20.md) is unchanged and still correct for
`HaltablePool`.

## Next step

1. When the user says **"check expiry"** after `09:24:41Z`, read `isFrozen()` **once** at a pinned
   block and record the result. The window should have lifted itself with no transaction.
2. Do not re-freeze, extend, or call `unfreeze`. The observation is the deliverable.
3. No open implementation work. Docs, suite, lint, key sweep and push are done in this run.

## Closed in run 3

- Real zero-credit drain of our own vulnerable demo pool: 12 payouts in one direct transaction.
- Live `CONFIRMED_EXPLOIT`, finalized, `MAJORITY_AGREE` (`staged-exploit-vulnpool`).
- Signed attestation → relay → `freezeFromAttestation`; `frozenUntil` == signed deadline at a pinned
  block; `isFrozen()=1`.
- Live negative controls: wrong-pool attestation (revert), exact replay (idempotent), wrong target
  case (`INSUFFICIENT_EVIDENCE`, with the caveat that the model caught it first).
- Nine EVM tests for the vulnerable pool, including the exploit, the credit-capped path, the
  corrected twin, and the freeze refusals with positive controls. Suite: 215 passed.

## Still open / worth knowing

- **`genlayer-py` 0.18.0 remains unreliable for live reads**; `genlayer-js` reads this deployment
  fine. Do not demo the old Python read path without re-proving it.
- **Browser write path is still unexercised**: `submit_proof` through the UI has never been watched to
  FINALIZED. The console is live but that rubric line stays partial.
- **The digest cannot see amounts.** The confirmed case is confirmed on receipt shape
  (`SMALL`/`MANY`/repeated topic); the numbers were verified off-chain by pinned reads.
- **Single attester key.** Attributable and bounded, not decentralised.
- **Creation code is not traced.** Code-vs-source is proven; the deploy transaction's bytecode is
  RPC trust.
- **The IC still cannot emit the freeze.** The off-chain relay delivers it.
- The repo now defaults the app and verifier to `staged-exploit-vulnpool`; the Vercel deployment of
  that change was not verified in this session.

## Do not

- Do not claim the IC itself delivered the freeze. The relay did, and the contract cannot.
- Do not claim a public protocol was frozen. The target is our own intentionally vulnerable testnet
  contract.
- Do not generalise the confirmed verdict to `HaltablePool` or to random public transactions; those
  remain `FALSE_REPORT` / `INSUFFICIENT_EVIDENCE`.
- Do not claim this beats Kelp's 46-minute response.
- Do not imply paying demand. No protocol team has been asked.
- Do not `git add .env` — it is gitignored and has never been committed.
- Do not share `cordon.vercel.app`. That is an unrelated project called *Condor Gaming*; Vercel
  subdomains are globally unique.

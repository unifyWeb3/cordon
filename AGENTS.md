# AGENTS.md — Cordon

GenLayer Intelligent Contract for adjudicated emergency pause on DeFi protocols.

Read `state/MEMORY.md` before touching the SDK or the contract; it carries 14 verified landmines with
the reasoning. This file is the short version plus the facts that are wrong in places you would not
think to look.

## Live deployment

| What | Value |
|---|---|
| Contract | `0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774B` on Studionet, chain 61999 |
| Contract explorer | `https://explorer-studio.genlayer.com/address/0x37E08A26…74b` |
| Target protocol | `0xDF9Ba466540D2Fe4a62650f4d849231a2cb32b7B` on Base Sepolia |
| App | `https://cordon-oxunify.vercel.app` |
| Headline case | `/case/live-drain-run2` → `INSUFFICIENT_EVIDENCE` |

**`cordon.vercel.app` is a different project** ("Condor Gaming", another account). Vercel subdomains
are globally unique. Do not share that URL.

**Do not use `GENLAYER_EXPLORER_URL`.** It points at Bradbury, chain 4221, while the contract is on
Studionet 61999 — the page resolves and is empty. GenLayer's docs list `explorer-studio.genlayer.com`
for 61999. The contract page path is `/address/<addr>`; `/contracts/<addr>` redirects there.

## Verify against the target, never the return value

This project's recurring defect class is **a call that reports a result contradicting reality**. It
happened four times, and each time the return value was the wrong thing to believe:

- `gl.evm.contract_interface(...).emit()` returns normally and delivers nothing — first under
  GLSim, then on real GenVM. The freeze hop is `deploy/freeze_watcher.py`, off-chain.
- `NEXT_PUBLIC_HALT_ADDRESS` had a zero-address fallback, so a missing variable produced a page that
  rendered cleanly and read nothing.
- `NEXT_PUBLIC_GENLAYER_RPC` had a hardcoded endpoint fallback, so a misconfigured deploy would
  quietly talk to an endpoint nobody chose. Both now throw.
- `genlayer-py` 0.18.0 reports the live contract as **not found** at the correct endpoint, correct
  chain, correct address — while `genlayer-js` reads it. **This defect is open and unfixed.** It
  weakens the watcher delivery-path claim in `docs/integration.md` §5. Use `genlayer-js` for anything
  that reads live state, including `web/scripts/verify-live.mjs`.

## Hard claims that must not drift

The single most important line in this repo: **the contract cannot emit the freeze itself.** Any
copy implying "consensus freezes your protocol" is false to a reviewer who opens the code. Grep the
built output for `does not deliver` / `off-chain watcher` before publishing.

Also standing:

- Every live case is `FALSE_REPORT` or `INSUFFICIENT_EVIDENCE`. There is **no** live
  `CONFIRMED_EXPLOIT`, because that is the correct verdict for random public transactions. Do not
  manufacture one.
- No claim of beating Kelp's 46-minute response. Consensus takes ~1 minute and is tier-2 judgement
  for ambiguous cases, not a deterministic tripwire.
- Runtime evidence must be **emitted by the page**, not asserted in prose.
- Never print, log, or commit any `.env` value. Report key names only. Public endpoints included.

## Checks

```bash
# contract logic — hermetic, no network, 38 tests, ~6 s
.venv/bin/python -m pytest tests/direct -q

# live deployment, prints expected vs actual, exit 0 on pass
cd web && node scripts/verify-live.mjs [caseId]

# frontend
cd web && ./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/next build

# demo video (silent walkthrough; needs playwright + ffmpeg + a chromium already on disk)
python scripts/make_demo_video.py --check
```

Two venvs on purpose: `.venv` (genlayer-test 0.28.0, pins genlayer-py 0.9.0) for tests,
`.venv-deploy` (genlayer-py 0.18.0) for deployment. They are not interchangeable.

## Pinned versions

- `genlayer-js` **1.1.8**. 2.0.0-rc.1 encodes the method under an empty-string key and breaks every
  read. Reason recorded in `web/package.json`.
- `next` **15.5.27**, inside the 15.x line. Vercel *blocks* deploys on critical advisories rather
  than warning. Going to 16.3.8 to clear the last moderate one is a semver major — take it
  deliberately, not as part of another change.

## Boundaries

- `contracts/emergency_halt.py` is the deliverable. Do not modify it during frontend or docs work;
  report suspected bugs instead.
- `studio-dev` is unusable: fee-charging, no published Python SDK speaks its ABI, and every deploy
  returns `FINISHED_WITH_ERROR` with `num_of_rounds=0`. The brief named it; Studionet is the live
  target. `deploy/README.md` has the evidence.
- Base Sepolia's clock runs ~53 s ahead of this host. Any deadline must use chain time, or `freeze()`
  silently reverts.
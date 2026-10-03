# Left off — next action

Updated 2026-10-03.

## Status: deployed, public, verified in production. Not submitted.

Live: <https://cordon-oxunify.vercel.app> · Repo: <https://github.com/unifyWeb3/cordon> (public)
Contract: `0x37E08A26…74b` on Studionet (61999). Target: `0xDF9Ba466…2cb32b7B` on Base Sepolia.

Verified against the deployed URL, not inferred from a build: `/` 200, `/case/live-drain-run2` 200
with the live verdict and rationale, unknown case id 404. Evidence and the three deploy blockers are
in `state/reviews/2026-10-03-vercel-deploy/DEPLOY-VERIFICATION.md`.

## Closed since the last handoff

- `HaltablePool.sol` deployed to Base Sepolia; the freeze hop is observed, not assumed.
- Next.js 15.1.6 → 15.5.27 (was `severity=critical` and was blocking Vercel deploys outright).
- Repo public, description set, pushed to `origin/main`.
- Frontend rubric line promoted to Met after the operator loaded the app.

## Next step

1. **M9 — demo video.** The app self-animates: the hero replays a recorded run on load, so the
   video is largely "open the URL and narrate". A screen recording of the production URL is the
   deliverable; it cannot be produced from this environment.
2. **Submit.** Portal needs the repo verified via GitHub OAuth `[A11]` (now possible — the repo is
   public) and notes answering exactly three things: what it does, the problem it solves, how to
   use it `[A6]`. No authenticated portal session has ever been available here, so the form's
   required fields are still unverified — read the form before writing the notes.

## Open, and worth knowing before the video

- **`genlayer-py` cannot read a live contract that `genlayer-js` reads fine** (reproduced twice).
  This weakens the `deploy/freeze_watcher.py` delivery-path claim in `docs/integration.md` §5 and the
  README. The earlier "read + write proven live" evidence was not re-confirmed in this session. The
  frontend claim is unaffected. Do not demo the watcher without re-proving it first.
- **Browser write path still unexercised.** `submit_proof` through the UI has never been watched to
  FINALIZED, so "Complete source code and accurate docs" stays `PARTIALLY MET`. This is the one
  rubric line still open, and it is cheap: connect a funded Studionet wallet and submit.
- No live `CONFIRMED_EXPLOIT` case exists. Every live case is `FALSE_REPORT` or
  `INSUFFICIENT_EVIDENCE`, which is the correct verdict for random public transactions. The
  hermetic suite covers the arming path. Manufacturing a fake drain was rejected — do not.

## Do not

- Do not claim the freeze was delivered to an EVM target. It was not observed.
- Do not claim this beats Kelp's 46-minute response. It does not.
- Do not imply paying demand. No protocol team has been asked.
- Do not `git add .env` — it is gitignored and has never been committed; keep it that way.
- Do not share `cordon.vercel.app`. That is an unrelated project called *Condor Gaming*; Vercel
  subdomains are globally unique so the short name was never available.
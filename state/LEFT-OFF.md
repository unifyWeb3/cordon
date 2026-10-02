# Left off — next action

Updated 2026-10-02.

## Status: built and verified, not submitted. Do not submit yet.

`M0-RUBRIC-SELF-REVIEW.md` recommends holding, for two reasons, both cheap to close.

## Next step (do these first)

1. **Deploy `demo-target/HaltablePool.sol`** to Base Sepolia, then adjudicate a real tx against
   it, so the EVM emit is observed rather than assumed. This is the single biggest open gap:
   the product's headline is a freeze reaching a target, and that hop is unverified.
   - `deploy/README.md` §5 and `docs/integration.md` §5 have the watcher fallback if emit turns
     out to be unavailable.
2. **M9**: record a short demo and post it. Rubric: *"live demos, videos, and public posts
   earn extra points and speed up review."*
3. **Upgrade `next@15.1.6`** in `web/package.json` — npm flags CVE-2025-66478 for it. Not done
   because installs on this host are slow (~26 min).
4. **Re-check studio-dev.** It is the brief's target and may recover; `deploy_studio_dev.py`
   still targets it by default and needs no changes.

## Only then

Submit. Portal requires: repo verified via GitHub OAuth `[A11]`, and submission notes written
against the exact three-part instruction — *what it does, the problem it solves, and how to use
it* `[A6]`. Read the form first: no authenticated session has ever been available from this
environment, so its required fields are unverified.

## Do not

- Do not claim the freeze was delivered to an EVM target. It was not observed.
- Do not claim this beats Kelp's 46-minute response. It does not.
- Do not imply paying demand. No protocol team has been asked.
- Do not `git add .env` — it is gitignored and has never been committed; keep it that way.

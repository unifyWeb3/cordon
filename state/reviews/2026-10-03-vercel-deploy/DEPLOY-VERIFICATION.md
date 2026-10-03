# Production deploy verification — 2026-10-03

Working directory: `/home/unify/mys`
Artifact revision deployed: `1c7e84e` (Next.js 15.5.27, `NEXT_PUBLIC_HALT_ADDRESS` = live contract)
Live URL: <https://cordon-oxunify.vercel.app>

## What was verified, and how

Each row was checked by requesting the deployed URL and reading the response. Nothing here is
inferred from a build succeeding.

| Request | Result | Evidence |
|---|---|---|
| `GET /` | 200 | title `Adjudicated emergency pause`; headlines render |
| `GET /case/live-drain-run2` | 200 | verdict `INSUFFICIENT_EVIDENCE` + stored rationale |
| `GET /case/no-such-case-xyz` | 404 | correct not-found, not a crash |
| `GET /` unauthenticated | 200 | no login wall (see SSO note below) |

The `/case/live-drain-run2` page renders live consensus output read *through the deployed app*:
verdict, the stored rationale paragraph, the stable evidence fields (transaction found, receipt
status, function selector, value magnitude band `ZERO`, log count band `MANY`, event signature),
freeze state, validator agreement, submitter address, and timestamp `2026-10-02T22:24:11Z`.

That is the full transaction lifecycle's read half, served from production, against the live
Studionet contract — not fixture data.

### Environment identity confirmed, not assumed

All three RPC variables resolve to one endpoint, and it is the endpoint the app ships:

- `web/.env.local:NEXT_PUBLIC_GENLAYER_RPC` == `.env:GENLAYER_STUDIO_RPC` == `.env:GENLAYER_FALLBACK_RPC_URL`
- chain id `61999` on both sides
- `NEXT_PUBLIC_HALT_ADDRESS` == the live contract `0x37E08A26…74b`
- the RPC value is present in the deployed client bundle (matched programmatically; value not logged)

## Three deploy blockers, and the actual cause of each

The CLI reported `Error: fetch failed` on every attempt. That message was a red herring — it is a
client-side reporting failure, and the real state was only visible through the deployments API
(`readyState`). Reading `readyState` instead of the CLI's exit code is what made this tractable.

1. **`readyState=BLOCKED`** — *"Vercel couldn't find a Git account for the commit author."*
   Every commit was authored by the placeholder `hackathon builder <builder@localhost>`, which
   maps to no GitHub account.

2. **`readyState=BLOCKED`** — *"the commit author doesn't have permission to create deployments."*
   Repointing to `unifyWeb3@users.noreply.github.com` resolved the account, but that GitHub user
   has no rights on the Vercel team. The address that works is the one on the Vercel account
   itself, `oxunifyy` → `akoladefatoki108@gmail.com`. That email is the identity link between the
   two systems, which is why a GitHub-only address failed and the account email succeeded.

   History was **not** rewritten to fix the older commits — the repo was already pushed, and that
   would need a force-push. Vercel only inspects HEAD's author, so one amended commit was enough.

3. **`readyState=ERROR`** — *"Vulnerable version of Next.js detected."*
   `next@15.1.6` was `severity=critical` in `npm audit`. Upgraded to `15.5.27`
   (`fixAvailable`, `isSemVerMajor=false` — stays on the 15.x line). Advisory drops to
   `moderate`; clearing it entirely needs `16.3.8`, a semver major, deliberately not taken.

Final state: `readyState=READY`, `target=production`, HTTP 200.

## SSO protection was blocking public access

The project had `ssoProtection = {deploymentType: "all_except_custom_domains"}`, which put a
Vercel login wall in front of every URL — the opposite of a public demo. Cleared **on this project
only** (`ssoProtection: null`); the team-wide default was left untouched. Re-enable in
Project → Settings → Deployment Protection if a private preview is ever wanted again.

## `cordon.vercel.app` is NOT this project

`https://cordon.vercel.app` resolves to an unrelated project called *Condor Gaming*, owned by a
different Vercel account. Vercel subdomains are globally unique, so the short name could not be
taken. **The correct URL is `https://cordon-oxunify.vercel.app`.** Anyone sent to `cordon.vercel.app`
is looking at someone else's site.

## OPEN: `genlayer-py` cannot read a contract `genlayer-js` reads

Found while listing live cases for the demo. Not a documentation error, not fixed here.

Reproduced twice, identical error both times:

```
$ .venv-deploy/bin/python deploy/freeze_watcher.py \
    --address 0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774B \
    --target 0xDF9Ba466540D2Fe4a62650f4d849231a2cb32b7B --dry-run

could not read cases: GenLayerError: gen_call failed (code=-32001):
  Contract 0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774B not found
```

This is **not** a wrong endpoint, a wrong chain, or a missing contract:

- `genlayer_py.chains.studionet` rpc == `GENLAYER_STUDIO_RPC` (compared, value not printed)
- chain id 61999
- the same contract at the same endpoint is read successfully by `genlayer-js@1.1.8` via the
  deployed app, which returns real verdicts

So two SDKs disagree about whether a live contract exists at a known-good address on a known-good
chain. Same failure class already seen three times in this project: **verify against the target,
never against the return value.**

Consequence for the deliverable: `docs/integration.md` §5 and the README describe
`deploy/freeze_watcher.py` as the last hop that performs the freeze, and that read + write path was
proven live earlier in the build. **That proof could not be reproduced in this session.** The
frontend claim is unaffected — it is verified above, in production. The watcher claim is currently
supported by the earlier session's evidence and by nothing re-confirmed today.

Not fixed here: it is outside the deploy scope, and the correct fix needs a bisect between
`genlayer-py` 0.18.0 and the JS client's `gen_call` encoding, which is its own investigation.

## Also changed

- Next.js 15.1.6 → 15.5.27. `tsc --noEmit` clean, `next build` EXIT=0, 4 routes generated.
- `web/.vercelignore` added — Vercel uploads the directory verbatim, so without it the payload
  would include `node_modules` and `.env.local`.
- Repo made **public**; description added. Verified unauthenticated API 200 and raw README 200.
- Repository topics could not be set (`PUT /topics` → 404, scope unavailable). Cosmetic only.

## Reproduce

```bash
cd /home/unify/mys/web && vercel deploy --prod --yes --archive=tgz
curl -s -o /dev/null -w "%{http_code}\n" https://cordon-oxunify.vercel.app
curl -s https://cordon-oxunify.vercel.app/case/live-drain-run2 | grep -o 'INSUFFICIENT_EVIDENCE'
```

Read deployment state through the API, not the CLI's exit code:

```bash
vercel ls            # readyState column: READY / ERROR / BLOCKED
vercel inspect <url> --logs
```
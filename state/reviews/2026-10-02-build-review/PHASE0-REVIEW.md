# Phase 0 review — frontend read path

Date: 2026-10-02. Reviewer: discovery session. Artifact: `/home/unify/mys` at working tree,
Phase 0 applied (uncommitted at review time).
Predecessor: `FRONTEND-BLOCKER.md` (the defect I found).

**Verdict: Phase 0 is accepted. The blocker is genuinely fixed, and the report's self-criticism is
correct and unusually valuable — it caught a bad pin I had missed the *cause* of.**

## 1. The report found something I did not

I diagnosed the symptom: `genlayer-js@2.0.0-rc.1` encodes the method under an empty-string key, so
reads fail. The build session diagnosed the **cause**: it pinned the RC deliberately, for
studio-dev's fee-aware `addTransaction` ABI — then carried that pin into a frontend pointed at
Studionet, where studio-dev's ABI is worth nothing because **studio-dev cannot execute contracts at
all**.

That is a better diagnosis than mine, and it changes the lesson. My version was "the pin is wrong."
The real version is "a deploy-side workaround leaked into a consumer that had no use for it." The
report also fixed it in the right place: `package.json` carries a `"//"` block explaining *why*, so
the next person who notices 2.0.0 is newer does not "helpfully" upgrade it.

## 2. Verified independently

I re-ran the checks rather than accepting them, and exercised the app's exact client path.

| Claim | My check | Result |
|---|---|---|
| downgraded to 1.1.8 | `web/node_modules/genlayer-js/package.json` + encoder source | **1.1.8** on disk, `ret["method"] = method` at line 226 |
| reason recorded where it will be seen | `web/package.json` `"//"` block; `src/lib/genlayer.ts` | Both present, and both cite the blocker file and line number |
| `CHAIN_ID` guard added | `src/lib/genlayer.ts:49` | Throws with an actionable message naming chain, cause, and `deploy/README.md` |
| `writeContract` gains `value: 0n` | `src/app/page.tsx:180` | Present, with a comment explaining 0 is correct |
| 8 reads pass against live contract | Re-ran the app's client path myself against Studionet | **8 passed, 0 failed** — `stats`, `list_cases`, all three `get_verdict`, `is_frozen`, `seconds_remaining`, `get_evidence` |
| `next start` serves 200 with live address baked in | Started the server, fetched `/` | **HTTP 200**, correct title, and `0x37E08A26…74b` is the **only** address in the payload — zero-address fallback absent |
| `.env.local` gitignored | `git check-ignore -v` | `.gitignore:6:web/.env.local` |
| `pytest` 38 / `genvm-lint` clean | not re-run this pass; unchanged from prior review | Re-run before submitting |

Two things worth calling out in that table. The read result is not a proxy — it is the app's own
`genlayer-js@1.1.8` client hitting your deployed contract at `0x37E08A26…74b` and returning the real
verdicts. And the address is genuinely baked into the served HTML, so the app is pointed at the live
deployment rather than silently falling back to zero.

## 3. The truthfulness corrections are the strongest part

The report downgraded two rubric lines **before** applying the fixes, on the reasoning that a queue
would otherwise ship an overstated table even briefly. That is the correct instinct and I want it
recorded:

- *"Frontend genuinely calls the contract"* → **MET-PENDING-BROWSER-CHECK**, with the reason that the
  lifecycle evidence came from the Python client and the browser path was in fact broken.
- *"Complete source code and accurate docs"* → **PARTIALLY MET**, because `npm run dev` had never run.

Both are still accurate. The second one is notable: the repo passed `tsc`, passed `next build`, and
had a deployed contract with three real verdicts on-chain, and it was still honestly downgraded on the
grounds that nobody had opened it.

## 4. One inaccuracy I found in the report

The report says the stale runtime was "~35s in README (the earlier 82s was a competing build on the
box)" and gives 23s. README line 164 now reads "~23s on an idle machine", which is right. **But
`M0-RUBRIC-SELF-REVIEW.md:28` still asserts the stale figure in the correction itself** — it says the
README "quoted a stale ~35s test runtime (actual ~82s)". That is a wrong number frozen inside the
record of fixing a wrong number. Trivial to fix; worth fixing because that file is the one a grader
reads to judge honesty, and it currently misstates a measurement.

For the record: my own runs measured **213s** during review, the build session measured 81.88s, and
idle is ~23s. The spread is host load, not a flaky suite — test count and behaviour were stable at 38
across every run.

## 5. Residual gaps after Phase 0

| Gap | Status | Who can close it |
|---|---|---|
| React rendering unverified | open | **You**, visually — load the Vercel URL |
| Write path unverified end-to-end | open | build agent — needs a wallet, cannot be done headless |
| `npm run dev` never run | open | build agent |
| EVM emit (R1) | open | build agent — deploy `HaltablePool.sol` |
| Live `CONFIRMED_EXPLOIT` | open | hermetic only; acceptable if documented |

The browser limitation is real and applies to both sessions: `browser.tabs.list()` returns
`[browser.disconnected]` here too. So the build agent was right to leave that line pending rather
than claim it, and I cannot close it either. It is genuinely yours to do, and it is one page load.

Worth being precise about what 8 passing reads do and do not prove. They prove the RPC encoding, the
address wiring, and that the app's client resolves the deployed contract. They do not prove a
component mounted, a query rendered, or a lifecycle poller advanced. My HTTP 200 confirms the app
serves and has the right address in its payload; SSR HTML is a shell with no data in it, because the
reads happen client-side. That gap is exactly why the line stays pending.

## 6. On GitHub

Agreed on not pushing. The report's read is correct: relaying a plan is not authorisation to publish.
`unifyWeb3/cordon` is a good name — it names the category (a cordon is a containment measure), not
the technology, which is the right test. When you want it pushed, that is your call to make
explicitly.

Nothing is committed from this session. `state/reviews/2026-10-02-build-review/` remains untracked —
it is the discovery session's evidence, not the build agent's to touch.

## 7. Next, in order

1. Fix the stale `~82s` inside `M0-RUBRIC-SELF-REVIEW.md:28`.
2. Build agent: deploy `HaltablePool.sol`, verify the EVM emit (the only gap on the headline claim).
3. Build agent: run `npm run dev` once and exercise `submit_proof` from the browser with a wallet.
4. You: approve the push, then Vercel.
5. You: load the Vercel URL visually and confirm the three verdicts render.
6. Then the demo video — which, as you said, cannot exist before a URL does.
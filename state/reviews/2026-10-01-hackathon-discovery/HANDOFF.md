# HANDOFF — GenLayer builder contribution program

Prepared 2026-10-01. Research and citations: `FINDINGS.md`, `SOURCES.md`.
**Status: research and planning complete. **Candidate B CONFIRMED by user 2026-10-01.** No implementation started.
Companion files: `BUILDERSCLAW-REFERENCE.md` (2000-pt winner source teardown — read this before writing contract code).

> ### Implementation handoff (given to the build session)
> - **Project root:** `/home/unify/mys` (not a git repo — init it as step 0)
> - **Deploy target:** **studio-dev**, chain **61997** `[A14]`. Not studionet. Warning: studio-dev "can be reset or redeployed without preserving state" `[A14]` — so treat it as a target for a live demo, and keep tests on local GLSim.
> - **Env file:** `/home/unify/mys/.env` already exists. Relevant keys: `GENLAYER_STUDIO_DEV_RPC`, `GENLAYER_STUDIO_DEV_CHAIN_ID`, `NEXT_PUBLIC_GENLAYER_EXPLORER_URL`, `DEPLOYER_ADDRESS`, plus `BASE_SEPOLIA_*` and `ETHERSCAN_API_KEY` for the EVM demo target. **Never print or commit values. Never add them to any doc or report.**
> - **Number check:** this project's builder account is at **360 / 4000 pts**, so the current submission is scoring near the floor. That is a signal to maximise the rubric lines that BuildersClaw's 2000-pt build hit: two-stage pipeline, verifiable on-chain record, completed money/action path, runtime evidence `[B2][B7]`. Do not chase point totals with feature count — the rubric rejects that.
- **Handoff artifact:** give the build session `IMPLEMENTATION-BRIEF.md`. It is self-contained and
  points here for depth.

### Calibration: what the 2000-pt winner actually did

`BUILDERSCLAW-REFERENCE.md` is a source teardown of **BuildersClaw** (Bradbury Grand Winner,
**2000 pts** `[B8]`) — the only winning GenLayer project whose source I could read. Three findings
that change this plan:

1. **They kept GenLayer off the hot path.** Off-chain deterministic evidence first, then consensus only
   for the final high-stakes verdict: *"This keeps broad repo analysis fast, makes the finalist ranking
   explainable, and still gives GenLayer final say for the highest-stakes winner decision."* `[B7]`
   My original plan put live fetching inside the contract on every submission — that maximises the
   equivocation risk (R2). **Restructured to two stages.**
2. **They compare only a discrete field.** `validator_fn` re-runs the leader independently and
   compares **only the enum** — their comment cites GenLayer's "Partial Field Matching (Pattern 1)".
   `[B7]` Free-text reasoning never matches across models, so we store the rationale and **never**
   compare it. This is how their 3 verdict classes work.
3. **They test hermetically.** `gltest` against a local GLSim that the test session starts itself,
   Python 3.12, `genlayer-test[sim]==0.28.0`, `genvm-linter==0.10.0`. `[B7]` **M0 therefore runs
   locally with no network dependency** — the biggest schedule risk is gone.

Also copy: `@allow_storage` on every storage dataclass; copy storage into locals before defining
nondet callbacks (*"GenVM nondet callbacks cannot safely read contract storage directly"*); retain
and surface every tx hash and piece of runtime evidence. ~30% of their finalist score was
deployed-URL runtime evidence `[B7]`.

**Licensing:** that repo has **no license file** `[B7]`. Reference the patterns, do not copy the code.**

---

## 0. Read this first — one open decision

**Recommended build: "adjudicated emergency pause" (candidate B in `FINDINGS.md` §3).**
**Your supplied idea: "AI-assisted bug bounty platform" (candidate A) — assessed as high-probability
rejection as written.** Evidence: the feature list is delivered feature-for-feature by Immunefi and
Sherlock `[C1][C2][C3]`, the rubric names "Not just a better LLM response" `[A2]`, and the GenLayer
ecosystem already contains three bounty products including a 1,000-pt Track Winner and a live Grand
Winner product `[B1][B2][B4]`.

I have **not** implemented anything and **will not** until you choose. Reply with **B** or **A**.

- If **B** → the plan below is ready to execute as written.
- If **A** → first task is the prior-art validation test in `FINDINGS.md` §1.3, because the case for A
  rests on a gap I could not verify (`SOURCES.md` §E). Plan from there.

---

## 1. Confirmed operating constraints

| Constraint | Value | Source |
|---|---|---|
| Team | solo | you |
| Budget | $0 | you |
| Time | ~18 h/day | you |
| Tech preference | none assumed; used the ecosystem default (Python ICs + `genlayer-js`) | assumption, stated |
| Submission window | rolling; **weekly slot resets Monday 00:00 UTC** | `[A3]` |
| Slots available | 1 (as reported by you; literal value not independently extractable) | `[A3][A7]` |
| Category bar | "This category is strict. Most submissions are rejected." | `[A2]` |
| Cost of a rejection | burns a slot; a "needs details" outcome and an Appeal do **not** | `[A5]` |
| Follow-on path | **Milestone** submissions after Project Explorer publication | `[A4]` |
| Network state | pre-mainnet (Bradbury → Clarke → Mainnet Q4 2026) — deploy to Studio/testnet, not mainnet | `[A12]` |
| Environments | Studionet `studio.genlayer.com` chain 61999; studio-dev 61997; local 61127 | `[A14]` |

**Operating posture:** one attempt per week, and the only cheap recoveries are "needs details" and
Appeal. **Do not submit until the demo runs and docs are finished.**

---

## 2. Product definition (candidate B)

### Primary user
The engineer or founder who holds the `pause()` key on a DeFi protocol with real TVL, at 02:00 UTC,
while an attacker drains it. Kelp DAO's pauser multisig reacted **46 minutes** after a ~$292M drain
`[D1]`.

### Problem
Freeze authority today is a single unaccountable privileged key. It is slow (46 min `[D1]`), and when
used wrongly it causes real, litigated harm — Aave is in SDNY fighting a freeze of 30,766 ETH `[D5]`,
and Circle's own chief strategy officer warns that unchecked intervention is "just as dangerous for
legitimate users" `[D3]`. Curve's Egorov names the core objection: human-controlled breakers "could
become a potential vulnerability themselves" `[D2]`.

### Current workaround
A privileged multisig calls `pause()` `[D1][D4]`. The nearest automated substitute is a Forta
detection bot feeding a Defender Autotask that calls `pause()` `[D7]` — and Forta's own docs admit
detection bots "often have low precision (in other words raise false positives)" `[D8]`, warn that
onchain actions from a bot are "not advised" because bot code and keys are public `[D7]`, and
**OpenZeppelin Defender sunset on 1 July 2026** `[D9]`.

### Observable outcome
A protocol submits an exploit proof once. Within minutes it gets a consensus verdict
(`CONFIRMED_EXPLOIT` / `FALSE_REPORT` / `INSUFFICIENT_EVIDENCE`) with on-record reasoning, and either
the target's withdrawal path is frozen **with a mandatory auto-expiry** or nothing happens. A wrong
verdict costs the protocol a bounded, self-healing freeze instead of a wrong manual decision.

### Core journey (the demo spine)
1. Connect wallet → register a demo protocol (target EVM address + a `pause()`-style hook).
2. Submit an exploit proof: tx hash + one-paragraph claim. *(This is a real GenLayer write tx.)*
3. Contract fetches the evidence live from a public source and runs multi-model consensus.
4. UI shows **PENDING / ACCEPTED / FINALIZED** distinctly — this is the "full transaction lifecycle"
   rubric line `[A2]`, and note the SDK warning that a tx "can be finalized by consensus but still have
   a failed execution. Always check `txExecutionResult`" `[A18]`.
5. On finality, the verdict is emitted toward the EVM target `[A16]`; the demo protocol's state
   reflects `frozen(until=T)`.
6. **Show the failure case too:** submit a *false* proof and demonstrate the verdict is
   `FALSE_REPORT` — and if it is confirmed-but-wrong, show the auto-expiry lifting the freeze with no
   human action. This is the differentiator; it is not optional.

### Explicit exclusions
No token transfers or value movement. No real user funds. No bug submission UI, no whitehat
network, no payout ledger, no severity taxonomy, no shared report registry. No multi-protocol
dashboard. No mobile UI. No auth beyond wallet.

### Differentiator (one sentence)
Anyone can *propose* a freeze, nobody unilaterally *performs* one, and a wrong freeze **expires by
itself** — which is precisely the failure mode the incumbent tools cannot fix `[D2][D7][D8][D9]`.

---

## 3. Hardest technical assumption and the smallest test

**Assumption:** a GenLayer Intelligent Contract can fetch live chain evidence via
`gl.nondet.web` and reach consensus on a *derived verdict* without equivocating, given that "the
leader and validators make **independent requests**" and external APIs may return different data
between calls `[A15]`.

**Smallest test (do this before writing anything else — roughly half a day):**
One contract, one method, three scenarios (real historical drain tx / benign tx / a tx that does not
exist). It must:
1. `gl.nondet.web.get` a public source per the docs' own pattern,
2. return **only stable fields or a derived status** — never raw bodies `[A15]`,
3. finalize to a stable verdict three times out of three, with the leader/validator comparison visible
   in `debugTraceTransaction` `[A18]`.

**Pass condition:** finalizes to the same verdict on 3/3 runs for the true and false cases, and
cleanly returns `INSUFFICIENT_EVIDENCE` (rather than stalling) for the bogus one.
**Fail condition:** any equivocation loop. If it fails, the whole design changes (see R2) — do not
work around it by narrowing to a single deterministic source, because then the trust thesis collapses
into "a better LLM response."

### Second, cheaper test (run in parallel, ~2 h)
Does `@gl.evm.contract_interface` `View`/`Write` + `emit()` work on **Studionet**, given
"Messages to EVM contract can be emitted only on finality" `[A16]` while the Studio page still says
"The Studio currently does not support token transfers, contract-to-contract interactions, or gas
consumption" `[A17]`? These conflict; the conflict is unresolved. Resolve it empirically.

---

## 4. Risks

| ID | Risk | Evidence | Likelihood | Mitigation / decision rule |
|---|---|---|---|---|
| R1 | EVM interaction unavailable on hosted Studio | `[A16]` vs `[A17]` — direct conflict | medium | Test early. Fallback: contract emits the verdict + a signed/attested payload; a small open-source watcher (documented, in-repo) performs the EVM call. Fallback still satisfies "frontend genuinely calls the contract". |
| R2 | Equivocation on live web data stalls consensus | `[A15]` states it explicitly | **high** | The §3 test. Use derived summaries, not raw data. If it still stalls, drop web fetch and feed a pre-fetched evidence digest into the LLM step — and say so honestly in the docs. |
| R3 | The organizer has already changed their mind on the "no live project" status | `[A8]` is undated | low | Check Project Explorer first. Cheap, decisive. |
| R4 | Prompt injection via the submitter's free-text claim | the contract *interprets language*; `[A15]` fetches attacker-influenced pages | **high** | Never let fetched/submitted text be authoritative; constrain output to an enum; treat all external text as data, not instructions. The GenLayer whitepaper's own position: "A lot of the responsibility for preventing prompt injection attacks will fall on the developer of an Intelligent Contract." `[A23]` |
| R5 | Consensus is too slow for a 46-minute problem | Optimistic Democracy + appeal windows | medium | Be honest: this is a *tier-2* judgement for ambiguous cases, not a replacement for deterministic tripwires. Say so in the docs. A judge will respect the honesty and punish the overclaim. |
| R6 | No evidence anyone will pay | payment evidence is level 3 for the category, level 5 for the product | **high** | Do not fake it. State it as a hypothesis in the submission notes. |
| R7 | Solo + $0: 1 slot per week, "most submissions are rejected" | `[A2][A3]` | **high** | Build to done before submitting. Use "needs details" for free corrections. |

---

## 5. Service inventory

No paid services. No API keys required for the MVP. $0 budget is sufficient.

| Purpose | Service | Access needed | Placement | Cost | Verification plan |
|---|---|---|---|---|---|
| Chain + consensus | GenLayer Studionet `studio.genlayer.com`, chain 61999 | Wallet + free testnet GEN from the official faucet | Backend/CLI | free | Deploy the §3 test contract; confirm finality in the explorer |
| Contract authoring | Python ICs, `Depends: py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` | none | Repo | free | `getContractSchemaForCode` succeeds (a known first-deploy failure mode) |
| Frontend | `genlayer-js` (viem-based) + any framework | none | Browser | free | `readContract`, `writeContract`, `waitForTransactionReceipt({status: ACCEPTED\|FINALIZED})`, `isSuccessful` `[A18]` |
| Live evidence source | A public explorer/RPC JSON endpoint; URL passed in at call time | **none — no key** | Called from the contract | free | Confirm `gl.nondet.web.get` returns parseable JSON from inside a contract |
| Demo EVM target | A local/hardhat fork or a public testnet contract with a `pause()` | none | Local | free | Emit a real call; assert the target's `frozen` flag flips |
| Project submission | `portal.genlayer.foundation` | Wallet + account, repo verified via GitHub OAuth `[A11]` | — | free | Read the form before writing notes |

**Proposed application variables (labels only — do not put real values in research output):**
`NEXT_PUBLIC_GENLAYER_RPC`, `NEXT_PUBLIC_GENLAYER_CHAIN_ID`, `GENLAYER_EVIDENCE_URL` (default
evidence source), `GENLAYER_TARGET_CHAIN_RPC`, `GENLAYER_TARGET_CONTRACT`. No secrets required at
this stage; do not add auth or key management to the MVP.

**Prefer the official tooling where it is free:** docs point to a GenLayer Skills plugin for Claude
Code that scaffolds, deploys, and operates contracts `[A22]`. Use it if it works — it cuts real hours
off a solo build. Verify what it actually does before relying on it.

---

## 6. Milestones

Each milestone ends in something observable. Do not start a milestone until the previous one is
observable. Total ≈ 2–3 weeks at 18 h/day; the §3 gate decides whether the plan survives.

| # | Milestone | Observable output | Est. |
|---|---|---|---|
| M0 | **Consensus gate** (the §3 test) | Contract finalizes a stable verdict 3/3 on true/false/bogus cases, with the comparison visible in the trace | 0.5 d |
| M0b | **EVM emit gate** (the §2 test) | A written proof: EVM `emit()` works on Studionet, or the documented watcher fallback is chosen | 0.25 d |
| M1 | Contract v1 | `submit_proof(target, tx_hash, claim)` → stores evidence, runs consensus, stores verdict + rationale + confidence; `get_verdict(id)`; reentrancy/duplicate-id guard | 2 d |
| M2 | Live evidence | Contract fetches the referenced tx and derives stable fields before judging `[A15]`; `INSUFFICIENT_EVIDENCE` path reachable | 1.5 d |
| M3 | Auto-expiry + emit | Freeze carries `expires_at`; a self-lifting path with no human; on-finality emit to the EVM target `[A16]` | 1.5 d |
| M4 | Frontend | Wallet connect, protocol registration, proof submission, **distinct PENDING / ACCEPTED / FINALIZED** states, failed-execution handling `[A18]`, verdict + rationale view, appeal entry point | 3 d |
| M5 | Demo target | A tiny EVM protocol with a pausable withdrawal path that visibly freezes and auto-unfreezes | 1 d |
| M6 | Adversarial demo script | The three scenarios written down as a repeatable script, incl. the false-report case | 1 d |
| M7 | Docs | README (what/why/how), integration guide for another builder's protocol, honest limitations incl. R2/R4/R5, exact reproduction steps | 1.5 d |
| M8 | Pre-submission review | Run the rubric against your own submission, line by line, using the verbatim bar in `FINDINGS.md` §0. **Only then submit.** | 0.5 d |
| M9 | Ship the extras | Public demo video + post — "live demos, videos, and public posts earn extra points and speed up review" `[A2]` | 0.5 d |

---

## 7. Acceptance checks

Traceability from rubric → artifact → evidence. **All currently PENDING. None has been run — no
implementation exists.**

| Requirement (source) | Output to inspect | Acceptance evidence | Result |
|---|---|---|---|
| Real Intelligent Contract, not lightweight `[A2]` | `contracts/` + deployed address | Contract on Studionet with non-trivial consensus logic; a reviewer could not call it a wrapper | PENDING |
| "Solves a real trust problem" `[A2]` | README §Problem | Names freeze authority, cites `[D1][D5][D2]`; states the trust problem in the buyer's words | PENDING |
| "Not just a better LLM response" `[A2]` | README §Why not an LLM | Shows consensus gating an irreversible action; M0 output included | PENDING |
| "Uses live or authoritative data" `[A2]` | M2 trace | `debugTraceTransaction` shows real fetched data and a derived stable verdict `[A15][A18]` | PENDING |
| "Meaningfully different from boilerplate / existing ecosystem contracts" `[A2][A8]` | README §Differentiation | A written comparison against AutoBounty, BuildersClaw, GHBounty, MergeProof `[B1][B2][B4]`; organizer listed this slot as empty `[A8]` | PENDING |
| "Reusable by other builders" `[A2]` | `docs/integration.md` | Another builder could integrate it by following the doc alone | PENDING |
| "Frontend genuinely calls the contract … full transaction lifecycle" `[A2]` | M4 | Real tx hash; PENDING/ACCEPTED/FINALIZED all reachable and distinct; failed-execution path handled `[A18]` | PENDING |
| "Complete source code and accurate docs" `[A2]` | Public repo + README | Clone → run → reproduce, no undocumented steps | PENDING |
| Repo verified via GitHub OAuth `[A11]` | Portal | Verified before submitting | PENDING |
| Notes: what it does, the problem, how to use it `[A6]` | Submission notes | Written against that exact three-part instruction | PENDING |
| "credible path to continued use" `[A2]` | README §Next | Honest: publish module → one integrating protocol → Milestone submissions `[A4]`. No revenue claim | PENDING |
| Not "a learning exercise" `[A2]` | whole repo | No "explore how consensus works" framing anywhere; the exploit scenario is M6, a product feature | PENDING |
| Adversarial case demonstrated | M6 | False report → `FALSE_REPORT`; confirmed-but-wrong → auto-expiry lifts it unaided | PENDING |
| Weekly slot not burned early | Portal | Submit only after M8 passes | PENDING |

---

## 8. Demo story (tied to the rubric)

Four minutes, three transactions, one failure case.

1. **0:00 — The problem (30s).** Kelp DAO: ~$292M drained, pauser multisig reacted **46 minutes
   later** `[D1]`. The freeze authority is one unaccountable key. Aave is currently in court over a
   freeze it says was illegitimate `[D5]`. *(Rubric: solves a real trust problem.)*
2. **0:30 — Why this cannot be a single LLM (30s).** Freezing is irreversible and cross-chain, and one
   key already caused a legal dispute. Show the M0 trace: **independent models fetched the chain
   independently and derived the same verdict** `[A15]`. *(Rubric: not just a better LLM response.)*
3. **1:00 — Live (2m).** Submit a real historical exploit tx. Show the contract fetching live
   evidence, the PENDING → ACCEPTED → FINALIZED lifecycle in the UI, and the verdict arriving on the
   EVM target with an `expires_at`. *(Rubric: live data; frontend genuinely calls the contract.)*
4. **3:00 — The failure case (1m).** Submit a **false** proof → `FALSE_REPORT`. Then show a
   confirmed-but-wrong freeze **lifting itself on expiry with nobody's permission.** *(Rubric:
   differentiator; answers the "human-controlled breakers are themselves a vulnerability" objection
   `[D2]`; the closest ecosystem projects have no equivalent `[B1][B2]`.)*
5. **4:00 — Reuse (20s).** Show `docs/integration.md`: drop the module into another protocol.
   *(Rubric: reusable by other builders.)*

**Anticipated judge questions — answer them before you submit:**
- *"Isn't a 46-minute pause too slow?"* → Yes. This is tier-2 judgement for ambiguous cases, not a
  replacement for deterministic tripwires. (R5)
- *"What stops a false report from freezing a healthy protocol?"* → Consensus plus a mandatory
  auto-expiry; no human action is required to undo it. Show it.
- *"Why GenLayer? Why not an LLM plus a script?"* → Because a single verdict authorizes freezing
  real user funds, and because a multisig cannot be audited afterwards. Point at the Aave filing.
- *"Aren't the validators' independent web fetches a bug?"* → Yes, and it is the core design
  constraint; here's the derived-summary technique `[A15]`.

---

## 9. What I could not verify (carry these forward)

1. No authenticated portal session — no browser was connected. The submission form's required
   fields and the exact 20–4,000 range are unverified `[A7]`. **Read the form before writing notes.**
2. Project Explorer was not enumerated. The "no live emergency-halt project" claim rests on the
   organizer's text `[A8]` plus a weak host scan `[B6]`. **Check this first — cheap and decisive (R3).**
3. EVM interaction on Studionet is contradicted between `[A16]` and `[A17]`. **Resolve in M0b (R1).**
4. No protocol team has been asked whether they want this. Payment evidence is level 3 for the
   category, level 5 for the product. **The cheapest upgrade is one real conversation or a signed
   LOI (R6).**
5. AutoBounty's repo was not inspected. **BuildersClaw's source WAS read** (2000-pt Grand Winner) → `BUILDERSCLAW-REFERENCE.md`; its code was not executed and its live platform was not exercised. No license file → reference-only, do not copy code `[B7][B8]`.
6. The cross-registry prior-art gap underpinning candidate C is **unconfirmed** (`SOURCES.md` §E).

---

## 10. Immediate next actions

1. **Answer: B or A.** Everything else waits on this.
2. If **B** — check the Project Explorer for an existing pause/circuit-breaker project (R3). Ten
   minutes, and it can overturn the recommendation.
3. If **B** — run M0, the consensus gate, before writing any product code. If it fails equivocation,
   stop and re-plan; do not paper over it.
4. If **A** — run the prior-art validation test in `FINDINGS.md` §1.3 before building anything.

Do not begin implementation until step 1 is answered.

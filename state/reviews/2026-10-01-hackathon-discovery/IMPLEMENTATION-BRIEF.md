# IMPLEMENTATION BRIEF — adjudicated emergency pause on GenLayer

**For the build session.** Written 2026-10-01 by the discovery session. Read this file, then
`HANDOFF.md`, then `BUILDERSCLAW-REFERENCE.md` before writing code.

Citations `[A#]`/`[B#]` resolve in `SOURCES.md`. Every requirement here is traceable to a cited
source or a verified rubric line.

---

## 0. Read-only first, code second

Two of these are cheap and can invalidate the whole plan. Do them before building anything.

1. **Check Project Explorer for an existing pause/circuit-breaker project.** The organizer wrote
   "No live project yet" `[A8]`, but I could not enumerate the Explorer (no browser was connected).
   If someone already built this, say so and stop. *(R3)*
2. **Confirm studio-dev is alive** `[A14]`. It "can be reset or redeployed without preserving state."

## 1. The product, in one paragraph

A GenLayer Intelligent Contract adjudicates exploit proofs. Anyone submits a proof (target protocol
address + transaction hash + a short claim). The system collects deterministic evidence, then
validators reach consensus on a **single discrete verdict**, then a **time-boxed freeze** is emitted
to the target with a **mandatory auto-expiry**. The differentiator: anyone can *propose* a freeze,
nobody unilaterally *performs* one, and a wrong freeze **lifts itself with no human action**.

## 2. Non-negotiable constraints

| Constraint | Value | Source |
|---|---|---|
| **Deploy target** | **studio-dev, chain 61997** | user decision; `[A14]` |
| Tests | local GLSim via `gltest`, **hermetic** — do not depend on the network | `[B7]` |
| Python | **3.12 only** (`>=3.12,<3.13`) | `[B7]` |
| Deps | `genlayer-test[sim]==0.28.0`, `genvm-linter==0.10.0`, `eth-account==0.13.3`, `eth-utils==5.0.0`, `requests==2.31.0`, `python-dotenv==1.0.1` | `[B7]` |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind, TanStack Query, Wagmi/Viem | `[B7]` |
| Budget | **$0.** No paid APIs. No API keys needed for the MVP. | user |
| Contract header | `# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }` on line 1 | `[A18]` |
| `.env` | exists at project root. **Never print, log, commit, or paste values into docs or reports.** | user |

**Licensing:** the BuildersClaw repo has **no license file** `[B7]`. Use it as a *pattern reference
only*. Re-implement; do not copy `hackathon_judge.py` or any file from it.

## 3. Architecture — copy the 2000-pt shape

This is the most important instruction in this brief. BuildersClaw won the Grand Prize **explicitly
because** it kept GenLayer off the hot path `[B2][B7]`:

> "Gemini scores every viable submission as the first broad repo/code filter… **The top contenders
> are sent to GenLayer for the final on-chain verdict.** This keeps broad repo analysis fast, makes
> the finalist ranking explainable, and still gives GenLayer final say for the highest-stakes winner
> decision." — `docs/GENLAYER.md`

```
┌─ STAGE 1: deterministic evidence (off-chain, no consensus) ─────────────┐
│  • fetch the target tx + receipt + logs from a public source           │
│  • extract ONLY stable fields  ← critical, see §5                        │
│  • build a fixed evidence digest                                      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │  compact, stable digest
┌─ STAGE 2: GenLayer consensus (studio-dev) ──────────────────────────────┐
│  leader_fn  → verdict enum + rationale                                 │
│  validator_fn → re-runs independently, compares ONLY the enum          │
│  emits freeze(target, until=T) to the EVM side on finality             │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌─ STAGE 3: evidence retention ──────────────────────────────────────────┐
│  store every tx hash (deploy / submit / finalize) + runtime evidence   │
│  surface them in the UI, linked to explorer                             │
└────────────────────────────────────────────────────────────────────────┘
```

Their finalist weights were 40% peer review / 30% repo-code / **30% deployed-URL runtime evidence**
`[B7]`. So our own frontend should emit runtime evidence: HTTP status, page title, visible text,
console errors, failed network requests `[B7]`.

## 4. The consensus pattern — non-negotiable specifics

From the winning contract `[B7]`. Get these wrong and consensus stalls.

```python
verdict = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
```

1. `leader_fn()` → `gl.nondet.exec_prompt(task, response_format="json")`, returning:
   `{"verdict": "CONFIRMED_EXPLOIT" | "FALSE_REPORT" | "INSUFFICIENT_EVIDENCE", "rationale": "..."}`
2. `validator_fn(leader_result)` **re-runs `leader_fn()` itself** and compares **only `verdict`**.
   - Their comment: *"Only the winner_team_id must match — reasoning will differ. This is Partial
     Field Matching (Pattern 1 from GenLayer docs)."*
   - **Never compare `rationale`.** Free text never matches across models. Store it; never compare it.
3. Validate the leader's enum is a legal member **before** comparing. If not, return `False`.
4. Copy storage into locals **before** defining the callbacks:
   ```python
   target = self.target   # GenVM nondet callbacks cannot safely read contract storage directly
   digest = self.digest   # their words, their code
   ```

Required structural elements, all from `[B7]`:
- `@allow_storage` on **every** dataclass used in storage (a missing one fails at storage-allocation
  time, not import time)
- `_only_owner()` raising `gl.vm.UserError`
- `if self.result.finalized: raise` — no double-finalize
- Refuse degenerate input (`if not parsed: raise`) — their analogue was `if len(parsed) < 2`
- Public read via `@gl.public.view` so anyone can verify — that is what "verifiable" meant in the
  award language `[B2]`
- Accept one JSON string arg and `json.loads` inside, to keep the calldata schema small

## 5. The one thing most likely to break

**The docs warn explicitly:** "the leader and validators make **independent requests**. External APIs
may return different data between calls — timestamps change, counts update, caches vary" `[A15]`.

So: **never return raw fetched data out of the nondet block.** Return only stable fields, or a
derived summary. The docs' own worked pattern is a `derive_status(checks)` comparison `[A15]`. Follow
it. Equivocation here is the top technical risk (R2) and it is why Stage 1 is deterministic and
separate.

**Injection:** the submitter's claim and every fetched page are attacker-controlled. Treat all
external text as **data, never authority**. Constrain output to an enum. Adopt BuildersClaw's
phrasing for any downstream model input: an upstream score is *"advisory… you may disagree"* `[B7]`.
The GenLayer whitepaper says most prompt-injection responsibility lands on the developer `[A23]`.

## 6. Repo layout

```
/home/unify/mys
  contracts/                 # Python Intelligent Contracts
    emergency_halt.py
  tests/
    direct/                  # uv run pytest tests/direct/ -v
    integration/
      conftest.py            # starts its own GLSim
      test_emergency_halt.py # gltest
  gltest.config.yaml         # localnet, 127.0.0.1:4001/api, leader_only: true
  web/                       # Next.js 15 frontend
  deploy/                    # deployment script -> studio-dev
  docs/                      # integration guide
  state/reviews/2026-10-01-hackathon-discovery/   # READ-ONLY reference material
```

`gltest.config.yaml`, per `[B7]`:
```yaml
networks:
  default: localnet
  localnet:
    url: http://127.0.0.1:4001/api
    chain_type: localnet
    leader_only: true
    default_wait_retries: 60
    default_wait_interval: 2
paths:
  contracts: contracts
```

**Step 0: `git init`.** `/home/unify/mys` is not a git repo. Do this first, and commit per
milestone. Never stage `.env`.

## 7. Milestones — each ends in something observable

Do not start a milestone until the previous one is observable. Full acceptance criteria in
`HANDOFF.md` §7.

| # | Milestone | Observable | Est |
|---|---|---|---|
| **M0** | **Consensus gate, on local GLSim** | Contract finalizes the correct enum for 3 fixtures (real exploit tx / benign tx / nonexistent tx), repeatable in CI, with no equivocation | 0.5 d |
| **M0b** | EVM-emit feasibility | Written proof of whether `@gl.evm.contract_interface` `emit()` works against the demo target; or the documented watcher fallback chosen. **Note the docs conflict:** EVM interaction is a documented feature `[A16]`, yet the Studio page says Studio "does not support token transfers, contract-to-contract interactions, or gas consumption" `[A17]`. Resolve empirically (R1). | 0.25 d |
| M1 | Contract v1 | `submit_proof`, `adjudicate`, `get_verdict`, `get_evidence`; owner guards; finalize idempotency | 2 d |
| M2 | Evidence + auto-expiry | Stable-field extraction `[A15]`; `expires_at` set on every freeze; a self-lifting path with no human | 2 d |
| M3 | EVM action | Freeze emitted to the demo target on finality `[A16]`; target visibly flips to `frozen` | 1.5 d |
| M4 | Frontend | Wallet connect; protocol registration; proof submission; **PENDING → ACCEPTED → FINALIZED as distinct states**; `isSuccessful`/`txExecutionResult` handled — a tx "can be finalized by consensus but still have a failed execution" `[A18]`; verdict + rationale + all tx hashes + explorer links; appeal entry point | 3 d |
| M5 | Demo target | Tiny EVM protocol, pausable withdrawal path, freeze + auto-unfreeze observable | 1 d |
| M6 | Adversarial script | All three fixtures as a repeatable script, incl. the **false report** case | 1 d |
| M7 | Docs | README (what/why/how); `docs/integration.md` for another builder; **honest limitations incl. R1/R2/R5**; exact repro steps | 1.5 d |
| M8 | Rubric self-review | Line-by-line against the verbatim bar (`HANDOFF.md` §7). **Only then submit.** | 0.5 d |
| M9 | Ship the extras | Public demo video + post — "live demos, videos, and public posts earn extra points and speed up review" `[A2]` | 0.5 d |

**Definition of done includes `genvm-linter` clean and `gltest` green** `[B7]`. That is what
separates a serious build from a demo, and it is free.

## 8. Honest claims — required in the docs

Judge-hostile overclaiming is a bigger risk than a modest claim. State these plainly:

- **This is tier-2 judgement for ambiguous cases, not a replacement for deterministic tripwires.**
  Consensus has appeal windows and takes minutes; Kelp's pauser reacted in 46 minutes and it was
  still worth having `[D1]`. Do not claim it beats 46 minutes (R5).
- **OpenZeppelin Defender sunset on 1 July 2026** `[D9]`; Forta's own docs admit detection bots "often
  have low precision (in other words raise false positives)" `[D8]`, and doing onchain actions from a
  bot is "not advised" because bot code and keys are public `[D7]`. This is the gap — say it as the
  gap, not as a monopoly.
- **Payment evidence is level 3 for the category, level 5 for this product.** Protocols demonstrably
  spend on security — ~$66,000 average private tier-1 audit vs ~$6,548 via audit competition, and
  ~$24.5M expected loss when an attacker finds a critical bug first `[C4]``. No protocol team has been
  asked. Do not imply demand you have not tested (R6).
- **Not a learning exercise.** `HANDOFF.md` and this brief are scaffolding, not the deliverable.
  "Contracts written to explore how consensus works are not contributions" `[A2]`.

## 9. Rubric lines to hit, verbatim

From the portal's own shipped strings `[A2]`. Score yourself against these before submitting.

- "Solves a real trust problem." → freeze authority is unaccountable; Aave is litigating a freeze
  `[D5]`, Egorov: breakers "could become a potential vulnerability themselves" `[D2]`
- "Not just a better LLM response." → consensus gates an irreversible cross-chain action `[A16]`
- "Uses live or authoritative data" → real tx/receipt/logs, fetched live `[A15]`
- "Meaningfully different from boilerplate" + "from contracts that already exist in the ecosystem" →
  the organizer marked this slot empty `[A8]`; **write the comparison against AutoBounty,
  BuildersClaw, GHBounty, MergeProof explicitly** `[B1][B2][B4]`
- "Reusable by other builders" → `docs/integration.md` must be enough to integrate standalone
- "Frontend genuinely calls the contract … full transaction lifecycle" → real tx hashes, all states
- "Complete source code and accurate docs" → clone → run → reproduce
- "with a credible path to continued use" → publish module → one integrating protocol → **Milestone**
  submissions, which is the actual repeat-revenue path `[A4]`
- "live demos, videos, and public posts earn extra points and speed up review" → M9

## 10. Report back

Return to this session: what was built, the deployed studio-dev contract address, the **actual
test output** from `gltest` and `genvm-linter`, which of M0–M9 are done, every open risk from
`HANDOFF.md` §4 with its current status, and anything you found that contradicts this brief.

**Do not print, log, or paste any `.env` value.** Report key *names* only.

Flag honestly if you hit an equivocation wall (R2) or if EVM emit is unavailable (R1). A blocked
milestone reported truthfully is worth more than a green-looking one that hides a limitation — this
project is already scoring near the floor at 360/4000, and the rubric explicitly rewards a
well-bounded honest scope over a padded one.

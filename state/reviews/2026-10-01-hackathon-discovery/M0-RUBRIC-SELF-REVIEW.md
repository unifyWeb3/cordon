# M8 — rubric self-review, line by line

Scored against the portal's own shipped strings `[A2]`. "Verdict" is my own assessment, not
a prediction of the score — reward weights are not published anywhere `[SOURCES.md]` §
"Research coverage limits".

## Honest claims required by the brief §8 — all stated in README

| Required claim | Where |
|---|---|
| Tier-2 judgement, not a replacement for deterministic tripwires | README limitations 1; integration.md §7 |
| Consensus takes minutes; does NOT beat Kelp's 46 minutes | README limitations 1, stated plainly |
| Defender sunset 1 July 2026; Forta low precision / onchain actions "not advised"; framed as the gap, not a monopoly | README problem section |
| Payment evidence is inference; no protocol team asked | README limitations 6 |
| Not a learning exercise; no "explore how consensus works" framing | README is product-framed throughout |

## Line-by-line

| Rubric line `[A2]` | Artifact | Verdict | Notes |
|---|---|---|---|
| "Solves a real trust problem." | README problem section; docs/integration.md §8 | **Met** | Names freeze authority; Kelp 46min, Aave SDNY, Egorov's "could become a potential vulnerability themselves", Circle's "just as dangerous for legitimate users". |
| "Not just a better LLM response." | contract `_adjudicate`; `test_validator_ignores_rationale`; README "Why this is not" | **Met** | Consensus gates an irreversible action. Proof is a test: different rationale + same verdict must agree. |
| "Uses live or authoritative data." | `live-drain` / `live-real-tx` transcripts; `_adjudicate` RPC batch | **Met** | Real Base Sepolia receipts fetched at adjudication time; stable fields derived from them. |
| "Meaningfully different from boilerplate" | README architecture; integration.md §8 | **Met** | Explicit two/three-stage design with the BuildersClaw rationale, plus the enum-only Partial Field Matching. |
| "…from contracts that already exist in the ecosystem" | integration.md §8 | **Partially met** | Written comparison vs AutoBounty, BuildersClaw, GHBounty, MergeProof. **Caveat:** could not enumerate the authenticated Project Explorer — no browser in this environment. "No evidence of prior art", not "confirmed none". |
| "Reusable by other builders" | docs/integration.md | **Met** | Steps, the Solidity interface, the `until`-is-a-timestamp requirement, the watcher fallback, the comparison table. |
| "Frontend genuinely calls the contract … full transaction lifecycle" | web/; LIVE-RUN.md | **Met** | `readContract` for stats/cases/evidence, `writeContract` for submit, polled lifecycle. PENDING→PROPOSING→COMMITTING→ACCEPTED→FINALIZED all observed live and rendered as discrete steps. |
| "Complete source code and accurate docs" | whole repo | **Met** | `uv sync` → `pytest` → `genvm-lint check` → `npm run dev`, all verified this session. |
| "with a credible path to continued use" | integration.md; README | **Weak** | Publish module → one integrating protocol → Milestone submissions `[A4]`. No revenue claim, because none is validated. |
| "live demos, videos, and public posts earn extra points" | — | **NOT DONE** | M9 not started: no video, no public post. |
| "Not a learning exercise." | whole repo | **Met** | The exploit scenario is the product, not a demo of consensus. |

## Technical claims checked against evidence, not assertion

| Claim | Evidence | Verdict |
|---|---|---|
| Verdict is correct per fixture, repeatable | 38 hermetic tests | Met |
| Validators agree (no equivocation) | `vm.run_validator()` in tests; `MAJORITY_AGREE` live, 4 transactions | Met |
| Rationale never compared | `test_validator_ignores_rationale` | Met |
| Enum always compared | `test_validator_compares_the_enum` | Met |
| Out-of-enum coerced, not obeyed | `test_out_of_enum_model_output_is_coerced` | Met |
| Prompt injection cannot override evidence | `test_injected_claim_does_not_override_evidence` | Met at the wiring level; a real model could still be talked into a *wrong enum*, bounded by expiry |
| Freeze always bounded | `test_confirmed_exploit_arms_a_bounded_freeze`; max 3600 enforced | Met |
| Freeze self-lifts, no human | `test_freeze_lifts_itself_with_no_human`, `test_reap_expired_is_permissionless_and_idempotent` | Met |
| Evidence digest is equivocation-safe | `test_rpc_reduction_is_stable_across_volatile_inputs` | Met |
| `genvm-linter` clean | `genvm-lint check` → lint + validation passed | Met |
| EVM emit delivers the freeze | **not verified** | **NOT ESTABLISHED** — see README "What we could not verify". Emit is a no-op under GLSim and never observed on real GenVM. |
| Deployed to studio-dev | attempted; execution broken there | **NO** — Studionet used instead |

## Where this is weakest

1. **The EVM emit is unverified.** The product's headline is a freeze being delivered to a
   target, and that last hop is not demonstrated. Documented watcher fallback is specified in
   integration.md §5, but not exercised.
2. **No demo target contract.** `docs/integration.md` gives the Solidity, but nothing is
   deployed to receive a freeze, so M3/M5 are incomplete.
3. **No `CONFIRMED_EXPLOIT` on live data.** Covered hermetically only. Honest, but weaker.
4. **Prior-art check incomplete** (no browser).
5. **No M9 artefacts.**

## Recommendation

Do not submit yet. The two cheapest high-value gaps to close are (a) deploy the Solidity demo
target so the last hop is real, and (b) M9. Both are smaller than what is already built.

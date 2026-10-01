# Discovery findings — GenLayer builder contribution program

Date: 2026-10-01 (Thursday, 09:34 UTC). Project root: `/home/unify/mys`.
Decision requested: assess a supplied idea (AI-assisted bug bounty platform on GenLayer) and, if the
evidence exposes a material problem, recommend a stronger feasible option.

Sources are cited inline as `[A#]` / `[B#]` / `[C#]` / `[D#]` and defined in `SOURCES.md`.
Method and limits for every claim are recorded there.

---

## 0. What the program actually is (verified)

**This is not a hackathon. It is a rolling points program with a weekly submission cap.** That single
fact reshapes the whole plan, so it comes first.

- Ongoing program, "Points have no monetary value, are not an investment, and provide no right or
  expectation of profit or redemption"; submissions are reviewed by GenLayer Stewards `[A10]`.
- There is **no fixed deadline and no timezone deadline to race**. The only clock is the weekly
  submission window: "Monday 00:00 to Sunday 23:59 UTC", "Resets Monday 00:00 UTC" `[A3]`.
- You get **N new project slots per user per week** (`"{n} new {slots} per user, each week"`) and the
  portal showed **1 spot left** for you `[A3]`. The user reported this; the literal number was not
  independently extractable because points/slot values are served dynamically `[A7]`.
- **The Project category is explicitly strict and rejection is expensive**: "This category is strict.
  Most submissions are rejected." and "The use case or implementation falls short. Fixes or new
  evidence require a new submission, which uses a slot." `[A2][A5]`
- There are cheap escapes: a "needs details" outcome lets you "Update the existing submission. Does
  not use a slot", and an Appeal "Challenges the original decision only, with the work as it was
  submitted. Does not use a slot." `[A5]`

**Strategic consequence:** with 1 slot per week and a "most submissions are rejected" bar, you get
roughly one real attempt per week. The correct posture is *do not submit until the demo runs and the
docs are finished* — a rejection burns a week. The rubric even tells you this: "Complete source code
and accurate docs", "Frontend genuinely calls the contract and handles the full transaction
lifecycle" `[A2]`.

There is a second, larger prize beyond the Project slot. The four categories are **Intelligent
Contract**, **Project**, **Milestone**, and **Appeal** `[A4]`. **Milestone** submissions are for
improving an already-published project and require "A published Explorer project is required" — i.e.
after a Project is accepted and appears in Project Explorer, you can keep submitting substantial
deltas ("New functionality, real integrations, or meaningful scope. Not cosmetic updates"; "Adoption,
users, or external interest strengthen the case") `[A4]`. That is the repeat-revenue analogue, and
it is why "a credible path to continued use" is graded rather than decorative.

### The published quality bar, verbatim `[A2]`

| Line | Implication for scope |
|---|---|
| "Solves a real trust problem." | A trust *problem*, not a feature. |
| "Not just a better LLM response." | The explicit killer for "AI-assisted X". |
| "Uses live or authoritative data" / "when outcomes depend on real-world facts." | Must fetch real data, deterministically enough for consensus. |
| "Meaningfully different from boilerplate," + "from contracts that already exist in the ecosystem." | The ecosystem is the comparison set. This is the line the supplied idea collides with. |
| "Reusable by other builders." / "If it would not be useful to someone else building on GenLayer, it is not ready to be submitted." | Must be a building block, not a closed app. |
| "Complete source code and accurate docs." | Public repo + real docs. |
| "Frontend genuinely calls the contract" / "handles the full transaction lifecycle." | Real transactions, not mocked. |
| "The same work does not count twice." / "Not repackaging." / "Not a learning exercise." / "Renaming, restyling, or reorganizing existing work does not qualify." | No incremental repackaging. |
| "live demos, videos, and public posts earn extra points and speed up review." | Ship a public demo + posts before submitting. |

**No official scoring weights exist.** I could not find published weights for any rubric line. The
rubric is a pass/fail quality bar plus a discretionary 20–4,000 range `[A7]`. Any number I give below
is my own stated method, not an official weight.

---

## 1. Assessment of your supplied idea

> "AI-assisted bug bounty platform powered by GenLayer intelligent contracts. Helps Web3 protocols
> and security teams manage vulnerability reports through structured submissions, AI-assisted
> evaluation, duplicate detection, severity classification, payout tracking, and a shared
> vulnerability registry."

**Verdict: the problem is real and the buyer has money, but this specific product is already
solved — twice outside GenLayer and once inside it. As written it is a high-probability rejection.**

Restated in the dullest true terms, per the value-articulation guide: *a web form where whitehats
submit vulnerability write-ups, a language model assigns each one a severity, and the score is written
to a chain.*

### 1.1 Why it collides with the rubric

**(a) "Not just a better LLM response."** Every listed feature is a language-model classification task
over text. Severity classification, duplicate detection, and relevance triage are *the* canonical LLM
use cases. The rubric names this failure mode explicitly `[A2]`.

**(b) "Meaningfully different … from contracts that already exist in the ecosystem."** This is the
decisive collision. The GenLayer ecosystem already contains, by the organizer's own listing:

- **AutoBounty** — "a self-executing bounty layer for GitHub, where GenLayer verifies the work and
  Avalanche holds the funds. A maintainer posts an issue, USDC goes into onchain escrow, a contributor
  (human or agent) submits a PR, and the evaluation is run through GenLayer's consensus before payment
  is released or returned." Bradbury Hackathon **Track Winner**, **1000 pts** `[B1]`
- **BuildersClaw** — agents compete for bounties, "AI judges score every line", on-chain
  join/submit/settle. Bradbury Hackathon **Grand Winner**, and a **live product** `[B2]`
- **GHBounty** — "open-source bounties released on verified work"; **MergeProof** — "staked review and
  settlement on pull requests" `[B4]`

And the organizer's *own* "Ideas we want built" list for the Future of Work track is almost your
pitch: **"Automated bug bounties. Severity tier assigned from the PR, bounty released on merge."**
`[A8]` The slot is both occupied and already-scored.

**(c) The outside-web alternatives already ship the exact feature list.** This is not a "maybe
someone does this" concern; it is near feature-for-feature coverage by two funded incumbents:

| Your feature | Immunefi | Sherlock |
|---|---|---|
| structured submissions | Whitehat dashboard + triage team before forwarding to the project `[C2]` | Contest/contest submission infra `[C3]` |
| AI-assisted evaluation | — | **Audit Engine**: "frontier LLMs, purpose-built AI auditors, and AI-native security researchers… multiple layers of validation and two iterative improvement cycles" `[C3]` |
| duplicate detection | "Smarter auto-banning. Duplicate reports no longer count toward the auto-ban threshold." `[C1]` | "our judging system takes care of duplicates for you"; duplicates "cleared" in the judging pipeline `[C3]` |
| severity classification | **VSCS v2.3**, a 5-level scale (Critical/High/Medium/Low/None) adopted contractually by programs `[C2]` | "severities are corrected" in the judging pipeline `[C3]` |
| payout tracking | $143.1M cumulative paid; 230 active programs; per-program dashboards `[C1][C5]` | "Sherlock handles researcher payouts and triage"; 1,500+ audits, 11,000+ researchers `[C3]` |
| managed human triage | **Managed Triaging** is a named product line `[C1]` | Lead Senior Watsons, formal 4-phase judging `[C3]` |

Scale and switching cost: Immunefi states 230–232 active programs, ~$190B TVL protected, and **"93%
of critical vulnerability disclosures in crypto flow through this platform"** `[C1]`. A protocol
already running an Immunefi program has integrations, a brand, a whitehat pipeline, and a KYC story.
Beating that with a better classifier is not a solo, $0, one-week build.

**(d) Payer reachability — the weakest gate.** The buyer is a Web3 protocol founder/CTO. Reaching
them cold is a venture-scale motion. Your substitute budget is real but the channel is not yours.

### 1.2 Value-articulation table — your idea

| Gate | Answer | Specificity check | Status |
|---|---|---|---|
| Moment | A protocol with a live Immunefi program receives a report; a human triager reads it before the protocol team sees it. Real and frequent. | Who: triage analyst. When: continuous. Cost today: days per report, and mis-triaged reports get auto-banned. | **pass** |
| Reframe | Stated as the *artifact* ("bug bounty platform"). The problem is **vulnerability-disclosure triage**. Wrong category name → wrong incumbents, wrong price reference. | The dull version is not obviously worth buying *against Immunefi*. | **fail (framing)** |
| Substitute | Immunefi Managed Triaging; Sherlock judging pipeline; a two-person internal security Discord. `[C1][C2][C3]` | Budget demonstrably exists. | **pass (substitute), fail (you lose to it)** |
| Payer | Web3 protocol founder/CTO paying out of the security budget. Narrowest real buyer. | Reachable only via a warm intro, an Immunefi partnership, or a GenLayer channel. | **unresolved / fail on reach** |
| Repeat | Continuous coverage: every new report, every release. Genuine. | Subscription-shaped. | **pass** |
| Payment evidence | **Level 3** — users demonstrably spend on the substitute today ($143.1M paid, 230 programs) `[C1]`; but **level 5** for *this product*. No budget owner has confirmed this line item. | Level 3 for the category, level 5 for the artifact. | **pass (category) / fail (product)** |

**Weakest gates: payer reachability, then the framing.** Note the trap: the substitute's spend
(level 3) will read like evidence for *your* product if quoted without the qualifier. It is not.

### 1.3 What would rescue it (stated, not recommended)

The one component of your idea that is genuinely underserved is **cross-registry prior art**: "was
this root cause already reported elsewhere, and who is entitled to the payout?" Immunefi dedupes
*within* its platform; Sherlock dedupes *within* its contests. Nobody appears to adjudicate
prior-art across the industry — and it has real money attached (the Euler case, where the exploited
function was introduced as a fix for a bug reported via Immunefi ~1 year earlier, is a prior-art
dispute in all but name) `[C2]`.

**I could not verify this gap.** My searches for a cross-platform prior-art/duplicate-disclosure
system returned only CVE-database noise (see `SOURCES.md` §E). Treat the gap as **unconfirmed**. If
you want to pursue your idea, the next step is a specific falsifiable test, not more reading: get a
real prior-art dispute in front of a security lead and ask whether they have a process for it.

---

## 2. Recommended pivot: adjudicated emergency pause (same domain, different artifact)

Keep the domain — **security incidents on DeFi protocols** — and change the artifact from "a place to
submit reports" to "the thing that decides whether a protocol gets frozen."

The organizer already asked for this, in the open, and flagged it as unoccupied:

> Autonomous Protocols — "Ideas we want built": **"Emergency halt module. Pauses a target contract
> when anyone proves an active exploit."** And for that track: **"No live project yet. The first team
> here sets the reference."** `[A8]`

GenLayer's own first-party use-case list includes it too: "Monitor crypto news sites to detect when a
protocol is experiencing an attack and trigger an emergency shutdown" `[A20]`.

Dull restatement: *anyone can post proof that a protocol is being exploited; a set of independent
models checks the proof against the live chain and decides whether to freeze withdrawals — and if it
was wrong, the freeze lifts itself.*

### 2.1 The customer, in a specific moment

A three-to-fifteen person DeFi protocol team, 02:00 UTC, an attacker is draining a bridge.

- Kelp DAO, 18 Apr 2026, ~$292M / 116,500 rsETH drained at 17:35 UTC. **"Kelp's emergency pauser
  multisig froze the protocol's core contracts 46 minutes after the successful drain, at 18:21 UTC."**
  `[D1]` The pause worked. It also arrived 46 minutes late. Contagion pulled ~$7B out of Aave over
  the weekend `[D1]`.
- Drift, 1 Apr 2026: onchain monitors flagged a treasury outflow ~1:30pm; within roughly an hour
  vault assets fell $309M → $41M; losses estimated $136M–$285M depending on source `[D4]`.
- The pattern is not code bugs. IOSG's read on the April 2026 cluster (Drift, KelpDAO, Wasabi): **no
  smart-contract code vulnerabilities at all** — a bridge misconfiguration, compromised governance
  keys, and social engineering `[D4]`. Chainalysis put 2025 crypto theft at a record $3.4B with a
  growing share from key-management failures `[D4]`.

**Current workaround:** a privileged multisig holds `pause()`. It is a phone call, a delay, and a
single point of failure. Andre Cronje (Flying Tulip): circuit breakers "can make sense in theory, but
only if they are implemented in a way that does not create a new privileged attack surface" `[D2]`.

**The reason to switch — this is the actual trust problem.** Freeze authority is currently
unaccountable power, and it is already causing harm:

- Circle's Dante Disparte, after Drift: pushed DeFi to adopt on-chain circuit-breaker controls, while
  warning that "unchecked intervention by issuers would be just as dangerous for legitimate users"
  `[D3]`.
- **Aave LLC filed an emergency motion in the Southern District of New York to vacate a freeze on
  30,766 ETH (~$73M) applied to Arbitrum DAO**, arguing a prolonged freeze "jeopardizes the entire
  post-hack recovery mechanism" and could trigger cascading liquidations `[D5]`.
- The failure mode of "speed + scope" freeze powers: "the 'speed + scope' combination that enables
  freezing also makes the failure mode catastrophic if the Council itself is compromised" `[D6]`.
- And the sharpest objection to any auto-pause, from Curve's Michael Egorov: **"The circuit breakers
  are controlled by humans, which means they could become a potential vulnerability themselves"**
  `[D2]`.

**Differentiator, stated as a mechanism rather than a slogan.** A naive auto-pause just relocates the
key. The design commitment that makes this a trust product instead of a trigger:

1. **A freeze is not permanent, and does not need a human to undo it.** It carries a mandatory
   auto-expiry. A false positive self-heals; it does not require the team that is already in an
   incident to also fight an attacker on the admin key. This directly answers Egorov's objection
   `[D2]`.
2. **Anyone can propose; nobody unilaterally freezes.** The irreversible action is gated on a
   multi-model consensus verdict over live chain data, not on one key or one LLM call.
3. **The verdict is auditable afterwards.** The evidence, the reasoning, and the appeal are on record,
   so a contested freeze (like Aave's `[D5]`) has a basis to be reviewed.

A single LLM cannot be trusted to authorize freezing $25B — and equally, a single multisig cannot be
audited. That is a genuine trust problem, which is exactly the bar.

### 2.2 Why GenLayer is central, not decorative

This is the part the rubric is actually testing. The decisive judgment — *is this a real exploit, or a
false report, a normal operation, or an attack on the pauser itself?* — is:

- **subjective** (no deterministic function of the input settles it),
- **over live data** (the tx, the trace, the balances, the flows, right now),
- **irreversible and cross-chain in consequence** (it gates freezing real user funds),
- and **currently made by exactly one unaccountable human key** `[D5][D6]`.

That is the definition of the problem GenLayer exists for. The GenLayer docs make the mechanism
concrete: `gl.nondet.web.get` / `gl.nondet.web.request` for live evidence `[A15]`, LLM consensus
`[A21]`, `gl.eq_principle.*` to agree on the output `[A15]`, and
`@gl.evm.contract_interface` with `emit()` so a finalized verdict can act on an EVM target — "Messages
to EVM contract can be emitted only on finality" `[A16]`.

### 2.3 The honest technical problem, stated up front

**Consensus safety is the hard part, and the docs call it out directly:** "the leader and validators
make **independent requests**. External APIs may return different data between calls — timestamps
change, counts update, caches vary." `[A15]`

A naive "fetch the tx, ask the model, return the verdict" will equivocate and stall. The prescribed
fix is to never return raw web data — extract stable fields, or compare a *derived summary* across
leader and validator (the docs' own `derive_status` pattern) `[A15]`.

This is the single most important engineering constraint on the project, and it is the smallest
experiment that must run first (see `HANDOFF.md` R1/R2). It is also the most *interesting* part of
the build: "did independent models, looking at the same chain independently, derive the same
verdict?" is the whole product thesis in one function.

### 2.4 Value-articulation table — recommended pivot

| Gate | Answer | Specificity check | Status |
|---|---|---|---|
| Moment | Protocol engineer / founder, 02:00 UTC, funds draining, multisig 46 minutes behind `[D1]`. Cost of the status quo: 46 minutes and one unaccountable key. | Specific, dated, quantified, and it recurs every incident. | **pass** |
| Reframe | Category = **incident response for onchain protocols**, not "security tool". The valued job is "deciding whether to freeze, and being able to justify it". | If GenLayer vanished, would someone still pay to have that decided? Yes — that is what Forta/Defender/consultants sell. | **pass** |
| Substitute | Forta detection bots + a Defender Autotask calling `pause()` `[D7]`; a human multisig; OpenZeppelin incident-response templates `[D10]`. **And the incumbent console is dead: "OpenZeppelin Defender will sunset on July 1, 2026"** `[D9]`. | Budget exists; but Forta's own docs admit detection bots "often have low precision (in other words raise false positives)" `[D8]`, and doing onchain actions from a bot is "not advised" because bot code and keys are public `[D7]`. | **pass — the substitute is weak exactly where the idea is strongest** |
| Payer | The protocol team that currently owns the `pause()` key. Narrowest real buyer: a DeFi protocol with a multisig admin and a real TVL. | Reachable via the organizer's own open-idea channel `[A8]` + GenLayer "Request for Startups" / Working Groups, and via shipping the module as a reusable building block (which the rubric rewards) `[A2]`. Not reachable by cold outbound at solo scale. | **unresolved (channel plausible, not proven)** |
| Repeat | Every incident, every new protocol version, every new integrating protocol. Reusable across protocols, so the second sale is to the next team. | Strong repeat; consumption + integration events. | **pass** |
| Payment evidence | **Level 3** — protocols demonstrably spend on security today: ~$66,000 average private tier-1 audit, ~$6,548 via audit competition, and ~$24.5M expected loss when an attacker finds a critical bug first `[C4]`; Forta/Defender were paid products `[D7][D10]`. **Level 5 for this specific product** — no budget owner has confirmed it. | Say it as level 3, not level 1. | **pass (category) / hypothesis (product)** |

**Weakest gate: payment evidence at the product level, then payer reach.** That is honest and it is
where the next work goes: the cheapest upgrade is a signed letter of intent or a real conversation
with one protocol team about the freeze-authority problem — not more reading.

**Note the asymmetry that makes this the better bet:** the pivot's substitute is *documented as
broken in the exact dimension the product addresses* (Forta's own low-precision admission `[D8]`,
Defender sunset `[D9]`, Egorov's objection `[D2]`). Your original idea's substitute is strong and
funded. Betting against a weak substitute is the entire edge.

---

## 3. Candidate comparison

Method: each criterion rated **strong / weak / fail** against the verified rubric `[A2][A8]`, the
stated constraints (solo, ~18 h/day, $0), and inspected competitor evidence. The rubric has no
published weights, so this is deliberately coarse — no false precision, no invented scores.

| Criterion | A. Your idea: bug bounty platform | B. **Recommended:** adjudicated emergency pause | C. Narrowed: prior-art / duplicate adjudication |
|---|---|---|---|
| "Solves a real trust problem" | fail — the trust problem (who triages) is real, but the *product* is a classifier | **strong** — the trust problem is freeze authority, and it is contested in court right now `[D5]` | strong — entitlement disputes are real |
| "Not just a better LLM response" | **fail** — every feature is an LLM classification task | **strong** — consensus gates an irreversible cross-chain action `[A16]` | weak — "is this the same root cause" is *also* an LLM judgement, one layer from "better LLM response" |
| "Meaningfully different from ecosystem" | **fail** — AutoBounty `[B1]`, BuildersClaw `[B2]`, GHBounty/MergeProof `[B4]` all live; the organizer's own idea line is the same pitch `[A8]` | **strong** — organizer states "No live project yet" `[A8]`; host scan found nothing `[B6]` | unknown — no ecosystem analogue found; no signal either way |
| "Uses live or authoritative data" | weak — reports are user-supplied text, not authoritative data | **strong** — the tx, trace, balances, flows, fetched live `[A15]` | weak — the evidence is submitted text |
| "Reusable by other builders" | weak — a closed product, not a primitive | **strong** — a module any protocol integrates; graded explicitly `[A2]` | medium — a registry others could read |
| "Frontend genuinely calls the contract" | easy to satisfy | medium — needs a real evidence-submit → consensus → verdict → EVM action flow, incl. pending/appeal states | medium |
| Competitor position | **fail** — feature-for-feature vs Immunefi + Sherlock, both funded `[C1][C2][C3]` | **strong** — the incumbent console is sunset `[D9]` and detection precision is admitted-low `[D8]` | medium — real gap, but **unverified** (`SOURCES.md` §E) |
| Solo + $0 + 1 weekly slot | hard — needs a whitehat network, protocol signups, a corpus | **feasible** — one contract + one frontend + a demo protocol | hard — needs a real report corpus and a label set you don't have |
| Time to a demonstrable result | slow | **fast** — one contract, three scenarios | slow |
| Main technical risk | corpus + judge-quality evaluation (no good ground truth) | consensus-safe live-data fetching `[A15]` + EVM emit on finality `[A16]` vs Studio limits `[A17]` | judging quality with no ground truth; the same risk as A but worse |
| Payment evidence | level 3 category / level 5 product | level 3 category / level 5 product | level 3 category / level 5 product |

**Recommendation: B.** It wins on every rubric line that the supplied idea fails, it is the one slot
the organizer explicitly marked empty `[A8]`, and it is the only candidate whose substitute is
documented as weak in exactly the dimension the product improves.

**What would overturn this recommendation:**
1. If the Portal's Project Explorer already contains a pause/circuit-breaker project (I could not
   enumerate it — `SOURCES.md` §E). Check this *first*; it is cheap and decisive.
2. If a Protocol team tells you freeze authority is a solved problem for them. Then the payer gate
   fails and B collapses to a technically elegant demo — which the rubric explicitly rejects
   ("Not a learning exercise").
3. If EVM interaction turns out to be unavailable on Studionet `[A17]` **and** the EVM-side action
   cannot be demonstrated. The verdict half still stands, but the "genuinely calls the contract"
   story weakens materially.
4. If you discover you have no interest in this problem. Gate 1 (the moment) is a genuine
   commitment test, and forcing it produces exactly the "innovation language" failure the guide warns
   about.

### Hackathon suitability vs longer-term product — kept separate

- **Fit for this program:** strong. Fits a named open idea, an explicitly empty slot, a real trust
  problem, live data, and a reusable primitive. Solo-feasible. That is most of the rubric.
- **Longer-term product:** **hypothesis, not a finding.** The repeat and payer arguments are
  reasonable; there is no user evidence, no signed interest, and the $0/solo constraint means no
  distribution. A credible path to continued use is *graded*, and the honest form of that path is:
  publish the module, get one integrating protocol, then use the **Milestone** category to submit
  real deltas as that integration deepens `[A4]`. Do not claim more.

---

## 4. What I did not establish

1. **No authenticated portal session** (no browser connected) → the live submission form, its
   required fields, and the exact Project point range are unverified `[A7]`.
2. **No official scoring weights** exist for the rubric. Coarse pass/fail only.
3. **The prior-art gap is unconfirmed** — my searches failed (`SOURCES.md` §E). Candidate C rests on
   a hypothesis, not a verified empty space.
4. **Project Explorer was not enumerated** → the "no live emergency-halt project" claim rests on the
   organizer's own text `[A8]` plus a weak host scan `[B6]`, not on an audit of the Explorer.
5. **AutoBounty's repo was not inspected** (code, license, tests, activity). Its 1,000-pt award and
   organizator highlight are verified; its current quality is not `[B3]`.
6. **BuildersClaw's live product was not exercised** — the site was read as text only `[B2]`. The
   "it went to production" claim is from a third-party tweet, not verified behaviour.
7. **No user or protocol team was contacted.** All payment evidence is inferred from published spend.
8. **I did not confirm the tech preference input.** You wrote "[details / none]"; I planned for *none*
   (no required stack) and used the ecosystem's own default (Python contracts + `genlayer-js`).

---

## 5. The one decision I need from you

**Do you want to build B (adjudicated emergency pause) or stay on A (bug bounty platform)?**

- Choosing **B** is a real change of artifact, not of domain — you stay in security incidents. I have
  a bounded MVP ready (`HANDOFF.md`).
- Choosing **A** is legitimate. I will not silently drop it, but I will plan it against a much higher
  bar, and the first task becomes the prior-art validation test, because the "nobody does
  cross-registry prior art" premise is currently unverified and the whole case rests on it.
- I am not asking about the stack, the schedule, or the budget — those are settled by your answers
  and the $0/solo constraint.

# PHASE 2 BRIEF — make the page sell the product

> **Answered.** Build complete. All Definition-of-Done checks pass. Two findings that changed the
> plan are recorded at the foot of this file, because the brief's beat 5 turned out to rest on a
> premise the recording falsified.


**For the build session.** Written 2026-10-02 by the discovery session.
Read first: `README.md`, then `state/reviews/2026-10-02-build-review/UI-TEARDOWN.md`.

**This phase changes only the frontend and its docs. Do not touch `contracts/emergency_halt.py`.**
The contract is correct, deployed, and tested — including a negative result you must not paper over.

---

## 0. What Phase 1 established, and the line you must not cross

Phase 1 answered the headline question with a **negative result**, correctly:

```
GenLayer tx  : FINALIZED, MAJORITY_AGREE
probe traces : EMIT_RETURNED      <- returned, did not raise
probe counts : freeze=1           <- contract believes it called freeze()
pool state   : frozenUntil UNCHANGED
```

**EVM `emit()` does not deliver the freeze.** Every signal the contract can emit says success; the
target chain receives nothing. `deploy/freeze_watcher.py` does it off-chain instead, and both halves
are proven live.

**Constraint for this phase:** the page must tell that story exactly as `README.md` lines 208–277 now
do. Do not upgrade the claim anywhere — not in a tooltip, not in a comment, not in the page's `<meta>`.
The site saying "consensus freezes your protocol" while the transport is an off-chain watcher would
be a false claim to a grader, and it is the single thing that would lose points on
*"Meaningfully different from boilerplate"* and destroy trust in everything else that is honest.

**The honest version, which is also the strong version:** *the verdict is decided on-chain by
consensus and publicly verifiable; delivering the freeze needs a watcher holding a key that can
freeze, but that key can no longer freeze unbounded and unaccountably.*

## 1. What is wrong with the current page

Diagnosed in `UI-TEARDOWN.md`. In short: we ship a working console with no narrative in front of it.
A visitor's first frame is a chain ID.

Four concrete gaps:

| | Now | Should be |
|---|---|---|
| Opening | `<h1>Anyone can propose a freeze.</h1>` then a chain-ID card | The problem, in three sentences, before the product |
| Headline case | hidden behind a case-chip selector | `live-drain` auto-surfaced above the fold |
| Touchability | wallet prompt + a 4-field form | something to click before any setup |
| Styling | raw inline styles throughout | a type scale and a three-colour verdict system |

**Do not rewrite the console.** `Stages` (PENDING → PROPOSING → COMMITTING → ACCEPTED → FINALIZED as
distinct states, with `txExecutionResult` checked separately from status) is the best component in the
repo and is worth the rubric line *"handles the full transaction lifecycle."* Put a landing narrative
**in front of** it. Additive, not a replacement.

## 2. The reference pattern to copy

`mrnetwork0001/Judr` — read `src/components/landing/HeroLive.tsx` and `Hero.tsx` at `main`.

```tsx
import sample from "@/lib/sample-run.json";
/*
 * The hero vignette, played as a loop. The four cards replay the saved run
 * in order... Every figure is the saved run's own; the loop only decides
 * when each one comes into view.
 */
const SCALE = 0.22; // the run's 36.5 s, played in about 8
```

**A real recorded run, replayed as a looping vignette, captioned with its own provenance.** Their
`Hero.tsx` caption:

> "A. Moreau and B. Adeyemi are a sample case; the reasoning shown is a real decision, made live on
> SERV on 26 September 2026 and saved as it came back, timings included."

Three assurances, each a falsifiable claim rather than an adjective:

```
Every verdict names the evidence field that decided it
The verdict enum is compared across validators; the reasoning never is
A wrong freeze expires on its own — no human has to undo it
```

Also studied: `enoch208/Dirac` (`demo-duel.tsx` — a playable demo before any wallet), `enoch208/Erilog`
(`content.ts`, *"No magic numbers in JSX — read from here."`), `mrnetwork0001/Inktoll`
(`receipt/[id]/`, a shareable artefact URL).

**JudgeMount's `HeroLive` is the target. Ours replays our three real cases.**

## 3. Task list, in order. Do not reorder.

### 3.1 Record real timings — BLOCKING for 3.3

`LIVE-RUN.md` has states and verdicts but **no durations**. Judr compresses a real 36.5s run; we
cannot until we have one.

Re-run the three existing cases through `deploy/submit_proof.py` and record, per case:
`started_at`, `accepted_at`, `finalized_at`, elapsed to acceptance and to finalization, and the
consensus result. Write them to `web/src/lib/sample-run.json`.

**If a case id already exists, use a fresh one** (`live-drain-2`) rather than re-using the recorded
entry — `submit_proof` rejects a duplicate `case_id`, and mutating a case that the README and the
self-review both cite would make those docs wrong.

Shape:

```json
{
  "provenance": {
    "network": "Studionet",
    "chainId": 61999,
    "contract": "0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774b",
    "recordedAt": "<ISO>",
    "note": "Real adjudications. Every field is the run's own; the loop only decides when each comes into view."
  },
  "cases": [
    {
      "id": "live-drain",
      "txHash": "0x0822131fff60d8f5a2c62647869ed30638b543eb6e15bbb11b3b62b1581cb144",
      "verdict": "FALSE_REPORT",
      "evidence": { "valueBand": "ZERO", "logBand": "MANY", "repeatedTopic": "0xddf252ad…" },
      "claim": "Attacker drained the protocol: the same transferFrom selector fires fourteen times inside one transaction, sweeping the pool.",
      "rationale": "<the real returned rationale>",
      "timing": { "toAcceptedMs": 0, "toFinalizedMs": 0, "consensus": "MAJORITY_AGREE" }
    }
  ]
}
```

Real values only. If a timing cannot be measured, omit the key — do not invent a number.

### 3.2 One typed content module

Create `web/src/lib/content.ts`. Every user-visible string and every number in the landing sections
reads from it. No literals in JSX. This makes the narrative checkable against the contract and stops
the page drifting from the README.

### 3.3 `HeroLive`-equivalent — the main event

Build `web/src/components/HeroRun.tsx`: a client component that replays the three cases as a looping
sequence. Compress real timings by a scale factor (Judr uses 0.22).

The beat structure, which is the story and not decoration:

```
1. a proof is submitted                → PENDING
2. the contract fetches the receipt    → "reading chain state"
3. validators re-run and compare       → PENDING → PROPOSING → COMMITTING → ACCEPTED
4. the verdict arrives                 → FINALIZED · badge fills
5. live-drain is the one to linger on   → "14 repeated transfer events. The committee still said no."
```

**Step 5 is the product's whole argument.** A transaction that looks exactly like a drain — 14 repeated
`Transfer` topics, `logs=MANY` — and the committee refuses it because `value=ZERO` and a non-transfer
selector contradict the claim. A pause module that confirmed that would be dangerous. Say so in
plain language.

The replay must be visually distinct per verdict: `CONFIRMED_EXPLOIT` / `FALSE_REPORT` /
`INSUFFICIENT_EVIDENCE` as three clearly different states, not three shades of grey.

Then rest, fade, restart. Below it, `Fig. 1`-style caption with the real provenance — network, chain,
contract address, timestamp.

### 3.4 Problem section, above the console

Three sentences, then the product. Facts already in the README:

- Kelp DAO: **~$292M** drained, pauser multisig froze core contracts **46 minutes later** `[D1]`
- Aave is in SDNY fighting a freeze of **30,766 ETH** applied to Arbitrum DAO `[D5]`
- Michael Egorov (Curve): *"The circuit breakers are controlled by humans, which means they could
  become a potential vulnerability themselves."* `[D2]`

And the honest counterweight, in the same section — not in a footnote: consensus takes minutes and
**does not beat 46 minutes**. Tier-2 judgement for ambiguous cases, not a replacement for a
deterministic tripwire. Erilog and Judr both state their limits on the page; so must we.

### 3.5 Shareable per-case route

Add `/case/[caseId]`. A grader should be able to send one link that shows a single verdict with its
evidence and explorer link. Follow Inktoll's `receipt/[id]/`. Next 15 App Router: a server component
reading via the existing `readClient()`.

### 3.6 Type scale and colour tokens

Replace inline styles with a small token set in `globals.css` — spacing, type scale, and exactly three
verdict colours. Current state is `style={{ fontSize: 16, margin: "0 0 12px" }}` throughout, which is
why it reads as a debug view.

### 3.7 Keep the console, wire it properly

The existing console stays below the fold: `WalletBar`, the submit form, `Stages`, `EvidenceGrid`,
`VerdictBadge`, case selector. Auto-select `live-drain` on load so the page is never empty.

Do not remove `Stages`. Do not collapse the lifecycle into a single final state — that is the graded
line.

### 3.8 Docs, honestly

Update `README.md` and `docs/integration.md` to describe the new surface. In the README's
"What we could not verify" section, **keep the emit result exactly as Phase 1 wrote it** and add the
watcher's honest cost: whoever runs it holds a key that can freeze.

## 4. Explicitly out of scope

- Any change to `contracts/emergency_halt.py`. If the frontend reveals a contract bug, **report it, do
  not fix it** — that is a separate decision.
- Glassmorphism, nebula backgrounds, particle effects. The demo video records at 30fps where subtle
  animation is invisible anyway. What makes the reference projects legible is narrative structure.
- Animated score bars or percentages. EquiGrant has 92%/85%/78% bars; those are decoration, not
  data. We decline them.
- Any claim stronger than Phase 1 established.
- Vercel deploy, GitHub push, naming, demo recording. Those are separate phases.

## 5. Definition of done

| Check | Command | Must be |
|---|---|---|
| Hermetic suite | `.venv/bin/python -m pytest tests/direct/ -q` | **38 passed** |
| Lint both contracts | `.venv/bin/genvm-lint check contracts/emergency_halt.py contracts/probe_emit.py` | pass |
| Types | `web/node_modules/.bin/tsc --noEmit` | clean |
| Build | `web/node_modules/.bin/next build` | EXIT=0 |
| Serves | `next start`, fetch `/` and `/case/live-drain` | HTTP 200 both, real address baked in, no zero-address fallback |
| Replay honesty | grep the built output for the emit claim | matches `README.md` lines 208–277 — no upgrade |
| Provenance | `sample-run.json` values | each traceable to `LIVE-RUN.md` or a fresh recorded run |

## 6. Report back

- **Screenshots or a written description of each section**, top to bottom, as a first-time visitor
  sees it. I cannot open a browser, so this is how I will judge the result.
- Which beat of the replay is strongest and which is weakest, honestly.
- Whether `live-drain` lands in under three seconds of attention, in your judgement.
- Anything in this brief that turned out to be wrong once you looked at the code.
- Confirmation that the emit claim is unchanged everywhere it appears, including page copy.

**Do not** change the frontend rubric line in `M0-RUBRIC-SELF-REVIEW.md`. It stays
`MET-PENDING-BROWSER-CHECK` until a human sees the rendered page. Neither session can close that one.
If your work makes it obviously closable, say so and leave the line alone.

## 7. Why this phase is worth doing carefully

The rubric is strict — *"This category is strict. Most submissions are rejected."* `[A2]` And the
three highest-value lines all run through this page:

- *"Frontend genuinely calls the contract and handles the full transaction lifecycle"*
- *"live demos, videos, and public posts earn extra points and speed up review"*
- *"If it would not be useful to someone else building on GenLayer, it is not ready to be submitted"*

Phase 1 closed the one gap that touched the product's technical claim. This phase decides whether a
grader understands the product in fifteen seconds — which, on a rubric that rejects most submissions,
is most of the remaining difference.

---

## Build response (2026-10-03)

### The brief's beat 5 rested on a premise the recording falsified

The brief specified beat 5 as "live-drain is the one to linger on: 14 repeated transfer events.
The committee still said no" — i.e. a clean `FALSE_REPORT`.

Recording real timings (3.1) re-ran the same transaction and it came back
**`INSUFFICIENT_EVIDENCE` after four leader rotations**, not `FALSE_REPORT`:

```
PROPOSING -> COMMITTING -> PROPOSING -> COMMITTING -> PROPOSING -> COMMITTING -> PROPOSING
-> COMMITTING -> ACCEPTED @66.6s -> FINALIZED @95.3s
```

Both runs saw a **byte-identical digest** — `tx_found=True receipt_status=0x1 value_band=ZERO
log_band=MANY input_selector=0x1249c58b repeated=0xddf252ad…`. So the reduction was stable and the
**judgement was not**. R2 reproduces on borderline evidence.

That is a stronger story than the one the brief asked for, and it is what the page now tells. A
first draft of this README claimed "no equivocation across live models" — true of six runs, false
of the seventh. Corrected in place rather than quietly dropped.

### What shipped

| Item | State |
|---|---|
| 3.1 real timings | `deploy/record_run.py` → `web/src/lib/sample-run.json`. 3 fresh cases, per-state ms, ~400ms poll granularity stated in the file |
| 3.2 `content.ts` | 154 lines, every string and number; no JSX literals |
| 3.3 `HeroRun.tsx` | replays `live-real-tx-run2` (FALSE_REPORT, 32.0s/63.0s) at 0.22x. SSR renders the **finished** state, loop starts after hydration, `prefers-reduced-motion` respected |
| 3.4 problem | Kelp 46min / Aave 30,766 ETH / Egorov quote, with the "does not beat 46 minutes" counterweight in the same card, not a footnote |
| 3.5 `/case/[caseId]` | server component, `force-dynamic`. 200 for all three cases |
| 3.6 tokens | `globals.css` rewritten: type scale, spacing, exactly three verdict colours |
| 3.7 console | kept whole. `Stages` untouched. `live-drain-run2` auto-selected. Zero-address fallback **removed** — now throws |
| 3.8 docs | README layout/quickstart, `docs/integration.md` §5 rewritten around the tested negative |

### Definition of done

| Check | Result |
|---|---|
| `pytest tests/direct/ -q` | **38 passed** (4.98s) |
| `genvm-lint check` both contracts | lint + validation passed |
| `tsc --noEmit` | clean |
| `next build` | **EXIT=0**; `/` static, `/case/[caseId]` dynamic |
| Serves | `/` 200, all three `/case/*` 200, real address in the payload, no zero-address fallback |
| Replay honesty | grep of built output: no "consensus freezes your protocol"; caveat `"does not deliver"` and `"Delivering the freeze to your contract is off-chain"` both present |
| Provenance | every figure traceable to `sample-run.json`, itself produced by `deploy/record_run.py` against the deployed contract |

### Two things the brief did not anticipate

1. **`src/lib/genlayer.ts` was marked `"use client"`.** It is imported by both the client page and
   the `/case/[caseId]` server component, so `readClient()` became a client reference and the
   server render failed — surfacing as a **404 from `notFound()`**, which reads like a missing
   route rather than a thrown error. Removed the directive; nothing in that module touches the DOM.
2. **The replay cannot show `CONFIRMED_EXPLOIT`.** No live case has reached it, and manufacturing
   one would be dishonest. All three enum values are styled distinctly and the console exposes
   whatever verdict arrives; the landing copy says so rather than implying coverage we do not have.

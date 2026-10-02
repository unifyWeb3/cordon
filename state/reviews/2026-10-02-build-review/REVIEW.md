# Review — build session report, adjudicated emergency pause

Reviewer: discovery session. Date: 2026-10-02.
Artifact reviewed: `/home/unify/mys` at `73476cd`, 8 commits, 53 tracked files.
Report under review: the build session's summary message.

**Overall: the report is accurate and unusually honest. Every claim I could test, I tested — and the
ones that matter hold.** I found no overclaiming and two documentation defects. I did **not** find
any code defect.

---

## 1. Claims verified independently

I re-ran everything that was cheap to re-run and independently read the deployed contract off
Studionet rather than trusting the transcript.

| Report claim | My method | Result |
|---|---|---|
| "38 passed — hermetic" | `.venv/bin/python -m pytest tests/direct/ -q` | **38 passed**, 213s. Confirmed. |
| "genvm-lint check → Lint + validation passed, 11 methods (6 view, 5 write)" | `.venv/bin/genvm-lint check contracts/emergency_halt.py` | **passed**, "Methods: 11 (6 view, 5 write)". Exact match. |
| Frontend "tsc clean" | `web/node_modules/.bin/tsc --noEmit` | **exit 0**. Confirmed. |
| Frontend "next build EXIT=0" | `web/node_modules/.bin/next build` | **exit 0**, 4/4 static. Confirmed. |
| Deployed at `0x37E08A26…74b` on Studionet with the reported schema | `gen_getContractCode` + `gen_getContractSchema` via `https://studio.genlayer.com/api` | Contract source on chain is **our** code (base64 decodes to the emergency_halt header). Schema lists exactly the 11 reported methods. |
| Live verdicts: `INSUFFICIENT_EVIDENCE`, `FALSE_REPORT`, `FALSE_REPORT` | My own read-only script against Studionet — `stats()`, `list_cases()`, `get_verdict()`, `get_evidence()` | **Exactly reproduced, independent of the transcript.** `stats()` → `submits:3, freezes:0, cases:3`. All three digests and rationales match. |
| "PENDING→PROPOSING→COMMITTING→ACCEPTED→FINALIZED, MAJORITY_AGREE" | Recorded in `LIVE-RUN.md`; I verified the terminal state on chain | Consistent. Lifecycle detail itself is from the report's own transcript, not independently re-run (would have cost a live submission). |
| ".env never committed" | `git log --all --name-only \| grep .env` | **No `.env` in any commit.** Confirmed. Working tree clean. |

**The most important verification: the deployed contract is real and does what it claims.** The
`live-drain` case deserves credit — the model saw 14 repeated `Transfer` topics and a `logs=MANY`
band, i.e. the exact drain signature, and still returned `FALSE_REPORT` because `value=ZERO` and a
non-transfer selector contradicted the claim. That is the product working as designed against a
plausible-looking lie, and the build session refused to dress it up as a confirmed exploit.

## 2. Confirmed as real problems (not excuses)

- **studio-dev (61997) cannot execute contracts.** I attempted the deploy myself. It fails at
  `eth_sendRawTransaction` with a deserialization error (`Deserializing list length (3) does not
  match sedes (1)`) — a *different* failure mode from the reported `FINISHED_WITH_ERROR`, but the
  same conclusion: **the brief's target is unusable.** The build session was right to deviate to
  Studionet and right to leave `deploy_studio_dev.py` pointing at studio-dev so it recovers without
  edits. This is a genuine environment fault, and the report labeled it as such.
- **EVM `emit()` unverified.** Consistent with the `M0B` document. The finding that it is a *silent*
  no-op under GLSim (`_generate_send` swallows the failure sentinel and returns `None` without
  raising) is a genuinely valuable discovery — it means an emit assertion would pass green and
  prove nothing. Correctly treated as blocking M3's verification, not papered over.
- **`.view()` / `EthCall` broken in the pinned SDK** (`self.parent.address` vs `_proxy_parent`).
  Verified as a code-level claim by the build session; I did not re-run it, but the reasoning is
  specific and checkable, and it explains why no view-based assertion was possible.

## 3. Discrepancies I found — documentation only, no code impact

**D1 — `evidence/` is empty, and both README and the contract docstring point at a file that does
not exist.** README's Layout section lists `evidence/  stage-1 helper`; the contract's module
docstring says *"Stage 1 lives in `evidence/collect.py`"*. `find -type d -empty` shows `evidence/`
is empty. In reality Stage 1 lives *inside the contract* — `derive_digest_from_rpc()`,
`digest_from_rpc_response()` at lines 296–382. That is arguably the better design (one fewer moving
part), so the fix is to correct the two references, not to invent the module. This matters because
"accurate docs" is a graded line `[A2]` and a dead path reference is the kind of thing a reviewer
clicks.

**D2 — `tests/integration/` is empty, but README lists it as "gltest suite against local GLSim."**
The report did disclose this ("`tests/integration/` is empty"), so this is not concealment — but the
README still advertises it. Either drop the line or leave a one-line note. The hermetic `direct`
suite is doing the real work, and `M0-RUBRIC-SELF-REVIEW.md` correctly credits it.

**D3 — two stale test-count/runtime figures in README.** README says the hermetic gate is "~35s";
observed 213s here (the report attributed 82s to host load — I measured worse, same cause). And the
Live results table row for `live-drain` says "14 repeated Transfer events" while the body says
"15 logs, 14 sharing one Transfer topic" — consistent, just worth aligning.

None of these are defects in the product. All three are in text a grader reads.

## 4. Report accuracy assessment

The report was **more candid than the rubric requires**, in ways that cost points if taken naively
but are correct:

- It led with the two `FALSE_REPORT`s and the absence of a live `CONFIRMED_EXPLOIT` instead of
  burying them.
- It stated "I did not manufacture a public transaction to look better."
- It flagged four separate places where the work **contradicts the brief** rather than quietly
  reinterpreting the brief.
- It marked the suite-runtime discrepancy and the lint/suite cache collision as unrelated noise
  rather than hiding them.

Where I add to its risk list: **the `CONFIRMED_EXPLOIT` path has never run against a real model on a
real network.** Every live case returned a non-freeze verdict. The freeze arming, expiry, and emit
code are proven hermetically with mocked models only. So the single most consequential branch of the
product — "the consensus agrees it's an exploit, arm a bounded freeze" — is the least verified. That
is not disqualifying, and it is honestly documented, but it should be the first thing the demo does
if the demo target gets deployed.

## 5. Risk register status after review

| Risk | Report | My view |
|---|---|---|
| R1 EVM emit | open | **Confirmed open.** Product's headline hop is undemonstrated. Highest-value gap. |
| R2 equivocation | not reproducing | **Confirmed.** Enum-only comparison is enforced by a test, not convention — and I read the code, the design is right. |
| R3 prior art | partial | **Confirmed partial.** "No evidence of prior art" ≠ "none exists". Correctly worded. |
| R4 injection | mitigated, bounded | **Confirmed as wiring-level only.** A real model can still be argued into a wrong enum; expiry bounds it. Right framing. |
| R5 too slow | stated plainly | **Confirmed.** README says it does not beat 46 minutes, unprompted. |
| R6 no demand | none | **Confirmed.** Correctly labeled inference from published figures. |
| **New: R7 headline branch unverified live** | not called out | Every live case was a non-freeze verdict; `CONFIRMED_EXPLOIT` is hermetic-only. |
| **New: R8 studio-dev may still be broken at submission time** | mentioned | Worth re-checking the day of submission; the brief named it, so a grader familiar with the program may expect it. |

## 6. On the 360/4000 point context

I did **not** find a scoring formula — none is published `[SOURCES.md]`. So I cannot say what cost
the earlier 360 points, and I am not going to invent a theory. What I can say from reading the rubric
and the 2000-pt winner:

This build now hits the lines that separated BuildersClaw from the field: a two-stage pipeline with
consensus reserved for the irreversible decision `[B7]`, a publicly verifiable record, live fetched
data, and honest bounded scope. The three rubric lines still unmet are **M9** (no demo video or
public post — and the rubric says those "earn extra points and speed up review" `[A2]`), the
unverified EVM emit, and the unverified live `CONFIRMED_EXPLOIT`.

The most likely remaining cause of a low score is **not** a missing feature. It is that "with a
credible path to continued use" is graded as **weak** in the self-review, and no build can fix that
alone. The credible path here is real and worth stating plainly in the submission notes: publish the
module, land one integrating protocol, then submit **Milestone** contributions `[A4]` — which is the
only repeatable points mechanism in the program and needs no weekly slot.

## 7. Verdict and next steps

**Accept the build.** It is honest, tested, deployed, documented, and materially stronger than the
bug-bounty idea it replaced. No code changes required.

Before submitting, in priority order — all three are smaller than what is already built:

1. **Deploy `demo-target/HaltablePool.sol`** and adjudicate against it so the emit is observed.
   This is the only gap that touches the product's headline claim. `LEFT-OFF.md` already sequences
   this first.
2. **Fix D1, D2, D3** — three text corrections, minutes of work, directly on a graded line.
3. **M9** — record a short demo and post it.

If (1) turns out emit genuinely does not work, ship the documented watcher fallback and say plainly
in the notes that the last hop is an off-chain watcher rather than an on-chain emit. That is a
weaker claim and a defensible one. What is not defensible is implying the emit works.

**Do not** submit until (1) and (2) are done. A rejection costs a weekly slot, and the only free
retries are a "needs details" outcome and an Appeal `[A5]`.
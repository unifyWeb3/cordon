# Adjudicated emergency pause

An **anyone can propose a freeze, nobody performs one unilaterally, and a wrong freeze lifts
itself** module for DeFi protocols.

A GenLayer Intelligent Contract reads the referenced transaction from a public chain RPC,
reduces it to a set of *stable fields*, and asks a committee of validators for a single
discrete verdict:

| Verdict | What happens to the target |
|---|---|
| `CONFIRMED_EXPLOIT` | A freeze is armed **with a mandatory auto-expiry**. No human performs it. |
| `FALSE_REPORT` | Nothing happens. The evidence contradicted the claim. |
| `INSUFFICIENT_EVIDENCE` | Nothing happens. No receipt, or nothing unambiguous to judge. |

---

## The trust problem this addresses

Freeze authority today is a single unaccountable privileged key.

- Kelp DAO's pauser multisig froze core contracts **46 minutes** after a ~$292M drain.
- Aave is in SDNY fighting a freeze of 30,766 ETH applied to Arbitrum DAO.
- Michael Egorov (Curve), on circuit breakers: *"The circuit breakers are controlled by
  humans, which means they could become a potential vulnerability themselves."*
- Circle's chief strategy officer, warning against unchecked intervention: *"just as
  dangerous for legitimate users."*

The nearest automated substitute is a Forta detection bot feeding an OpenZeppelin Defender
Autotask that calls `pause()`. Forta's own docs admit detection bots *"often have low
precision (in other words raise false positives)"* and that performing onchain actions from
a bot is *"not advised"* because bot code and keys are public. **OpenZeppelin Defender sunset
on 1 July 2026.** That is the gap: the incumbent tooling cannot do this safely, and the
consensus layer can.

## Why this is not "a better LLM response"

The LLM never decides anything. It picks one of three strings. What it decides is gated by:

1. **Independent re-execution.** Validators re-run the leader's function themselves and
   compare. Only the enum is compared — never the reasoning, because two models will never
   write the same sentence. A test asserts this directly: a leader result with a *completely
   different rationale* and the same verdict must still be accepted.
2. **Evidence it cannot argue with.** The model sees measured, stable fields. If the evidence
   contradicts the claim, the model is expected to say so — and the live demo does exactly
   that.
3. **A bounded blast radius.** Even a wrong `CONFIRMED_EXPLOIT` is capped at
   `default_freeze_seconds` (max 3600) and lifts itself. Nobody has to come back and undo it.

---

## Architecture: three stages

```
STAGE 1  deterministic evidence  (no consensus)
  contract POSTs ONE batched JSON-RPC call to the target chain's public RPC
    -> eth_getTransactionReceipt + eth_getTransactionByHash
  reduces to stable fields ONLY  (see "Why stable fields" below)

STAGE 2  GenLayer consensus
  leader_fn    -> {"verdict": <enum>, "rationale": str, "digest": {...}}
  validator_fn -> re-runs leader_fn, compares ONLY the enum

STAGE 3  retention
  verdict, rationale, evidence, expires_at and every tx hash, all publicly readable
```

This is the shape that won BuildersClaw its 2000-point Grand Prize: *"The top contenders are
sent to GenLayer for the final on-chain verdict. This keeps broad repo analysis fast, makes
the finalist ranking explainable, and still gives GenLayer final say for the highest-stakes
winner decision."* Consensus belongs on the few irreversible decisions, not on every request.

### Why stable fields

The GenLayer docs are explicit: *"the leader and validators make **independent requests**.
External APIs may return different data between calls — timestamps change, counts update,
caches vary."* So the contract **never lets raw fetched data cross the consensus boundary.**

Dropped, because they move between two fetches seconds apart: block number, gas, timestamps,
raw logs, the raw response body, the transaction hash.

Kept, because they are fixed for a given transaction forever:

| Field | Why it is stable |
|---|---|
| `input_selector` | first 4 bytes of calldata |
| `selectors` / `repeated_selectors` | event topic hashes and their counts |
| `value_band` | bucketed magnitude, not wei |
| `log_band` | bucketed count, not an exact count |
| `receipt_status` | 0x0 / 0x1 |

There is a test that proves it: the same transaction with a different block number and
different gas yields a **byte-identical** digest signature.

The repeated-event-topic field is the drain signature — the same `Transfer` topic firing many
times inside one transaction.

---

## Live results

Deployed and verified against Studionet (chain 61999):

**Contract:** `0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774b`

| Case | Input | Verdict | Evidence | Result |
|---|---|---|---|---|
| `live-missing` | a hash not on chain | `INSUFFICIENT_EVIDENCE` | `found=False status=NOT_FOUND` | nothing frozen |
| `live-real-tx` | a real Base Sepolia tx, with a *false* exploit claim | `FALSE_REPORT` | `found=True status=0x1 value=ZERO logs=FEW rep=` | nothing frozen |
| `live-drain` | a real tx with 14 repeated Transfer events, claimed as a drain | `FALSE_REPORT` | `found=True value=ZERO logs=MANY rep=0xddf252ad…` | nothing frozen |

Observed lifecycle, as distinct states:

```
PENDING -> PROPOSING -> COMMITTING -> ACCEPTED -> FINALIZED      (MAJORITY_AGREE)
```

Read the second and third rows carefully, because they are the honest result. **On random
public transactions, the correct answer is usually "not an exploit."** The system reached
`FALSE_REPORT` against a fabricated claim and against a transaction that superficially looked
like a drain, because the measured evidence did not support it. A pause module that confirmed
both would be dangerous, and this is the behaviour you want.

The `CONFIRMED_EXPLOIT` path is exercised by the hermetic suite instead (§ Tests), where the
evidence fixture is constructed to carry the drain signature.

Full transcript: `state/reviews/2026-10-01-hackathon-discovery/LIVE-RUN.md`.

---

## Layout

```
contracts/emergency_halt.py      the Intelligent Contract
contracts/minimal_probe.py       20-line deploy probe (see "What we could not verify")
deploy/                          deploy + submit scripts, and deploy/README.md
docs/integration.md              how another protocol plugs this in
tests/direct/                    hermetic suite: 38 tests, no network
web/                             Next.js 15 frontend
```

## Quick start

Requires Python 3.12 and Node 20+.

```bash
uv sync                       # pinned test harness (genlayer-test 0.28.0, genvm-linter 0.10.0)

# 1. the hermetic gate -- no network, ~25s on an idle machine
uv run pytest tests/direct/ -v

# 2. contract lint + SDK validation
uv run genvm-lint check contracts/emergency_halt.py

# 3. the frontend
cd web && npm install && npm run dev
```

Live deploy needs a second environment, because `genlayer-test` hard-pins `genlayer-py==0.9.0`
while the deploy scripts want a current SDK — see `deploy/README.md`.

## Tests

`uv run pytest tests/direct/ -v` → **38 passed**. ~23s on an idle machine; budget a few
minutes if something else is loading the box. The test count is the stable number, not the
wall clock.

Hermetic by construction: the web fetch and the model are both mocked from recorded evidence.
The model stand-in keys off the *observed evidence in the prompt*, so if the contract ever
stopped passing evidence through, the patterns would stop matching and the tests would fail.

What the hermetic gate proves, and what it does not:

- **Proves:** the enum is correct per fixture; the validator agrees (`vm.run_validator()`);
  rationale is not compared; the enum is; out-of-enum output is coerced; injected claims
  cannot override evidence; freezes are bounded; expiry is permissionless and self-lifting;
  degenerate input is refused; the owner guard holds; evidence is public and stable-field only.
- **Does not prove:** that two *different real models* agree. That needs a live network and is
  demonstrated separately by the live runs above (`MAJORITY_AGREE`).

---

## Honest limitations

Read this section. It is the most important part of the README.

**1. Consensus is slow. It does not beat 46 minutes.**
Optimistic Democracy has appeal windows, so a verdict takes minutes. Kelp's pauser reacted in
46 minutes and was still worth having. **This does not beat that, and claiming otherwise would
be dishonest.** This is *tier-2 judgement for ambiguous cases* — a second, accountable pair of
eyes on a suspicious transaction — not a replacement for a deterministic tripwire. If you need
a 3-second circuit breaker, this is the wrong tool.

**2. A confirmed-but-wrong freeze still costs you a bounded window.**
Freezes are capped at 3600s and self-lift, but during that window withdrawals are blocked. A
false positive is not free; it is *bounded and self-healing* instead of indefinite and manual.

**3. studio-dev (chain 61997) currently cannot execute contracts.**
Verified empirically. Every deploy — including `contracts/minimal_probe.py` — finalizes with
`tx_execution_result = FINISHED_WITH_ERROR`, `result_name = MAJORITY_AGREE`,
`num_of_rounds = 0`, with and without `leaderOnly`, and no contract is registered afterwards.
Identical code deploys and executes on Studionet. studio-dev is also fee-charging and **no
published Python SDK speaks that ABI** (`deploy/README.md` has the full finding and the
~40 lines of encoding that work around it). The brief specified studio-dev; the live demo runs
on Studionet because studio-dev cannot execute anything. studio-dev remains configured as the
deploy target, so it becomes usable unchanged if the preview recovers.

**4. EVM emit does not deliver, and the freeze reaches the target off-chain.** Tested on
Studionet against a live target: consensus finalized, the contract recorded the call, the call
returned without raising — and the target chain received nothing. `deploy/freeze_watcher.py` does
that last hop, so whoever runs it holds a key that can freeze. What changes is that the key can no
longer freeze *unbounded and unaccountably*: the window comes from an adjudicated verdict, it is
on the public record, and the target lapses it itself. Full evidence in the next section.

**5. This is tier-2, and the evidence is shallow.**
The digest uses receipt status, one selector, event-topic counts and two magnitude bands. It
does **not** resolve the token contract, check whether the caller is privileged, compare
balances, or trace a call tree. On a real protocol you would feed in a prepared evidence
bundle. This is enough to demonstrate the trust model; it is not a finished risk engine.

**6. No payment evidence.** No protocol team has been asked whether they want this. Published
security spend is real (~66,000 average private tier-1 audit vs ~6,548 via audit competition,
~24.5M expected loss when an attacker finds a critical bug first), but that is inference from
published figures, not a validated demand signal. Treat demand as a hypothesis.

**7. The ecosystem overlap is not fully surveyed.**
The organiser listed the "Emergency halt module" slot as *"No live project yet. The first team
here sets the reference."* We could not enumerate the authenticated Project Explorer from this
environment, and web search surfaced no existing GenLayer pause/circuit-breaker project — but
"no result found" is not the same as "none exists." Closest ecosystem neighbours are
AutoBounty (1000-pt Track Winner), BuildersClaw (2000-pt Grand Prize), GHBounty and
MergeProof; the comparison against them is in `docs/integration.md`.

## Tested, and found broken

### EVM `emit()` does not deliver. Tested 2026-10-02, not assumed.

This was the one gap touching the headline claim. It is now **tested, and the answer is no.**

`HaltablePool.sol` (Base Sepolia, `0xDF9Ba466540D2Fe4a62650f4d849231a2cb32b7B`) is a deployed
pausable pool. A probe contract (`contracts/probe_emit.py`, on Studionet) called the identical
emit path the product uses. Result:

```
GenLayer tx   : FINALIZED, MAJORITY_AGREE
probe traces  : EMIT_RETURNED          <- call returned, did not raise
probe counts  : freeze=1              <- contract believes it called freeze()
pool state    : frozenUntil UNCHANGED <- nothing arrived
```

Every signal the contract can produce says success, and the target chain received nothing. Ruled
out first: ABI shape (positional-only params, same declaration as the product), ghost-contract
registration (`isGhostContract` returns `true` for the target), and call site (outside the
nondet block, which is the only legal place).

Under local GLSim the same call is a **verified silent no-op** — `gltest`'s WASI mock has no
`EthSend` branch, so the sentinel becomes `Lazy(lambda: None)` and `_generate_send` returns it
without raising. That is why this was easy to miss: a local test asserting the emit worked would
pass green.

Full evidence: `state/reviews/2026-10-02-build-review/R1-EMIT-RESULTS.md`.

### So the last hop is off-chain, and here is the honest cost

The verdict, rationale, evidence, bounded window and self-lifting expiry are all verified — 38
hermetic tests plus live consensus runs. **Delivery of the freeze to an EVM contract is not.**

`deploy/freeze_watcher.py` does it instead, as working code rather than a documented intention:

- **read path, live:** polled the deployed contract, found all 3 cases, correctly took no action
- **write path, live:** invoked against the real target — `frozenUntil` moved, `isFrozen()` went
  true, then false on expiry **with no unfreeze transaction sent**

Only the composition (verdict observed → watcher fires) is unexercised, because no live case has
reached `CONFIRMED_EXPLOIT`.

**State the trade plainly:** whoever runs the watcher holds a key that can freeze. What this
architecture changes is that the key can no longer freeze *unbounded and unaccountably* — the
window comes from an adjudicated verdict, it is on the public record, and the target lapses it
itself. That is weaker than "consensus freezes your protocol". It is the claim the evidence
supports, and it is still the one nobody else in the ecosystem is making.

### Also broken in the pinned SDK

`.view()` / `EthCall` raises `AttributeError` on every call:
`genlayer/gl/_internal/eth.py` reads `self.parent.address` while the generated proxy only defines
`_proxy_parent`. SDK defect, not a harness gap; it breaks the published docs example too.

### Not verified

**The frontend in a browser.** No browser was connected to this environment. The app was served
over HTTP (200) and its exact client path was exercised in Node — 8 reads against the live
contract, all passing — but React rendering and the write path were never observed visually.

**Did we check the Project Explorer for an existing pause project?** Partially. No browser
was connected to this environment, so the authenticated Explorer could not be enumerated. Web
search found no existing GenLayer emergency-halt or circuit-breaker project. Treat this as
"no evidence of prior art," not "confirmed none."

## Licensing note

The BuildersClaw repository has **no license file**, so it is used here as a *pattern
reference only*. No code from it is copied or vendored. The consensus pattern
(`run_nondet_unsafe` + compare-only-the-enum) is re-implemented from the published GenLayer
Partial Field Matching documentation.

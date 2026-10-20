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

**Live app:** <https://cordon-oxunify.vercel.app> — reads the deployed contract on GenLayer
Studionet (chain 61999). Shareable case links: `/case/<caseId>`. The headline case is
[`/case/live-drain-run2`](https://cordon-oxunify.vercel.app/case/live-drain-run2).

**Demo video:** [`demo/cordon-demo.mp4`](demo/cordon-demo.mp4) — 41 s, silent. It is a rendered
walkthrough of the live deployment, including the adjudicated-run replay and the shareable case
page. Regenerate with `python scripts/make_demo_video.py` (needs playwright, ffmpeg, and a
chromium already on disk); `--check` reports what is missing.

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

Deployed and verified against Studionet (chain 61999) and Base Sepolia (84532):

**Contract:** `0x95be4d883F89F28CF9cE986e1B400c8CB0808201` (Studionet; source-proven identical to
`main` on 2026-10-20) · **non-vulnerable pool:** `0xe9797e7102d5B2b35C0DeE0C12257542ddD1359E`
(Base Sepolia) · **intentionally vulnerable demo pool:** `0x4d7b0793476Ce614539feC663fccD4ab6f1eFaed`
(Base Sepolia). All runtimes are verified against a fresh compile outside their immutables.
`cd web && node scripts/verify-live.mjs` prints expected vs actual, exit 0 on pass.

The vulnerable pool is a **deliberately buggy testnet contract** (`VulnerableDemoPool.sol`, header
says so). It exists for one purpose: to make a real zero-credit drain possible in a single direct
transaction, so the confirmed→attested-freeze lifecycle can be exercised live. It is not a product
contract and must never hold value.

The previous pool `0x9e6c83C8…` is still on chain but its owner key is dead and its attester is not
one we hold, so nothing we hold can freeze it. It is history, not a live target.

Current deployment (2026-10-20 — every hash is in
[`docs/live-run-2026-10-20.md`](docs/live-run-2026-10-20.md) and
[`docs/live-run-2026-10-20-confirmed.md`](docs/live-run-2026-10-20-confirmed.md)):

| Case | Input | Verdict | Evidence | Result |
|---|---|---|---|---|
| `staged-drain-plain` | a real `deposit()` and then one `withdraw(all)` that **emptied the pool** — a true drain of our own testnet pool, labelled as staged | `FALSE_REPORT` | `found=True status=0x1 value=ZERO logs=FEW rep=` | nothing frozen, **and correctly so for this target**: `withdraw` is not payable and emits one event, so the receipt reads as ordinary activity |
| `control-wrong-to` | a real tx that emptied the pool through a forwarding harness, submitted with `target` = the pool while `tx_to` = the harness | `INSUFFICIENT_EVIDENCE` | `found=True value=SMALL logs=SOME rep=0xc36b5179…` | nothing frozen; also the run's live proof that `repeated_selectors` populates when a receipt really has repeated events |
| `staged-exploit-vulnpool` | on the **intentionally vulnerable** pool: a caller with zero deposit ran `claimRewards(12)`; 12 payouts in one transaction emptied another depositor's 0.00004 ETH, labelled staged | **`CONFIRMED_EXPLOIT`** | `found=True status=0x1 value=SMALL logs=MANY rep=0x7084f547…` | **frozen live**: relay tx `0xe78a9cb0…9ffb1`, `frozenUntil` = signed deadline `1792488281` at a pinned block |

The rows below belong to the earlier deployment (2026-10-17, old pool), kept as they were observed
there:

| Case | Input | Verdict | Evidence | Result |
|---|---|---|---|---|
| `live-missing` | a hash not on chain | `INSUFFICIENT_EVIDENCE` | `found=False status=NOT_FOUND` | nothing frozen |
| `live-real-tx` | a real Base Sepolia tx, with a *false* exploit claim | `FALSE_REPORT` | `found=True status=0x1 value=ZERO logs=FEW rep=` | nothing frozen |
| `live-drain` | a real tx with 14 repeated Transfer events, claimed as a drain | `FALSE_REPORT` | `found=True value=ZERO logs=MANY rep=0xddf252ad…` | nothing frozen |

Observed lifecycle, as distinct states:

```
PENDING -> PROPOSING -> COMMITTING -> ACCEPTED -> FINALIZED      (MAJORITY_AGREE)
```

### Equivocation does happen. Found on a second run of the same transaction.

Re-running `live-drain`'s transaction produced **four leader rotations**:

```
PROPOSING -> COMMITTING -> PROPOSING -> COMMITTING -> PROPOSING -> COMMITTING -> PROPOSING
-> COMMITTING -> ACCEPTED @66.6s -> FINALIZED @95.3s
```

and landed on `INSUFFICIENT_EVIDENCE` where the first run of the *same* evidence had landed on
`FALSE_REPORT`. Both runs saw a byte-identical digest —

```
tx_found=True  receipt_status=0x1  value_band=ZERO  log_band=MANY
input_selector=0x1249c58b  repeated=0xddf252ad1be2c8…
```

— so the **reduction was stable and the judgement was not**. That is the honest result and it
splits the risk in two:

- The anti-equivocation discipline works. Two independent fetches produced the same evidence.
- On genuinely borderline evidence, independent models *do* disagree. The digest cannot prevent
  that; it can only prevent the evidence itself from being the reason.

What saved it was the rotation mechanism, resolving a contested call toward the **conservative**
verdict. That is the property you want: a disputed freeze becomes no freeze. The cost is latency
—95s here versus 52–63s for cases that agree — and a `live-drain` case that flaps is a fair
signal that the committee is genuinely undecided rather than confidently wrong.

An earlier draft of this README claimed "no equivocation across live models." That was true of
six runs and false of the seventh. Corrected rather than quietly dropped.

Read the negative rows carefully, because they are the honest result for those targets. **On random
public transactions, the correct answer is usually "not an exploit."** The system reached
`FALSE_REPORT` against a fabricated claim and against a transaction that superficially looked like a
drain, because the measured evidence did not support it. A pause module that confirmed both would be
dangerous, and this is the behaviour you want.

The `staged-exploit-vulnpool` row is different in kind, and its label matters. It is a genuine
zero-credit drain of our own **deliberately vulnerable** testnet pool, and its receipt carries the
shape the digest can measure: value on the call, `MANY` logs, one repeated event. It proves the
lifecycle, not that a public drain would be confirmed — and the IC's arming rules are still exercised
independently by the hermetic suite (§ Tests).

Full transcript: `state/reviews/2026-10-01-hackathon-discovery/LIVE-RUN.md`.

---

## Layout

```
contracts/emergency_halt.py      the Intelligent Contract
contracts/minimal_probe.py       20-line deploy probe (see "What we could not verify")
deploy/                          deploy + submit scripts, and deploy/README.md
deploy/attestation.py            key-free EIP-712 encoder: attester, relay and tests all share it
deploy/attest.py                 signs one adjudicated freeze (the only attester key)
deploy/freeze_watcher.py         verifies and relays a signed freeze (holds no attester key)
demo-target/src/HaltablePool.sol the EVM target: attestation-only pause, self-lifting expiry
demo-target/src/VulnerableDemoPool.sol intentionally vulnerable testnet twin: same freeze, one real bug
docs/integration.md              how another protocol plugs this in
tests/direct/                    hermetic suite: 215 tests, no network
web/                             Next.js 15 frontend (landing narrative + console)
web/src/lib/content.ts           every user-visible string and number, no JSX literals
web/src/lib/sample-run.json      a real recorded adjudication, timings included
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
#   then http://localhost:3000  ·  a single case is shareable at /case/<caseId>
```

Live deploy needs a second environment, because `genlayer-test` hard-pins `genlayer-py==0.9.0`
while the deploy scripts want a current SDK — see `deploy/README.md`.

## Tests

`uv run pytest tests/direct/ -v` → **215 passed**. ~85s on an idle machine; budget a few
minutes if something else is loading the box. The test count is the stable number, not the
wall clock.

Three of those modules — `test_haltable_pool.py`, `test_vulnerable_demo_pool.py` and
`test_relay_attestation.py` — compile an EVM target with `solc-js` and execute it on an in-process
EVM (`py-evm`), signing real attestations and sending real signed transactions. Those skip
**loudly** if `solc` is missing rather than passing quietly; run `cd demo-target && npm install`
first.

Hermetic by construction: the web fetch and the model are both mocked from recorded evidence.
The model stand-in keys off the *observed evidence in the prompt*, so if the contract ever
stopped passing evidence through, the patterns would stop matching and the tests would fail.

The suite pins the GenVM bundle to `v0.2.16` (`SDK_VERSION` in `tests/direct/conftest.py`).
That is the last release publishing `genvm-universal.tar.xz`; upstream renamed the asset to
`genvm-runners-all.tar.xz` at `v0.3.0-rc0`, and `genlayer-test` 0.28.0 hardcodes the old name, so
a `v0.3.0-rc*` pin 404s. The consequence: **the hermetic gate runs on an older GenVM bundle than
Studionet does.** The runner hash the contract pins and the std-lib hash it resolves to were
verified byte-identical between v0.2.16 and v0.3.0-rc7, so what is under test is unchanged — but
the bundle is genuinely older. `genlayer-test` 0.30.0rc2 fixes the filename and adds
`GENVM_VERSION` / `GENVM_PREBUILT_DIR`; adopting it is a deliberate follow-up, not a drive-by,
because it is a pre-release, moves the bundle to `genvm-manager`, and re-pins `genlayer-py`.

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
returned without raising — and the target chain received nothing. Those `emit` calls have since
been removed, so nothing in the contract now reports a delivery it did not achieve. The last hop
is off-chain and split in two: `deploy/attest.py` signs a statement naming the case, the pool and
the deadline; `deploy/freeze_watcher.py` carries it and pays the gas without holding any key that
can freeze. With one attester configured the attester key is still a single point of failure,
bounded by the pool's maximum window — what changes is that a wrong freeze is now attributable to
a signed, public statement rather than an anonymous pause. Full evidence in the next section.

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

### The evidence digest cannot see an ETH outflow. Tested 2026-10-20.

`value_band` is the **transaction's own** `msg.value`, and the digest carries no balance and no
transferred amount. `withdraw()` is not payable, so a complete drain of the ETH demo pool is
`value=ZERO logs=FEW rep=`. Adjudicated live as `staged-drain-plain` → `FALSE_REPORT`, rationale:
*"ZERO value magnitude band, indicating no significant ETH transfer ... ordinary, authorized
protocol activity"*.

The gap is structural for `HaltablePool`, not a tuning problem: a transaction to the pool executes
exactly one function, the pool emits exactly one event per successful call, and the target binding
requires `evidence.tx_to == target` — so for every binding-valid case `repeated_selectors` is empty
and `log_band <= FEW`, while a withdrawal's `value_band` is always `ZERO`. **No honest live
`CONFIRMED_EXPLOIT` is reachable on that target**, and `staged-drain-plain` is the observation. Full
hashes, both controls and the argument: `docs/live-run-2026-10-20.md`.

A different, deliberately vulnerable contract can produce the shape: `VulnerableDemoPool.claimRewards`
is payable and emits 12 identical events in one call, so its receipt digests as
`value=SMALL logs=MANY rep=0x7084f547…` and the attested freeze was exercised live against it
(`docs/live-run-2026-10-20-confirmed.md`). What the digest still cannot see is the **amounts** or the
caller's credit. The model confirmed the receipt shape; the claim's numbers were verified off-chain
by pinned reads, not by the digest.

### EVM `emit()` does not deliver. Tested 2026-10-02, not assumed.

This was the one gap touching the headline claim. It is now **tested, and the answer is no.**

`HaltablePool.sol` is deployed on Base Sepolia — currently at
`0xe9797e7102d5B2b35C0DeE0C12257542ddD1359E`; the probe below ran against the earlier deployment,
`0xDF9Ba466540D2Fe4a62650f4d849231a2cb32b7B`. A probe contract (`contracts/probe_emit.py`, on
Studionet) called the identical emit path the product uses. Result:

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

The verdict, rationale, evidence, bounded window and self-lifting expiry are all verified — 215
hermetic tests plus live consensus runs. **Delivery of the freeze to an EVM contract is not**,
and since 2026-10-17 the contract no longer attempts it: the `emit` calls were **removed** rather
than left in place, so nothing in the contract can report a delivery that did not happen.

`deploy/freeze_watcher.py` does the last hop, as working code rather than a documented intention.
Since the attestation change it is split in two, so that no single program can both invent a freeze
and apply it:

- **read path, live:** the older watcher polled the deployed contract, found all 3 cases, and
  correctly took no action
- **write path, older interface:** under the former `freeze(string,uint256)` entry point, the
  watcher was invoked against the real target and `frozenUntil` moved, `isFrozen()` went true,
  then false on expiry **with no unfreeze transaction sent**. That entry point has since been
  removed, so this is history rather than a claim about the current relay.
- **write path, current:** the attestation-to-freeze path runs end to end on an in-process EVM
  with real signatures and a real signed transaction (`tests/direct/test_relay_attestation.py`),
  including the assertion that the pool's `frozenUntil` equals the signed deadline exactly. It was
  also run against a deployed target on 2026-10-20: `VulnerableDemoPool` at
  `0x4d7b0793…1eFaed`, relay tx
  `0xe78a9cb057709f613148967c6b610732bd3bb1335a0d21cf20fff94f1479ffb1`, `frozenUntil` read back at
  the relay block equal to the signed deadline `1792488281`. That target is intentionally
  vulnerable and ours; see `docs/live-run-2026-10-20-confirmed.md`.

The composition (verdict observed → relay fires) is now exercised once, against our own
deliberately vulnerable testnet pool. No public protocol has been frozen, and no verdict was
manufactured.

**State the trade plainly.** The attester holds the only key that can authorise a freeze. The relay
that carries it holds no such key and can choose neither the pool, the verdict nor the deadline:
editing any of them breaks the signature, and a substituted deadline fails as `unknown attester`
rather than being quietly accepted. With one attester configured this is **still a single key**, and
it can freeze wrongly for up to the maximum window. What changes is that it can no longer do so
*unattributably* — a wrong freeze is a signed, public, appealable statement by a known address
rather than an anonymous pause, and the target lapses it by itself. That is weaker than "consensus
freezes your protocol". It is the claim the evidence supports, and it is still the one nobody else
in the ecosystem is making.

**The one authority the relay does have, named rather than left out.** The pool's `owner` can clear
`frozenUntil`, and can only ever clear it — never create a freeze, never extend one. That is not
asserted but enumerated: every write site in `HaltablePool.sol` is audited in
`tests/direct/test_haltable_pool.py`
(`test_the_only_writers_of_frozenUntil_are_the_attested_path_and_unfreeze`), and there are exactly
two, the attested path and an owner-only `unfreeze` that writes literal zero. The demo deploys the
pool with the relay key as `owner`, so the gas payer can end a freeze early and cannot start one.
Deploy with a different `owner` (or `transferOwnership`) if you do not want that either — the
attested entry point is permissionless, so the relay needs no authority to deliver a freeze.

A live deadline can also be **shortened** by a second attestation naming a *nearer* expiry — a later
one is refused as `cannot extend a live freeze`. Nothing anywhere can push a deadline out, which is
the property that matters: even a compromised attester cannot keep a freeze running past what a
signature said.

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

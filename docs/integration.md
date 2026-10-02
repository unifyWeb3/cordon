# Integrating the adjudicated pause

This is the guide for a builder who wants to put this in front of their own protocol. If you
can follow section 2 alone, you are done.

---

## 1. What you get

A deployed GenLayer Intelligent Contract that:

- accepts a proof from **anyone** (`submit_proof`) — a target address, a transaction hash, and
  a short claim;
- fetches that transaction from your chain's public RPC itself — **no keys, no indexing
  service, no hosting**;
- reduces it to stable evidence fields;
- has a validator committee agree on one of three verdicts;
- arms a **self-expiring** freeze on `CONFIRMED_EXPLOIT`, and does nothing otherwise.

Permissioning is a deployment choice: submit a transaction from your own address and read
`submitter` on the record, or expose it fully and accept that anyone can propose. The
contract does not restrict who may submit.

## 2. Five steps

### Step 1 — deploy the contract

```bash
uv sync
.venv-deploy/bin/python deploy/deploy_studio_dev.py     # or add --network studionet
```

Constructor arguments:

| Argument | Value |
|---|---|
| `owner` | your address — guards the admin setters |
| `evidence_url_template` | only used in `digest` mode; leave empty for `jsonrpc` |
| `evidence_mode` | `jsonrpc` (default; fetches your chain directly) or `digest` |
| `evidence_rpc_url` | your chain's public JSON-RPC endpoint |

### Step 2 — point it at your chain

Either at deploy time, or later:

```python
contract.write("set_evidence_rpc", ["https://your-chain-rpc.example", "jsonrpc"])
```

The contract POSTs **one batched** request asking for `eth_getTransactionReceipt` and
`eth_getTransactionByHash`. Any standard EVM JSON-RPC endpoint works. A public endpoint is
fine — the request is read-only and the response is reduced to stable fields before anything
consensus-bound sees it.

### Step 3 — your target needs two functions

```solidity
interface IHaltable {
    function isFrozen() external view returns (bool);
    function freeze(string calldata reason, uint256 until) external;
    function unfreeze(string calldata reason) external;
}
```

The contract calls exactly these, on finality only.

**`until` is a unix timestamp in seconds.** Make `isFrozen()` return false once `block.timestamp`
passes it. That is what makes the freeze self-lifting on the EVM side as well as in GenLayer
storage — the contract can emit an unfreeze, but it cannot force one, so the target must
enforce the deadline itself. **This is the single most important integration requirement.**

```solidity
mapping address => uint256 public frozenUntil;

function isFrozen() external view returns (bool) {
    return frozenUntil[msg.sender] > block.timestamp;  // adapt to your access pattern
}

function freeze(string calldata reason, uint256 until) external onlyPauseAuthority {
    frozenUntil[address(this)] = until;
    emit Frozen(reason, until);
}

function unfreeze(string calldata reason) external onlyPauseAuthority {
    frozenUntil[address(this)] = 0;
    emit Unfrozen(reason);
}
```

Then gate withdrawals:

```solidity
function withdraw(uint256 amount) external {
    require(!isFrozen(), "paused");
    // ...
}
```

### Step 4 — submit and watch

```bash
.venv-deploy/bin/python deploy/submit_proof.py \
  --address 0xYOUR_CONTRACT \
  --tx 0xSUSPICIOUS_TX \
  --claim "repeated transferFrom in one transaction swept the pool"
```

From your own frontend, `client.writeContract` then poll the lifecycle. **Do not collapse the
states** — `PENDING → PROPOSING → COMMITTING → ACCEPTED → FINALIZED` are all distinct and the
wait is real.

### Step 5 — read the outcome

```typescript
const proof = await client.readContract({
  address: HALT,
  functionName: "get_evidence",
  args: [caseId],
});
// proof.verdict, proof.rationale, proof.evidence, proof.frozen, proof.expires_at
```

`is_frozen` and `seconds_remaining` are views, so your UI can render freeze state without
sending a transaction.

## 3. Checking the execution result — do not skip this

A GenLayer transaction can be **finalized by consensus and still have a failed execution.**
Consensus agreeing that a call threw is a valid, recorded outcome.

```typescript
const tx = await client.waitForFinalization({ hash });
if (!isSuccessful(tx)) {
  // Do NOT blindly resubmit: the write may already have executed.
  console.error(tx.statusName, tx.txExecutionResultName);
}
```

Retrying a timed-out write blindly is how you get two submissions for one user action.

## 4. Appeals

Consensus is appealable, and an appeal is a first-class part of the product — not an escape
hatch:

```typescript
await client.appealTransaction({ txId, appealTo: <round> });
```

A frozen protocol whose verdict was wrong can be challenged through the normal GenLayer
appeal process. Note the asymmetry worth stating plainly: **the auto-expiry is the fast path,
appeals are the considered one.** Expiry bounds the blast radius; an appeal can overturn the
reasoning.

## 5. Delivery is off-chain: run the watcher

**`freeze()` is not delivered by the GenLayer contract.** This was tested, not assumed
(2026-10-02): consensus finalized with `MAJORITY_AGREE`, `emit().freeze()` returned without
raising, the contract recorded the call — and the target chain received nothing. Full transcript
in `state/reviews/2026-10-02-build-review/R1-EMIT-RESULTS.md`.

So the last hop is yours to run, and it is small:

    python deploy/freeze_watcher.py --address <HALT> --target <POOL> --dry-run   # inspect
    python deploy/freeze_watcher.py --address <HALT> --target <POOL>             # freeze

What it does: reads `get_evidence` for every case, and for any `CONFIRMED_EXPLOIT` case that has
not been emitted yet, calls `freeze(reason, epoch(expires_at))` on your target. The window comes
from the adjudicated verdict, not from the watcher's own clock.

**State this trade to your users.** Whoever runs the watcher holds a key that can freeze. What this
architecture changes is that the key can no longer freeze *unbounded and unaccountably* — the
window is on the public record, appealable, and your target lapses it itself. Ship the watcher in
your repo, not as a hosted dependency.

If you want to do it yourself instead, the inputs are all public and need no privileged GenLayer
access:

1. Read the verdict from GenLayer storage: `get_evidence`, `is_frozen`, `expires_at`.
2. Call `freeze()` with `until` taken from `expires_at`.

Note the deadline must come from **chain time**. Base Sepolia's clock ran ~53s ahead of our host
during testing, and a host-computed `until` was already in the past by the time the transaction
landed — so `freeze()` reverted silently with nothing frozen.

The verdict, the reasoning, the evidence and the deadline are all publicly readable on-chain,
so a watcher needs no privileged GenLayer access — only your own pause authority. Ship it in
your repo, not as a hosted dependency.

## 6. Tuning

```python
contract.write("set_default_freeze_seconds", [900])   # 1..3600
```

Defaults to 3600. The cap of 3600 is deliberate: a wrong freeze must be cheap. Lower it if your
protocol can tolerate a shorter window, raise it if 15 minutes is not enough to respond.

## 7. What this is *not* good for

- **Not a fast circuit breaker.** Minutes, not seconds. Pair it with a deterministic invariant
  check for the cases you can detect in one block.
- **Not a substitute for careful pause-key hygiene.** It makes freeze authority *accountable*;
  it does not make it correct.
- **Not a finished risk engine.** The default evidence is deliberately shallow (receipt status,
  one selector, event-topic counts, two magnitude bands). For real money, feed it a prepared
  evidence bundle via `digest` mode and extend `derive_digest` for your protocol.

## 8. Comparison with the nearest GenLayer projects

The organiser listed the emergency-halt slot as *"No live project yet."* Nearest neighbours:

| Project | What it does | How this differs |
|---|---|---|
| **AutoBounty** (1000-pt Track Winner) | Self-executing bounty layer; GenLayer verifies the work, Avalanche holds the funds | Escrow and payout. No freeze authority problem. |
| **BuildersClaw** (2000-pt Grand Prize) | Two-stage hackathon judging with escrow and payouts end to end | Judgement, not intervention. Same two-stage *shape*, different action: it scores, this freezes. |
| **GHBounty** | Open-source bounties released on verified work | Bounty release. |
| **MergeProof** | Staked review and settlement on pull requests | Review settlement. |

Common thread: they resolve **payment**. This resolves **intervention** — specifically, who is
allowed to pull a plug on a live protocol, and what happens when they are wrong. None of them
carries a self-expiring, consensus-gated freeze. The live projects we found do not include one.

## 9. Honest gaps

- EVM delivery does not work on the current GenLayer stack; it is done off-chain by the watcher,
  and that watcher holds a key that can freeze (README, docs section 5).
- The default evidence digest is shallow; extend it for your protocol.
- We ran against Studionet, not studio-dev, because studio-dev could not execute contracts
  when we tested (deploy/README.md).
- We have no paying user. Treat this as a proposal.

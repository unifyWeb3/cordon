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
- records a **self-expiring** freeze window on `CONFIRMED_EXPLOIT`, and does nothing otherwise.
  The contract holds no signing key, so it cannot itself freeze your protocol: your EVM target
  acts on a signed attestation carried by an off-chain relay (§5), and can only ever pause for
  the deadline the record states.

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

### Step 3 — your target must verify the attestation

```solidity
interface IHaltable {
    function isFrozen() external view returns (bool);
    function freezeFromAttestation(
        bytes32 caseId,
        bytes32 verdictHash,
        bool finalized,
        uint256 expiresAt,
        bytes calldata signature
    ) external;
    function unfreeze(string calldata reason) external;
}
```

**The GenLayer contract does not call any of this.** It holds no signing key, so it cannot
produce an attestation, and `emit()` does not deliver anyway (§5). What calls
`freezeFromAttestation` is the off-chain relay, carrying a signature made by an attester key
over a record the GenLayer contract wrote. Your target's job is to check that signature — not
to trust the caller.

Two requirements, in order of importance.

**1. `isFrozen()` must be a pure read of the deadline.** Make it return false once
`block.timestamp` passes `expiresAt`. Nothing else has to happen for the freeze to end: no
keeper, no unfreeze transaction, not even the GenLayer contract staying alive. **This is the
single most important integration requirement**, and it is what makes a wrong verdict cheap.

**2. The deadline and the verdict are *signed*. Verify them, and reject a caller who
substitutes his own.** `verdictHash` must be `keccak256("CONFIRMED_EXPLOIT")`, `finalized` must
be `true`, and the digest below must be recomputed from `expiresAt` as passed in — so a relay
that changes the deadline breaks the signature.

```solidity
bytes32 public constant VERDICT_CONFIRMED_EXPLOIT = keccak256("CONFIRMED_EXPLOIT");

bytes32 private constant _DOMAIN_TYPEHASH = keccak256(
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
);
bytes32 private constant _ATTESTATION_TYPEHASH = keccak256(
    "Attestation(bytes32 caseId,address target,bytes32 verdictHash,bool finalized,uint256 expiresAt)"
);

bytes32 private immutable DOMAIN_SEPARATOR;

constructor(address[] memory attesters_, uint256 maxWindow_) {
    require(attesters_.length > 0, "no attesters");
    require(maxWindow_ > 0, "zero window");
    for (uint256 i = 0; i < attesters_.length; i++) {
        attesterSet[attesters_[i]] = true;                  // no setter, ever — see below
    }
    DOMAIN_SEPARATOR = keccak256(
        abi.encode(
            _DOMAIN_TYPEHASH,
            keccak256("CordonVerdictAttestation"),
            keccak256("1"),
            block.chainid,
            address(this)                                   // binds the digest to THIS pool
        )
    );
}

function isFrozen() public view returns (bool) {
    return frozenUntil > block.timestamp;
}

/// `target` is not a parameter. It is `address(this)` inside the digest, so an attestation
/// minted for another pool recovers a meaningless signer and fails as "unknown attester".
function attestationDigest(
    bytes32 caseId, bytes32 verdictHash, bool finalized, uint256 expiresAt
) public view returns (bytes32) {
    return keccak256(
        abi.encodePacked(
            bytes1(0x19), bytes1(0x01), DOMAIN_SEPARATOR, _ATTESTATION_TYPEHASH,
            caseId, address(this), verdictHash, finalized, expiresAt
        )
    );
}

function freezeFromAttestation(
    bytes32 caseId, bytes32 verdictHash, bool finalized,
    uint256 expiresAt, bytes calldata signature
) external {
    require(verdictHash == VERDICT_CONFIRMED_EXPLOIT, "verdict not confirmed");
    require(finalized, "verdict not finalized");

    address signer = _recover(
        attestationDigest(caseId, verdictHash, finalized, expiresAt), signature
    );
    require(signer != address(0) && attesterSet[signer], "unknown attester");

    require(expiresAt > block.timestamp, "window already closed");
    require(expiresAt <= block.timestamp + MAX_WINDOW, "expiry beyond max window");
    require(
        frozenUntil == 0 || frozenUntil <= block.timestamp || expiresAt <= frozenUntil,
        "cannot extend a live freeze"
    );

    frozenUntil = expiresAt;                                // the SIGNED deadline, exactly
    emit Frozen(caseId, signer, expiresAt);
}

function _recover(bytes32 hash, bytes memory sig) internal pure returns (address) {
    if (sig.length != 65) return address(0);
    (bytes32 r, bytes32 s, uint8 v) = _split(sig);
    // Reject the upper half of the curve order: otherwise one signature has two valid
    // encodings, and "who signed this" stops having a single answer.
    if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
        return address(0);
    }
    if (v != 27 && v != 28) return address(0);
    return ecrecover(hash, v, r, s);
}
```

Then gate withdrawals:

```solidity
function withdraw(uint256 amount) external {
    require(!isFrozen(), "paused");
    // ...
}
```

**Do not add an owner-only pause.** The point of the design is that no key — not yours, not
the relay's — can freeze on its own. If you keep a `freeze()` callable by an owner, that owner
is the authority and the attestation is decoration. Likewise, **the attester set must be
constructor-set and immutable**: if the relay key can edit the set, it can appoint itself and
bypass the gate entirely. `demo-target/src/HaltablePool.sol` is a complete worked example, and
`tests/direct/test_haltable_pool.py` executes it on an EVM with real signatures.

Two further details that are easy to get wrong and are covered by tests in this repo:

- The DOMAIN_SEPARATOR uses `abi.encode` (so `address` occupies a **32-byte word**), while the
  attestation preimage uses `abi.encodePacked` (so `address` is **20 bytes** and `bool` is
  **1 byte**). Mixing the two produces a well-formed digest that never matches.
- The scheme is EIP-712-*style*: the domain separator and the `0x19 0x01` prefix are standard,
  but the struct is hashed flat into the preimage rather than via a two-level struct hash. A
  wallet signing it as EIP-712 typed data would produce a different digest and the freeze would
  be rejected. Sign with the repo's own `deploy/attest.py`.


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

## 5. Delivery is off-chain: run the attester, then the relay

**The GenLayer contract cannot deliver the freeze, and no longer pretends to.** This was tested,
not assumed (2026-10-02): consensus finalized with `MAJORITY_AGREE`, `emit().freeze()` returned
without raising, the contract recorded the call — and the target chain received nothing. Full
transcript in `state/reviews/2026-10-02-build-review/R1-EMIT-RESULTS.md`. The `emit` calls have
since been **removed** from `contracts/emergency_halt.py`, so there is no longer a call that
reports success and delivers nothing. What remains in its place is a commented note pointing here.

The last hop is two programs, deliberately split so that the key that pays the gas is not the key
that decides:

    # 1. The attester signs. This is the only program that holds an attester key.
    python deploy/attest.py --case <CASE_ID> --out /tmp/opencode/attestation.json

    # 2. The relay verifies and broadcasts. It holds NO attester key.
    python deploy/freeze_watcher.py --case <CASE_ID> \
        --target <POOL> --attestation /tmp/opencode/attestation.json --dry-run
    python deploy/freeze_watcher.py --case <CASE_ID> \
        --target <POOL> --attestation /tmp/opencode/attestation.json

`attest.py` reads `get_evidence` and refuses to sign unless the record is a finalized
`CONFIRMED_EXPLOIT` **in `jsonrpc` evidence mode** whose `target` — and whose *fetched
transaction's* `tx_to` — is the pool being attested. It then signs `expires_at` from the record.
That refusal matters: in `digest` mode the submitter supplies `to` along with every other digest
field, so the target binding is not chain-enforced and signing would assert "this transaction
touched this pool" on the submitter's word alone.

`freeze_watcher.py` then re-reads the record itself (keylessly), recomputes the digest, recovers
the signer from the signature and requires it to be a configured attester — before sending
anything. It treats the attestation file's own `digest` and `signer` fields as claims to check,
not facts. After the transaction lands it reads `frozenUntil()` back from the pool and requires it
to equal the signed deadline exactly, because a status-1 receipt only proves the call did not
revert.

**State this trade to your users, precisely.** With one attester configured this is *still a single
key*: compromise it and it can freeze, bounded by `MAX_WINDOW`, with no exploit at all. What the
design changes is that the key can no longer freeze *unattributably*. The signature names the case,
the pool and the deadline, so a wrong freeze is a signed, public, appealable statement by a known
address rather than an anonymous pause — and the relay operator, who pays the gas, cannot choose
any of those three things. The honest summary is: an unaccountable pause key has been replaced by
an attributable, window-bounded signature. It is not decentralisation.

**One authority the pool does hand out, and it is worth naming: `unfreeze`.** The pool's `owner` can
clear `frozenUntil`, and it can only ever *clear* it — never create a freeze, never extend one. That
is checked rather than asserted: every write site in the contract is enumerated in
`tests/direct/test_haltable_pool.py`
(`test_the_only_writers_of_frozenUntil_are_the_attested_path_and_unfreeze`), and there are exactly
two, the attested path and an owner-only `unfreeze` that writes literal zero. The demo deploys the
pool with the relay key as `owner` for convenience, because one key is one thing to configure; the
consequence is that the gas payer can end a freeze early and still cannot start one. If you do not
want the gas payer to hold even that, deploy the pool with a different `owner` (or
`transferOwnership` afterwards): `freezeFromAttestation` is permissionless, so the relay needs no
authority at all to deliver a freeze.

**Two paths shorten a live deadline, and both are deliberate.** `frozenUntil` can go *down* in two
ways, never up:

* a second attestation with a **nearer** `expiresAt` replaces a live freeze — the check quoted above
  is `expiresAt <= frozenUntil`, so a later deadline is refused ("cannot extend a live freeze") and
  a nearer one is accepted. That is what lets a milder, more recent adjudication supersede a harsher
  one without waiting for the window to lapse
  (`test_a_live_freeze_may_be_shortened`, `test_reapplying_the_same_attestation_is_idempotent`);
* `unfreeze` zeroes it, as above.

Nothing anywhere can push a deadline *out*. If your threat model includes "the attester is
compromised", note that the compromise can end a freeze early, and still cannot keep one running
past what a signature said.

If you want to do the last hop yourself, the inputs are all public and need no privileged GenLayer
access:

1. Read the verdict from GenLayer storage: `get_evidence`, `verdict`, `expires_at`, `evidence.tx_to`.
2. Refuse anything that is not a finalized `CONFIRMED_EXPLOIT` for your pool in `jsonrpc` mode.
3. Sign `expiresAt = epoch(expires_at)` with the attester key, then call `freezeFromAttestation`.

**Read the deadline from chain time, never the host clock.** Base Sepolia's clock ran ~53 s ahead
of our host during testing, and a host-computed deadline was already in the past by the time the
transaction landed. Both programs take `expires_at` from the record and the *target chain's* latest
block timestamp for the "is this window still open" check.

**A note on the read path.** `genlayer-py` 0.18.0 reports the live contract as `not found`
(`gen_call failed (code=-32001)`) at the correct endpoint, chain and address, while `genlayer-js`
reads the same contract; and `read_contract` raises unless an account is connected, so reading
public state through the SDK client would need a GenLayer key. `deploy/genlayer_read.py` therefore
keeps the SDK's calldata encoder (still reliable) and does the transport itself over plain HTTPS
with no account and no key. This defect is unfixed, so treat a Python-SDK "contract not found" as
a reader bug rather than an on-chain fact.

Ship both programs in your repo, not as a hosted dependency.

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

- EVM delivery does not work on the current GenLayer stack, so it is done off-chain by two
  programs. The split matters: the **attester** holds the only key that can authorise a freeze
  (and with one attester configured, that is still a single key — bounded by `MAX_WINDOW`, and
  attributable because the signature names case, pool and deadline). The **relay** holds no such
  key and can only choose when, and who pays the gas (README, docs section 5).
- No `CONFIRMED_EXPLOIT` has been produced against a live public transaction, and none was
  manufactured for the demo: real public drains adjudicate to `FALSE_REPORT` or
  `INSUFFICIENT_EVIDENCE`. The attestation-to-freeze path is exercised on an EVM in
  `tests/direct/test_relay_attestation.py`, not claimed from a live freeze.
- The default evidence digest is shallow; extend it for your protocol.
- We ran against Studionet, not studio-dev, because studio-dev could not execute contracts
  when we tested (deploy/README.md).
- Live GenLayer reads are made by `deploy/genlayer_read.py` rather than the Python SDK client,
  because `genlayer-py` 0.18.0 reports the live contract as not found at the correct endpoint,
  chain and address. That defect is unfixed upstream, and the write path would hit it too.
- We have no paying user. Treat this as a proposal.

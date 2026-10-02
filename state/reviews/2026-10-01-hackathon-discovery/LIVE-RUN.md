# Live run transcript — Studionet (chain 61999)

Recorded 2026-10-01. Reproduce with `deploy/submit_proof.py` (commands at the bottom).

## Deployment

    contract address : 0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774b
    deploy txId      : 0xb24a7dcc3afe86c6228cd1d90ae3b5d1346bbe7515df5371a993dee8ec14fd32
    lifecycle        : COMMITTING -> ACCEPTED -> FINALIZED
    consensus        : MAJORITY_AGREE
    schema           : ctor(owner, evidence_url_template, evidence_mode, evidence_rpc_url)

Read-only verification immediately after deploy:

    stats()  -> {'cases': 0, 'default_freeze_seconds': 3600,
                 'evidence_url_template': '', 'freezes': 0,
                 'owner': '0x3211…', 'submits': 0}
    list_cases() -> []
    methods -> get_evidence, get_verdict, is_frozen, list_cases, reap_expired,
               seconds_remaining, set_default_freeze_seconds, set_evidence_rpc,
               set_evidence_url_template, stats, submit_proof

Constructor state round-tripped correctly (owner, mode, freeze window), which confirms the
deploy really executed rather than merely registering an address.

## Case 1 — nonexistent transaction

    tx id        : 0x7f7b4fff0aeeaf28f6814d8f277f7c83ff52385cb06ec5b54a9e9ef9050e8188
    target tx    : 0x0000…0001   (not on chain)
    claim        : "Definitely an exploit, trust me."
    lifecycle    : PENDING -> PROPOSING -> COMMITTING -> ACCEPTED -> FINALIZED
    consensus    : MAJORITY_AGREE
    verdict      : INSUFFICIENT_EVIDENCE
    frozen       : False
    expires_at   : (empty)
    rationale    : "The transaction could not be located on-chain, so there is no data to
                   confirm or refute an exploit."
    evidence     : found=False status=NOT_FOUND value=UNKNOWN logs=UNKNOWN
    signature    : emergency-halt/evidence@1|found=0|ok=0|value=UNKNOWN|logs=UNKNOWN|rep=

## Case 2 — real transaction, false claim

    tx id        : 0xf0ac9f674397c31db2dded5c6827044cdb0746ad9d5cbf162ca9795e9e145c5e
    target tx    : 0xa7329a50fd54721c60a2d01deccbf8def3ed1ff03a31e03a40d06d135dcb19d7
                   (real Base Sepolia tx)
    claim        : "Attacker drained the protocol with a repeated unbounded transferFrom in a
                   single transaction."
    lifecycle    : PROPOSING -> COMMITTING -> ACCEPTED -> FINALIZED
    consensus    : MAJORITY_AGREE
    verdict      : FALSE_REPORT
    frozen       : False
    rationale    : "The transaction executed successfully but shows zero value magnitude and
                   only a few logs with no repeated event signatures, which directly
                   contradicts the claim of a 'repeated unbounded transferFrom' drain — such
                   an expl…"
    evidence     : found=True status=0x1 value=ZERO logs=FEW
    signature    : emergency-halt/evidence@1|found=1|ok=1|value=ZERO|logs=FEW|rep=

## Case 3 — real transaction that superficially looks like a drain

    tx id        : 0x22bfd736878f6d810a0c0e7e078e85ecb118d814c690e4bc96e7468d0b53eeda
    target tx    : 0x0822131fff60d8f5a2c62647869ed30638b543eb6e15bbb11b3b62b1581cb144
                   (15 logs, 14 sharing one Transfer topic)
    claim        : "Attacker drained the protocol: the same transferFrom selector fires
                   fourteen times inside one transaction, sweeping the pool."
    lifecycle    : PROPOSING -> COMMITTING -> ACCEPTED -> FINALIZED
    consensus    : MAJORITY_AGREE
    verdict      : FALSE_REPORT
    frozen       : False
    rationale    : "The transaction succeeded with many Transfer events but zero value moved
                   and a non-transfer function (0x1249c58b) called; this matches ordinary
                   batch or liquidity activity, not an unauthorized drain."
    evidence     : found=True status=0x1 value=ZERO logs=MANY
    signature    : emergency-halt/evidence@1|found=1|ok=1|value=ZERO|logs=MANY|
                   rep=0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef

### What cases 2 and 3 actually show

Both are `FALSE_REPORT`, and that is the correct outcome, not a failure:

- Case 2 is a **false report**: the claim was fabricated and the evidence said so.
- Case 3 has the surface signature (14 repeated `Transfer` topics, `logs=MANY`) but
  `value=ZERO` and a non-`transferFrom` outer selector (`0x1249c58b`). The models weighed
  the measured evidence over the narrative and declined to freeze.

A pause module that confirmed both would freeze a healthy protocol on a rumour and on a
liquidity operation. **On random public transactions the right answer is usually "not an
exploit",** and a system that cannot say that is unsafe. That is the single most important
observation in this transcript.

`CONFIRMED_EXPLOIT` is covered by the hermetic suite, where the evidence fixture is built to
carry the drain signature (see `tests/direct/test_consensus_gate.py`). We did not manufacture a
public transaction just to make the demo look better.

## Demo target — deployed and verified on Base Sepolia (added 2026-10-02)

    contract : HaltablePool.sol  ->  0xDF9Ba466540D2Fe4a62650f4d849231a2cb32b7B
    deployer : 0x3211d1419709682b81c53cc51cb63622e25488d3

Freeze semantics proven live, with no GenLayer involved:

1. `deposit()` 0.01 ETH -> success
2. `freeze("manual-test", now+120)` -> status `0x1`, event emitted
3. `isFrozen()` -> **true**, `secondsUntilUnfreeze()` counting down
4. `withdraw(...)` -> **reverts `paused`**
5. wait for expiry, send **nothing**
6. `isFrozen()` -> **false**, and `withdraw(...)` **succeeded**

Step 5 is the thesis: the target lapsed its own freeze with no human action.

### Two practical traps found the hard way

- **Base Sepolia's clock runs ahead of the host** (~53s when measured). A deadline computed with
  `date +%s` produced a `until` already in the past, so `freeze()` silently reverted and
  `isFrozen()` stayed false — with no error surfaced by the send. **Read chain time.**
- **Base is an OP-stack L2 and requires `gasPrice`** alongside EIP-1559 fields, or `eth-account`
  rejects the transaction with `Transaction must include these fields: {'gasPrice'}`.

### EVM emit: tested, and it does not deliver

See `R1-EMIT-RESULTS.md` in the 2026-10-02 review directory for the full transcript. Summary:
consensus `FINALIZED` / `MAJORITY_AGREE`, `emit().freeze()` returned without raising, the probe
recorded `freeze=1` — and `HaltablePool.frozenUntil` was unchanged. Ghost-contract registration
is not the missing step (`isGhostContract` returns true).

## Caveat on the execution-result field

`txExecutionResultName` reads as `None` through `genlayer-py` 0.18.0 on Studionet — an
SDK/field-name skew, not a failed execution: the verdict and evidence reads succeed
immediately afterwards, which cannot happen if execution failed. On studio-dev the field is
populated (`FINISHED_WITH_ERROR`, see `deploy/README.md`). The client must still check it
properly, because a genuine FINALIZED-with-failed-execution is real.

## Reproduce

    .venv-deploy/bin/python deploy/submit_proof.py \
      --address 0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774b \
      --tx 0x0000000000000000000000000000000000000000000000000000000000000001 \
      --claim "Definitely an exploit, trust me." \
      --case-id repro-missing --network studionet

Note that each public transaction can only be adjudicated once per contract instance,
because a duplicate `case_id` is rejected. Use a fresh `--case-id` for repeat runs.

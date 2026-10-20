# Deployment

Two environments, two virtualenvs, because they genuinely differ.

| venv | SDK | Used for |
|---|---|---|
| `.venv` | `genlayer-py==0.9.0` (pinned by `genlayer-test==0.28.0`) | tests: `gltest`, `genvm-lint` |
| `.venv-deploy` | `genlayer-py==0.18.0` | deploy and submit scripts |

`genlayer-test` hard-pins `genlayer-py==0.9.0`, so upgrading the test environment is not an
option without breaking the pinned harness the brief requires. The deploy scripts need a
current SDK, hence the second environment.

## Commands

    # tests (pinned harness)
    uv run pytest tests/direct/ -v

    # lint + SDK validation
    uv run genvm-lint check contracts/emergency_halt.py

    # if validation reports "Failed to load SDK: HTTP Error 404", point the tool at
    # the SDK gltest has already extracted (see state/MEMORY.md for why)
    GENVMROOT=/tmp/opencode/genvmroot uv run genvm-lint check contracts/emergency_halt.py

    # deploy
    .venv-deploy/bin/python deploy/deploy_studio_dev.py --check
    .venv-deploy/bin/python deploy/deploy_studio_dev.py

    # submit a proof and watch the lifecycle
    .venv-deploy/bin/python deploy/submit_proof.py \
        --address 0x... --tx 0x... --claim "..." --case-id my-case --network studionet

## Freezing the target (two programs, deliberately split)

    # 1. the attester signs -- the ONLY program holding an attester key
    python deploy/attest.py --case my-case --out /tmp/opencode/attestation.json

    # 2. the relay verifies and broadcasts -- holds NO attester key
    python deploy/freeze_watcher.py --case my-case \
        --target 0x... --attestation /tmp/opencode/attestation.json --dry-run

`attest.py` refuses to sign a `digest`-mode record, because in that mode the submitter supplies the
transaction's `to` and the target binding is not chain-enforced. `freeze_watcher.py` re-reads the
record itself, recomputes the digest, recovers the signer and only then sends. See
`docs/integration.md` §5.

Environment variable **names** the two programs read (never print or commit their values):
`CORDON_ATTESTER_PRIVATE_KEY`, `CORDON_ATTESTER_ADDRESS`, `BASE_SEPOLIA_RPC_URL`,
`BASE_SEPOLIA_PRIVATE_KEY`.

## Networks

| Network | chain | Fees | Contract execution |
|---|---|---|---|
| Studionet | 61999 | no | **works** |
| studio-dev | 61997 | yes | **fails — see below** |

### studio-dev findings (verified empirically, 2026-10-01)

1. studio-dev is **fee-charging**. `sim_getFeeConfig` reports `enabled: true`.
2. A transaction must carry a fee distribution and a non-zero `feeValue`, or the node reverts
   with `FeesDistributionMissing` / `FeeValueMustBeNonZero`.
3. **No published Python SDK speaks this ABI.** `genlayer-py` 0.9.0 and 0.18.0 both encode the
   old five-argument `addTransaction`. `genlayer-js` 1.1.8 does too. Only
   `genlayer-js@2.0.0-rc.1` matches. `deploy/fees_aware.py` reproduces the ~40 lines of
   encoding from the RC's own ABI declaration so the Python path can deploy at all.
4. **Contract execution does not currently work on studio-dev.** Every deploy — including
   `contracts/minimal_probe.py`, a 20-line contract — finalizes with
   `tx_execution_result = FINISHED_WITH_ERROR`, `result_name = MAJORITY_AGREE`,
   `num_of_rounds = 0`, both with and without `leaderOnly`. Consensus agrees that execution
   failed. No contract is registered afterwards (`gen_getContractSchema` returns
   "not found"). This is environment-side, not contract-side: the same code deploys and
   executes on Studionet.
5. studio-dev also does not expose `gen_dbg_traceTransaction`, so the execution error cannot
   be read back from the node. Its "development preview can be reset or redeployed without
   preserving state" `[A14]` is consistent with what is observed.

**Consequence:** the live deployment and the demo run on **Studionet (61999)**. That is a
deviation from the brief's target and is reported as such. studio-dev remains configured and
the deploy script targets it by default, so it becomes usable unchanged if the preview recovers.

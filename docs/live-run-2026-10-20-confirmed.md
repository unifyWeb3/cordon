# Live run, 2026-10-20 (confirmed) — a real exploit, a real `CONFIRMED_EXPLOIT`, a real attested freeze

This is a **new** transcript. The earlier one, [`live-run-2026-10-20.md`](live-run-2026-10-20.md),
is left exactly as it was written: it records a negative result on `HaltablePool` and is still true
for that target. This file records a different target and a different result.

**What was staged, and what was real.** The target is
`demo-target/src/VulnerableDemoPool.sol`, an intentionally vulnerable testnet contract whose header
says so. The ETH is ours on Base Sepolia. The exploit is not simulated: a caller with no deposit
took another depositor's funds in one transaction, and the pinned state proves it. The adjudication
is consensus over the real receipt. Nothing about the IC, its prompt, its enum or its thresholds was
changed.

Design and the reason a new target was needed: [`state/DESIGN-live.md`](../state/DESIGN-live.md).

## 1. Artifacts

| What | Value |
|---|---|
| IC | `0x95be4d883F89F28CF9cE986e1B400c8CB0808201` (Studionet 61999, unchanged) |
| Vulnerable target | `0x4d7b0793476Ce614539feC663fccD4ab6f1eFaed` (Base Sepolia 84532) |
| Deployment tx | `0xde2e7a52443a6cbb5d9704a20d6a8749b634b783f384d0b50e1da149fe8e11b1` |
| Deployment block / gas | `0x2e1e2be` (48,358,078) / 1,126,924 |
| Constructor args | attester `0xaA1444844a653943634b0F3621C62A942a8E3D73`, `MAX_WINDOW = 3600` |
| Runtime | 4,693 bytes; sha256 `e696ac973ca6bf6693c06df6db297a42d0cfcf5c2643ebfa64799d85dab59324` |
| Runtime keccak | `0xed018ec60deb672dd940fd47c2a97c14694b6c438130fd2c5ccb781821fb2b59` |
| `DOMAIN_SEPARATOR` | `0x5a15bdb86d3aaf05e91d56a4c345c626da0a989d91913d306303e9fcc3a25b3f` |

`deploy/verify_pool_code.py --source demo-target/src/VulnerableDemoPool.sol` proves the on-chain
runtime is a fresh compile of the source outside exactly the constructor-written immutable slots
(`attesterCount=1`, `MAX_WINDOW=3600` twice, the domain separator), and that the domain separator is
the one recomputed from chain 84532 and this address. It does **not** prove the creation transaction
carried that bytecode — creation code is not recoverable without tracing. That remains RPC trust.

## 2. The exploit (real, direct, one transaction to the pool)

`VulnerableDemoPool.claimRewards(uint256 rounds)` is payable and takes its budget from
`address(this).balance` instead of `deposits[msg.sender]`, deducting nothing. The victim deposited
through the correct `deposit()`; the attacker had never deposited.

| Step | Tx | Block | Observed |
|---|---|---|---|
| victim `deposit()` of 40,000,000,000,000 wei | `0x8376d542a31de01550b719fbcae52623448b731350d302d3ac9f00d79d65bb42` | 48,358,116 | `status 0x1`, gas 47,034 |
| attacker `claimRewards(12)` with 1 wei | `0x5fca99a5567bc92ab8246738cb1037d6a916f66096392a678ee286f04674a0ab` | 48,358,119 | `status 0x1`, gas 124,446, 12 logs |

Pinned reads (never `latest`) at the deposit block and at the claim block:

| Read | Before claim (block 48,358,116) | After claim (block 48,358,119) |
|---|---|---|
| `deposits(victim)` | 40,000,000,000,000 | **40,000,000,000,000** (unchanged) |
| `deposits(attacker)` | 0 | 0 |
| pool balance | 40,000,000,000,000 | **5 wei** |

The attacker was paid 12 × 3,333,333,333,333 = 39,999,999,999,996 wei out of the victim's deposit,
leaving 5 wei of rounding dust. The victim's credit was never touched, which is the accounting lie.

Receipt, as the adjudicator saw it:

```
status          0x1
tx.to           0x4d7b0793476ce614539fec663fccd4ab6f1efaed   (== target)
tx value        1 wei                                         (value_band SMALL)
logs            12                                            (log_band MANY)
input selector  0x0962ef79  = claimRewards(uint256)
event topic0    0x7084f5476618d8e60b11ef0d7d3f06914655adb8793e28ff7f018d4c76d505d5  ×12
```

All 12 logs are emitted by the pool. `repeated_selectors` is that one topic repeated twelve times —
the receipt shape the product documents as the drain signature, now on a transaction that actually
is a drain.

## 3. The adjudication

| Field | Value |
|---|---|
| Case | `staged-exploit-vulnpool` |
| GenLayer tx | `0x15db6c4e58aa7857a7e6a979d1055d6ff2d33f5b8345ac088b49e270eac26c49` |
| Lifecycle | `PROPOSING → COMMITTING → ACCEPTED → FINALIZED`, `MAJORITY_AGREE` |
| Verdict | **`CONFIRMED_EXPLOIT`**, `frozen=true` |
| Recorded | `2026-10-20T08:24:41Z`; expires `2026-10-20T09:24:41Z` (epoch 1792488281) |
| Evidence signature | `emergency-halt/evidence@1\|found=1\|ok=1\|value=SMALL\|logs=MANY\|to=0x4d7b0793476ce614539fec663fccd4ab6f1efaed\|rep=0x7084f5476618d8e60b11ef0d7d3f06914655adb8793e28ff7f018d4c76d505d5` |

The stored rationale is truncated by the IC at 500 characters; it ends mid-word. That is the
contract's own limit, not an edit here:

> The transaction executed successfully against a pool contract, with the repeated event signature
> indicating a reward-claiming function fired multiple times in a single call — consistent with the
> described reentrancy or loop-based drain where claimRewards paid out 12 iterations from the pool's
> global balance rather than the caller's credited deposit. Even though the claim labels this a
> 'staged test,' the on-chain behavior (MANY logs, repeated identical event, successful execution
> draining funds b

Two things follow. The receipt, not the staging label, is what was adjudicated; and the digest still
cannot see the amounts or the victim's credit. The numbers in the claim are true (the pinned reads
above are the proof) but they were not independently checkable by the model.

## 4. Attestation and relay

`deploy/attest.py` re-read the record and signed it; it refuses a non-finalized verdict, a
non-`jsonrpc` record, or a target/`tx_to` mismatch.

```
attestation digest  0x7fc09a7f1b06eb7c798f70c6374571c91356bb10f9d5600629a583de7d8a49b4
signer              0xaA1444844a653943634b0F3621C62A942a8E3D73
deadline            2026-10-20T09:24:41Z (1792488281)
signature           0xe6fd6fc600bbd6612c5d2f70c72bfff9df32b9c76b6fa439077fa592ba3c23bd222d953311fae1404c917f5873af20e343c8f0882ea0b8fefbfb1f36a97633be1b
```

The relay re-verified the record against the contract, not against the file, then broadcast:

| What | Value |
|---|---|
| Relay tx | `0xe78a9cb057709f613148967c6b610732bd3bb1335a0d21cf20fff94f1479ffb1` |
| Block / gas | `0x2e1e37f` (48,358,271) / `status 0x1` |
| `isFrozen()` at that block | `1` |
| `frozenUntil()` at that block | `1792488281` |
| Signed `expiresAt` | `1792488281` — **equal** |
| `freezeCaseId()` | `0xa0f10c9f17f549feeebdb06ae4e6e456e80c82a2af7d48f22b7202e64f88e972` = `keccak("staged-exploit-vulnpool")` |
| `freezeAttester()` | `0x000…aA1444844a653943634b0F3621C62A942a8E3D73` |

This is the complete path, live: consensus verdict → signed attestation → off-chain delivery →
`freezeFromAttestation` → a pool whose `frozenUntil` is the signed deadline. The IC still cannot
deliver the freeze itself; the relay did.

## 5. Negative controls

All are real transactions or real GenLayer cases.

| Control | Evidence | Result |
|---|---|---|
| **wrong-pool attestation** — signed for the decoy `0x…dEaD`, sent to the frozen pool | Base tx `0x50ad8418119de4ef975f2277bacd9da0544c19cdafc4b976bdddb46acf6b6b75`, block 48,358,327, gas 31,007 | `status 0x0`, `unknown attester`; recovered against the pool's digest `0x2BAfD1c2f62Ad0eF0F3Fd6f10D62Ad307f7bEdB0` ≠ attester; state byte-identical before/after |
| **replay** — the exact signed attestation, re-sent | Base tx `0x163d6dad91cd229cd0d711f904db84b04b2761232fafd64e46ec6e7bbe631319`, block 48,358,348, gas 49,086 | `status 0x1`, idempotent: `frozenUntil` still `1792488281`, same case id; no extension |
| **wrong target** — the identical exploit receipt, submitted against `0xe979…1359E` | GenLayer tx `0xdeceeeb0189fced65077cfa1aa2231539787b95e481c123b27bafc9a029c163b`, case `control-wrong-target-vulnpool` | `FINALIZED`, `INSUFFICIENT_EVIDENCE`, `frozen=false`. Same evidence signature as the confirmed case (`to=0x4d7b…`) |

The third control needs a caveat. The model's own rationale identified the mismatch —

> The transaction was sent to address 0x4d7b…efaed, which does not match the target address
> 0xe979…1359e identified in the claim. Evidence for one target cannot be used to confirm an
> exploit on a different, unrelated address.

— so the contract's `tx_to != target` downgrade was **not independently isolated**: the verdict was
already `INSUFFICIENT_EVIDENCE` when `_record` saw it. The pipeline refused; which layer refused
first is not distinguished by this case.

## 6. What this proves, and what it does not

Proved by the hashes above: a direct transaction to a target pool can be a real zero-credit drain;
the IC can return a finalized `CONFIRMED_EXPLOIT` for it; the attester can sign exactly that record;
the relay can land the freeze; and `frozenUntil` equals the signed deadline at a pinned block.

Not proved: that the digest measures the theft (it does not — it measures the call's own value, the
log count and the topics); that the verdict was independent of the claim's numbers (it was not); that
the model will confirm a *non-staged* public drain (untested); that the layer which rejected the
wrong-target case was the contract (it was not isolated); and that expiry works on this pool in
practice. Expiry is the next observation: the window closes at **2026-10-20T09:24:41Z**, and there
is no unfreeze transaction. The owner key exists and could clear it early; it was not used.

Trust that remains: the attester is one key; the evidence comes from one configured RPC; the relay
pays the gas and chooses when; and the vulnerable contract is ours, so this is a proof of the
lifecycle, not of anyone's production safety.

## 7. Re-verification

```bash
# 1. code-vs-source proof for the vulnerable target
.venv-deploy/bin/python deploy/verify_pool_code.py \
  --address 0x4d7b0793476Ce614539feC663fccD4ab6f1eFaed \
  --source demo-target/src/VulnerableDemoPool.sol

# 2. the IC record (genlayer-js is the client that reads this deployment)
cd web && node scripts/verify-live.mjs staged-exploit-vulnpool

# 3. the pool, at the relay block (never `latest`)
.venv-deploy/bin/python - <<'PY'
import json, os, sys
sys.path.insert(0, "deploy")
from dotenv import load_dotenv; load_dotenv(".env", override=False)
from deploy_target import Rpc
rpc = Rpc(os.environ["BASE_SEPOLIA_RPC_URL"])
pool = "0x4d7b0793476Ce614539feC663fccD4ab6f1eFaed"
blk = "0x2e1e37f"
print("frozenUntil", rpc.read_uint(pool, "frozenUntil()", block=blk))   # 1792488281
print("isFrozen   ", rpc.read_uint(pool, "isFrozen()", block=blk))       # 1
PY

# 4. the exploit receipt's shape
.venv-deploy/bin/python - <<'PY'
import os, sys
sys.path.insert(0, "deploy")
from dotenv import load_dotenv; load_dotenv(".env", override=False)
from deploy_target import Rpc
rpc = Rpc(os.environ["BASE_SEPOLIA_RPC_URL"])
r = rpc.call("eth_getTransactionReceipt",
             ["0x5fca99a5567bc92ab8246738cb1037d6a916f66096392a678ee286f04674a0ab"])
print("status", r["status"], "logs", len(r["logs"]), "to", r["to"])
PY

# 5. tests, including the exploit and the corrected twin
.venv/bin/python -m pytest tests/direct/test_vulnerable_demo_pool.py -q
```

The prior transcript `docs/live-run-2026-10-20.md` was not edited.

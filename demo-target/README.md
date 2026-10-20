# Demo target — `HaltablePool.sol`

The EVM side of the demo: a pausable withdrawal pool that accepts a freeze **only** as a signed,
finalized `CONFIRMED_EXPLOIT` naming itself, at a deadline an attester signed, and that lifts the
freeze on its own.

`src/HaltablePool.sol` is the canonical source. (An older copy used to sit in this directory; it
described an interface that no longer exists and has been deleted.)

## Why it looks like this

Two properties matter, in this order.

```solidity
function isFrozen() public view returns (bool) {
    return frozenUntil > block.timestamp;
}
```

**1. `isFrozen()` is a pure read of a deadline.** A freeze cannot outlive its window even if no
unfreeze transaction is ever sent, and even if the GenLayer contract goes away entirely. That is
what makes a wrong verdict cheap rather than dangerous.

If you integrate this and compute `isFrozen()` any other way — a boolean that only a separate call
can clear — you have reintroduced exactly the failure mode this project exists to fix: freeze state
that depends on someone remembering to undo it.

**2. The freeze is *attested*, not authorised.** There is no owner pause path. `freeze(string,uint256)`
used to exist and has been **removed**; so has any attester-setter. The attester set is
constructor-set and cannot be changed by anyone afterwards, including the deployer. If the relay
key could edit the set, it could appoint itself and the whole gate would be decoration.

## Interface the relay calls

```solidity
function isFrozen() external view returns (bool);
function freezeFromAttestation(
    bytes32 caseId,
    bytes32 verdictHash,
    bool finalized,
    uint256 expiresAt,
    bytes calldata signature
) external;
function unfreeze(string calldata reason) external;   // owner-only, and only shortens
```

**The GenLayer contract calls none of these.** It holds no signing key, and `gl.evm.contract_interface(…).emit()`
does not deliver on the current stack (tested 2026-10-02, transcript in
`state/reviews/2026-10-02-build-review/R1-EMIT-RESULTS.md`). `freezeFromAttestation` is
permissionless and called by the off-chain relay; the authority is the signature, not the caller.

`expiresAt` is a **unix timestamp in seconds**, and it must be the exact value the attester signed.
`docs/integration.md` §3 has the digest construction, and `deploy/attestation.py` computes it
independently — the two are asserted byte-identical by
`tests/direct/test_attestation_digest.py`, because a silent disagreement between them presents as
"unknown attester" and is indistinguishable from a wrong key.

## Compiling

No Solidity toolchain is assumed to be installed. `solc` is pulled from npm as the WASM build, which
is deliberate: the upstream `solc-static-linux` binary is amd64-only and will not run on
linux/aarch64, where this project is developed.

```bash
cd demo-target
npm install          # solc 0.8.24, pinned
npm run build        # -> out/src_HaltablePool_sol_HaltablePool.{bin,abi}
```

`tests/direct/evm_harness.py` compiles the same source with the same npm package, so the artifact
the tests execute is the artifact this builds. It does **not** reuse `out/`: it compiles into
`out/harness/` fresh on every session. That is deliberate. `solcjs` names its output after the
input path *as it was given*, so the name depends on the working directory — and a harness that
guessed one name found the stale artifact left behind by `npm run build`, then reported a
successful execution of a contract it had never compiled. Recompiling removes both the guessed
name and the stale artifact.

If `solc` is missing entirely, the EVM tests **skip** — and `tests/direct/conftest.py` then
**fails the session**, because "50 passed, 38 skipped" otherwise reads as a green run while the
whole freeze path went unverified. Set `CORDON_ALLOW_SKIP_NO_SOLC=1` to accept that skip on the
record.

## Exercising the freeze

The intended way to drive a real freeze is the two programs described in `docs/integration.md` §5:
`deploy/attest.py` signs, `deploy/freeze_watcher.py` verifies and broadcasts.

For a local, no-network run, the repository's own harness deploys this contract onto an in-process
EVM and exercises the complete path with real signatures:

```bash
cd ..
.venv/bin/python -m pytest tests/direct/test_haltable_pool.py -q         # every accept/reject path
.venv/bin/python -m pytest tests/direct/test_relay_attestation.py -q     # record -> attest -> freeze
```

`test_haltable_pool.py` covers, among others: a genuine attestation freezing for exactly the signed
deadline; the deadline returning the freeze to open with nobody acting; a wrong pool; a
caller-substituted deadline; a non-attester signature; a high-`s` (malleable) signature; an expiry
beyond `MAX_WINDOW`; an attempted extension of a live freeze; and the absence of any owner pause.

Step "the deadline returns the freeze to open with nobody acting" is the whole thesis: **the failure
mode self-heals.**

## Honest status

This contract is **not deployed**, and no live `CONFIRMED_EXPLOIT` has ever been produced — real
public transactions adjudicate to `FALSE_REPORT` or `INSUFFICIENT_EVIDENCE`, and none was
manufactured. So the attestation-to-freeze path is verified against a real EVM with real signatures
and a real signed transaction, but it has **not** been exercised end to end against a deployed
GenLayer contract and a live target. See "What we could not verify" in the top-level README.

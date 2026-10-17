"""The complete path: finalized CONFIRMED_EXPLOIT verdict -> signed attestation -> freeze.

These tests execute the Solidity on a real EVM, with real ECDSA signatures. Nothing here is
asserted from the ABI alone; `ecrecover` runs, the deadline is written to storage, and the
revert strings come back from the EVM.

The security claim under test is narrow and worth stating exactly: after this change the
target accepts a freeze ONLY from a signed, finalized CONFIRMED_EXPLOIT, for that same pool,
at the exact signed deadline. The relay holds no freeze authority.

What the target still trusts is ONE attester key. It cannot verify GenLayer consensus, and it
does not try to; it verifies that a registered key signed a statement. With a single attester
configured that is still a single key -- see the note in `docs/integration.md` section 5.

Deadlines are computed from BLOCK time, never the host clock. `maxWindow` is measured against
`block.timestamp`, and a host-clock deadline is how you get a freeze that reverts for reasons
nobody can reproduce on another machine.
"""

import pytest

from attestation import (
    CONFIRMED_EXPLOIT,
    VERDICT_HASH_CONFIRMED,
    attestation_digest,
    case_hash,
    verdict_hash,
)
from evm_harness import (  # noqa: F401
    Pool,
    accounts,
    attester,
    deployment_revert_reason,
    deploy_pool,
    evm,
    keys,
    pool_artifact,
    relay,
    sign,
)

CASE = "live-drain-run2"
MAX_WINDOW = 3600


def _deploy(evm, pool_artifact, attesters, max_window=MAX_WINDOW, deployer=None):
    abi, bytecode = pool_artifact
    return deploy_pool(evm, abi, bytecode, attesters, max_window, deployer=deployer)


def _deadline(pool, offset=600):
    """A deadline the pool will accept: inside `maxWindow` of the current block time."""
    return pool.block_time + offset


def _attest(evm, pool, key, *, case=CASE, verdict=CONFIRMED_EXPLOIT, finalized=True,
            expires_at, target=None):
    """Sign an attestation for `pool`. `target` defaults to the pool itself."""
    digest = attestation_digest(
        evm.backend.chain.chain_id,
        pool.address,
        case,
        target or pool.address,
        verdict,
        finalized,
        expires_at,
    )
    return sign(digest, key)


# ------------------------------------------------------------------ the complete path


def test_confirmed_verdict_to_freeze_end_to_end(evm, pool_artifact, accounts, attester, relay):
    """A finalized CONFIRMED_EXPLOIT, attested, freezes the pool for the signed deadline.

    Submitted by the RELAY, which is not an attester -- authority comes from the signature,
    not from msg.sender.
    """
    attester_addr, attester_key = attester
    relay_addr, _ = relay
    pool = _deploy(evm, pool_artifact, [attester_addr])

    assert pool.call("isFrozen") is False
    assert pool.call("frozenUntil") == 0

    expires = _deadline(pool)
    signature = _attest(evm, pool, attester_key, expires_at=expires)

    receipt = pool.expect_ok(
        relay_addr,
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        expires,
        signature,
    )
    assert receipt["status"] == 1

    assert pool.call("isFrozen") is True
    assert pool.call("frozenUntil") == expires
    assert pool.call("freezeAttester") == attester_addr
    assert pool.call("freezeCaseId") == case_hash(CASE)


def test_frozen_until_equals_the_signed_expiry_exactly(evm, pool_artifact, accounts, attester):
    """The recorded deadline must be the signed one, with nothing rounded or clamped.

    A fresh pool per case, because a second freeze may only shorten a live one.
    """
    attester_addr, attester_key = attester

    for offset in (60, 600, 3599):
        pool = _deploy(evm, pool_artifact, [attester_addr])
        expected = _deadline(pool, offset)

        pool.expect_ok(
            attester_addr,
            "freezeFromAttestation",
            case_hash(CASE),
            VERDICT_HASH_CONFIRMED,
            True,
            expected,
            _attest(evm, pool, attester_key, expires_at=expected),
        )
        assert pool.call("frozenUntil") == expected, (
            "frozenUntil must equal the signed expiresAt, not a value the caller chose"
        )
        assert pool.call("isFrozen") is True


def test_the_caller_cannot_substitute_a_different_deadline(
    evm, pool_artifact, accounts, attester, relay
):
    """The relay passes the deadline as an argument -- so it must match the signed one.

    This is the "relay cannot choose another deadline" requirement, asserted directly: the
    same signature replayed with a longer deadline must not verify.
    """
    attester_addr, attester_key = attester
    relay_addr, _ = relay
    pool = _deploy(evm, pool_artifact, [attester_addr])

    signed = _deadline(pool, 600)
    signature = _attest(evm, pool, attester_key, expires_at=signed)

    longer = _deadline(pool, 1800)
    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        longer,
        signature,
        sender=relay_addr,
    )
    assert reason == "unknown attester", (
        "changing the deadline must break the signature, not merely be ignored"
    )
    assert pool.call("frozenUntil") == 0


def test_withdrawals_are_blocked_while_frozen(evm, pool_artifact, accounts, attester):
    """The freeze has to actually mean something to a user."""
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])
    user = accounts[3]

    pool.expect_ok(user, "deposit", value=10**18, gas=200_000)
    assert pool.call("deposits", user) == 10**18

    expires = _deadline(pool)
    pool.expect_ok(
        user,
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        expires,
        _attest(evm, pool, attester_key, expires_at=expires),
    )

    assert pool.revert_reason("withdraw", 10**17, sender=user) == "paused"
    assert pool.revert_reason("deposit", sender=user, value=1) == "paused"


def test_the_freeze_lifts_itself_once_the_deadline_passes(
    evm, pool_artifact, accounts, attester
):
    """`isFrozen()` is a pure read of the deadline, so nobody has to unfreeze it."""
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])
    user = accounts[3]

    pool.expect_ok(user, "deposit", value=10**18, gas=200_000)

    expires = _deadline(pool, 60)
    pool.expect_ok(
        attester_addr, "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED,
        True, expires, _attest(evm, pool, attester_key, expires_at=expires),
    )
    assert pool.call("isFrozen") is True
    assert pool.call("secondsUntilUnfreeze") > 0
    assert pool.revert_reason("withdraw", 10**17, sender=user) == "paused"

    # Move past the deadline with nobody acting -- no unfreeze transaction, no keeper.
    assert pool.advance_to(expires + 1) > expires

    assert pool.call("isFrozen") is False, "the window must close on its own"
    assert pool.call("secondsUntilUnfreeze") == 0
    pool.expect_ok(user, "withdraw", 10**17, gas=200_000)


# ------------------------------------------------------------------ rejections


def test_wrong_pool_attestation_is_rejected_as_unknown_attester(
    evm, pool_artifact, accounts, attester
):
    """An attestation minted for another pool recovers a meaningless signer.

    `target` is NOT a parameter of `freezeFromAttestation`. It is baked into DOMAIN_SEPARATOR
    as `verifyingContract`, so a foreign attestation produces a digest this pool never signed,
    `ecrecover` returns some unrelated address, and the failure surfaces as "unknown attester".

    There is deliberately no target-specific error string: the contract has no way to know a
    foreign attestation was ever intended for it, so inventing one would be a lie about what
    was actually checked.
    """
    attester_addr, attester_key = attester
    victim = _deploy(evm, pool_artifact, [attester_addr])
    other = _deploy(evm, pool_artifact, [attester_addr])
    assert other.address != victim.address

    # Signed against `other`, replayed at `victim`.
    signature = _attest(evm, other, attester_key, expires_at=_deadline(other))

    reason = victim.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        _deadline(victim),
        signature,
    )
    assert reason == "unknown attester"
    assert victim.call("frozenUntil") == 0
    assert victim.call("isFrozen") is False


def test_attestation_naming_a_different_target_is_rejected(
    evm, pool_artifact, accounts, attester
):
    """The `target` field inside the signed payload is bound too, not just the domain."""
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])
    expires = _deadline(pool)
    signature = _attest(evm, pool, attester_key, expires_at=expires, target=accounts[9])

    reason = pool.expect_revert(
        "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED, True, expires, signature
    )
    assert reason == "unknown attester"
    assert pool.call("frozenUntil") == 0


def test_non_attester_signature_is_rejected(evm, pool_artifact, accounts, attester, relay):
    """The relay key is the owner, and still cannot freeze."""
    attester_addr, _ = attester
    relay_addr, relay_key = relay
    pool = _deploy(evm, pool_artifact, [attester_addr])
    expires = _deadline(pool)

    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        expires,
        _attest(evm, pool, relay_key, expires_at=expires),
    )
    assert reason == "unknown attester"
    assert pool.call("isAttester", relay_addr) is False
    assert pool.call("frozenUntil") == 0


def test_non_confirmed_verdict_is_rejected(evm, pool_artifact, accounts, attester):
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])

    for bad_verdict in ("FALSE_REPORT", "INSUFFICIENT_EVIDENCE"):
        expires = _deadline(pool)
        signature = _attest(evm, pool, attester_key, verdict=bad_verdict, expires_at=expires)
        reason = pool.expect_revert(
            "freezeFromAttestation",
            case_hash(CASE),
            verdict_hash(bad_verdict),
            True,
            expires,
            signature,
        )
        assert reason == "verdict not confirmed"
    assert pool.call("frozenUntil") == 0


def test_unfinalized_verdict_is_rejected(evm, pool_artifact, accounts, attester):
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])
    expires = _deadline(pool)

    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        False,
        expires,
        _attest(evm, pool, attester_key, finalized=False, expires_at=expires),
    )
    assert reason == "verdict not finalized"
    assert pool.call("frozenUntil") == 0


def test_already_expired_deadline_is_rejected(evm, pool_artifact, accounts, attester):
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])

    past = pool.block_time - 1
    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        past,
        _attest(evm, pool, attester_key, expires_at=past),
    )
    assert reason == "window already closed"
    assert pool.call("frozenUntil") == 0


def test_expiry_beyond_max_window_is_rejected(evm, pool_artifact, accounts, attester):
    """Even a genuine attester signature cannot buy a longer pause than the pool allows.

    The overshoot is a full hour, not one second, on purpose: the check is
    `expiresAt <= block.timestamp + MAX_WINDOW` and time advances by at least a second when
    the confirmation transaction is mined. Asserting exactly one second over the bound would
    be asserting against a clock that has moved -- see the note on `expect_revert`.
    """
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr], max_window=60)

    too_far = pool.block_time + 60 + 3600
    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        too_far,
        _attest(evm, pool, attester_key, expires_at=too_far),
    )
    assert reason == "expiry beyond max window"
    assert pool.call("frozenUntil") == 0
    assert pool.call("isFrozen") is False


def test_max_window_boundary_is_inclusive(evm, pool_artifact, accounts, attester):
    """Exactly `MAX_WINDOW` ahead is accepted; the bound is `<=`, not `<`."""
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr], max_window=60)

    exact = pool.block_time + 60
    pool.expect_ok(
        attester_addr, "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED,
        True, exact, _attest(evm, pool, attester_key, expires_at=exact),
    )
    assert pool.call("frozenUntil") == exact


def test_a_live_freeze_cannot_be_extended(evm, pool_artifact, accounts, attester):
    """An attester can re-apply or shorten, but never stretch an open window."""
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])

    first = _deadline(pool, 600)
    pool.expect_ok(
        attester_addr, "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED,
        True, first, _attest(evm, pool, attester_key, expires_at=first),
    )
    assert pool.call("frozenUntil") == first

    longer = _deadline(pool, 1200)
    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        longer,
        _attest(evm, pool, attester_key, expires_at=longer),
    )
    assert reason == "cannot extend a live freeze"
    assert pool.call("frozenUntil") == first


def test_a_live_freeze_may_be_shortened(evm, pool_artifact, accounts, attester):
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])

    first = _deadline(pool, 1200)
    pool.expect_ok(
        attester_addr, "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED,
        True, first, _attest(evm, pool, attester_key, expires_at=first),
    )

    shorter = _deadline(pool, 300)
    pool.expect_ok(
        attester_addr, "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED,
        True, shorter, _attest(evm, pool, attester_key, expires_at=shorter),
    )
    assert pool.call("frozenUntil") == shorter


def test_reapplying_the_same_attestation_is_idempotent(evm, pool_artifact, accounts, attester):
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])
    expires = _deadline(pool)
    signature = _attest(evm, pool, attester_key, expires_at=expires)

    for _ in range(2):
        pool.expect_ok(
            attester_addr, "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED,
            True, expires, signature,
        )
    assert pool.call("frozenUntil") == expires


# ------------------------------------------------------------------ signature handling


def test_high_s_signature_is_rejected(evm, pool_artifact, accounts, attester):
    """Reject the malleable encoding, so one signature has exactly one valid form."""
    attester_addr, attester_key = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])
    expires = _deadline(pool)

    digest = attestation_digest(
        evm.backend.chain.chain_id, pool.address, CASE, pool.address,
        CONFIRMED_EXPLOIT, True, expires,
    )
    signature = bytearray(sign(digest, attester_key))
    n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    s = int.from_bytes(signature[32:64], "big")
    signature[32:64] = (n - s).to_bytes(32, "big")
    signature[64] = 55 - signature[64]  # 27 <-> 28

    reason = pool.expect_revert(
        "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED, True, expires,
        bytes(signature),
    )
    assert reason == "unknown attester"
    assert pool.call("frozenUntil") == 0


@pytest.mark.parametrize("bad_len", [0, 64, 66])
def test_malformed_signature_length_is_rejected(evm, pool_artifact, accounts, attester, bad_len):
    attester_addr, _ = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])
    reason = pool.expect_revert(
        "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED, True,
        _deadline(pool), b"\x01" * bad_len,
    )
    assert reason == "unknown attester"


def test_all_zero_signature_is_rejected(evm, pool_artifact, accounts, attester):
    attester_addr, _ = attester
    pool = _deploy(evm, pool_artifact, [attester_addr])
    reason = pool.expect_revert(
        "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED, True,
        _deadline(pool), b"\x00" * 65,
    )
    assert reason == "unknown attester"


# ------------------------------------------------------------------ no owner pause


def test_there_is_no_owner_pause_path(evm, pool_artifact, accounts, attester):
    """A1: the owner (who is the relay) has no unilateral freeze. Asserted from the ABI."""
    attester_addr, _ = attester
    pool = _deploy(evm, pool_artifact, [attester_addr], deployer=accounts[0])

    names = {e["name"] for e in pool.abi if e.get("type") == "function"}
    assert "freeze" not in names, "the old owner-only freeze entry point must be gone"
    assert "pause" not in names
    assert "emergencyPause" not in names
    assert pool.call("owner") == accounts[0]
    assert pool.call("frozenUntil") == 0


def test_attester_set_has_no_admin_function(evm, pool_artifact, accounts, attester):
    """Constructor-set and final: the relay-as-owner must not be able to appoint itself."""
    attester_addr, _ = attester
    pool = _deploy(evm, pool_artifact, [attester_addr], deployer=accounts[0])

    names = {e["name"] for e in pool.abi if e.get("type") == "function"}
    for forbidden in ("setAttester", "addAttester", "removeAttester", "setAttesters",
                      "setMaxWindow", "setMAX_WINDOW"):
        assert forbidden not in names, f"{forbidden} would let the owner bypass the gate"

    assert pool.call("attesterCount") == 1
    assert pool.call("isAttester", attester_addr) is True
    assert pool.call("isAttester", accounts[0]) is False, "the deployer is not an attester"


def test_constructor_rejects_an_empty_attester_set(evm, pool_artifact):
    """A pool with no attesters could never be frozen; refuse it at deploy time."""
    abi, bytecode = pool_artifact
    reason = deployment_revert_reason(evm, abi, bytecode, [])
    assert reason == "no attesters"


def test_constructor_rejects_a_zero_window(evm, pool_artifact, accounts, attester):
    attester_addr, _ = attester
    abi, bytecode = pool_artifact
    reason = deployment_revert_reason(evm, abi, bytecode, [attester_addr], max_window=0)
    assert reason == "zero window"


def test_constructor_rejects_a_zero_attester(evm, pool_artifact):
    abi, bytecode = pool_artifact
    reason = deployment_revert_reason(evm, abi, bytecode, ["0x" + "00" * 20])
    assert reason == "zero attester"


def test_unfreeze_shortens_and_the_owner_is_required(evm, pool_artifact, accounts, attester):
    """`unfreeze` cannot create a freeze, and is not callable by anyone else."""
    attester_addr, attester_key = attester
    owner = accounts[0]
    pool = _deploy(evm, pool_artifact, [attester_addr], deployer=owner)

    assert pool.revert_reason("unfreeze", "nope", sender=accounts[5]) == "not owner"
    assert pool.call("frozenUntil") == 0

    expires = _deadline(pool)
    pool.expect_ok(
        attester_addr, "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED,
        True, expires, _attest(evm, pool, attester_key, expires_at=expires),
    )
    assert pool.call("isFrozen") is True

    pool.expect_ok(owner, "unfreeze", "cleared")
    assert pool.call("frozenUntil") == 0
    assert pool.call("isFrozen") is False

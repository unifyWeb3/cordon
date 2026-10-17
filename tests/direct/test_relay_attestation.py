"""The relay path: record -> attest -> verify -> freeze, plus every refusal on the way.

The claim this module defends is: a freeze reaches the EVM target only from a finalized
CONFIRMED_EXPLOIT naming *that* target, at *exactly* the recorded deadline, and the relay can
choose none of those things.

Two levels are tested, and they are not the same level:

  * `refusal_reason` / `build_attestation` -- what the attester will and will not sign. Pure
    functions: no network, no key beyond a test key.
  * `verify` / `broadcast` -- what the relay will and will not send. `verify` re-derives
    everything from its own read of the record; the headline test then pushes the result
    through a real signed transaction into a real EVM and reads `frozenUntil()` back.

The last two tests are deliberately structural rather than behavioural: they assert that the
relay's source cannot sign and does not use the removed entry point. A behavioural test cannot
demonstrate the absence of a capability.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from eth_account import Account

from attest import RefusedToSign, build_attestation, refusal_reason
from attestation import (
    CONFIRMED_EXPLOIT,
    VERDICT_HASH_CONFIRMED,
    SECP256K1_HALF_N,
    attestation_digest,
    case_hash,
    iso_to_epoch,
    normalize_address,
    recover_signer,
)
from evm_harness import (  # noqa: F401
    accounts,
    attester,
    deploy_pool,
    evm,
    keys,
    pool_artifact,
    relay,
)
import attestation
from freeze_watcher import Evm, RefusedToBroadcast, broadcast, main, verify
from rpc_stub import LocalRpc, RawRpc, py_evm_handler

CASE = "live-drain-run2"
ROOT = Path(__file__).resolve().parent.parent.parent
CURVE_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

# Deadlines used by the pure tests. `NOW` is arbitrary; only the comparisons matter.
DEFINED_LATER = 4102444800
LONG_AGO = 1_000_000


@pytest.fixture
def pool_address():
    """A stand-in pool address. The encoding functions are pure, so no chain is needed here.

    Real-chain behaviour is covered by `test_confirmed_record_to_frozen_deadline_end_to_end`.
    """
    return "0x" + "22" * 20


def iso_of(epoch: int) -> str:
    """Unix seconds -> the ISO shape the contract records (second resolution, trailing Z)."""
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def make_record(
    pool_address: str,
    deadline: int,
    *,
    case_id: str = CASE,
    mode: str = "jsonrpc",
    verdict: str = CONFIRMED_EXPLOIT,
    frozen: bool = True,
    expires_at: str | None = None,
    tx_to: str | None = None,
    target: str | None = None,
) -> dict:
    """A GenLayer `Proof`, as `get_evidence` returns it.

    `tx_to` defaults to the pool, which is the coherent case. Pass a different address for the
    record where the fetched transaction went somewhere else.
    """
    return {
        "case_id": case_id,
        "submitter": "0x" + "bb" * 20,
        "target": target or pool_address,
        "tx_hash": "0x" + "ab" * 32,
        "claim": "drained the pool",
        "evidence_url": "https://evidence.test/exploit",
        "evidence_mode": mode,
        "submitted_at": iso_of(deadline - 600),
        "finalized": True,
        "verdict": verdict,
        "rationale": "eight repeated transferFrom selectors at LARGE value",
        "evidence": {
            "source_url": "https://evidence.test/exploit",
            "tx_found": True,
            "receipt_ok": True,
            "success": True,
            "receipt_status": "0x1",
            "tx_to": pool_address if tx_to is None else tx_to,
            "input_selector": "0x23b872dd",
            "selectors": "0x23b872dd",
            "repeated_selectors": "0x23b872dd",
            "value_band": "LARGE",
            "log_band": "MANY",
            "signature": "deadbeef",
        },
        "evidence_signature": "deadbeef",
        "leader_verdict": verdict,
        "validator_agreed": True,
        "frozen": frozen,
        "expires_at": iso_of(deadline) if expires_at is None else expires_at,
        "unfrozen_at": "",
    }


def _document(pool_address, record, key, *, chain_id=1, now=None, case_id=CASE):
    return build_attestation(
        record,
        pool_address,
        chain_id=chain_id,
        verifying_contract=pool_address,
        private_key=key,
        now_epoch=now,
    )


def _malleable(signature: bytes) -> bytes:
    """The other, equally valid encoding of the same signature: (n - s), v flipped."""
    out = bytearray(signature)
    s = int.from_bytes(out[32:64], "big")
    out[32:64] = (CURVE_N - s).to_bytes(32, "big")
    out[64] = 55 - out[64]  # 27 <-> 28
    return bytes(out)


# --------------------------------------------------------------------- the deadline conversion


@pytest.mark.parametrize(
    "iso",
    [
        "2026-10-17T09:00:00Z",
        "2026-10-17T09:00:00.123456Z",
        "2026-01-01T00:00:00Z",
        "2027-12-31T23:59:59Z",
        "2000-02-29T12:00:00Z",
        "1970-01-01T00:00:00Z",
    ],
)
def test_iso_to_epoch_agrees_with_the_contract(contract_module, iso):
    """The attester's deadline conversion must equal the contract's own.

    The contract records `expires_at`; the attester turns that string into the `expiresAt` it
    signs. If the two conversions differed by even a second, every attestation would name a
    deadline the record does not state -- precisely the failure this design exists to prevent --
    and it would present as a signature problem, not a rounding problem.
    """
    assert iso_to_epoch(iso) == contract_module._epoch(iso)


def test_iso_to_epoch_truncates_subsecond_precision_like_the_contract(contract_module):
    """Sub-second digits are TRUNCATED on both sides, not rounded."""
    iso = "2026-10-17T09:00:00.999999Z"
    assert iso_to_epoch(iso) == iso_to_epoch("2026-10-17T09:00:00Z")
    assert iso_to_epoch(iso) == contract_module._epoch(iso)


# --------------------------------------------------------------------- what the attester signs


def test_a_coherent_record_is_attestable(pool_address):
    assert refusal_reason(make_record(pool_address, DEFINED_LATER), pool_address) is None


def test_digest_mode_is_refused(pool_address):
    """The mandated refusal: in digest mode the submitter supplies `to`."""
    record = make_record(pool_address, DEFINED_LATER, mode="digest")
    reason = refusal_reason(record, pool_address)
    assert reason is not None
    assert "digest" in reason
    assert "submitter" in reason

    with pytest.raises(RefusedToSign):
        build_attestation(
            record,
            pool_address,
            chain_id=1,
            verifying_contract=pool_address,
            private_key="0x" + "11" * 32,
        )


@pytest.mark.parametrize("mode", ["digest", "DIGEST", " digest ", "", "http", "json-rpc"])
def test_only_the_chain_enforced_mode_is_accepted(pool_address, mode):
    """A whitelist, not a blacklist: an unrecognised mode is refused, not assumed benign."""
    assert refusal_reason(make_record(pool_address, DEFINED_LATER, mode=mode), pool_address)


@pytest.mark.parametrize("verdict", ["FALSE_REPORT", "INSUFFICIENT_EVIDENCE", "", "confirmed"])
def test_a_non_confirmed_verdict_is_refused(pool_address, verdict):
    assert refusal_reason(
        make_record(pool_address, DEFINED_LATER, verdict=verdict), pool_address
    )


def test_an_unfrozen_record_is_refused(pool_address):
    assert refusal_reason(
        make_record(pool_address, DEFINED_LATER, frozen=False), pool_address
    )


def test_a_missing_expiry_is_refused(pool_address):
    assert refusal_reason(
        make_record(pool_address, DEFINED_LATER, expires_at=""), pool_address
    )


def test_a_record_naming_another_target_is_refused(pool_address):
    other = "0x" + "99" * 20
    reason = refusal_reason(make_record(pool_address, DEFINED_LATER, target=other), pool_address)
    assert reason is not None and other in reason


def test_a_transaction_that_went_elsewhere_is_refused(pool_address):
    """The binding that makes the attestation about *this* pool and not just any drain."""
    other = "0x" + "99" * 20
    reason = refusal_reason(make_record(pool_address, DEFINED_LATER, tx_to=other), pool_address)
    assert reason is not None
    assert other in reason


def test_a_record_with_no_destination_is_refused(pool_address):
    assert refusal_reason(make_record(pool_address, DEFINED_LATER, tx_to=""), pool_address)


def test_a_closed_window_is_refused_only_when_the_clock_is_supplied(pool_address):
    """Offline the record is structurally fine; with target chain time it is not signable."""
    record = make_record(pool_address, LONG_AGO)
    assert refusal_reason(record, pool_address) is None
    reason = refusal_reason(record, pool_address, now_epoch=2_000_000)
    assert reason is not None and "closed" in reason


def test_an_unparseable_expiry_is_refused(pool_address):
    record = make_record(pool_address, 0, expires_at="the heat death of the universe")
    assert refusal_reason(record, pool_address, now_epoch=0)


def test_build_attestation_signs_the_exact_recorded_deadline(pool_address):
    """The signature covers `expires_at` from the record, in seconds, and nothing else."""
    key = "0x" + "11" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key, chain_id=7, now=1)

    assert document["expires_at"] == record["expires_at"]
    assert document["expires_at_epoch"] == DEFINED_LATER
    assert document["expires_at_epoch"] == iso_to_epoch(record["expires_at"])

    expected = attestation_digest(
        chain_id=7,
        verifying_contract=pool_address,
        case_id=CASE,
        target=pool_address,
        verdict=CONFIRMED_EXPLOIT,
        finalized=True,
        expires_at=DEFINED_LATER,
    )
    assert bytes.fromhex(document["digest"][2:]) == expected
    assert normalize_address(
        recover_signer(expected, bytes.fromhex(document["signature"][2:]))
    ) == normalize_address(document["signer"])


def test_a_different_deadline_produces_a_different_digest(pool_address):
    key = "0x" + "11" * 32
    a = _document(pool_address, make_record(pool_address, DEFINED_LATER), key, chain_id=7)
    b = _document(pool_address, make_record(pool_address, DEFINED_LATER + 1), key, chain_id=7)
    assert a["digest"] != b["digest"]
    assert a["signature"] != b["signature"]


# --------------------------------------------------------------------- what the relay sends


def test_verify_accepts_a_genuine_attestation(pool_address):
    key = "0x" + "11" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)
    signer = document["signer"]

    verified = verify(
        record,
        document,
        claimed_target=pool_address,
        chain_id=1,
        expected_attesters=[signer],
        now_epoch=LONG_AGO,
    )
    assert verified["deadline"] == DEFINED_LATER
    assert normalize_address(verified["signer"]) == normalize_address(signer)
    assert verified["case_hash"] == case_hash(CASE)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda r: r.update(evidence_mode="digest"), "digest"),
        (lambda r: r.update(verdict="FALSE_REPORT"), "FALSE_REPORT"),
        (lambda r: r.update(frozen=False), "not frozen"),
        (lambda r: r.update(expires_at=""), "expires_at"),
    ],
)
def test_verify_refuses_what_the_attester_should_never_have_signed(
    pool_address, mutate, expected
):
    """Defence in depth: a signature that exists is still re-checked against the record."""
    key = "0x" + "11" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)

    edited = make_record(pool_address, DEFINED_LATER)
    mutate(edited)

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            edited,
            document,
            claimed_target=pool_address,
            chain_id=1,
            expected_attesters=[document["signer"]],
            now_epoch=LONG_AGO,
        )
    assert expected in str(exc.value)


def test_verify_refuses_a_record_about_another_pool(pool_address):
    key = "0x" + "11" * 32
    other = "0x" + "99" * 20
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            record, document, claimed_target=other, chain_id=1,
            expected_attesters=[document["signer"]], now_epoch=LONG_AGO,
        )
    assert "target" in str(exc.value)


def test_verify_refuses_a_record_whose_transaction_went_elsewhere(pool_address):
    """The relay checks `tx_to` against its OWN read, and this is the only check that can.

    Worth being precise about why: `tx_to` is not part of the signed digest. The attestation
    asserts "case X on pool P is a confirmed exploit expiring at D" -- the contract already
    enforced the target binding when it wrote the record. So the relay's gate here is its own
    fresh read of GenLayer storage, not the signature. That is sufficient because only the
    contract can write a record, and the relay does not trust a document's word about one.
    """
    key = "0x" + "11" * 32
    other = "0x" + "99" * 20
    # A genuine signature over the coherent record ...
    document = _document(pool_address, make_record(pool_address, DEFINED_LATER), key)
    # ... offered against a record whose transaction went somewhere else.
    edited = make_record(pool_address, DEFINED_LATER, tx_to=other)

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            edited, document, claimed_target=pool_address, chain_id=1,
            expected_attesters=[document["signer"]], now_epoch=LONG_AGO,
        )
    assert other in str(exc.value)
    assert "not evidence about this pool" in str(exc.value)


def test_the_attester_refuses_to_sign_a_record_about_another_pool(pool_address):
    """The same incoherence stops earlier, at signing time. Defence in depth, not a gap."""
    other = "0x" + "99" * 20
    record = make_record(pool_address, DEFINED_LATER, tx_to=other)
    with pytest.raises(RefusedToSign):
        _document(pool_address, record, "0x" + "11" * 32)


def test_verify_refuses_a_tampered_deadline(pool_address):
    """The relay cannot move the goalposts: the deadline is recomputed from the record."""
    key = "0x" + "11" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)
    document["expires_at_epoch"] = DEFINED_LATER + 86_400  # a day longer, please

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            record, document, claimed_target=pool_address, chain_id=1,
            expected_attesters=[document["signer"]], now_epoch=LONG_AGO,
        )
    assert "expires" in str(exc.value)


def test_verify_refuses_when_the_record_moved_after_signing(pool_address):
    """Same signature, record edited afterwards: the digest no longer recovers to an attester."""
    key = "0x" + "12" * 32
    document = _document(pool_address, make_record(pool_address, DEFINED_LATER), key)
    edited = make_record(pool_address, DEFINED_LATER + 60)

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            edited, document, claimed_target=pool_address, chain_id=1,
            expected_attesters=[document["signer"]], now_epoch=LONG_AGO,
        )
    assert "expires" in str(exc.value)


def test_verify_refuses_a_signature_from_a_non_attester(pool_address):
    key = "0x" + "13" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            record, document, claimed_target=pool_address, chain_id=1,
            expected_attesters=["0x" + "44" * 20], now_epoch=LONG_AGO,
        )
    assert "not a configured attester" in str(exc.value)


def test_verify_refuses_when_no_attester_is_configured(pool_address):
    key = "0x" + "14" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            record, document, claimed_target=pool_address, chain_id=1,
            expected_attesters=[], now_epoch=LONG_AGO,
        )
    assert "no expected attester" in str(exc.value)


def test_verify_refuses_a_signature_minted_for_another_chain(pool_address):
    """A signature minted for chain A must not be relayable on chain B.

    Two independent refusals stand in the way, and the digest check fires first: `verify`
    recomputes the digest with the chain id of the chain it is actually talking to, so the
    document's own digest no longer matches. The underlying property is asserted separately
    below, because the message alone does not prove the *signature* is chain-bound.
    """
    key = "0x" + "15" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key, chain_id=1)
    signer = document["signer"]
    signature = bytes.fromhex(document["signature"][2:])

    with pytest.raises(RefusedToBroadcast):
        verify(
            record, document, claimed_target=pool_address, chain_id=2,
            expected_attesters=[signer], now_epoch=LONG_AGO,
        )

    # And the signature itself does not recover to the attester under chain 2's digest.
    chain_2_digest = attestation_digest(
        2, pool_address, CASE, pool_address, CONFIRMED_EXPLOIT, True, DEFINED_LATER
    )
    assert recover_signer(chain_2_digest, signature) != normalize_address(
        normalize_address(signer)
    ), "the signature must not be valid on another chain"


def test_verify_refuses_a_closed_window_in_target_chain_time(pool_address):
    key = "0x" + "16" * 32
    record = make_record(pool_address, LONG_AGO)
    document = _document(pool_address, record, key, now=0)

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            record, document, claimed_target=pool_address, chain_id=1,
            expected_attesters=[document["signer"]], now_epoch=LONG_AGO + 1,
        )
    assert "closed" in str(exc.value)


@pytest.mark.parametrize("signature", ["0x", "0x" + "11" * 64, "0x" + "11" * 66, "", "zz"])
def test_verify_refuses_a_malformed_signature(pool_address, signature):
    key = "0x" + "17" * 32
    document = _document(pool_address, make_record(pool_address, DEFINED_LATER), key)
    document["signature"] = signature

    with pytest.raises(RefusedToBroadcast):
        verify(
            make_record(pool_address, DEFINED_LATER), document, claimed_target=pool_address,
            chain_id=1, expected_attesters=[document["signer"]], now_epoch=LONG_AGO,
        )


def test_verify_refuses_a_malleable_signature(pool_address):
    """Two encodings of one signature would make attribution ambiguous. Both are refused."""
    key = "0x" + "18" * 32
    document = _document(pool_address, make_record(pool_address, DEFINED_LATER), key)
    document["signature"] = "0x" + _malleable(bytes.fromhex(document["signature"][2:])).hex()

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            make_record(pool_address, DEFINED_LATER), document, claimed_target=pool_address,
            chain_id=1, expected_attesters=[document["signer"]], now_epoch=LONG_AGO,
        )
    assert "canonical" in str(exc.value)


def test_verify_refuses_a_cross_pool_attestation(pool_address):
    """Signed for pool A, offered to pool B: the digest differs, so nothing recovers."""
    key = "0x" + "19" * 32
    other = "0x" + "99" * 20
    document = _document(other, make_record(other, DEFINED_LATER), key)

    with pytest.raises(RefusedToBroadcast):
        verify(
            make_record(pool_address, DEFINED_LATER), document, claimed_target=pool_address,
            chain_id=1, expected_attesters=[document["signer"]], now_epoch=LONG_AGO,
        )


# --------------------------------------------------------------------- signature strictness


def test_recover_signer_matches_the_contracts_acceptance_rules(pool_address):
    """`recover_signer` must accept and reject exactly what `HaltablePool._recover` does.

    A relay more permissive than the pool would clear a signature the pool then refuses, and
    its own verdict would contradict the chain's -- the defect class this repo keeps hitting.
    """
    key = "0x" + "1a" * 32
    digest = attestation_digest(
        1, pool_address, CASE, pool_address, CONFIRMED_EXPLOIT, True, DEFINED_LATER
    )
    good = bytes(Account.unsafe_sign_hash(digest, private_key=key).signature)

    assert normalize_address(recover_signer(digest, good)) == normalize_address(
        Account.from_key(key).address
    )
    assert recover_signer(digest, good[:64]) is None
    assert recover_signer(digest, good + b"\x00") is None
    assert recover_signer(digest, b"") is None
    for bad_v in (0, 1, 26, 29, 255):
        broken = bytearray(good)
        broken[64] = bad_v
        assert recover_signer(digest, bytes(broken)) is None, f"v={bad_v} must be rejected"
    assert recover_signer(digest, _malleable(good)) is None, "high-s must be rejected"
    assert int.from_bytes(good[32:64], "big") <= SECP256K1_HALF_N


def test_the_relay_and_the_pool_reject_the_same_signatures(evm, pool_artifact, accounts, attester):
    """The strictness above, confirmed against the contract instead of asserted in a comment."""
    attester_addr, attester_key = attester
    abi, bytecode = pool_artifact
    pool = deploy_pool(evm, abi, bytecode, [attester_addr], 3600)
    deadline = pool.block_time + 600

    digest = attestation_digest(
        evm.backend.chain.chain_id, pool.address, CASE, pool.address,
        CONFIRMED_EXPLOIT, True, deadline,
    )
    good = bytes(Account.unsafe_sign_hash(digest, private_key=attester_key).signature)

    high_s = bytearray(good)
    high_s[32:64] = (CURVE_N - int.from_bytes(good[32:64], "big")).to_bytes(32, "big")
    high_s[64] = 55 - good[64]

    zero_v = bytearray(good)
    zero_v[64] = 0

    # These two pass both cheap checks -- `v` is genuine, `s` is below the half-order -- and are
    # refutable only by `ecrecover` itself, which returns the zero address for them. They are the
    # only inputs that exercise the `signer != address(0)` clause, so without them the guard is
    # present but unproven.
    zero_r = bytearray(good)
    zero_r[:32] = b"\x00" * 32

    zero_s = bytearray(good)
    zero_s[32:64] = b"\x00" * 32

    cases = {
        "genuine": good,
        "short": good[:64],
        "long": good + b"\x00",
        "v=0": bytes(zero_v),
        "high-s": bytes(high_s),
        "all-zero": b"\x00" * 65,
        "r=0": bytes(zero_r),
        "s=0": bytes(zero_s),
    }

    for label, signature in cases.items():
        relay_accepted = recover_signer(digest, signature) is not None
        reason = pool.revert_reason(
            "freezeFromAttestation", case_hash(CASE), VERDICT_HASH_CONFIRMED, True,
            deadline, signature,
        )
        pool_accepted = reason == ""
        assert relay_accepted == pool_accepted, (
            f"{label}: relay accepted={relay_accepted} but pool accepted={pool_accepted} "
            f"(pool said {reason!r})"
        )
        if label in ("r=0", "s=0"):
            # An unmarshallable signature must fail as "not an attester", not as a panic: the
            # pool has no way to distinguish a malformed one from a foreign one, and a revert
            # string that pretended otherwise would misreport what it checked.
            assert reason == "unknown attester", f"{label}: pool said {reason!r}"

    assert recover_signer(digest, good) is not None, "the genuine signature must be accepted"


# --------------------------------------------------------------------- the whole path


def test_confirmed_record_to_frozen_deadline_end_to_end(
    evm, pool_artifact, accounts, attester, relay
):
    """Record -> attest -> relay verify -> real transaction -> exact deadline on the pool.

    The relay is `accounts[2]`, which is NOT an attester. It cannot freeze on its own; it can
    only carry a signature the attester already made. The deadline is read back from the pool's
    own storage, not inferred from the transaction succeeding.
    """
    attester_addr, attester_key = attester
    _, relay_key = relay
    abi, bytecode = pool_artifact
    pool = deploy_pool(evm, abi, bytecode, [attester_addr], 3600)

    deadline = pool.block_time + 600
    record = make_record(pool.address, deadline)
    document = build_attestation(
        record,
        pool.address,
        chain_id=evm.backend.chain.chain_id,
        verifying_contract=pool.address,
        private_key=attester_key,
        now_epoch=pool.block_time,
    )

    assert pool.call("frozenUntil") == 0
    verified = verify(
        record,
        document,
        claimed_target=pool.address,
        chain_id=evm.backend.chain.chain_id,
        expected_attesters=[attester_addr],
        now_epoch=pool.block_time,
    )

    rpc = LocalRpc(py_evm_handler(evm))
    try:
        relay_evm = Evm(rpc.url, relay_key)
        # The read path as it goes on the wire: assert the sender the relay really used, rather
        # than trusting that the code looks keyless.
        relay_evm.frozen_until(pool.address)
        assert rpc.requests[-1]["params"][0]["from"] == "0x" + "00" * 20, (
            "reads must not carry a key-bearing sender"
        )

        assert relay_evm.account.address == accounts[2]
        assert relay_evm.account.address != attester_addr, "the relay must not be the attester"

        tx = broadcast(relay_evm, verified, dry_run=False)
        assert tx, "a real transaction hash is expected"
    finally:
        rpc.close()

    assert pool.call("frozenUntil") == deadline, (
        "the pool's deadline must be exactly the recorded one"
    )
    assert pool.call("isFrozen") is True
    assert pool.call("freezeAttester") == attester_addr
    assert pool.call("freezeCaseId") == case_hash(CASE)


def test_the_relay_cannot_freeze_without_an_attester_signature(
    evm, pool_artifact, accounts, attester, relay
):
    """The same relay, the same call, no signature: the pool refuses."""
    attester_addr, _ = attester
    relay_addr, _ = relay
    abi, bytecode = pool_artifact
    pool = deploy_pool(evm, abi, bytecode, [attester_addr], 3600)
    deadline = pool.block_time + 600

    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        deadline,
        b"\x00" * 65,
        sender=relay_addr,
    )
    assert reason == "unknown attester"
    assert pool.call("frozenUntil") == 0


def test_a_second_relay_cannot_replay_the_signature_at_a_longer_deadline(
    evm, pool_artifact, accounts, attester, relay
):
    """Even holding a genuine signature, the relay cannot choose a different deadline."""
    attester_addr, attester_key = attester
    relay_addr, _ = relay
    abi, bytecode = pool_artifact
    pool = deploy_pool(evm, abi, bytecode, [attester_addr], 3600)

    signed = pool.block_time + 600
    digest = attestation_digest(
        evm.backend.chain.chain_id, pool.address, CASE, pool.address,
        CONFIRMED_EXPLOIT, True, signed,
    )
    signature = bytes(Account.unsafe_sign_hash(digest, private_key=attester_key).signature)

    longer = pool.block_time + 1800
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
        "substituting a deadline must break the signature, not be quietly ignored"
    )
    assert pool.call("frozenUntil") == 0


def test_broadcast_refuses_when_the_pool_stores_a_different_deadline(
    evm, pool_artifact, accounts, attester, relay, monkeypatch
):
    """Verify against the target: a status-1 receipt is not evidence the deadline landed."""
    attester_addr, attester_key = attester
    _, relay_key = relay
    abi, bytecode = pool_artifact
    pool = deploy_pool(evm, abi, bytecode, [attester_addr], 3600)
    deadline = pool.block_time + 600

    record = make_record(pool.address, deadline)
    document = build_attestation(
        record, pool.address, chain_id=evm.backend.chain.chain_id,
        verifying_contract=pool.address, private_key=attester_key, now_epoch=pool.block_time,
    )
    verified = verify(
        record, document, claimed_target=pool.address, chain_id=evm.backend.chain.chain_id,
        expected_attesters=[attester_addr], now_epoch=pool.block_time,
    )

    rpc = LocalRpc(py_evm_handler(evm))
    try:
        relay_evm = Evm(rpc.url, relay_key)
        real = relay_evm.frozen_until
        # Simulate a target that accepted the call but stored something else: the exact
        # "reports success, delivers nothing" shape AGENTS.md warns about.
        monkeypatch.setattr(type(relay_evm), "frozen_until", lambda self, to: real(to) + 1)
        with pytest.raises(RefusedToBroadcast) as exc:
            broadcast(relay_evm, verified, dry_run=False)
        assert "NOT what was attested" in str(exc.value)
    finally:
        rpc.close()

    # The transaction really did land and really did store the right deadline -- which is
    # exactly why the readback matters: the receipt alone would have said "success".
    assert pool.call("frozenUntil") == deadline


# --------------------------------------------------------------------- the role split


def test_the_relay_source_cannot_sign_an_attestation():
    """A behavioural test cannot prove the absence of a capability. This one can.

    The split is the design: `attest.py` signs, `freeze_watcher.py` only carries. If the relay
    could mint an attestation it would be the old unaccountable pause key with more ceremony.
    """
    attester_source = (ROOT / "deploy" / "attest.py").read_text()
    relay_source = (ROOT / "deploy" / "freeze_watcher.py").read_text()

    assert "CORDON_ATTESTER_PRIVATE_KEY" in attester_source
    assert "CORDON_ATTESTER_PRIVATE_KEY" not in relay_source, (
        "the relay must not be able to sign an attestation"
    )
    assert "unsafe_sign_hash" in attester_source
    assert "unsafe_sign_hash" not in relay_source, "signing has no place in the relay"
    assert "build_attestation" not in relay_source
    assert "unfreeze" not in relay_source, "the relay cannot lift a freeze either"


def test_the_deploy_path_only_uses_the_attested_entry_point():
    """The removed `freeze(string,uint256)` must not survive as a live constant anywhere.

    The string may still appear inside a comment explaining why it is gone, which is why this
    checks the constant rather than the bare text.
    """
    relay_source = (ROOT / "deploy" / "freeze_watcher.py").read_text()
    assert "freezeFromAttestation" in relay_source
    assert "FREEZE_SIG" not in relay_source, "the old owner-only call constant is still defined"
    assert 'freeze(string,uint256)"' not in relay_source


# ------------------------------------------------- refusals that used to raise instead


@pytest.mark.parametrize("field", ["signer", "target"])
def test_verify_refuses_a_malformed_address_in_the_attestation_file(pool_address, field):
    """The attestation file is the untrusted input in this path: it is a document handed over.

    `normalize_address` raises `ValueError` on a malformed string, and `main` handles
    `RefusedToBroadcast` only. So before this was fixed a junk field escaped as a traceback and
    the relay said "this tool is broken" where the true answer was "this attestation is not
    valid". A refusal path that crashes is not a refusal path.
    """
    key = "0x" + "21" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)
    real_signer = document["signer"]

    document[field] = "not-an-address"

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            record,
            document,
            claimed_target=pool_address,
            chain_id=1,
            expected_attesters=[real_signer],
            now_epoch=LONG_AGO,
        )
    assert "is not an address" in str(exc.value)


def test_verify_refuses_a_malformed_configured_attester(pool_address):
    """`--attester` / CORDON_ATTESTER_ADDRESS is operator input, and it is normalised too."""
    key = "0x" + "22" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            record,
            document,
            claimed_target=pool_address,
            chain_id=1,
            expected_attesters=["0xnothex"],
            now_epoch=LONG_AGO,
        )
    assert "configured attester" in str(exc.value)


def test_verify_refuses_a_malformed_target_in_the_record(pool_address):
    """A record's `target` is whatever a submitter stored in GenLayer, so it is not trusted.

    The document here was minted for a *good* record that has since been replaced -- which is
    exactly the case the target check exists for, and the one that used to raise `ValueError`
    out of the check whose whole job is to refuse.
    """
    key = "0x" + "23" * 32
    good = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, good, key)
    record = make_record(pool_address, DEFINED_LATER, target="0xdeadbeef")

    with pytest.raises(RefusedToBroadcast) as exc:
        verify(
            record,
            document,
            claimed_target=pool_address,
            chain_id=1,
            expected_attesters=[document["signer"]],
            now_epoch=LONG_AGO,
        )
    assert "is not an address" in str(exc.value)


def test_build_attestation_refuses_a_malformed_target_instead_of_raising(pool_address):
    """The attester's gate must *refuse*: `attestation_digest` would raise `ValueError` later.

    Before this, a claimed target that was not an address skipped the gate as "no reason to
    refuse" and then blew up inside the encoder. A crash on the way to signing is the one
    outcome an attester must never produce.
    """
    key = "0x" + "24" * 32

    with pytest.raises(RefusedToSign) as exc:
        build_attestation(
            make_record(pool_address, DEFINED_LATER),
            "0xdeadbeef",
            chain_id=1,
            verifying_contract=pool_address,
            private_key=key,
        )
    assert "not an address" in str(exc.value)

    with pytest.raises(RefusedToSign) as exc:
        build_attestation(
            make_record(pool_address, DEFINED_LATER, target="zz"),
            pool_address,
            chain_id=1,
            verifying_contract=pool_address,
            private_key=key,
        )
    assert "not an address" in str(exc.value)


def test_build_attestation_refuses_an_unparseable_expiry_without_a_clock(pool_address):
    """`--skip-window-check` is the one path where the gate does not parse `expires_at`.

    The gate only parses the expiry when it has a clock, so this conversion was the only thing
    left that could fail -- and it failed with a `ValueError` traceback instead of a refusal.
    `main` reports refusals; it does not report crashes.
    """
    key = "0x" + "25" * 32
    record = make_record(pool_address, DEFINED_LATER, expires_at="not-a-timestamp")

    with pytest.raises(RefusedToSign) as exc:
        build_attestation(
            record,
            pool_address,
            chain_id=1,
            verifying_contract=pool_address,
            private_key=key,
            now_epoch=None,
        )
    assert "not parseable" in str(exc.value)


# ------------------------------------------------------- the deadline conversion, once more


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-10-17T09:00:00Z",           # the shape the contract writes
        "2026-10-17T09:00:00.987654Z",    # sub-second, which is what a node hands back
        "2026-10-17T09:00:00",            # no zone at all: both sides read it as UTC
        "2026-10-17T09:00:00+02:00",      # an explicit offset, no fraction
        "2026-10-17T09:00:00.123+02:00",  # the offset WITH sub-second precision
        "2026-10-17T09:00:00.123",        # sub-second, no zone
    ],
)
def test_iso_to_epoch_and_the_contract_agree_on_every_timestamp_shape(contract_module, stamp):
    """`iso_to_epoch` must return exactly what the contract's `_epoch` returns, for every shape.

    This replaced a divergence test. `_strip_us` used to drop the zone together with the
    fraction, so `...:00.123+02:00` became `...:00Z` -- two hours from the instant it spells.
    The attester signs the value `iso_to_epoch` produces, so a shift there is a signed deadline
    the record does not mean. Both sides now keep the zone, and agreement is asserted on the
    shapes either could see rather than argued from the ones a test happened to pick.
    """
    assert iso_to_epoch(stamp) == contract_module._epoch(stamp)


def test_a_zone_that_follows_the_fraction_moves_the_instant(contract_module):
    """The regression itself: the zone is folded in, not discarded with the fraction.

    `...09:00:00.123+02:00` names 07:00Z. Reading it as 09:00Z is the silent two-hour shift the
    old `split(".", 1)[0]` performed, and the assertions below fail if either side returns to it.
    """
    shifted = "2026-10-17T09:00:00.123+02:00"

    assert contract_module._strip_us(shifted) == "2026-10-17T09:00:00+02:00"
    assert contract_module._epoch(shifted) == iso_to_epoch("2026-10-17T07:00:00Z")
    assert iso_to_epoch(shifted) == iso_to_epoch("2026-10-17T07:00:00Z")
    assert contract_module._epoch(shifted) != iso_to_epoch("2026-10-17T09:00:00Z")


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2026-10-17T09:00:00Z", "2026-10-17T09:00:00Z"),
        ("2026-10-17T09:00:00.987654Z", "2026-10-17T09:00:00Z"),
        ("2026-10-17T09:00:00.987654", "2026-10-17T09:00:00Z"),
        ("2026-10-17T09:00:00", "2026-10-17T09:00:00Z"),
        ("2026-10-17T09:00:00+02:00", "2026-10-17T09:00:00+02:00"),
        ("2026-10-17T09:00:00.987654+02:00", "2026-10-17T09:00:00+02:00"),
    ],
)
def test_strip_us_keeps_the_zone_and_drops_only_the_fraction(contract_module, stamp, expected):
    """Byte-identical to the old behaviour wherever the old behaviour was right, and idempotent.

    `_strip_us` is applied to values that have already been through it, so a second pass must
    change nothing -- including the passes that now carry an offset instead of a `Z`.
    """
    assert contract_module._strip_us(stamp) == expected
    assert contract_module._strip_us(expected) == expected


def test_the_window_comparison_orders_by_instant_and_not_by_text(contract_module):
    """Keeping the zone exposed a second place that had assumed a trailing `Z`.

    `_iso_le` compared the stripped strings as text. `...10:00:00+02:00` *is* 08:00Z, which is
    after `...07:30:00Z`, but as text it sorts before. On a node-provided clock carrying an
    offset that decides whether a freeze is still live, so the offset is folded in first. The
    `Z`-against-`Z` path -- which is every `expires_at`, since `_iso_shift` always emits `Z` --
    is unchanged.
    """
    assert contract_module._iso_le("2026-10-17T07:30:00Z", "2026-10-17T10:00:00+02:00") is True
    assert contract_module._iso_le("2026-10-17T07:30:00Z", "2026-10-17T06:00:00+02:00") is False
    assert contract_module._iso_le("2026-10-17T07:30:00Z", "2026-10-17T07:30:00Z") is True
    assert contract_module._iso_le("2026-10-17T07:30:00.500Z", "2026-10-17T07:30:00Z") is True


def test_attestation_offers_no_v_normalising_helper():
    """The contract accepts `v` in {27,28} only. A helper that rewrites {0,1} into {27,28} invites
    the relay to clear a signature the pool refuses -- divergent normalisation between the two
    sides is this repo's recurring defect class.

    `split_signature` did exactly that, had no callers, and also contradicted `recover_signer`
    (which refuses the same input). It is gone; this keeps it gone. The rule itself is pinned by
    `test_the_relay_and_the_pool_reject_the_same_signatures`.
    """
    assert not hasattr(attestation, "split_signature")
    assert "v += 27" not in (ROOT / "deploy" / "attestation.py").read_text()


# ------------------------------------------------------------- attaching to a real endpoint


def test_the_relay_reports_an_unusable_target_rpc_instead_of_crashing():
    """A wrong endpoint is the likeliest operator error, so it has to read like one.

    `requests` reports HTML-from-a-proxy as a JSONDecodeError whose text names nothing useful,
    and a non-object JSON body turned into an AttributeError from `.get`. Both reached the
    operator as a traceback that pointed at neither the URL nor the key.
    """
    html = RawRpc(body=b"<html>wrong endpoint</html>", content_type="text/html")
    try:
        with pytest.raises(RuntimeError) as exc:
            Evm(html.url, "0x" + "0f" * 32)
        assert "did not answer with JSON" in str(exc.value)
    finally:
        html.close()

    envelope = RawRpc(body=b'["not", "an", "envelope"]')
    try:
        with pytest.raises(RuntimeError) as exc:
            Evm(envelope.url, "0x" + "0f" * 32)
        assert "malformed JSON-RPC envelope" in str(exc.value)
    finally:
        envelope.close()

    proxy = RawRpc(status=502, body=b'{"jsonrpc":"2.0","id":1,"error":{"message":"bad gateway"}}')
    try:
        with pytest.raises(RuntimeError) as exc:
            Evm(proxy.url, "0x" + "0f" * 32)
        assert "bad gateway" in str(exc.value), "the node's own error text is the useful part"
    finally:
        proxy.close()


def test_main_reports_a_bad_target_rpc_instead_of_dumping_a_traceback(
    tmp_path, monkeypatch, capsys
):
    """The same fix seen from the outside: exit code 2 and a sentence, not a stack trace."""
    rpc = RawRpc(body=b"<html>proxy</html>", content_type="text/html")
    attestation_file = tmp_path / "attestation.json"
    attestation_file.write_text("{}")

    monkeypatch.setenv("BASE_SEPOLIA_PRIVATE_KEY", "0x" + "0f" * 32)
    monkeypatch.setenv("BASE_SEPOLIA_RPC_URL", rpc.url)
    monkeypatch.setenv("CORDON_ATTESTER_ADDRESS", "0x" + "11" * 20)
    try:
        code = main(
            [
                "--case", CASE,
                "--target", "0x" + "22" * 20,
                "--attestation", str(attestation_file),
            ]
        )
    finally:
        rpc.close()

    assert code == 2
    assert "target chain unusable" in capsys.readouterr().err


def test_the_relays_decision_ignores_the_documents_unsigned_fields(pool_address):
    """`tx_hash`, `evidence_signature` and `created_at` are copied into the document and are NOT
    covered by the signature. Nothing may depend on them.

    Taking provenance from its own read of the record is the right design, but it has to be
    pinned: a later version that printed `document["tx_hash"]` as "the transaction that
    justified this freeze" would be presenting an unattested string as evidence. Tampering with
    every unsigned field at once must leave the verified result byte-identical.
    """
    key = "0x" + "26" * 32
    record = make_record(pool_address, DEFINED_LATER)
    document = _document(pool_address, record, key)

    baseline = verify(
        record,
        document,
        claimed_target=pool_address,
        chain_id=1,
        expected_attesters=[document["signer"]],
        now_epoch=LONG_AGO,
    )

    tampered = dict(document)
    tampered["tx_hash"] = "0x" + "ff" * 32
    tampered["evidence_signature"] = "0x" + "ee" * 65
    tampered["created_at"] = "1999-01-01T00:00:00Z"
    tampered["evidence_mode"] = "digest"
    tampered["tx_to"] = "0x" + "33" * 20

    after = verify(
        record,
        tampered,
        claimed_target=pool_address,
        chain_id=1,
        expected_attesters=[document["signer"]],
        now_epoch=LONG_AGO,
    )
    assert after == baseline
    assert after["target"] == normalize_address(pool_address)

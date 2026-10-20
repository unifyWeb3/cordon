"""The deliberately vulnerable demo pool: the exploit, the corrected twin, and the freeze path.

Why this file exists
--------------------
`docs/live-run-2026-10-20.md` records why `HaltablePool` cannot honestly reach
`CONFIRMED_EXPLOIT`: its only outflow is not payable (`value=ZERO`), one call emits one event
(`repeated_selectors` empty), and the adjudicator's target binding requires the transaction to be
sent to the pool. `VulnerableDemoPool` is the smallest target whose *own* direct entry point is a
real accounting bug, so a live adjudication can be honest and the freeze path can be exercised.

Every test here executes the Solidity on py-evm with real values and real signatures; nothing is
asserted from the ABI. Each refusal has a positive control in the same test, so "it reverted" can
never be satisfied by a contract that reverts everything.
"""

from pathlib import Path

import pytest
from eth_utils import keccak, to_checksum_address

from attestation import (
    CONFIRMED_EXPLOIT,
    VERDICT_HASH_CONFIRMED,
    attestation_digest,
    case_hash,
    verdict_hash,
)
from evm_harness import (  # noqa: F401
    VULNERABLE_SOURCE,
    Pool,
    SolcMissing,
    accounts,
    attester,
    compile_source,
    deploy_pool,
    evm,
    keys,
    relay,
    sign,
)

CASE = "staged-exploit-vulnpool"
MAX_WINDOW = 3600
ROUNDS = 12
VICTIM_DEPOSIT = 5 * 10**18

WITHDRAWN_TOPIC = "0x" + keccak(text="Withdrawn(address,uint256)").hex()
FIXED_SOURCE = Path(__file__).resolve().parent / "contracts" / "FixedClaimPool.sol"


@pytest.fixture(scope="session")
def vulnerable_artifact():
    import evm_harness

    try:
        return compile_source(VULNERABLE_SOURCE)
    except SolcMissing as exc:
        evm_harness.SOLC_SKIPPED = str(exc)
        pytest.skip(str(exc))


@pytest.fixture(scope="session")
def fixed_artifact():
    import evm_harness

    try:
        return compile_source(FIXED_SOURCE)
    except SolcMissing as exc:
        evm_harness.SOLC_SKIPPED = str(exc)
        pytest.skip(str(exc))


def _deploy(tester, artifact, attesters, max_window=MAX_WINDOW, deployer=None):
    abi, bytecode = artifact
    return deploy_pool(tester, abi, bytecode, attesters, max_window, deployer=deployer)


def _attest(tester, pool, key, *, expires_at, case=CASE, verdict=CONFIRMED_EXPLOIT,
            finalized=True, target=None):
    digest = attestation_digest(
        tester.backend.chain.chain_id,
        pool.address,
        case,
        target or pool.address,
        verdict,
        finalized,
        expires_at,
    )
    return sign(digest, key)


# ------------------------------------------------------------------ the exploit


def test_claim_rewards_lets_a_zero_deposit_caller_take_the_pool(
    evm, vulnerable_artifact, accounts, attester
):
    """A real accounting bug: the budget is the pool's balance, not the caller's credit.

    12 payouts in one transaction, each emitting the same event — which is the receipt shape the
    live adjudication digests as `value=SMALL logs=MANY rep=<Withdrawn topic>`.
    """
    attester_addr, _ = attester
    victim, attacker = accounts[3], accounts[4]
    pool = _deploy(evm, vulnerable_artifact, [attester_addr])

    pool.expect_ok(victim, "deposit", value=VICTIM_DEPOSIT, gas=200_000)
    assert pool.call("deposits", victim) == VICTIM_DEPOSIT
    assert pool.call("deposits", attacker) == 0
    assert evm.get_balance(pool.address) == VICTIM_DEPOSIT

    before = evm.get_balance(attacker)
    receipt = pool.expect_ok(attacker, "claimRewards", ROUNDS, value=1, gas=600_000)

    # One log per payout, all the same topic: a direct transaction to the pool that a reader
    # (and the digest) can see paying the same address over and over.
    assert len(receipt["logs"]) == ROUNDS
    assert {log["topics"][0].lower() for log in receipt["logs"]} == {WITHDRAWN_TOPIC.lower()}
    assert all(to_checksum_address(log["address"]) == pool.address for log in receipt["logs"])

    slice_ = (VICTIM_DEPOSIT + 1) // ROUNDS
    paid = slice_ * ROUNDS
    # py-evm charges gas at its default price, so the attacker's delta is exact only to within
    # one transaction's fee. The pool's own balance is not gas-affected and is asserted exactly.
    after = evm.get_balance(attacker)
    assert before - 1 + paid - 10**15 <= after <= before - 1 + paid
    assert evm.get_balance(pool.address) == VICTIM_DEPOSIT + 1 - paid
    assert evm.get_balance(pool.address) < ROUNDS

    # The accounting lie that makes it a bug: the victim's credit was never touched.
    assert pool.call("deposits", victim) == VICTIM_DEPOSIT
    assert pool.call("withdrawals", victim) == 0


def test_the_credit_capped_path_refuses_the_same_attacker(
    evm, vulnerable_artifact, accounts, attester
):
    """Positive control for the refusal: the attacker cannot use `withdraw`, the victim can."""
    attester_addr, _ = attester
    victim, attacker = accounts[3], accounts[4]
    pool = _deploy(evm, vulnerable_artifact, [attester_addr])
    pool.expect_ok(victim, "deposit", value=VICTIM_DEPOSIT, gas=200_000)

    reason = pool.expect_revert("withdraw", 1, sender=attacker)
    assert "insufficient deposit" in reason

    before = evm.get_balance(victim)
    pool.expect_ok(victim, "withdraw", 10**18, gas=200_000)
    assert before + 10**18 - 10**15 <= evm.get_balance(victim) <= before + 10**18


def test_the_corrected_budget_does_not_pay_a_zero_deposit_caller(
    evm, fixed_artifact, accounts
):
    """The fix-free path: same loop, budget = deposits[msg.sender], effects before interactions.

    The attacker is refused; a genuine depositor is paid (positive control). This is the exact
    one-line difference from `VulnerableDemoPool.claimRewards`.
    """
    victim, attacker = accounts[3], accounts[4]
    abi, bytecode = fixed_artifact
    h = evm.send_transaction({"from": accounts[0], "data": "0x" + bytecode, "gas": 3_000_000})
    pool = Pool(evm, abi, evm.get_transaction_receipt(h)["contract_address"])
    pool.expect_ok(victim, "deposit", value=VICTIM_DEPOSIT, gas=200_000)

    reason = pool.expect_revert("claimRewards", ROUNDS, sender=attacker)
    assert "nothing to claim" in reason

    credit = pool.call("deposits", victim)
    expected = (credit // ROUNDS) * ROUNDS
    before = evm.get_balance(victim)
    receipt = pool.expect_ok(victim, "claimRewards", ROUNDS, gas=600_000)
    assert len(receipt["logs"]) == ROUNDS
    assert before + expected - 10**15 <= evm.get_balance(victim) <= before + expected
    assert pool.call("deposits", victim) == 0


def test_claim_rewards_refuses_zero_rounds_and_accepts_one(
    evm, vulnerable_artifact, accounts, attester
):
    """Both sides of the input bound, so the range check is tested rather than assumed."""
    attester_addr, _ = attester
    victim, attacker = accounts[3], accounts[4]
    pool = _deploy(evm, vulnerable_artifact, [attester_addr])
    pool.expect_ok(victim, "deposit", value=VICTIM_DEPOSIT, gas=200_000)

    reason = pool.expect_revert("claimRewards", 0, sender=attacker)
    assert "rounds out of range" in reason

    # Positive control: rounds=1 is inside the bound and pays the whole balance.
    pool.expect_ok(attacker, "claimRewards", 1, gas=200_000)
    assert evm.get_balance(pool.address) == 0


# ------------------------------------------------------------------ the freeze path


def test_freeze_stops_claim_rewards_and_unfreeze_restores_it(
    evm, vulnerable_artifact, accounts, attester
):
    """The freeze must protect the flawed path, not just deposit/withdraw.

    Positive control before the freeze, refusal while frozen, positive control after the owner
    lifts it (the owner can only shorten a window, never create one).
    """
    attester_addr, attester_key = attester
    owner = accounts[0]
    victim, attacker = accounts[3], accounts[4]
    pool = _deploy(evm, vulnerable_artifact, [attester_addr], deployer=owner)
    pool.expect_ok(victim, "deposit", value=VICTIM_DEPOSIT, gas=200_000)

    expires = pool.block_time + 600
    pool.expect_ok(
        accounts[5],
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        expires,
        _attest(evm, pool, attester_key, expires_at=expires),
        gas=300_000,
    )
    assert pool.call("isFrozen") is True
    assert pool.call("frozenUntil") == expires

    reason = pool.expect_revert("claimRewards", ROUNDS, sender=attacker)
    assert "paused" in reason
    reason = pool.expect_revert("deposit", sender=victim)
    assert "paused" in reason

    pool.expect_ok(owner, "unfreeze", "test over", gas=100_000)
    assert pool.call("isFrozen") is False
    pool.expect_ok(attacker, "claimRewards", 2, gas=200_000)


def test_wrong_attester_is_refused_and_the_real_one_accepted(
    evm, vulnerable_artifact, accounts, attester, keys
):
    attester_addr, attester_key = attester
    pool = _deploy(evm, vulnerable_artifact, [attester_addr])
    expires = pool.block_time + 600
    forged = _attest(evm, pool, keys[7], expires_at=expires)

    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        expires,
        forged,
    )
    assert "unknown attester" in reason
    assert pool.call("isFrozen") is False

    pool.expect_ok(
        accounts[5],
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        expires,
        _attest(evm, pool, attester_key, expires_at=expires),
        gas=300_000,
    )
    assert pool.call("frozenUntil") == expires


def test_a_verdict_that_is_not_confirmed_is_refused_but_confirmed_is_accepted(
    evm, vulnerable_artifact, accounts, attester
):
    attester_addr, attester_key = attester
    pool = _deploy(evm, vulnerable_artifact, [attester_addr])
    expires = pool.block_time + 600

    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        verdict_hash("FALSE_REPORT"),
        True,
        expires,
        _attest(evm, pool, attester_key, expires_at=expires, verdict="FALSE_REPORT"),
    )
    assert "verdict not confirmed" in reason

    pool.expect_ok(
        accounts[5],
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        expires,
        _attest(evm, pool, attester_key, expires_at=expires),
        gas=300_000,
    )
    assert pool.call("isFrozen") is True


def test_unfreeze_is_owner_only_with_the_owner_as_positive_control(
    evm, vulnerable_artifact, accounts, attester
):
    attester_addr, attester_key = attester
    owner = accounts[0]
    pool = _deploy(evm, vulnerable_artifact, [attester_addr], deployer=owner)
    expires = pool.block_time + 600
    pool.expect_ok(
        accounts[5],
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        expires,
        _attest(evm, pool, attester_key, expires_at=expires),
        gas=300_000,
    )

    reason = pool.expect_revert("unfreeze", "nope", sender=accounts[6])
    assert "not owner" in reason
    assert pool.call("isFrozen") is True

    pool.expect_ok(owner, "unfreeze", "owner clears", gas=100_000)
    assert pool.call("isFrozen") is False
    assert pool.call("frozenUntil") == 0


def test_expiry_beyond_max_window_is_refused_and_the_boundary_accepted(
    evm, vulnerable_artifact, accounts, attester
):
    attester_addr, attester_key = attester
    pool = _deploy(evm, vulnerable_artifact, [attester_addr])
    too_far = pool.block_time + MAX_WINDOW + 600

    reason = pool.expect_revert(
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        too_far,
        _attest(evm, pool, attester_key, expires_at=too_far),
    )
    assert "expiry beyond max window" in reason

    inside = pool.block_time + MAX_WINDOW - 60
    pool.expect_ok(
        accounts[5],
        "freezeFromAttestation",
        case_hash(CASE),
        VERDICT_HASH_CONFIRMED,
        True,
        inside,
        _attest(evm, pool, attester_key, expires_at=inside),
        gas=300_000,
    )
    assert pool.call("frozenUntil") == inside

"""The Python attester and the Solidity target must agree on the digest, byte for byte.

This is the load-bearing test for the whole attestation scheme. If the two sides disagree,
every attestation silently fails to verify and the failure looks like "unknown attester" --
indistinguishable from a wrong key, a wrong pool, or a tampered deadline. A cross-language
digest test is the only cheap way to tell those apart, and it is why `attestationDigest` is a
public view rather than an internal helper.

It caught a real bug during development. `HaltablePool` builds DOMAIN_SEPARATOR with
`abi.encode`, which pads `address` to a full 32-byte word; the attestation preimage uses
`abi.encodePacked`, which packs it as 20. The first Python implementation used 20 bytes in
both places and produced a perfectly well-formed digest that never matched.

WHAT THE SCHEME IS, EXACTLY
---------------------------
EIP-712-*style*, not the two-level EIP-712 construction. The preimage is a single flat
concatenation:

    0x19 0x01 | DOMAIN_SEPARATOR | ATTESTATION_TYPEHASH | caseId | address(this)
              | verdictHash | finalized(1 byte) | expiresAt

Standard EIP-712 would hash a struct first and then hash `0x1901 || domain || structHash`.
This collapses the struct into the outer preimage instead. That is safe here because every
field has a fixed width, so the concatenation is unambiguous -- and it is deliberate, because
the signer is our own tooling and never a wallet asked to render typed data. The consequence
to be honest about: a wallet signing this as EIP-712 typed data would produce a *different*
digest and the freeze would be rejected. Fail-closed, not exploitable, but not a claim this
code should make.
"""

import pytest
from eth_utils import keccak

from attestation import (  # noqa: F401
    ATTESTATION_TYPEHASH,
    CONFIRMED_EXPLOIT,
    VERDICT_HASH_CONFIRMED,
    attestation_digest,
    case_hash,
    domain_separator,
    verdict_hash,
)
from evm_harness import accounts, attester, evm, keys, pool_artifact  # noqa: F401

CASE = "live-drain-run2"
# Deliberately far outside any `maxWindow`: these tests only compute digests, they never
# submit a freeze, so the value is free to be recognisable.
EXPIRES = 4102444800


def _pool(evm, pool_artifact, attesters, max_window=3600):
    from evm_harness import deploy_pool

    abi, bytecode = pool_artifact
    return deploy_pool(evm, abi, bytecode, attesters, max_window)


@pytest.mark.parametrize("finalized", [True, False])
def test_python_digest_equals_solidity_digest(evm, pool_artifact, accounts, attester, finalized):
    """The exact assertion the whole scheme rests on."""
    pool = _pool(evm, pool_artifact, [attester[0]])
    chain_id = evm.backend.chain.chain_id

    solidity = pool.call(
        "attestationDigest", case_hash(CASE), VERDICT_HASH_CONFIRMED, finalized, EXPIRES
    )
    python = attestation_digest(
        chain_id, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, finalized, EXPIRES
    )

    assert solidity == python, (
        "Python and Solidity disagree on the attestation digest; every signature would "
        "fail to verify as 'unknown attester'"
    )


def test_digest_matches_a_hand_built_preimage(evm, pool_artifact, accounts, attester):
    """Pin the byte layout, so a change to it is a deliberate act rather than a surprise.

    Asserts the widths directly: `address` packed to 20 bytes, `bool` to 1, and the
    `0x19 0x01` marker present as two literal bytes rather than padded words. Getting any of
    these wrong still produces a valid-looking 32-byte digest, which is what makes the trap
    worth a test of its own.
    """
    pool = _pool(evm, pool_artifact, [attester[0]])
    chain_id = evm.backend.chain.chain_id
    dom = domain_separator(chain_id, pool.address)
    assert len(dom) == 32

    body = (
        ATTESTATION_TYPEHASH
        + case_hash(CASE)
        + bytes.fromhex(pool.address[2:])  # 20 packed bytes, NOT a 32-byte word
        + VERDICT_HASH_CONFIRMED
        + b"\x01"  # bool, 1 packed byte
        + EXPIRES.to_bytes(32, "big")
    )
    preimage = b"\x19\x01" + dom + body
    assert len(preimage) == 2 + 32 + 32 + 32 + 20 + 32 + 1 + 32 == 183

    assert pool.call(
        "attestationDigest", case_hash(CASE), VERDICT_HASH_CONFIRMED, True, EXPIRES
    ) == keccak(preimage)

    # The marker is two literal bytes, not two padded words. If `abi.encode` were used for
    # the prefix, the preimage would be 30 bytes longer and the digest would differ.
    padded_marker = b"\x19".rjust(32, b"\x00") + b"\x01".rjust(32, b"\x00")
    assert keccak(padded_marker + dom + body) != keccak(preimage)


def test_digest_is_bound_to_the_pool(evm, pool_artifact, accounts, attester):
    """Two pools on the same chain must not share a digest, or one attestation fits both."""
    one = _pool(evm, pool_artifact, [attester[0]])
    two = _pool(evm, pool_artifact, [attester[0]])
    assert one.address != two.address

    chain_id = evm.backend.chain.chain_id
    a = attestation_digest(chain_id, one.address, CASE, one.address, CONFIRMED_EXPLOIT, True, EXPIRES)
    b = attestation_digest(chain_id, two.address, CASE, two.address, CONFIRMED_EXPLOIT, True, EXPIRES)
    assert a != b, "verifyingContract must be inside the signed data"


def test_digest_is_bound_to_the_chain(evm, pool_artifact, accounts, attester):
    """A testnet signature must not be replayable on mainnet."""
    pool = _pool(evm, pool_artifact, [attester[0]])
    chain_id = evm.backend.chain.chain_id
    a = attestation_digest(chain_id, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, True, EXPIRES)
    b = attestation_digest(
        chain_id + 1, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, True, EXPIRES
    )
    assert a != b


def test_digest_is_bound_to_the_deadline(evm, pool_artifact, accounts, attester):
    pool = _pool(evm, pool_artifact, [attester[0]])
    chain_id = evm.backend.chain.chain_id
    a = attestation_digest(chain_id, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, True, EXPIRES)
    b = attestation_digest(
        chain_id, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, True, EXPIRES + 1
    )
    assert a != b, "changing the deadline must invalidate the signature"


def test_digest_is_bound_to_the_case(evm, pool_artifact, accounts, attester):
    """Two cases must not be able to share one attestation."""
    pool = _pool(evm, pool_artifact, [attester[0]])
    chain_id = evm.backend.chain.chain_id
    a = attestation_digest(chain_id, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, True, EXPIRES)
    b = attestation_digest(
        chain_id, pool.address, CASE + "-2", pool.address, CONFIRMED_EXPLOIT, True, EXPIRES
    )
    assert a != b


def test_digest_is_bound_to_the_verdict(evm, pool_artifact, accounts, attester):
    pool = _pool(evm, pool_artifact, [attester[0]])
    chain_id = evm.backend.chain.chain_id
    a = attestation_digest(chain_id, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, True, EXPIRES)
    b = attestation_digest(chain_id, pool.address, CASE, pool.address, "FALSE_REPORT", True, EXPIRES)
    assert a != b


def test_digest_is_bound_to_finalization(evm, pool_artifact, accounts, attester):
    pool = _pool(evm, pool_artifact, [attester[0]])
    chain_id = evm.backend.chain.chain_id
    a = attestation_digest(chain_id, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, True, EXPIRES)
    b = attestation_digest(chain_id, pool.address, CASE, pool.address, CONFIRMED_EXPLOIT, False, EXPIRES)
    assert a != b


def test_solidity_constants_match_python(evm, pool_artifact, accounts, attester):
    """Typehash and verdict hash are literals on both sides; drift would be silent."""
    pool = _pool(evm, pool_artifact, [attester[0]])
    assert pool.call("ATTESTATION_TYPEHASH") == ATTESTATION_TYPEHASH
    assert pool.call("VERDICT_CONFIRMED_EXPLOIT") == VERDICT_HASH_CONFIRMED
    assert verdict_hash("CONFIRMED_EXPLOIT") == VERDICT_HASH_CONFIRMED


def test_the_confirmed_verdict_hash_is_not_any_other_verdict(evm, pool_artifact, accounts, attester):
    """The one hash the target accepts must be the hash of exactly that one word."""
    pool = _pool(evm, pool_artifact, [attester[0]])
    confirmed = pool.call("VERDICT_CONFIRMED_EXPLOIT")
    for other in ("FALSE_REPORT", "INSUFFICIENT_EVIDENCE", "CONFIRMED_EXPLOIT ", "confirmed_exploit"):
        assert verdict_hash(other) != confirmed

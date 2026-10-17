"""EIP-712 attestation encoding, shared by the attester, the relay and the tests.

This module is deliberately dependency-light and key-free: it computes digests and encodes
payloads, and never reads a private key or opens a socket. That is what lets the hermetic
suite assert the Python digest is byte-identical to the one `HaltablePool` computes.

Byte-for-byte agreement with `demo-target/src/HaltablePool.sol` is the whole point of this
file, and it is checked rather than assumed -- see `tests/direct/test_attestation_digest.py`.
If you change one side, that test must be re-run and must still pass.

The Solidity side uses ``abi.encodePacked`` for the whole struct hash, so the widths here
are NOT the default ``abi.encode`` ones:

    bytes1  0x19
    bytes1  0x01
    bytes32 DOMAIN_SEPARATOR
    bytes32 ATTESTATION_TYPEHASH
    bytes32 caseId
    address target            -> 20 bytes packed, not 32
    bytes32 verdictHash
    bool    finalized         ->  1 byte packed, not 32
    uint256 expiresAt
"""

from __future__ import annotations

from datetime import datetime

from eth_account import Account
from eth_utils import keccak, to_checksum_address

DOMAIN_NAME = "CordonVerdictAttestation"
DOMAIN_VERSION = "1"

DOMAIN_TYPEHASH = keccak(
    text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)

ATTESTATION_TYPEHASH = keccak(
    text="Attestation(bytes32 caseId,address target,bytes32 verdictHash,bool finalized,uint256 expiresAt)"
)

CONFIRMED_EXPLOIT = "CONFIRMED_EXPLOIT"
VERDICT_HASH_CONFIRMED = keccak(text=CONFIRMED_EXPLOIT)


def case_hash(case_id: str) -> bytes:
    """GenLayer case id (arbitrary text) -> bytes32."""
    return keccak(text=case_id)


def verdict_hash(verdict: str) -> bytes:
    """Verdict enum string -> bytes32, matching keccak256(bytes(verdict)) in Solidity."""
    return keccak(text=verdict)


def _addr20(address: str) -> bytes:
    """Hex address -> exactly 20 bytes. Rejects anything that is not an address."""
    text = address.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if len(text) != 40:
        raise ValueError(f"not a 20-byte address: {address!r}")
    try:
        raw = bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(f"not hex: {address!r}") from exc
    return raw


def domain_separator(chain_id: int, verifying_contract: str) -> bytes:
    """EIP-712 domain separator for one chain and one pool.

    NOTE the width trap, which cost real debugging time. Solidity's `HaltablePool` builds this
    with `abi.encode`, which pads `address` to a FULL 32-BYTE WORD. The attestation digest
    below uses `abi.encodePacked`, which packs it as 20 bytes. The two must not be confused:
    using 20 bytes here produces a well-formed digest that simply never matches the contract.
    `tests/direct/test_attestation_digest.py` is what caught this.
    """
    return keccak(
        DOMAIN_TYPEHASH
        + keccak(text=DOMAIN_NAME)
        + keccak(text=DOMAIN_VERSION)
        + int(chain_id).to_bytes(32, "big")
        + _addr20(verifying_contract).rjust(32, b"\x00")  # abi.encode -> 32-byte word
    )


def attestation_digest(
    chain_id: int,
    verifying_contract: str,
    case_id: str,
    target: str,
    verdict: str,
    finalized: bool,
    expires_at: int,
) -> bytes:
    """Full EIP-712 digest. Mirrors `HaltablePool.attestationDigest` exactly.

    `verifying_contract` and `target` are passed separately on purpose: the contract bakes
    its own address in as `verifyingContract`, so an attestation minted for a different pool
    produces a different digest and `ecrecover` returns a meaningless address. That is why a
    wrong-pool attestation surfaces as "unknown attester" and not as a target-specific error.
    """
    return keccak(
        b"\x19\x01"
        + domain_separator(chain_id, verifying_contract)
        + ATTESTATION_TYPEHASH
        + case_hash(case_id)
        + _addr20(target)
        + verdict_hash(verdict)
        + (b"\x01" if finalized else b"\x00")
        + int(expires_at).to_bytes(32, "big")
    )


# Half the secp256k1 group order. `HaltablePool._recover` rejects anything above it.
SECP256K1_HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0


def recover_signer(digest: bytes, signature: bytes) -> str | None:
    """Recover the signer, applying EXACTLY the contract's acceptance rules.

    `HaltablePool._recover` returns address(0) -- which then fails the attester check -- for a
    signature that is not exactly 65 bytes, whose `s` is in the upper half of the curve order,
    or whose `v` is not 27/28. `ecrecover` itself accepts more than that, and a signature in
    the upper half has a second, equally valid encoding.

    Reproducing the strictness here matters because the relay reports the reason. A relay that
    used bare `ecrecover` would clear a malleable signature as "signed by the attester" and
    then watch the pool reject it with a generic error -- the relay's own verdict disagreeing
    with the chain's, which is the defect class this repo keeps hitting. Returns `None` when the
    signature would not be accepted.
    """
    if len(signature) != 65:
        return None
    if int.from_bytes(signature[32:64], "big") > SECP256K1_HALF_N:
        return None
    if signature[64] not in (27, 28):
        return None
    try:
        return Account._recover_hash(digest, signature=signature)
    except Exception:  # noqa: BLE001  -- invalid point, etc: not a signer, by definition
        return None


def normalize_address(value: str) -> str:
    """Lowercase hex address for EQUALITY CHECKS ONLY. Raises on malformed input.

    Do not use this to build a transaction. `eth_account` refuses to sign a lowercase `to`
    ("Transaction had invalid fields"), while a chain-level `eth_call` is happy with it -- so
    mixing the two uses produces code that reads fine and fails at signing time. See
    `checksum_address`.
    """
    return "0x" + _addr20(value).hex()


def checksum_address(value: str) -> str:
    """EIP-55 checksummed address, for anything that gets signed or sent."""
    return to_checksum_address(_addr20(value))


def iso_to_epoch(iso: str) -> int:
    """ISO-8601 UTC -> unix seconds.

    Must agree with `emergency_halt._epoch`, because this conversion is what turns the
    contract's recorded `expires_at` into the `expiresAt` an attester signs. If the two drifted,
    the signature would name a deadline the record does not -- exactly the "the relay chose a
    different deadline" failure this design is meant to make impossible. Asserted equal in
    `tests/direct/test_relay_attestation.py`.

    Handles the shape the contract emits (`2026-10-17T09:00:00Z`, second resolution), the
    sub-second shape a node may hand back, and an explicit numeric offset. Sub-second precision
    is truncated rather than rounded, for the same reason `_strip_us` truncates: agreement
    matters more than precision.

    ONE SHAPE IS REFUSED RATHER THAN TRUNCATED. `_strip_us` drops everything after the dot,
    which is right for `...:00.123Z` and WRONG for `...:00.123+02:00`: the offset goes with the
    fraction, the remainder is then read as UTC, and the instant silently shifts by two hours.
    The contract carries the same defect, and it cannot arise from a record because the contract
    only ever writes `...Z`. A signature over a deadline must never rest on a guess, so this
    refuses that shape and names the contract-side divergence instead of quietly disagreeing
    with it -- pinned by `test_iso_to_epoch_refuses_what_the_contract_would_silently_shift`.
    """
    text = iso.strip()
    head, sep, fraction = text.partition(".")
    if sep:
        rest = fraction.lstrip("0123456789")
        if rest and rest != "Z":
            raise ValueError(
                f"sub-second timestamp carrying an offset is not handled: {iso!r}. "
                f"emergency_halt._strip_us would discard {rest!r} together with the fraction "
                "and then treat what remains as UTC, moving the instant; refusing rather than "
                "signing a deadline the record may not mean."
            )
    if not (head.endswith("Z") or "+" in head):
        head += "Z"
    return int(datetime.fromisoformat(head.replace("Z", "+00:00")).timestamp())

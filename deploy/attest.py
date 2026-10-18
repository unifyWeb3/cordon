"""Attester: turn a finalized CONFIRMED_EXPLOIT record into a signed attestation.

WHY THIS IS A SEPARATE PROGRAM FROM THE RELAY
---------------------------------------------
This is the only program in the repo that holds an attester key. `freeze_watcher.py` holds
none: it re-reads the record, recomputes the digest, recovers the signer and only then
broadcasts. That split is the point. A relay that could mint an attestation would be the
unaccountable pause key again, just with extra steps.

WHAT IS SIGNED, AND WHY IT MATTERS
----------------------------------
The signature covers a fixed-width preimage that binds all of:

    caseId        which adjudication
    target        which pool
    verdictHash   must be keccak("CONFIRMED_EXPLOIT")
    finalized     must be true
    expiresAt     the exact recorded deadline, in seconds

plus the chain id and the target's own address inside DOMAIN_SEPARATOR. So the signature
cannot be replayed at another pool, on another chain, for another case, or with a different
deadline -- the target recomputes all of it, and the relay cannot substitute its own value
because the substituted value would break the signature.

WHAT THIS DOES *NOT* ESTABLISH
------------------------------
That GenLayer consensus happened. The attester trusts its own read of GenLayer storage. A
compromised attester can freeze for up to the pool's `MAX_WINDOW` with no exploit at all. The
change here is accountability and boundedness, not decentralisation -- see the trust note in
`docs/integration.md`.

REFUSALS
--------
`refusal_reason` is the gate. The one that is easy to miss is digest mode: in `digest` mode the
submitter supplies the transaction's `to` along with every other digest field, so the target
binding is NOT chain-enforced and an attestation would assert "this transaction touched this
pool" on the submitter's word alone. `jsonrpc` mode reads `to` from the chain inside the
nondeterministic block. This program therefore refuses to sign a digest-mode record at all.

Usage
-----
    python deploy/attest.py --case live-drain-run2 --out /tmp/opencode/attestation.json
    python deploy/attest.py --case live-drain-run2 --out -            # stdout, for inspection

Reads key names only: `CORDON_ATTESTER_PRIVATE_KEY`, `BASE_SEPOLIA_RPC_URL`. Never prints a
value from the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import requests  # noqa: E402
from eth_account import Account  # noqa: E402

from attestation import (  # noqa: E402
    CONFIRMED_EXPLOIT,
    VERDICT_HASH_CONFIRMED,
    attestation_digest,
    case_hash,
    iso_to_epoch,
    normalize_address,
)
from genlayer_read import GenLayerReadError, GenLayerReader, studionet_rpc_url  # noqa: E402

DEFAULT_HALT_ADDRESS = "0x95be4d883F89F28CF9cE986e1B400c8CB0808201"
DEFAULT_TARGET = "0x9e6c83C8ea2b6d15aBe38105484FDCD6BA91300e"

ATTESTER_KEY_ENV = "CORDON_ATTESTER_PRIVATE_KEY"

# The two modes the contract supports. See module docstring for why `digest` is refused.
CHAIN_ENFORCED_MODE = "jsonrpc"


class RefusedToSign(RuntimeError):
    """The record is not attestable. Never sign a partial or qualified version of it."""


def _address_or_none(value: str) -> str | None:
    """Normalised address, or `None` when the string is not one.

    `normalize_address` raises on a malformed value. That is right for a function whose caller
    has already decided the input is an address, and wrong here: this is the gate, and a gate
    that raises is a gate that reports "the tool is broken" when the correct answer is "this
    record is not attestable". Downstream, `attestation_digest` would raise the same way.
    """
    try:
        return normalize_address(value)
    except ValueError:
        return None


def target_chain_now(rpc_url: str, timeout: int = 30) -> int:
    """Block timestamp of the target chain, NOT the host clock.

    Base Sepolia's clock runs about 53 seconds ahead of the host this was developed on
    (`AGENTS.md`). A deadline judged against the host clock can therefore look valid here and
    be rejected by the pool, or the reverse -- and the failure is unreproducible by anyone who
    runs the code somewhere else.
    """
    response = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber", "params": ["latest", False]},
        timeout=timeout,
    )
    payload = response.json()
    if payload.get("error"):
        raise RefusedToSign(f"target chain unreadable: {json.dumps(payload['error'])}")
    block = payload.get("result")
    if not isinstance(block, dict) or "timestamp" not in block:
        raise RefusedToSign("target chain returned no latest block")
    return int(block["timestamp"], 16)


def refusal_reason(
    record: dict,
    claimed_target: str,
    *,
    now_epoch: int | None = None,
) -> str | None:
    """Why this record must not be signed. `None` means it is attestable.

    Pure function of the record, so the whole gate is testable without a network or a key.
    Order matters only for the quality of the message: the cheapest structural checks first.
    """
    if not isinstance(record, dict):
        return "record is not an object"

    mode = str(record.get("evidence_mode", "")).strip().lower()
    if mode != CHAIN_ENFORCED_MODE:
        return (
            f"evidence_mode={mode!r}: only {CHAIN_ENFORCED_MODE!r} reads the transaction "
            "destination from the chain. In digest mode the submitter supplies `to`, so the "
            "target binding is not chain-enforced and signing would assert it on the "
            "submitter's word alone."
        )

    if record.get("verdict") != CONFIRMED_EXPLOIT:
        return f"verdict is {record.get('verdict')!r}, not {CONFIRMED_EXPLOIT}"

    if not record.get("frozen"):
        return "record is not frozen"

    expires_at = str(record.get("expires_at") or "").strip()
    if not expires_at:
        return "record carries no expires_at"

    claim = _address_or_none(claimed_target)
    if claim is None:
        return f"{claimed_target!r} is not an address, so there is nothing to bind to"

    recorded_target = str(record.get("target") or "")
    recorded = _address_or_none(recorded_target)
    if recorded is None:
        return (
            f"record names target {recorded_target!r}, which is not an address; a signature "
            "must bind a real pool, not a claim about one"
        )
    if recorded != claim:
        return (
            f"record names target {recorded_target!r}, which is not the pool being attested "
            f"({claimed_target})"
        )

    evidence = record.get("evidence") or {}
    if not isinstance(evidence, dict):
        return "record has no evidence object"
    tx_to = str(evidence.get("tx_to") or "")
    if not tx_to:
        return "evidence records no transaction destination"
    went_to = _address_or_none(tx_to)
    if went_to is None:
        return (
            f"evidence records transaction destination {tx_to!r}, which is not an address, so "
            "the target binding cannot be checked"
        )
    if went_to != recorded:
        return (
            f"the fetched transaction went to {tx_to!r}, not to {claimed_target}: a "
            "CONFIRMED_EXPLOIT on a transaction that never called this pool is not evidence "
            "about this pool"
        )

    if now_epoch is not None:
        try:
            deadline = iso_to_epoch(expires_at)
        except ValueError as exc:
            return f"expires_at {expires_at!r} is not parseable: {exc}"
        if deadline <= now_epoch:
            return (
                f"the recorded window closed at {expires_at} ({deadline} <= {now_epoch} in "
                "target chain time); a signature over it could never be used"
            )

    return None


def build_attestation(
    record: dict,
    claimed_target: str,
    *,
    chain_id: int,
    verifying_contract: str,
    private_key: str,
    now_epoch: int | None = None,
) -> dict:
    """Record + key -> the attestation document `freeze_watcher.py` consumes.

    Raises `RefusedToSign` rather than returning a document with a caveat attached. An
    attestation that says "signed, but please check X" is one a relay will broadcast.
    """
    reason = refusal_reason(record, claimed_target, now_epoch=now_epoch)
    if reason:
        raise RefusedToSign(reason)

    case_id = str(record["case_id"])
    expires_at = str(record["expires_at"]).strip()
    try:
        expires_epoch = iso_to_epoch(expires_at)
    except ValueError as exc:
        # `refusal_reason` only parses the expiry when it is given a clock, so this is the path
        # that actually runs with `--skip-window-check`. Without it, an unparseable expiry
        # escapes as a ValueError traceback instead of a refusal -- and a refusal is what
        # `main` reports as "REFUSED to sign".
        raise RefusedToSign(f"expires_at {expires_at!r} is not parseable: {exc}") from exc

    digest = attestation_digest(
        chain_id,
        verifying_contract,
        case_id,
        claimed_target,
        CONFIRMED_EXPLOIT,
        True,
        expires_epoch,
    )
    signature = Account.unsafe_sign_hash(digest, private_key=private_key).signature

    return {
        "schema": "cordon-attestation/1",
        "case_id": case_id,
        "target": normalize_address(claimed_target),
        "verdict": CONFIRMED_EXPLOIT,
        "verdict_hash": "0x" + VERDICT_HASH_CONFIRMED.hex(),
        "finalized": True,
        "expires_at": expires_at,
        "expires_at_epoch": expires_epoch,
        "case_hash": "0x" + case_hash(case_id).hex(),
        "chain_id": int(chain_id),
        "verifying_contract": normalize_address(verifying_contract),
        "digest": "0x" + digest.hex(),
        "signature": "0x" + signature.hex(),
        "signer": Account.from_key(private_key).address,
        "evidence_mode": record["evidence_mode"],
        "evidence_signature": record.get("evidence_signature", ""),
        "tx_hash": record.get("tx_hash", ""),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def attest(
    *,
    halt_address: str,
    target: str,
    case_id: str,
    chain_id: int,
    rpc_url: str,
    private_key: str,
    now_epoch: int | None,
) -> dict:
    """Read the live record and attest it, or raise."""
    reader = GenLayerReader(rpc_url)
    record = reader.call(halt_address, "get_evidence", [case_id])
    if not isinstance(record, dict):
        raise GenLayerReadError(
            f"get_evidence returned {type(record).__name__}, not a record object"
        )
    return build_attestation(
        record,
        target,
        chain_id=chain_id,
        verifying_contract=target,
        private_key=private_key,
        now_epoch=now_epoch,
    )


def read_target_chain_id(rpc_url: str, timeout: int = 30) -> int:
    response = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []},
        timeout=timeout,
    )
    payload = response.json()
    if payload.get("error"):
        raise RefusedToSign(f"target chain unreadable: {json.dumps(payload['error'])}")
    return int(payload["result"], 16)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sign one adjudicated freeze.")
    ap.add_argument("--address", default=DEFAULT_HALT_ADDRESS, help="EmergencyHalt contract")
    ap.add_argument("--target", default=DEFAULT_TARGET, help="the pool being frozen")
    ap.add_argument("--case", required=True, help="case_id to attest")
    ap.add_argument("--rpc", default=None, help="GenLayer RPC (defaults to the SDK's Studionet)")
    ap.add_argument("--out", default="-", help="write the attestation here ('-' = stdout)")
    ap.add_argument(
        "--skip-window-check",
        action="store_true",
        help=(
            "do not consult the target chain's clock. Still needs BASE_SEPOLIA_RPC_URL, "
            "because the chain id is part of what gets signed -- this is not an offline mode"
        ),
    )
    args = ap.parse_args(argv)

    key = os.environ.get(ATTESTER_KEY_ENV)
    if not key:
        # Print the KEY NAME only. AGENTS.md: never echo a .env value.
        print(f"missing {ATTESTER_KEY_ENV}", file=sys.stderr)
        return 2

    rpc_url = args.rpc or studionet_rpc_url()
    now_epoch: int | None = None
    chain_id: int | None = None
    target_rpc = os.environ.get("BASE_SEPOLIA_RPC_URL")
    if not args.skip_window_check:
        if not target_rpc:
            # Print the KEY NAME only.
            print("missing BASE_SEPOLIA_RPC_URL (or pass --skip-window-check)", file=sys.stderr)
            return 2
        chain_id = read_target_chain_id(target_rpc)
        now_epoch = target_chain_now(target_rpc)

    if chain_id is None:
        if not target_rpc:
            print("missing BASE_SEPOLIA_RPC_URL (needed for the chain id)", file=sys.stderr)
            return 2
        chain_id = read_target_chain_id(target_rpc)

    try:
        document = attest(
            halt_address=args.address,
            target=args.target,
            case_id=args.case,
            chain_id=chain_id,
            rpc_url=rpc_url,
            private_key=key,
            now_epoch=now_epoch,
        )
    except RefusedToSign as exc:
        print(f"REFUSED to sign: {exc}", file=sys.stderr)
        return 3
    except GenLayerReadError as exc:
        print(f"could not read the record: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        print(text, end="")
    else:
        Path(args.out).write_text(text)
        # Summarise without echoing any environment value.
        print(f"attested {document['case_id']}")
        print(f"  target        : {document['target']}")
        print(f"  deadline      : {document['expires_at']} ({document['expires_at_epoch']})")
        print(f"  signer        : {document['signer']}")
        print(f"  evidence mode : {document['evidence_mode']} (chain-enforced)")
        print(f"  written to    : {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

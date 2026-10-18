"""Relay: broadcast a signed attestation to the EVM target.

WHAT THIS PROGRAM CAN AND CANNOT DO
-----------------------------------
It holds no attester key. Everything it needs to authorise a freeze comes from bytes it
re-read from GenLayer storage and a signature it did not produce:

1. read the record from GenLayer storage with NO account and NO key (`genlayer_read`)
2. refuse anything unattestable -- digest mode, a non-confirmed verdict, a closed window
3. recompute the EIP-712 digest from the freshly read record, using the record's own
   `expires_at` and the target chain's own id
4. recover the signer from the supplied signature and require it to be an expected attester

Only then does it broadcast. The relay's only power is paying gas and choosing *when*; it
cannot choose the pool, the verdict or the deadline. Change any of those and the signature
stops recovering to the attester, and the pool refuses the call.

WHY `client.read_contract` IS GONE
----------------------------------
The previous version read through `genlayer_py`'s client. `read_contract` raises unless an
account is connected, so reading PUBLIC state required a GenLayer key — the structural reason,
still true. On top of that, 0.18.0 reported an earlier deployment as not found at the correct
endpoint, correct chain and correct address while `genlayer-js` read it (twice; it did not
reproduce against the redeployment on 2026-10-17). This version encodes with the SDK and does
the transport itself over plain HTTPS, keyless. Both facts are in `state/MEMORY.md`.

VERIFY AGAINST THE TARGET, NEVER THE RETURN VALUE
-------------------------------------------------
The freeze is not reported as done because a transaction was sent. After it lands, the pool's
own `frozenUntil()` is read back and must equal the signed deadline exactly. A receipt with
status 1 only proves the call did not revert; it does not prove the deadline that was stored.

Usage
-----
    python deploy/freeze_watcher.py --case live-drain-run2 --attestation /tmp/opencode/attestation.json --dry-run
    python deploy/freeze_watcher.py --case live-drain-run2 --attestation /tmp/opencode/attestation.json

Reads key names only: `BASE_SEPOLIA_RPC_URL`, `BASE_SEPOLIA_PRIVATE_KEY`,
`CORDON_ATTESTER_ADDRESS`. Never prints a value from the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import requests  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_abi import encode as abi_encode  # noqa: E402
from eth_utils import keccak  # noqa: E402

from attestation import (  # noqa: E402
    CONFIRMED_EXPLOIT,
    VERDICT_HASH_CONFIRMED,
    attestation_digest,
    case_hash,
    checksum_address,
    iso_to_epoch,
    normalize_address,
    recover_signer,
)
from genlayer_read import GenLayerReadError, GenLayerReader, studionet_rpc_url  # noqa: E402

DEFAULT_HALT_ADDRESS = "0x95be4d883F89F28CF9cE986e1B400c8CB0808201"
ATTESTER_ADDRESS_ENV = "CORDON_ATTESTER_ADDRESS"

FREEZE_FROM_ATTESTATION_SIG = "freezeFromAttestation(bytes32,bytes32,bool,uint256,bytes)"
FROZEN_UNTIL_SIG = "frozenUntil()"
IS_FROZEN_SIG = "isFrozen()"

# Modes the contract can be in. Only `jsonrpc` reads the destination from the chain.
CHAIN_ENFORCED_MODE = "jsonrpc"

STATE = Path("/tmp/opencode/cordon-watcher-state.json")


class RefusedToBroadcast(RuntimeError):
    """The attestation does not describe what the chain currently says. Do not send."""


def _norm_or_refuse(value: str, what: str) -> str:
    """Normalised address, or a refusal.

    `normalize_address` raises `ValueError` on a malformed string, and `verify` is called from
    `main` inside a handler for `RefusedToBroadcast` only. So a malformed address in the record
    or -- more to the point -- in the *attestation file*, which is just a file an operator was
    handed, would escape as a ValueError traceback: the relay would look broken instead of
    saying "this attestation is not valid". A refusal path that crashes is not a refusal path.
    """
    try:
        return normalize_address(value)
    except ValueError as exc:
        raise RefusedToBroadcast(f"{what} is not an address: {value!r}") from exc


def selector(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


# Read-only calls are sent from the zero address explicitly. `eth_call` without `from` is
# standard-legal and works on most nodes, but not on all of them (py-evm rejects it outright:
# "Transaction is missing the required keys: 'from'"). Stating it costs nothing and removes a
# provider-dependent failure from the read path -- and the read path is the one that was
# already broken once. It is also, deliberately, not a key-bearing sender.
READ_FROM = "0x" + "00" * 20


class Evm:
    """Minimal read + broadcast client. No attester authority lives here."""

    def __init__(self, rpc: str, key: str) -> None:
        self.rpc = rpc
        self.account = Account.from_key(key)
        self.nonce = int(self._call("eth_getTransactionCount", [self.account.address, "latest"]), 16)

    def _call(self, method: str, params: list):
        """One JSON-RPC request. Every wire failure becomes a `RuntimeError` that names it.

        The common real-world failure is a wrong endpoint -- a stale value in the environment,
        a proxy, a captive portal answering with HTML -- and `requests` reports all of them as
        a JSONDecodeError, or as an AttributeError from `.get` on a non-dict body. Both escaped
        `main` as a traceback, which tells an operator nothing about which setting is wrong.
        """
        try:
            payload = requests.post(
                self.rpc,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=40,
            ).json()
        except requests.exceptions.JSONDecodeError as exc:
            # Must be caught BEFORE RequestException: requests' JSONDecodeError inherits from
            # BOTH ValueError and RequestException, so the transport branch would swallow it and
            # report a bad body as a network fault. The same trap was already fixed once in
            # genlayer_read.py; it was left standing here.
            raise RuntimeError(f"{method}: the endpoint did not answer with JSON: {exc}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"{method}: transport failure: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"{method}: the endpoint did not answer with JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"{method}: malformed JSON-RPC envelope ({type(payload).__name__})"
            )
        if payload.get("error"):
            raise RuntimeError(f"{method}: {payload['error']}")
        return payload.get("result")

    @property
    def chain_id(self) -> int:
        return int(self._call("eth_chainId", []), 16)

    @property
    def block_time(self) -> int:
        """Target chain time. NOT the host clock: Base Sepolia runs ~53 s ahead of it."""
        block = self._call("eth_getBlockByNumber", ["latest", False])
        if not isinstance(block, dict) or "timestamp" not in block:
            raise RuntimeError("target chain returned no latest block")
        return int(block["timestamp"], 16)

    def _read_uint(self, to: str, sig: str) -> int:
        out = self._call(
            "eth_call",
            [{"from": READ_FROM, "to": to, "data": "0x" + selector(sig)}, "latest"],
        )
        if not out or out == "0x":
            raise RuntimeError(f"{sig} returned nothing at {to}")
        return int(out, 16)

    def frozen_until(self, to: str) -> int:
        return self._read_uint(to, FROZEN_UNTIL_SIG)

    def is_frozen(self, to: str) -> bool:
        return self._read_uint(to, IS_FROZEN_SIG) == 1

    def send(self, to: str, sig: str, arg_types: list, args: list) -> str:
        data = "0x" + selector(sig) + abi_encode(arg_types, args).hex()
        tx = {
            "from": self.account.address,
            "to": to,
            "data": data,
            "nonce": hex(self.nonce),
            "value": "0x0",
            "chainId": self.chain_id,
            # Base is an OP-stack L2: legacy gasPrice is required alongside EIP-1559 fields,
            # and eth-account rejects the transaction outright without it. Learned the hard way
            # -- "Transaction must include these fields: {'gasPrice'}".
            "gasPrice": "0x3b9aca00",  # 1 gwei
        }
        tx["gas"] = self._call("eth_estimateGas", [tx])
        signed = self.account.sign_transaction(tx)
        raw = "0x" + bytes(signed.raw_transaction).hex()
        h = self._call("eth_sendRawTransaction", [raw])
        self.nonce += 1
        receipt = None
        for _ in range(40):
            receipt = self._call("eth_getTransactionReceipt", [h])
            if receipt:
                break
            time.sleep(1)
        if not receipt or int(receipt["status"], 16) != 1:
            raise RuntimeError(
                f"{sig} reverted on target (tx {h}): {(receipt or {}).get('revertReason')}"
            )
        return h


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except ValueError:
            pass
    return {"applied": []}


def verify(
    record: dict,
    document: dict,
    *,
    claimed_target: str,
    chain_id: int,
    expected_attesters: list[str],
    now_epoch: int,
) -> dict:
    """Re-derive the whole attestation from the record. Raise if anything disagrees.

    Every check here re-reads rather than trusts. The document's own `digest` and `signer`
    fields are treated as claims to be confirmed, and the *record* -- freshly fetched from
    GenLayer storage in this process -- is what the digest is rebuilt from.
    """
    if not isinstance(record, dict):
        raise RefusedToBroadcast("record is not an object")

    # --- the record must be attestable at all (same gate the attester applies)
    mode = str(record.get("evidence_mode", "")).strip().lower()
    if mode != CHAIN_ENFORCED_MODE:
        raise RefusedToBroadcast(
            f"evidence_mode={mode!r}: only {CHAIN_ENFORCED_MODE!r} reads the transaction "
            "destination from the chain, so the target binding is not chain-enforced"
        )
    if record.get("verdict") != CONFIRMED_EXPLOIT:
        raise RefusedToBroadcast(f"verdict is {record.get('verdict')!r}")
    if not record.get("frozen"):
        raise RefusedToBroadcast("record is not frozen")

    recorded_target = _norm_or_refuse(
        str(record.get("target") or ""), "the record's target"
    )
    claim = _norm_or_refuse(claimed_target, "--target")
    if recorded_target != claim:
        raise RefusedToBroadcast(
            f"record names target {record.get('target')!r}, but this run is for {claimed_target}"
        )

    evidence = record.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise RefusedToBroadcast("record has no evidence object")
    tx_to = str(evidence.get("tx_to") or "")
    if not tx_to:
        raise RefusedToBroadcast("evidence records no transaction destination")
    if _norm_or_refuse(tx_to, "the record's evidence.tx_to") != recorded_target:
        raise RefusedToBroadcast(
            f"the fetched transaction went to {tx_to}, not to the recorded target "
            f"{record.get('target')}: not evidence about this pool"
        )

    # --- the document must agree with the record
    if str(document.get("schema", "")) != "cordon-attestation/1":
        raise RefusedToBroadcast(f"unsupported attestation schema {document.get('schema')!r}")
    if str(document.get("case_id")) != str(record.get("case_id")):
        raise RefusedToBroadcast(
            f"attestation is for case {document.get('case_id')!r}, record is "
            f"{record.get('case_id')!r}"
        )
    if _norm_or_refuse(str(document.get("target", "")), "the attestation's target") != recorded_target:
        raise RefusedToBroadcast("attestation names a different target than the record")
    if document.get("verdict") != CONFIRMED_EXPLOIT or document.get("finalized") is not True:
        raise RefusedToBroadcast("attestation does not state a finalized CONFIRMED_EXPLOIT")

    expires_at = str(record.get("expires_at") or "").strip()
    if not expires_at:
        raise RefusedToBroadcast("record carries no expires_at")
    deadline = iso_to_epoch(expires_at)
    if int(document.get("expires_at_epoch", -1)) != deadline:
        raise RefusedToBroadcast(
            f"attestation is signed for {document.get('expires_at_epoch')} but the record "
            f"expires at {deadline} ({expires_at})"
        )

    # --- rebuild the digest from the record, not from the document
    digest = attestation_digest(
        chain_id,
        claimed_target,
        str(record["case_id"]),
        claimed_target,
        CONFIRMED_EXPLOIT,
        True,
        deadline,
    )
    if document.get("digest") and str(document["digest"]).lower() != "0x" + digest.hex():
        raise RefusedToBroadcast("attestation carries a digest that does not match the record")

    signature_hex = str(document.get("signature", ""))
    if not signature_hex.startswith("0x") or len(signature_hex) != 132:
        raise RefusedToBroadcast("attestation carries no well-formed 65-byte signature")
    signature = bytes.fromhex(signature_hex[2:])

    signer = recover_signer(digest, signature)
    if signer is None:
        raise RefusedToBroadcast(
            "signature is not acceptable: wrong length, non-canonical `s`, or v outside "
            "{27,28} -- the pool would reject it too"
        )
    if document.get("signer") and _norm_or_refuse(
        str(document["signer"]), "the attestation's signer"
    ) != normalize_address(signer):
        raise RefusedToBroadcast(
            f"attestation claims signer {document.get('signer')} but the signature recovers "
            f"to {signer}"
        )
    expected = {_norm_or_refuse(a, "a configured attester") for a in expected_attesters if a}
    if not expected:
        raise RefusedToBroadcast(
            f"no expected attester configured -- set {ATTESTER_ADDRESS_ENV} or pass --attester"
        )
    if normalize_address(signer) not in expected:
        raise RefusedToBroadcast(
            f"signature recovers to {signer}, which is not a configured attester; the pool "
            "would reject this as 'unknown attester'"
        )

    if deadline <= now_epoch:
        raise RefusedToBroadcast(
            f"the signed window closed at {expires_at} ({deadline} <= {now_epoch} in target "
            "chain time); the pool would reject it as 'window already closed'"
        )

    return {
        "case_id": str(record["case_id"]),
        # Checksummed, not lowercased: this value is what the relay signs and sends, and
        # eth-account rejects a lowercase `to` at signing time. Comparisons elsewhere use
        # `normalize_address`.
        "target": checksum_address(claimed_target),
        "deadline": deadline,
        "expires_at": expires_at,
        "signer": signer,
        "signature": signature,
        "case_hash": case_hash(str(record["case_id"])),
        "digest": digest,
    }


def broadcast(evm: Evm, verified: dict, *, dry_run: bool) -> str | None:
    """Send the freeze, then confirm it from the pool's own storage."""
    print(f"  freezeFromAttestation({verified['deadline']}) ...")
    if dry_run:
        print("  DRY RUN: not sending")
        return None

    tx = evm.send(
        verified["target"],
        FREEZE_FROM_ATTESTATION_SIG,
        ["bytes32", "bytes32", "bool", "uint256", "bytes"],
        [
            verified["case_hash"],
            VERDICT_HASH_CONFIRMED,
            True,
            verified["deadline"],
            verified["signature"],
        ],
    )
    print(f"  tx            : {tx}")

    # Verify against the target, never the return value. A status-1 receipt only proves the
    # call did not revert; it does not prove which deadline was stored.
    stored = evm.frozen_until(verified["target"])
    if stored != verified["deadline"]:
        raise RefusedToBroadcast(
            f"target reports frozenUntil={stored} but the signed deadline was "
            f"{verified['deadline']}: the freeze is NOT what was attested"
        )
    print(f"  frozenUntil   : {stored} (== signed deadline, read back from the pool)")
    print(f"  isFrozen      : {evm.is_frozen(verified['target'])}")
    return tx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Relay one signed freeze to the EVM target.")
    ap.add_argument("--address", default=DEFAULT_HALT_ADDRESS, help="EmergencyHalt contract")
    ap.add_argument("--target", required=True, help="the pool being frozen")
    ap.add_argument("--case", required=True, help="case_id to relay")
    ap.add_argument("--attestation", required=True, help="attestation JSON from deploy/attest.py")
    ap.add_argument("--attester", action="append", default=[], help="expected attester address")
    ap.add_argument("--rpc", default=None, help="GenLayer RPC (defaults to the SDK's Studionet)")
    ap.add_argument("--dry-run", action="store_true", help="verify and report, never send")
    args = ap.parse_args(argv)

    key = os.environ.get("BASE_SEPOLIA_PRIVATE_KEY")
    evm_rpc = os.environ.get("BASE_SEPOLIA_RPC_URL")
    if not key or not evm_rpc:
        # Print KEY NAMES only. AGENTS.md: never echo a .env value.
        missing = [
            n
            for n, v in (
                ("BASE_SEPOLIA_PRIVATE_KEY", key),
                ("BASE_SEPOLIA_RPC_URL", evm_rpc),
            )
            if not v
        ]
        print(f"missing {', '.join(missing)}", file=sys.stderr)
        return 2

    expected = list(args.attester)
    if os.environ.get(ATTESTER_ADDRESS_ENV):
        expected.append(os.environ[ATTESTER_ADDRESS_ENV])
    if not expected:
        print(
            f"no expected attester: pass --attester or set {ATTESTER_ADDRESS_ENV}",
            file=sys.stderr,
        )
        return 2

    document = json.loads(Path(args.attestation).read_text())

    # The whole pre-flight reads the target chain, so any of it can fail on a bad endpoint. It
    # is reported rather than raised: an operator debugging a traceback cannot tell a wrong URL
    # from a wrong key from a chain that is down.
    try:
        evm = Evm(evm_rpc, key)
    except ValueError as exc:
        print(f"BASE_SEPOLIA_PRIVATE_KEY is not a usable key: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"target chain unusable: {exc}", file=sys.stderr)
        return 2

    try:
        chain_id = evm.chain_id
        already_frozen = evm.is_frozen(args.target)
        current_until = evm.frozen_until(args.target)
    except RuntimeError as exc:
        print(f"target chain unusable: {exc}", file=sys.stderr)
        return 2

    print(f"halt contract : {args.address}")
    print(f"target        : {args.target}")
    print(f"target chain  : {chain_id}")
    print(f"target frozen : {already_frozen} (frozenUntil={current_until})")
    print(f"mode          : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    reader = GenLayerReader(args.rpc or studionet_rpc_url())
    try:
        record = reader.call(args.address, "get_evidence", [args.case])
    except GenLayerReadError as exc:
        print(f"{args.case}: UNREADABLE -- {exc}", file=sys.stderr)
        print(
            "  (not 'no such case'. The Python SDK is known to report a live contract as "
            "missing -- state/MEMORY.md.)",
            file=sys.stderr,
        )
        return 2

    try:
        chain_time = evm.block_time
    except RuntimeError as exc:
        print(f"target chain unusable: {exc}", file=sys.stderr)
        return 2

    try:
        verified = verify(
            record,
            document,
            claimed_target=args.target,
            chain_id=chain_id,
            expected_attesters=expected,
            now_epoch=chain_time,
        )
    except RefusedToBroadcast as exc:
        print(f"{args.case}: REFUSED -- {exc}", file=sys.stderr)
        return 3

    print(f"case          : {verified['case_id']}")
    print(f"  verdict     : {record.get('verdict')}")
    print(f"  deadline    : {verified['expires_at']} ({verified['deadline']})")
    print(f"  tx_to       : {(record.get('evidence') or {}).get('tx_to')}")
    print(f"  signer      : {verified['signer']} (verified against the record, not the file)")
    print(f"  digest      : 0x{verified['digest'].hex()}")

    state = load_state()
    idempotency_key = f"{verified['case_id']}:{verified['deadline']}"
    if idempotency_key in state["applied"]:
        print(f"  already applied at this deadline ({idempotency_key}) -> nothing to do")
        return 0

    try:
        tx = broadcast(evm, verified, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if tx:
        state["applied"].append(idempotency_key)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

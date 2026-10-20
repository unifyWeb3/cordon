"""Live negative controls for the freeze path, as commands a reviewer can re-run.

There are three controls in the design, and this program covers the two that are executable
without a live `CONFIRMED_EXPLOIT` record:

* `wrong-pool` — sign an attestation that names a DIFFERENT pool, then send it to the real pool.
  The pool bakes its own address into `DOMAIN_SEPARATOR`, so the digest it computes is not the one
  that was signed; `ecrecover` yields a meaningless address and the call must revert
  `unknown attester`. This is the control that shows a signature is bound to one pool, and it does
  not need any verdict, because it fails before the attester check can succeed anyway.
* `replay` — re-send an attestation that has already been applied. On the same deadline the pool
  accepts it idempotently; with a later deadline it must revert `cannot extend a live freeze`.
  **This one needs a live freeze, so it cannot run until a real CONFIRMED_EXPLOIT has been
  relayed.** The command is here so the control is repeatable when that day comes.

Every send is a real transaction; `--dry-run` does the same call as `eth_call` and sends nothing.
Nothing here signs a false statement: `wrong-pool` signs a statement about a *decoy* pool, which
is exactly what the control is testing, and `replay` re-sends a statement that was already true.
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

from eth_account import Account  # noqa: E402
from eth_abi import encode  # noqa: E402
from eth_utils import keccak, to_checksum_address  # noqa: E402

import attestation as A  # noqa: E402
from deploy_target import Rpc  # noqa: E402

FREEZE_SIG = "freezeFromAttestation(bytes32,bytes32,bool,uint256,bytes)"


def calldata(case_id: str, expires_at: int, signature: bytes, verdict: str = "CONFIRMED_EXPLOIT") -> str:
    args = encode(
        ["bytes32", "bytes32", "bool", "uint256", "bytes"],
        [A.case_hash(case_id), A.verdict_hash(verdict), True, expires_at, signature],
    )
    return "0x" + (keccak(text=FREEZE_SIG)[:4] + args).hex()


def read_state(rpc: Rpc, pool: str, block: str = "latest") -> dict:
    return {
        "frozenUntil": rpc.read_uint(pool, "frozenUntil()", block=block),
        "isFrozen": rpc.read_uint(pool, "isFrozen()", block=block),
        "freezeCaseId": rpc.call_contract(pool, "freezeCaseId()", block=block),
    }


def retry(fn, tries: int = 6, delay: float = 3.0):
    """A public load-balanced endpoint may not have the block a receipt names yet."""
    last = None
    for _ in range(tries):
        try:
            return fn()
        except RuntimeError as exc:
            last = exc
            time.sleep(delay)
    raise RuntimeError(f"gave up after {tries} tries: {last}")


def send(rpc: Rpc, account, pool: str, data: str) -> dict:
    tx = {
        "from": account.address,
        "to": pool,
        "value": "0x0",
        "data": data,
        "nonce": hex(rpc.nonce(account.address)),
        "chainId": rpc.chain_id(),
        "gasPrice": hex(rpc.gas_price()),
        "gas": hex(400_000),
    }
    signed = account.sign_transaction(tx)
    tx_hash = "0x" + bytes(signed.hash).hex()
    print(f"  sent {tx_hash} (nonce {int(tx['nonce'], 16)})", flush=True)
    sent = rpc.send_raw("0x" + bytes(signed.raw_transaction).hex())
    if sent.lower() != tx_hash.lower():
        raise RuntimeError(f"node returned {sent!r} for {tx_hash}")
    receipt = rpc.receipt(tx_hash)
    return {
        "tx": tx_hash,
        "block": receipt["blockNumber"],
        "status": receipt["status"],
        "gasUsed": int(receipt["gasUsed"], 16),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="live negative controls for the attested freeze")
    ap.add_argument("control", choices=["wrong-pool", "replay"])
    ap.add_argument("--pool", required=True)
    ap.add_argument("--case", default="control-wrong-pool")
    ap.add_argument("--decoy", default="0x000000000000000000000000000000000000dEaD")
    ap.add_argument("--attestation", default="", help="attestation JSON for `replay`")
    ap.add_argument("--expires-at", type=int, default=0, help="override the replay deadline")
    ap.add_argument("--dry-run", action="store_true", help="eth_call only; send nothing")
    ap.add_argument("--out", default="", help="write the observed result here")
    args = ap.parse_args(argv)

    rpc = Rpc(os.environ["BASE_SEPOLIA_RPC_URL"])
    account = Account.from_key(os.environ["BASE_SEPOLIA_PRIVATE_KEY"])
    attester = Account.from_key(os.environ["CORDON_ATTESTER_PRIVATE_KEY"])
    pool = to_checksum_address(args.pool)
    block = rpc.call("eth_getBlockByNumber", ["latest", False])
    chain_now = int(block["timestamp"], 16)
    result: dict = {"control": args.control, "pool": pool, "chain_now": chain_now}

    if args.control == "wrong-pool":
        decoy = to_checksum_address(args.decoy)
        expires = chain_now + 900
        digest = A.attestation_digest(
            chain_id=rpc.chain_id(),
            verifying_contract=decoy,
            case_id=args.case,
            target=decoy,
            verdict="CONFIRMED_EXPLOIT",
            finalized=True,
            expires_at=expires,
        )
        signature = bytes(Account.unsafe_sign_hash(digest, private_key=attester.key).signature)
        result.update(
            {
                "decoy": decoy,
                "expiresAt": expires,
                "signer": attester.address,
                "signed_digest": "0x" + digest.hex(),
                "signed_for": "a different pool (the decoy)",
            }
        )
        pool_digest_call = "0x" + (
            keccak(text="attestationDigest(bytes32,bytes32,bool,uint256)")[:4]
            + encode(
                ["bytes32", "bytes32", "bool", "uint256"],
                [A.case_hash(args.case), A.verdict_hash("CONFIRMED_EXPLOIT"), True, expires],
            )
        ).hex()
        pool_digest = rpc.call("eth_call", [{"to": pool, "data": pool_digest_call}, "latest"])
        result["pool_computed_digest"] = pool_digest
        result["digests_differ"] = pool_digest.lower() != ("0x" + digest.hex())
        result["recovered_against_pool"] = A.recover_signer(bytes.fromhex(pool_digest[2:]), signature)
        result["attester"] = attester.address
        data = calldata(args.case, expires, signature)
    else:
        if not args.attestation:
            raise SystemExit("`replay` needs --attestation from deploy/attest.py")
        doc = json.loads(Path(args.attestation).read_text())
        signature = bytes.fromhex(doc["signature"][2:])
        expires = args.expires_at or int(doc["expiresAt"])
        result["case"] = doc.get("caseId")
        result["expiresAt"] = expires
        data = calldata(doc["caseId"], expires, signature)

    before = read_state(rpc, pool)
    result["state_before"] = before
    try:
        call = rpc.call("eth_call", [{"from": account.address, "to": pool, "data": data}, "latest"])
        result["eth_call"] = call if isinstance(call, str) else "no result"
    except RuntimeError as exc:
        # A revert is the expected answer for these controls, not a failure of the harness.
        result["eth_call"] = f"reverted: {exc}"
        result["eth_call_reverted"] = True

    if not args.dry_run:
        result["transaction"] = send(rpc, account, pool, data)
        block = result["transaction"]["block"]
        try:
            result["state_after"] = retry(lambda: read_state(rpc, pool, block))
        except RuntimeError as exc:
            result["state_after"] = f"unreadable at {block}: {exc}"
            result["state_latest_after"] = read_state(rpc, pool)
    else:
        result["transaction"] = "dry run: not sent"

    print(json.dumps(result, indent=2, sort_keys=True))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

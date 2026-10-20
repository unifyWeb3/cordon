"""Staged drain of our own Base Sepolia demo pool — the exploit side of the live lifecycle.

THIS IS NOT A REAL EXPLOIT AND MUST NEVER BE PRESENTED AS ONE. It moves funds through the pool's
own public entry points (`deposit()` / `withdraw(uint256)`) from a key we control, on a testnet
pool we deployed, so that the adjudicator has a real transaction to judge and the relay has a real
verdict to carry. The claim submitted with it says exactly that.

Why two modes:

* `plain` — the only drain this contract's own functions allow: the sole depositor withdraws its
  own deposit in one transaction, so the pool's balance goes to zero. Fully authorised; the
  receipt looks like an ordinary withdrawal (value band ZERO, one `Withdrawn` log).
* `harness` — the same authorised withdrawal, but routed through `DrainHarness.sol`, which
  forwards the proceeds to several sinks and emits one event per hop. That is the *shape* a drain
  takes in the evidence digest (`repeated_selectors` non-empty), and it exists because an ETH pool
  emits only one event per withdrawal, so the plain mode can never carry that signature.

Both modes are labelled as staged everywhere they surface: in the case id, in the claim, in the
transcript. Nothing here writes contract state by any route other than the pool's real functions.

    python deploy/staged_drain.py plain --pool 0x... --amount-wei 200000000000000
    python deploy/staged_drain.py harness --pool 0x... --amount-wei 200000000000000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from eth_account import Account  # noqa: E402
from eth_abi import encode  # noqa: E402
from eth_utils import keccak, to_checksum_address  # noqa: E402

import deploy_target  # noqa: E402
from deploy_target import Rpc, selector  # noqa: E402


def call_data(signature: str, args: list) -> str:
    inner = signature[signature.index("(") + 1 : -1].strip()
    types = [t.strip() for t in inner.split(",")] if inner else []
    return "0x" + (keccak(text=signature)[:4] + encode(types, args)).hex()


def send(rpc: Rpc, account, to: str, data: str, value: int, gas: int, label: str) -> dict:
    tx = {
        "from": account.address,
        "to": to,
        "value": hex(value),
        "data": data,
        "nonce": hex(rpc.nonce(account.address)),
        "chainId": rpc.chain_id(),
        "gasPrice": hex(rpc.gas_price()),
        "gas": hex(gas),
    }
    signed = account.sign_transaction(tx)
    tx_hash = "0x" + bytes(signed.hash).hex()
    print(f"  {label:<18} tx {tx_hash}  (nonce {int(tx['nonce'], 16)}, value {value})")
    sent = rpc.send_raw("0x" + bytes(signed.raw_transaction).hex())
    if not isinstance(sent, str) or sent.lower() != tx_hash.lower():
        raise RuntimeError(f"the node returned {sent!r} for signed tx {tx_hash}; not believing it")
    receipt = rpc.receipt(tx_hash)
    ok = int(receipt["status"], 16) == 1
    print(f"  {'':<18}    status {receipt['status']}  block {receipt['blockNumber']}"
          f" ({int(receipt['blockNumber'], 16)})  gasUsed {int(receipt['gasUsed'], 16)}")
    if not ok:
        raise RuntimeError(f"{label} reverted on chain ({tx_hash})")
    return {"label": label, "tx": tx_hash, "block": receipt["blockNumber"], "gasUsed": int(receipt["gasUsed"], 16)}


def deploy_harness(rpc: Rpc, account, pool: str, sinks: list[str], out: Path) -> str:
    _abi, bytecode = deploy_target.compile_source(
        ROOT / "demo-target" / "src" / "DrainHarness.sol", "DrainHarness"
    )
    data = "0x" + bytecode + encode(["address", "address[]"], [pool, sinks]).hex()
    tx = {
        "from": account.address,
        "value": "0x0",
        "data": data,
        "nonce": hex(rpc.nonce(account.address)),
        "chainId": rpc.chain_id(),
        "gasPrice": hex(rpc.gas_price()),
    }
    tx["gas"] = hex(int(rpc.call("eth_estimateGas", [tx]), 16) * 5 // 4)
    signed = account.sign_transaction(tx)
    tx_hash = "0x" + bytes(signed.hash).hex()
    print(f"  harness deploy     tx {tx_hash}")
    rpc.send_raw("0x" + bytes(signed.raw_transaction).hex())
    receipt = rpc.receipt(tx_hash)
    if int(receipt["status"], 16) != 1 or not receipt.get("contractAddress"):
        raise RuntimeError(f"harness deployment failed: {receipt}")
    address = to_checksum_address(receipt["contractAddress"])
    record = {"pool": pool, "sinks": sinks, "harness": address, "tx": tx_hash,
              "block": receipt["blockNumber"], "gasUsed": int(receipt["gasUsed"], 16)}
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"  harness            {address}  block {receipt['blockNumber']}")
    return address


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="staged drain of our own demo pool (test-only)")
    ap.add_argument("mode", choices=["plain", "harness"])
    ap.add_argument("--pool", required=True)
    ap.add_argument("--amount-wei", type=int, required=True)
    ap.add_argument("--sinks", default="", help="comma-separated forward addresses (harness mode)")
    ap.add_argument("--out", default=str(ROOT / "deploy" / "out" / "staged-drain.json"))
    ap.add_argument(
        "--existing-deposit-tx",
        default="",
        help="a deposit already mined by a previous run of this script; recorded, not repeated",
    )
    args = ap.parse_args(argv)

    rpc = Rpc(os.environ["BASE_SEPOLIA_RPC_URL"])
    account = Account.from_key(os.environ["BASE_SEPOLIA_PRIVATE_KEY"])
    pool = to_checksum_address(args.pool)
    out = Path(args.out)
    run: dict = {"pool": pool, "mode": args.mode, "actor": account.address, "transactions": []}

    if args.mode == "plain":
        # deposit(): the pool credits msg.sender, then withdraw(all) pays it back and empties the pool.
        if args.existing_deposit_tx:
            receipt = rpc.receipt(args.existing_deposit_tx)
            run["transactions"].append(
                {
                    "label": "deposit",
                    "tx": args.existing_deposit_tx,
                    "block": receipt["blockNumber"],
                    "gasUsed": int(receipt["gasUsed"], 16),
                    "reused": True,
                }
            )
        else:
            run["transactions"].append(
                send(rpc, account, pool, call_data("deposit()", []), args.amount_wei, 120_000, "deposit")
            )
        before = rpc.read_uint(pool, "deposits(address)", [account.address])
        print(f"  deposits(actor)    {before}")
        run["transactions"].append(
            send(rpc, account, pool, call_data("withdraw(uint256)", [before]), 0, 150_000, "withdraw-all")
        )
        run["drained_wei"] = before
    else:
        sinks = [to_checksum_address(s) for s in args.sinks.split(",") if s.strip()]
        if not sinks:
            raise SystemExit("harness mode needs --sinks")
        harness = deploy_harness(rpc, account, pool, sinks, out.with_name("drain-harness.json"))
        run["harness"] = harness
        run["sinks"] = sinks
        # The harness becomes the pool's depositor, then empties the pool in ONE transaction and
        # forwards the proceeds to the sinks. 1 wei rides along on `drain()` on purpose: the
        # digest's `value_band` is the transaction's own value, so a zero-value call reads as
        # "no significant transfer" no matter how much the call moved (see staged-drain-plain).
        run["transactions"].append(
            send(rpc, account, harness, call_data("deposit()", []), args.amount_wei, 200_000, "harness-deposit")
        )
        run["transactions"].append(
            send(rpc, account, harness, call_data("drain()", []), 1, 400_000, "harness-drain")
        )
        run["drained_wei"] = args.amount_wei

    balance = int(rpc.call("eth_getBalance", [pool, "latest"]), 16)
    run["pool_balance_after"] = balance
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(run, indent=2) + "\n")
    print(f"  pool balance after {balance} wei")
    print(f"  recorded           {out}")
    for tx in run["transactions"]:
        print(f"    {tx['label']:<18} {tx['tx']}  block {int(tx['block'], 16)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

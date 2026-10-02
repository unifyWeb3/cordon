"""Watcher fallback: turn a GenLayer freeze verdict into an EVM freeze.

WHY THIS EXISTS
---------------
`gl.evm.contract_interface(...).emit()` does not deliver on the current GenLayer stack. Tested
2026-10-02 on Studionet against a live target; see
state/reviews/2026-10-02-build-review/R1-EMIT-RESULTS.md for the evidence.

Short version: consensus finalized with MAJORITY_AGREE, the contract recorded the call, the call
returned without raising -- and the target chain never received anything. A return value is not
evidence of delivery. Under local GLSim the same call silently no-ops, which is why this problem
is easy to miss entirely.

So the last hop is off-chain and explicit. The watcher reads the verdict, the evidence and the
deadline from GenLayer storage -- all publicly readable, no privileged GenLayer access needed --
and calls `freeze()` on the target using the protocol's OWN pause authority.

That trade is the honest cost: whoever runs the watcher holds a key that can freeze. What
changes is that the key can no longer freeze *unbounded and unaccountably* -- the window comes
from the adjudicated verdict, it is on the public record, and the target lapses it on its own.

Usage
-----
    python deploy/freeze_watcher.py --address <HALT> --target <POOL> --dry-run
    python deploy/freeze_watcher.py --address <HALT> --target <POOL>        # actually freeze

Only ever uses keys already in the project's .env. Never prints a value from it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
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
from genlayer_py import create_client  # noqa: E402
from genlayer_py.chains.studionet import studionet as sn  # noqa: E402

STATE = Path("/tmp/opencode/cordon-watcher-state.json")

FREEZE_SIG = "freeze(string,uint256)"
UNFREEZE_SIG = "unfreeze(string)"
IS_FROZEN_SIG = "isFrozen()"


def selector(sig: str) -> str:
	return keccak(text=sig)[:4].hex()


def iso_to_epoch(iso: str) -> int:
	return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


class Evm:
	"""Minimal EVM caller. Only what a freeze needs."""

	def __init__(self, rpc: str, key: str) -> None:
		self.rpc = rpc
		self.account = Account.from_key(key)
		self.nonce = int(
			self._call("eth_getTransactionCount", [self.account.address, "latest"]), 16
		)

	def _call(self, method: str, params: list):
		resp = requests.post(
			self.rpc,
			json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
			timeout=40,
		).json()
		if resp.get("error"):
			raise RuntimeError(f"{method}: {resp['error']}")
		return resp.get("result")

	def is_frozen(self, to: str) -> bool:
		out = self._call(
			"eth_call", [{"to": to, "data": "0x" + selector(IS_FROZEN_SIG)}, "latest"]
		)
		return int(out, 16) == 1

	def send(self, to: str, sig: str, arg_types: list, args: list) -> str:
		data = "0x" + selector(sig) + abi_encode(arg_types, args).hex()
		tx = {
			"from": self.account.address,
			"to": to,
			"data": data,
			"nonce": hex(self.nonce),
			"value": "0x0",
			"chainId": int(self._call("eth_chainId", []), 16),
			# Base is an OP-stack L2: legacy gasPrice is required alongside EIP-1559 fields,
			# and eth-account rejects the transaction outright without it. Learned the hard way
			# -- "Transaction must include these fields: {'gasPrice'}".
			"gasPrice": "0x3b9aca00",  # 1 gwei
		}
		tx["gas"] = self._call("eth_estimateGas", [tx])
		signed = self.account.sign_transaction(tx)
		raw = self.account._encode_transaction(signed.raw_transaction) if hasattr(
			self.account, "_encode_transaction"
		) else "0x" + signed.raw_transaction.hex()
		h = self._call("eth_sendRawTransaction", [raw])
		self.nonce += 1
		receipt = None
		for _ in range(40):
			receipt = self._call("eth_getTransactionReceipt", [h])
			if receipt:
				break
			time.sleep(1)
		ok = receipt and int(receipt["status"], 16) == 1
		if not ok:
			raise RuntimeError(
				f"{sig} reverted on target: {(receipt or {}).get('revertReason')}"
			)
		return h


def load_state() -> dict:
	if STATE.exists():
		try:
			return json.loads(STATE.read_text())
		except ValueError:
			pass
	return {"emitted": [], "released": []}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--address", required=True, help="EmergencyHalt contract on GenLayer")
	ap.add_argument("--target", required=True, help="target EVM protocol address")
	ap.add_argument("--network", default="studionet", choices=["studionet", "studio-dev"])
	ap.add_argument("--dry-run", action="store_true", help="report, never send a transaction")
	ap.add_argument("--once", action="store_true", help="one pass instead of polling")
	args = ap.parse_args()

	rpc = os.environ["BASE_SEPOLIA_RPC_URL"]
	key = os.environ["BASE_SEPOLIA_PRIVATE_KEY"]
	client = create_client(
		chain=sn, account=Account.from_key(os.environ["GENLAYER_PRIVATE_KEY"])
	)
	evm = Evm(rpc, key)
	state = load_state()

	print(f"halt contract : {args.address}")
	print(f"target        : {args.target}")
	print(f"target frozen : {evm.is_frozen(args.target)}")
	print(f"mode          : {'DRY RUN' if args.dry_run else 'LIVE'}")
	print()

	try:
		cases = client.read_contract(args.address, "list_cases", [], [])
	except Exception as exc:  # noqa: BLE001
		print(f"could not read cases: {type(exc).__name__}: {exc}")
		return 2

	print(f"cases on chain: {len(cases)}")
	acted = 0
	for case_id in cases:
		try:
			proof = client.read_contract(args.address, "get_evidence", [case_id], [])
		except Exception as exc:  # noqa: BLE001
			print(f"  {case_id}: unreadable ({type(exc).__name__})")
			continue

		verdict = proof.get("verdict")
		frozen = bool(proof.get("frozen"))
		expires = proof.get("expires_at") or ""
		row = (
			f"  {case_id:<16} {str(verdict):<22} frozen={str(frozen):<5} "
			f"expires_at={expires or '-'}"
		)

		if not frozen or verdict != "CONFIRMED_EXPLOIT" or not expires:
			print(row + "  -> no action")
			continue
		if case_id in state["emitted"]:
			print(row + "  -> already emitted")
			continue

		until = iso_to_epoch(expires)
		reason = f"genlayer:{case_id}:{proof.get('evidence_signature', '')[:80]}"
		print(row + f"  -> WOULD freeze until {until}")

		if args.dry_run:
			acted += 1
			continue
		try:
			h = evm.send(args.target, FREEZE_SIG, ["string", "uint256"], [reason, until])
			state["emitted"].append(case_id)
			STATE.write_text(json.dumps(state, indent=2))
			acted += 1
			print(f"{'':>22}   freeze tx {h}")
			print(f"{'':>22}   target now frozen: {evm.is_frozen(args.target)}")
		except Exception as exc:  # noqa: BLE001
			print(f"{'':>22}   FAILED: {type(exc).__name__}: {exc}")

	print()
	print(f"actions this pass: {acted}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

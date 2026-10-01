"""Submit a proof to a deployed EmergencyHalt contract and report the lifecycle.

    uv run --python .venv-deploy python deploy/submit_proof.py \
        --address 0x... --tx 0x... --claim "why this is an exploit" [--case-id id]

Deliberately separates three things that are easy to conflate:
  * the transaction hash returned by writeContract (the GenLayer tx id)
  * the lifecycle status (PENDING/ACCEPTED/FINALIZED)
  * the EXECUTION result, which can be a failure even when consensus accepted the tx

Env values are never printed; only variable names are reported.
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
from genlayer_py import create_client  # noqa: E402
from genlayer_py.chains.studionet import studionet as sn  # noqa: E402

import studio_chain  # noqa: E402


def build_client(network: str):
	key = os.environ["GENLAYER_PRIVATE_KEY"]
	account = Account.from_key(key)
	if network == "studionet":
		chain = sn
	else:
		chain = studio_chain.studio_dev_chain()
	return create_client(chain=chain, account=account), account


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--address", required=True)
	ap.add_argument("--tx", required=True, help="tx hash on the TARGET chain")
	ap.add_argument("--claim", required=True)
	ap.add_argument("--target", default="0x" + "22" * 20, help="target protocol address")
	ap.add_argument("--case-id", default=None)
	ap.add_argument(
		"--network",
		default="studionet",
		choices=["studionet", "studio-dev"],
		help="GenLayer network hosting the contract",
	)
	ap.add_argument("--wait", type=int, default=120)
	args = ap.parse_args()

	client, account = build_client(args.network)
	case_id = args.case_id or f"live-{args.tx[:10]}"

	payload = json.dumps(
		{
			"case_id": case_id,
			"target": args.target,
			"tx_hash": args.tx,
			"claim": args.claim,
		}
	)

	print(f"network         : {args.network} (chain {client.chain.id})")
	print(f"contract        : {args.address}")
	print(f"case_id         : {case_id}")
	print(f"target chain tx : {args.tx}")

	tx_id = client.write_contract(
		address=args.address,
		function_name="submit_proof",
		args=[payload],
		kwargs={},
	)
	print(f"GenLayer tx id  : {tx_id}")

	seen: set[str] = set()
	for _ in range(args.wait):
		status = client.provider.make_request(
			"gen_getTransactionStatus", [tx_id]
		).get("result")
		if status and status not in seen:
			seen.add(status)
			print(f"  lifecycle     : {status}")
		if status == "FINALIZED":
			break
		time.sleep(2)

	try:
		tx = client.get_transaction(tx_id)
		execution = tx.get("tx_execution_result_name") or tx.get("tx_execution_result")
		print(f"  status        : {tx.get('status_name')}")
		print(f"  consensus     : {tx.get('result_name')}")
		print(f"  EXECUTION     : {execution}")
	except Exception as exc:  # noqa: BLE001
		print(f"  (tx query unavailable: {type(exc).__name__})")

	try:
		print(f"  verdict       : {client.read_contract(args.address, 'get_verdict', [case_id], [])}")
		ev = client.read_contract(args.address, "get_evidence", [case_id], [])
		print(f"  frozen        : {ev.get('frozen')}")
		print(f"  expires_at    : {ev.get('expires_at')}")
		print(f"  rationale     : {str(ev.get('rationale'))[:220]}")
		e = ev.get("evidence") or {}
		print(f"  evidence      : found={e.get('tx_found')} status={e.get('receipt_status')} "
			  f"value={e.get('value_band')} logs={e.get('log_band')}")
		print(f"  signature     : {e.get('signature')}")
	except Exception as exc:  # noqa: BLE001
		print(f"  (reads unavailable: {type(exc).__name__}: {exc})")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

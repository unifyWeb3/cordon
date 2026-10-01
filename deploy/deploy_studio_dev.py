"""Deploy emergency_halt.py to studio-dev (chain 61997).

Uses the env file at the project root. Values are never printed -- only variable NAMES are
reported, and the only things echoed are public artefacts (contract address, tx hash).

    uv run python deploy/deploy_studio_dev.py            # deploy
    uv run python deploy/deploy_studio_dev.py --check    # pre-flight only

studio-dev "can be reset or redeployed without preserving state", so treat the deployed
address as a live-demo target rather than something to build on.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from eth_account import Account  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fees_aware import (  # noqa: E402
	DEFAULT_NUM_INITIAL_VALIDATORS,
	ZERO_ADDRESS,
	create2_contract_address,
	encode_add_transaction_with_fees,
	parse_fee_config,
)
from studio_chain import studio_dev_chain  # noqa: E402
from genlayer_py import create_client  # noqa: E402
from genlayer_py.consensus.abi import (  # noqa: E402
    CONSENSUS_DATA_ABI,
    CONSENSUS_MAIN_ABI,
)
from genlayer_py.types import (  # noqa: E402
    GenLayerChain,
    NativeCurrency,
    TransactionStatus,
)

CONTRACT = ROOT / "contracts" / "emergency_halt.py"

# Public Base Sepolia RPC. No API key, so the contract can reach it from any node.
PUBLIC_RPC = "https://base-sepolia-rpc.publicnode.com"


def build_client():
	key = os.environ["GENLAYER_PRIVATE_KEY"]
	account = Account.from_key(key)
	client = create_client(chain=studio_dev_chain(), account=account)
	return client, account


def owner_address(client, account) -> str:
	"""Prefer the configured owner; fall back to the deploying key's own address."""
	owner = os.environ.get("DEPLOYER_ADDRESS") or account.address
	print(f"  chainId          : {studio_dev_chain().id}")
	try:
		constraints = client.provider.make_request("gen_getEnforcedConstraints", [])
		print(f"  enforced owner   : {constraints.get('gen_address', '<unset>')}")
	except Exception as exc:  # noqa: BLE001
		# Hosted Studio networks do not expose chain-level owner enforcement. That is fine:
		# authorisation is enforced by the contract's own _only_owner() guard.
		print(f"  enforced owner   : not enforced by this network ({type(exc).__name__})")
	print(f"  deployer         : {account.address}")
	print(f"  owner arg        : {owner}")
	return owner


def deploy_fee_aware(client, account, code: str, args, owner: str, salt_nonce: int = 0) -> tuple[str, str]:
	"""Deploy via the fee-charging `addTransaction` ABI that studio-dev requires.

	Neither published Python SDK speaks this encoding, so it is built here. See
	deploy/fees_aware.py for the full explanation and the upstream ABI it reproduces.
	"""
	import requests

	from genlayer_py.abi import calldata
	from genlayer_py.abi.transactions import serialize
	from genlayer_py.contracts.utils import make_calldata_object

	rpc = client.chain.rpc_urls["default"]["http"][0]

	config = client.provider.make_request("sim_getFeeConfig", [])
	fee_value, distribution = parse_fee_config(config.get("result", {}))
	print(f"  fee charging     : {bool(config.get('result', {}).get('enabled'))}")
	print(f"  feeValue (wei)   : {fee_value}")
	print(f"  distribution     : {'from network defaults' if distribution else 'zeroed'}")

	ctor_args = [owner, args.template, args.evidence_mode, args.rpc_url]
	serialized = serialize(
		[
			code,
			calldata.encode(
				make_calldata_object(method=None, args=ctor_args, kwargs={})
			),
			False,  # leader_only
		]
	)
	# serialize() returns a 0x-prefixed hex string; the ABI encoder wants raw bytes.
	tx_calldata = bytes.fromhex(serialized[2:] if serialized.startswith("0x") else serialized)

	# For a deploy, `recipient` IS the contract address (genlayer-js decodeInputData returns
	# `contractAddress: recipient`). Passing 0 leaves the node to pick an address we cannot
	# predict, which then cannot be verified. So derive it and pass it explicitly.
	address = create2_contract_address(account.address, salt_nonce, client.chain.id)

	encoded = encode_add_transaction_with_fees(
		sender=account.address,
		recipient=address,
		num_of_initial_validators=DEFAULT_NUM_INITIAL_VALIDATORS,
		max_rotations=args.max_rotations,
		tx_calldata=tx_calldata,
		fees_distribution=distribution,
	)

	from genlayer_py.contracts.actions import _prepare_transaction

	tx = _prepare_transaction(
		self=client,
		sender=account.address,
		recipient=client.chain.consensus_main_contract["address"],
		data=encoded,
	)
	tx["value"] = hex(fee_value)

	signed = account.sign_transaction(tx)
	raw = client.w3.to_hex(signed.raw_transaction)
	resp = requests.post(
		rpc,
		json={
			"jsonrpc": "2.0",
			"id": 1,
			"method": "eth_sendRawTransaction",
			"params": [raw],
		},
		timeout=90,
	).json()
	if resp.get("error"):
		raise RuntimeError(f"eth_sendRawTransaction failed: {resp['error']}")
	tx_hash = resp["result"]

	import time

	for _ in range(30):
		receipt = client.provider.make_request(
			"eth_getTransactionReceipt", [tx_hash]
		).get("result")
		if receipt:
			if int(receipt.get("status", "0x0"), 16) != 1:
				raise RuntimeError(
					f"deploy reverted: {receipt.get('revertReason', 'unknown')}"
				)
			break
		time.sleep(2)
	else:
		raise RuntimeError("deploy receipt never appeared")

	return tx_hash, address


def wait_for_status(client, tx_hash: str, until: str, tries: int = 150) -> str:
	"""Poll `gen_getTransactionStatus` until the transaction reaches `until`.

	GenLayer statuses are not linear -- a transaction can go PENDING -> UNDETERMINED -> NEW ->
	ACCEPTED -> FINALIZED, and UNDETERMINED is retried by the network rather than being a
	terminal failure. So we keep polling until the deadline instead of erroring early.
	"""
	import time

	order = ["PENDING", "NEW", "UNDETERMINED", "ACCEPTED", "FINALIZED"]
	for attempt in range(tries):
		try:
			resp = client.provider.make_request("gen_getTransactionStatus", [tx_hash])
			result = resp.get("result")
		except Exception:  # noqa: BLE001 - transient while the tx is not yet indexed
			time.sleep(2)
			continue
		# This RPC returns a bare status string on studio-dev, e.g. "ACCEPTED".
		name = result if isinstance(result, str) else str(
			(result or {}).get("status", (result or {}).get("status_name", "?"))
		)
		execution = "<see gen_getTransactionStatusBySlot / tx query>"
		progress = f" [{order.index(name)}/{len(order) - 1}]" if name in order else ""
		print(f"    {attempt:>3} {name}{progress}")
		if name == until:
			return name
		time.sleep(2)
	return f"TIMEOUT before {until}"


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--check", action="store_true", help="pre-flight only, do not deploy")
	parser.add_argument(
		"--evidence-mode",
		default="jsonrpc",
		choices=["jsonrpc", "digest"],
		help="jsonrpc = contract POSTs the public chain RPC directly (no hosting needed)",
	)
	parser.add_argument("--template", default="", help="evidence URL template for digest mode")
	parser.add_argument("--rpc-url", default=PUBLIC_RPC)
	parser.add_argument("--max-rotations", type=int, default=3)
	parser.add_argument(
		"--salt-nonce",
		type=int,
		default=0,
		help="CREATE2 salt; changes the derived contract address",
	)
	args = parser.parse_args()

	if not CONTRACT.exists():
		print(f"contract not found: {CONTRACT}")
		return 1

	code = CONTRACT.read_text()
	print(f"contract          : {CONTRACT.relative_to(ROOT)} ({len(code)} bytes)")

	client, account = build_client()
	owner = owner_address(client, account)

	# Pre-flight the schema. Hosted networks reject this RPC, which is why genlayer_py itself
	# ships a hosted-Studio client purely for schema lookup (see get_gl_hosted_studio_client).
	schema_ok = False
	try:
		schema = client.get_contract_schema_for_code(code)
		methods = schema.get("methods", [])
		print(f"schema ok         : {len(methods)} methods (via studio-dev)")
		schema_ok = True
	except Exception as exc:  # noqa: BLE001
		print(f"schema via studio-dev unavailable: {type(exc).__name__}: {exc}")
		try:
			from genlayer_py.chains import studionet

			hosted = create_client(
				chain=studionet,
				account=Account.from_key(os.environ["GENLAYER_PRIVATE_KEY"]),
			)
			schema = hosted.get_contract_schema_for_code(code)
			methods = schema.get("methods", [])
			print(f"schema ok         : {len(methods)} methods (via hosted Studio)")
			schema_ok = True
		except Exception as exc2:  # noqa: BLE001
			print(f"SCHEMA FAILED everywhere: {type(exc2).__name__}: {exc2}")
			if args.check:
				return 2
			print("continuing to deploy anyway; the deploy call is the real test")
	if args.check:
		return 0

	print("deploying (fee-aware) ...")
	tx_hash, address = deploy_fee_aware(
		client, account, code, args, owner, salt_nonce=args.salt_nonce
	)
	print(f"deploy tx hash    : {tx_hash}")
	print(f"contract address  : {address}")

	# Poll the node's own RPC rather than the SDK's get_transaction(): the studio-dev node
	# returns a wider struct than genlayer-py 0.18.0 can decode, so the SDK path raises a
	# decoding error even on a perfectly healthy transaction.
	status = wait_for_status(client, tx_hash, "ACCEPTED")
	print(f"  status          : {status}")

	print("waiting for FINALIZED (consensus) ...")
	status = wait_for_status(client, tx_hash, "FINALIZED")
	print(f"  status          : {status}")

	print("\nnext:")
	print(f"  export HALT_ADDRESS={address}")
	print(f"  export HALT_TX_HASH={tx_hash}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

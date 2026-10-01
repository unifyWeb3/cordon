"""Fee-aware transaction encoding for fee-charging GenLayer networks (studio-dev).

Why this file exists
--------------------
studio-dev is a fee-charging deployment. Its `ConsensusMain` is the `WithFees` variant, whose
`addTransaction` takes a single 10-field tuple and is `payable` -- the fee deposit travels as
`value`. The Python SDKs (genlayer-py 0.9.0 and 0.18.0) and genlayer-js 1.1.8 all still encode
the OLD 5-argument `addTransaction`, so a deploy through them reverts with:

    FeesDistributionMissing

genlayer-js 2.0.0-rc.1 is the first published client that speaks this ABI, and its docs name
it as the release candidate matching studio-dev. Rather than depend on an RC npm package from
a Python build, the ~40 lines needed to encode the tuple are reproduced here from the RC's
own ABI declaration.

Values come from `sim_getFeeConfig`, which studio-dev exposes and which reports
`enabled: true` plus a `defaultFees` block. Nothing is hardcoded.
"""

from __future__ import annotations

from typing import Any

from eth_abi import encode as abi_encode

FEES_DISTRIBUTION_COMPONENTS = [
    ("leaderTimeunitsAllocation", "uint256"),
    ("validatorTimeunitsAllocation", "uint256"),
    ("appealRounds", "uint256"),
    ("executionBudgetPerRound", "uint256"),
    ("executionConsumed", "uint256"),
    ("totalMessageFees", "uint256"),
    ("rotations", "uint256[]"),
    ("maxPriceGenPerTimeUnit", "uint256"),
    ("storageFeeMaxGasPrice", "uint256"),
    ("receiptFeeMaxGasPrice", "uint256"),
]

MESSAGE_FEE_ALLOCATION_COMPONENTS = [
    ("messageType", "uint8"),
    ("onAcceptance", "bool"),
    ("parentIndex", "uint256"),
    ("recipient", "address"),
    ("callKey", "bytes32"),
    ("budget", "uint256"),
    ("feeParams", "bytes"),
]

ADD_TRANSACTION_PARAMS_COMPONENTS = [
    ("sender", "address"),
    ("recipient", "address"),
    ("numOfInitialValidators", "uint256"),
    ("maxRotations", "uint256"),
    ("validUntil", "uint256"),
    ("saltNonce", "uint256"),
    ("userValue", "uint256"),
    ("feesDistribution", "tuple"),
    ("txCalldata", "bytes"),
    ("messageAllocations", "tuple[]"),
]

ZERO_ADDRESS = "0x" + "00" * 20
DEFAULT_MAX_ROTATIONS = 5
DEFAULT_NUM_INITIAL_VALIDATORS = 5
EMPTY_CALL_KEY = "0x" + "00" * 32


def default_fees_distribution() -> tuple:
	"""A zeroed FeesDistribution tuple.

	Zero allocations still satisfy `FeesDistributionMissing` (the revert is about the field
	being absent, not about it being non-zero). The real numbers come from the network's fee
	policy via `sim_getFeeConfig`.
	"""
	return (
		0,  # leaderTimeunitsAllocation
		0,  # validatorTimeunitsAllocation
		0,  # appealRounds
		0,  # executionBudgetPerRound
		0,  # executionConsumed
		0,  # totalMessageFees
		[],  # rotations
		0,  # maxPriceGenPerTimeUnit
		0,  # storageFeeMaxGasPrice
		0,  # receiptFeeMaxGasPrice
	)


def _fees_tuple_type() -> str:
	return "(" + ",".join(t for _, t in FEES_DISTRIBUTION_COMPONENTS) + ")"


def _alloc_tuple_type() -> str:
	return "(" + ",".join(t for _, t in MESSAGE_FEE_ALLOCATION_COMPONENTS) + ")[]"


def _params_tuple_type() -> str:
	"""Canonical ABI type of the single `_params` struct argument.

	A Solidity function taking one struct is written with DOUBLE parentheses in its signature:
	`addTransaction((address,address,...))`. Getting this wrong produces a plausible-looking
	4-byte selector for a function that does not exist.
	"""
	fields = [
		"address",  # sender
		"address",  # recipient
		"uint256",  # numOfInitialValidators
		"uint256",  # maxRotations
		"uint256",  # validUntil
		"uint256",  # saltNonce
		"uint256",  # userValue
		_fees_tuple_type(),
		"bytes",  # txCalldata
		_alloc_tuple_type(),
	]
	return "(" + ",".join(fields) + ")"


def encode_add_transaction_with_fees(
	*,
	sender: str,
	recipient: str,
	num_of_initial_validators: int,
	max_rotations: int,
	tx_calldata: bytes,
	fees_distribution: tuple | None = None,
	valid_until: int = 0,
	salt_nonce: int = 0,
	user_value: int = 0,
	message_allocations: list | None = None,
) -> str:
	"""Encode `addTransaction(_params)` for a fee-charging deployment."""
	distribution = fees_distribution or default_fees_distribution()
	params = (
		sender,
		recipient,
		num_of_initial_validators,
		max_rotations,
		valid_until,
		salt_nonce,
		user_value,
		distribution,
		tx_calldata,
		message_allocations or [],
	)
	params_type = _params_tuple_type()
	selector = keccak_selector("addTransaction", [params_type])
	return "0x" + selector.hex() + abi_encode([params_type], [params]).hex()


def keccak_selector(name: str, types: list[str]) -> bytes:
	"""4-byte selector for `name(type1,type2,...)`.

	The argument list is part of the preimage -- hashing the bare name yields a selector for
	a function that does not exist, and the node rejects the call with an unhelpful error.
	"""
	import eth_utils

	return eth_utils.keccak(text=f"{name}({','.join(types)})")[:4]


def parse_fee_config(result: dict[str, Any]) -> tuple[int, dict | None]:
	"""Pull (feeValue, distribution) out of a `sim_getFeeConfig` reply.

	Returns feeValue=0 and distribution=None when the network has fees disabled, in which case
	the caller can fall back to the legacy encoding.
	"""
	if not result.get("enabled"):
		return 0, None
	default_fees = result.get("defaultFees") or {}
	raw = default_fees.get("distribution")
	fee_value = int(default_fees.get("feeValue", 0))
	if not raw:
		return fee_value, None
	distribution = (
		int(raw["leaderTimeunitsAllocation"]),
		int(raw["validatorTimeunitsAllocation"]),
		int(raw["appealRounds"]),
		int(raw["executionBudgetPerRound"]),
		int(raw["executionConsumed"]),
		int(raw["totalMessageFees"]),
		[int(r) for r in raw["rotations"]],
		int(raw["maxPriceGenPerTimeUnit"]),
		int(raw["storageFeeMaxGasPrice"]),
		int(raw["receiptFeeMaxGasPrice"]),
	)
	return fee_value, distribution


def create2_contract_address(sender: str, salt_nonce: int, chain_id: int) -> str:
	"""GenLayer's CREATE2-style contract address derivation.

	Mirrors `genlayer.py._internal.create2_address`, which is what GenVM itself uses:
	    keccak(0x01 || sender(20) || saltNonce(32) || chainId(32))[0:20]
	Deterministic, so the deployed address is known before the transaction is sent.
	"""
	import eth_utils

	digest = eth_utils.keccak(
		b"\x01"
		+ bytes.fromhex(sender[2:])
		+ int(salt_nonce).to_bytes(32, "big")
		+ int(chain_id).to_bytes(32, "big")
	)
	return "0x" + digest[:20].hex()

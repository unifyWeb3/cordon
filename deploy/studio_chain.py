"""studio-dev chain config, shared by the deploy and submit scripts.

genlayer-py does not ship a studio.dev constant, and its GenLayerChain signature differs
between releases (0.9.0 vs 0.18.0 both occur in this repo). Deriving from the shipped
studionet config and overriding id + RPC keeps this working on either SDK.
"""

import dataclasses
import os

from genlayer_py.types import GenLayerChain, NativeCurrency

DEFAULT_MAX_ROTATIONS = 3
DEFAULT_NUM_INITIAL_VALIDATORS = 5


def studio_dev_chain() -> GenLayerChain:
	"""Build a studio-dev chain config from the studio.net config, overriding id and RPC.

	genlayer-py does not ship a studio.dev constant, and its GenLayerChain signature differs
	between releases (0.9.0 vs 0.18.0 both work for this build). Deriving from the shipped
	studionet chain and overriding the two fields that actually differ keeps this working on
	either SDK -- see deploy/README for why there are two virtualenvs.
	"""
	rpc = os.environ["GENLAYER_STUDIO_DEV_RPC"]
	chain_id = int(os.environ.get("GENLAYER_STUDIO_DEV_CHAIN_ID", "61997"))
	explorer = os.environ.get("GENLAYER_EXPLORER_URL", "")

	try:
		from genlayer_py.chains.studionet import studionet as base
	except ImportError:  # older layout exposed the module, not the instance
		from genlayer_py.chains import studionet as _mod

		base = _mod.studionet

	overrides = {
		"id": chain_id,
		"name": "GenLayer Studio Dev",
		"rpc_urls": {"default": {"http": [rpc]}},
	}
	if explorer:
		overrides["block_explorers"] = {
			"default": {"name": "GenLayer Explorer", "url": explorer}
		}
	try:
		return dataclasses.replace(base, **overrides)
	except TypeError:  # not a dataclass on this SDK version
		return GenLayerChain(
			id=overrides["id"],
			name=overrides["name"],
			rpc_urls=overrides["rpc_urls"],
			native_currency=base.native_currency,
			block_explorers=overrides.get("block_explorers", getattr(base, "block_explorers", {})),
			testnet=True,
			consensus_main_contract=base.consensus_main_contract,
			consensus_data_contract=base.consensus_data_contract,
			**{
				f: getattr(base, f)
				for f in (
					"fee_manager_contract",
					"rounds_storage_contract",
					"appeals_contract",
					"staking_contract",
				)
				if f in getattr(base, "__dataclass_fields__", {})
			},
			default_number_of_initial_validators=base.default_number_of_initial_validators,
			default_consensus_max_rotations=base.default_consensus_max_rotations,
		)

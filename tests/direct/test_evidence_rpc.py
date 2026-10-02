"""Stage-1 reduction and the JSON-RPC evidence path.

Two things are under test:
  1. The reduction drops volatile fields and keeps only ones that are fixed for a given tx
     forever. This is the anti-equivocation device from the docs' derive_status pattern.
  2. The contract can drive the real thing -- a JSON-RPC batch against a public endpoint --
     with no hosting and no API key.
"""

import json

import pytest

from conftest import CONTRACT, OWNER, SDK_VERSION, SUBMITTER  # noqa: F401

RPC_URL = "https://base-sepolia-rpc.publicnode.com"

# A real-shaped receipt: many Transfer logs, one transaction, large value.
EXPLOIT_RECEIPT = {
    "status": "0x1",
    "blockNumber": "0x14a2b3c",
    "gasUsed": "0x1e8480",
    "logs": [
        {"topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]}
        for _ in range(9)
    ],
}
EXPLOIT_TX = {
    "value": "0x3635c9adc5dea00000",
    "input": "0x23b872dd0000000000000000",
    "from": "0x" + "cc" * 20,
    "to": "0x" + "dd" * 20,
}
BENIGN_RECEIPT = {
    "status": "0x1",
    "blockNumber": "0x14a2b3d",
    "logs": [
        {"topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]},
        {"topics": ["0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"]},
    ],
}
BENIGN_TX = {"value": "0x37a", "input": "0x2e1a7d4d", "from": "0x" + "cc" * 20, "to": "0x" + "dd" * 20}


def batch(receipt, tx):
    return json.dumps([{"jsonrpc": "2.0", "id": 1, "result": receipt},
                       {"jsonrpc": "2.0", "id": 2, "result": tx}])


def not_found():
    return json.dumps([{"jsonrpc": "2.0", "id": 1, "result": None},
                       {"jsonrpc": "2.0", "id": 2, "result": None}])


# ------------------------------------------------------------------ the reduction itself


def test_rpc_reduction_drops_volatile_fields(contract_module):
    """Block number and gas must not reach the digest; they change between two fetches."""
    digest = contract_module.derive_digest_from_rpc(EXPLOIT_RECEIPT, EXPLOIT_TX)
    flat = json.dumps(digest)
    assert "14a2b3c" not in flat, "block number leaked into the digest"
    assert "1e8480" not in flat, "gas leaked into the digest"
    assert digest["value_band"] == "MEDIUM"
    assert digest["log_band"] == "MANY"
    assert digest["input_selector"] == "0x23b872dd"
    assert digest["repeated_selectors"], "repeated Transfer topic is the drain signature"


def test_rpc_reduction_is_stable_across_volatile_inputs(contract_module):
    """Same tx, different block/gas/timestamps -> byte-identical digest.

    This is the property that keeps leader and validators from equivocating.
    """
    mod = contract_module
    a = mod.derive_digest_from_rpc(EXPLOIT_RECEIPT, EXPLOIT_TX)
    shifted = dict(EXPLOIT_RECEIPT, blockNumber="0xffffff", gasUsed="0x999999")
    b = mod.derive_digest_from_rpc(shifted, dict(EXPLOIT_TX))
    assert mod.digest_signature(a) == mod.digest_signature(b)


def test_missing_transaction_is_a_verdict_input_not_an_error(contract_module):
    digest = contract_module.derive_digest_from_rpc(None, None)
    assert digest["tx_found"] is False
    assert digest["receipt_status"] == "NOT_FOUND"


@pytest.mark.parametrize("status,body", [(404, b""), (500, b""), (200, b"not json"), (200, b"[]")])
def test_bad_rpc_responses_degrade_without_raising(contract_module, status, body):
    digest = contract_module.digest_from_rpc_response(status, body)
    assert digest["tx_found"] is False


# ------------------------------------------------------------------ end to end in rpc mode


def test_contract_fetches_a_public_rpc_and_confirms(direct_vm, direct_deploy):
    direct_vm.mock_web(
        RPC_URL,
        {"method": "POST", "status": 200, "body": batch(EXPLOIT_RECEIPT, EXPLOIT_TX)},
    )
    # Same evidence-driven stand-in model as the rest of the suite.
    direct_vm.mock_llm(
        r"event_signatures_repeated_within_this_tx: 0xddf252ad",
        json.dumps({"verdict": "CONFIRMED_EXPLOIT", "rationale": "nine Transfer events in one tx"}),
    )

    halt = direct_deploy(CONTRACT, owner=OWNER, evidence_url_template="",
                         evidence_mode="jsonrpc", evidence_rpc_url=RPC_URL,
                         sdk_version=SDK_VERSION)
    direct_vm.sender = SUBMITTER
    halt.submit_proof(json.dumps({
        "case_id": "rpc-1",
        "target": "0x" + "22" * 20,
        "tx_hash": "0x" + "ab" * 32,
        "claim": "drain",
    }))

    assert halt.get_verdict("rpc-1") == "CONFIRMED_EXPLOIT"
    p = halt.get_evidence("rpc-1")
    assert p.evidence_mode == "jsonrpc"
    assert p.evidence.value_band == "MEDIUM"
    assert p.evidence.input_selector == "0x23b872dd"
    assert p.frozen is True
    assert direct_vm.run_validator() is True


def test_contract_reports_insufficient_for_unknown_tx(direct_vm, direct_deploy):
    direct_vm.mock_web(RPC_URL, {"method": "POST", "status": 200, "body": not_found()})
    direct_vm.mock_llm(
        r"transaction_found: False",
        json.dumps({"verdict": "INSUFFICIENT_EVIDENCE", "rationale": "no receipt"}),
    )
    halt = direct_deploy(CONTRACT, owner=OWNER, evidence_url_template="",
                         evidence_mode="jsonrpc", evidence_rpc_url=RPC_URL,
                         sdk_version=SDK_VERSION)
    direct_vm.sender = SUBMITTER
    halt.submit_proof(json.dumps({
        "case_id": "rpc-2",
        "target": "0x" + "22" * 20,
        "tx_hash": "0x" + "cd" * 32,
        "claim": "definitely an exploit",
    }))
    assert halt.get_verdict("rpc-2") == "INSUFFICIENT_EVIDENCE"
    assert halt.get_evidence("rpc-2").frozen is False

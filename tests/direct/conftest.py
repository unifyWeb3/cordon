"""Shared fixtures for the hermetic M0 consensus gate.

No network. The web fetch and the model are both mocked from recorded evidence, which is
what makes the gate repeatable in CI (brief section 2: tests must not depend on the network).
"""

import json
import sys
from pathlib import Path

import pytest
from gltest.direct import pytest_plugin  # noqa: F401  (registers direct_* fixtures)

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import FIXTURES, submit_payload  # noqa: E402

CONTRACT = "contracts/emergency_halt.py"
OWNER = "0x" + "aa" * 20
SUBMITTER = "0x" + "bb" * 20
TARGET = "0x" + "22" * 20

EXPLOIT_URL = "https://evidence.test/exploit"
BENIGN_URL = "https://evidence.test/benign"
MISSING_URL = "https://evidence.test/nonexistent"

URL_FOR = {"real_exploit": EXPLOIT_URL, "benign": BENIGN_URL, "nonexistent": MISSING_URL,
           "injected": BENIGN_URL}


def _web_mocks():
    """Serve the recorded stage-1 payloads. The nonexistent case is a real HTTP 404."""
    return [
        (EXPLOIT_URL, 200, json.dumps(FIXTURES["real_exploit"]["payload"])),
        (BENIGN_URL, 200, json.dumps(FIXTURES["benign"]["payload"])),
        (MISSING_URL, 404, "not found"),
    ]


def _llm_mocks():
    """A deterministic stand-in model that keys off the *observed evidence* in the prompt.

    This is what makes the gate a real test rather than a tautology: if the contract ever
    stopped passing evidence to the model, these patterns would stop matching and the
    expected verdicts would not be produced.

    It does NOT test that two different real models agree -- that needs a live network and
    is out of scope for a hermetic gate. See README "What the hermetic gate does not prove".
    """
    return [
        # exploited: a selector was called more than once, and value is LARGE
        (
            r"event_signatures_repeated_within_this_tx: 0x23b872dd",
            json.dumps(
                {
                    "verdict": "CONFIRMED_EXPLOIT",
                    "rationale": "transferFrom selector repeats eight times in one "
                    "transaction at LARGE value magnitude.",
                }
            ),
        ),
        # transaction absent from the chain
        (
            r"transaction_found: False",
            json.dumps(
                {
                    "verdict": "INSUFFICIENT_EVIDENCE",
                    "rationale": "No receipt was retrieved, so there is nothing to judge.",
                }
            ),
        ),
        # ordinary activity
        (
            r"transaction_found: True",
            json.dumps(
                {
                    "verdict": "FALSE_REPORT",
                    "rationale": "Single withdraw then a transfer, no repeated selector.",
                }
            ),
        ),
    ]


@pytest.fixture
def halt(direct_vm, direct_deploy):
    """Deployed contract with evidence + model mocks registered."""
    for url, status, body in _web_mocks():
        direct_vm.mock_web(url, {"method": "GET", "status": status, "body": body})
    for pattern, response in _llm_mocks():
        direct_vm.mock_llm(pattern, response)

    contract = direct_deploy(CONTRACT, owner=OWNER,
                             evidence_url_template="https://evidence.test/{tx_hash}")
    direct_vm.sender = OWNER
    return contract


def advance_time(vm, iso: str) -> None:
	"""Move the chain clock to `iso`.

	`VMContext.warp()` sets `vm._datetime` and refreshes the cached `gl.message`, but it does
	NOT update `gl.message_raw["datetime"]` -- see `_refresh_gl_message` in
	gltest/direct/vm.py, which only refreshes sender_address and origin_address. Because
	`message_raw` is decoded once at contract import time, a contract reading the transaction
	datetime (which is what a real Intelligent Contract must do) cannot see a bare `warp()`.

	So we do both. This is a harness workaround, not contract behaviour: on a real node the
	datetime arrives fresh with every transaction.
	"""
	import genlayer.gl as _gl

	vm.warp(iso)
	_gl.message_raw["datetime"] = iso


def submit(contract, vm, case_name: str, case_id: str | None = None):
    """Submit one fixture as an arbitrary (non-owner) sender."""
    fixture = FIXTURES[case_name]
    vm.sender = SUBMITTER
    payload = submit_payload(
        case_id or case_name,
        fixture,
        URL_FOR[case_name],
    )
    return contract.submit_proof(payload)


@pytest.fixture
def contract_module(direct_deploy):
	"""The loaded contract module.

	The stage-1 reduction helpers are pure and deterministic, so they can be exercised
	directly rather than only through a full adjudicate() round trip.
	"""
	import sys

	direct_deploy(CONTRACT, owner=OWNER, evidence_url_template="https://evidence.test/{tx_hash}")
	return sys.modules["_contract_emergency_halt"]

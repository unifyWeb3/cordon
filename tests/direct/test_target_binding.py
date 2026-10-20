"""Target binding: a CONFIRMED_EXPLOIT must be *about the pool it names*.

The hole this closes: `submit_proof` takes `target` and `tx_hash` as two unconnected
strings. Nothing stopped a submitter naming a victim pool while pointing at a transaction
that never touched it -- so a genuine drain on some unrelated contract could arm a freeze
on the victim, and the model would confirm it in good faith because the evidence really does
look like a drain.

The rule enforced here: an armed freeze requires the fetched transaction's `to` to equal the
recorded `target`. A mismatch is downgraded to INSUFFICIENT_EVIDENCE -- not raised, because
"that transaction does not involve that pool" is a verdict input, not a caller error.

The negative tests use the SAME fixture as the positive control, so the only variable is the
target address. If the model mock were driving the result, the mismatch case would still
come back CONFIRMED_EXPLOIT.
"""

import json

import pytest

from conftest import CONTRACT, OWNER, SDK_VERSION, SUBMITTER, submit  # noqa: F401
from fixtures import TARGET

OTHER_POOL = "0x" + "99" * 20


# --------------------------------------------------------------- digest mode


def test_matching_target_confirms_and_arms_a_freeze(halt, direct_vm):
    """Positive control: `to` == target, so the freeze stands."""
    submit(halt, direct_vm, "real_exploit")
    p = halt.get_evidence("real_exploit")
    assert p.verdict == "CONFIRMED_EXPLOIT"
    assert p.frozen is True
    assert p.evidence.tx_to == TARGET
    assert p.target == TARGET


def test_confirmed_verdict_is_downgraded_when_target_differs(halt, direct_vm):
    """The mismatch case. Same fixture, same verdict from the model, different target."""
    submit(halt, direct_vm, "real_exploit", case_id="mismatch", target=OTHER_POOL)

    p = halt.get_evidence("mismatch")
    assert p.verdict == "INSUFFICIENT_EVIDENCE", (
        "a transaction that never touched the named pool is not evidence about that pool"
    )
    assert p.frozen is False
    assert p.expires_at == ""
    assert halt.is_frozen("mismatch") is False


def test_mismatch_does_not_count_as_a_freeze(halt, direct_vm):
    submit(halt, direct_vm, "real_exploit", case_id="ok")
    submit(halt, direct_vm, "real_exploit", case_id="mismatch", target=OTHER_POOL)

    stats = halt.stats()
    assert stats["submits"] == 2
    assert stats["freezes"] == 1, "the downgraded case must not increment the freeze count"
    assert set(halt.list_cases()) == {"ok", "mismatch"}


def test_target_match_is_case_insensitive(halt, direct_vm):
    """Checksummed vs lowercase target must not read as a mismatch."""
    submit(halt, direct_vm, "real_exploit", case_id="upper",
           target="0x" + "22" * 20)
    assert halt.get_evidence("upper").verdict == "CONFIRMED_EXPLOIT"


@pytest.mark.parametrize("case_name", ["benign", "injected"])
def test_non_confirmed_verdicts_are_unaffected_by_the_binding_rule(
    halt, direct_vm, case_name
):
    """The rule only gates CONFIRMED_EXPLOIT; FALSE_REPORT stays FALSE_REPORT."""
    submit(halt, direct_vm, case_name)
    assert halt.get_evidence(case_name).verdict == "FALSE_REPORT"


# --------------------------------------------------------------- jsonrpc mode

RPC_URL = "https://base-sepolia-rpc.publicnode.com"

RECEIPT = {
    "status": "0x1",
    "blockNumber": "0x14a2b3c",
    "gasUsed": "0x1e8480",
    "logs": [
        {"topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]}
        for _ in range(9)
    ],
}


def _rpc_contract(direct_vm, direct_deploy, tx_to):
    body = json.dumps(
        [
            {"jsonrpc": "2.0", "id": 1, "result": RECEIPT},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "value": "0x3635c9adc5dea00000",
                    "input": "0x23b872dd0000000000000000",
                    "from": "0x" + "cc" * 20,
                    "to": tx_to,
                },
            },
        ]
    )
    direct_vm.mock_web(RPC_URL, {"method": "POST", "status": 200, "body": body})
    direct_vm.mock_llm(
        r"event_signatures_repeated_within_this_tx: 0xddf252ad",
        json.dumps({"verdict": "CONFIRMED_EXPLOIT", "rationale": "nine Transfer events"}),
    )
    halt = direct_deploy(
        CONTRACT,
        owner=OWNER,
        evidence_url_template="",
        evidence_mode="jsonrpc",
        evidence_rpc_url=RPC_URL,
        sdk_version=SDK_VERSION,
    )
    direct_vm.sender = SUBMITTER
    return halt


def _submit_rpc(halt, case_id, target):
    halt.submit_proof(
        json.dumps(
            {
                "case_id": case_id,
                "target": target,
                "tx_hash": "0x" + "ab" * 32,
                "claim": "drain",
            }
        )
    )


def test_rpc_mode_freezes_when_fetched_tx_touched_the_named_pool(direct_vm, direct_deploy):
    """Positive control in jsonrpc mode, where `to` comes from the chain, not the submitter."""
    halt = _rpc_contract(direct_vm, direct_deploy, tx_to=OTHER_POOL)
    _submit_rpc(halt, "rpc-ok", target=OTHER_POOL)

    p = halt.get_evidence("rpc-ok")
    assert p.verdict == "CONFIRMED_EXPLOIT"
    assert p.frozen is True
    assert p.evidence.tx_to == OTHER_POOL


def test_rpc_mode_downgrades_when_fetched_tx_touched_another_address(
    direct_vm, direct_deploy
):
    """The whole point: the chain says the tx went elsewhere, so the claim fails."""
    halt = _rpc_contract(direct_vm, direct_deploy, tx_to=OTHER_POOL)
    _submit_rpc(halt, "rpc-bad", target=TARGET)

    p = halt.get_evidence("rpc-bad")
    assert p.verdict == "INSUFFICIENT_EVIDENCE"
    assert p.frozen is False
    assert p.evidence.tx_to == OTHER_POOL, "the true destination is still on the record"


def test_rpc_mode_with_no_destination_is_not_confirmed(direct_vm, direct_deploy):
    """A contract-creation tx has `to` == null. It cannot have called the pool."""
    halt = _rpc_contract(direct_vm, direct_deploy, tx_to=None)
    _submit_rpc(halt, "rpc-null", target=TARGET)
    assert halt.get_evidence("rpc-null").verdict == "INSUFFICIENT_EVIDENCE"


# --------------------------------------------------------------- digest integrity


def test_tx_to_is_part_of_the_stable_signature(contract_module):
    """`to` is fixed for a transaction forever, so it belongs in the audit fingerprint."""
    mod = contract_module
    tx = {"value": "0x1", "input": "0x2e1a7d4d", "to": TARGET}
    a = mod.derive_digest_from_rpc({"status": "0x1", "logs": []}, tx)
    assert a["tx_to"] == TARGET

    other = dict(tx, to=OTHER_POOL)
    b = mod.derive_digest_from_rpc({"status": "0x1", "logs": []}, other)
    assert mod.digest_signature(a) != mod.digest_signature(b), (
        "two transactions to different pools must not share a signature"
    )


def test_tx_to_survives_volatile_field_churn(contract_module):
    """Still stable across block/gas changes -- the anti-equivocation property holds."""
    mod = contract_module
    tx = {"value": "0x1", "input": "0x2e1a7d4d", "to": TARGET}
    a = mod.derive_digest_from_rpc({"status": "0x1", "blockNumber": "0x1", "logs": []}, tx)
    b = mod.derive_digest_from_rpc(
        {"status": "0x1", "blockNumber": "0xffffff", "gasUsed": "0x999999", "logs": []},
        dict(tx),
    )
    assert mod.digest_signature(a) == mod.digest_signature(b)


def test_missing_transaction_carries_no_destination(contract_module):
    digest = contract_module.derive_digest_from_rpc(None, None)
    assert digest["tx_to"] == ""
    assert digest["tx_found"] is False

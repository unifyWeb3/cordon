"""M0 -- consensus gate.

Pass condition from HANDOFF.md section 3: the same verdict on 3/3 for the true and false
cases, and INSUFFICIENT_EVIDENCE (not a stall) for the bogus one, with the leader/validator
comparison visible.

The leader runs inline in direct mode and the validator is captured rather than auto-run, so
`vm.run_validator()` is what actually exercises the equivalence check. That is used below to
prove the gate is real rather than decorative.
"""

import pytest

from conftest import halt, submit  # noqa: F401  (fixture import for pytest discovery)


# --------------------------------------------------------------------- M0 pass condition


@pytest.mark.parametrize(
    "case,expected",
    [
        ("real_exploit", "CONFIRMED_EXPLOIT"),
        ("benign", "FALSE_REPORT"),
        ("nonexistent", "INSUFFICIENT_EVIDENCE"),
    ],
)
def test_correct_verdict_for_each_fixture(halt, direct_vm, case, expected):
    submit(halt, direct_vm, case)
    assert halt.get_verdict(case) == expected


@pytest.mark.parametrize(
    "case,expected",
    [
        ("real_exploit", "CONFIRMED_EXPLOIT"),
        ("benign", "FALSE_REPORT"),
        ("nonexistent", "INSUFFICIENT_EVIDENCE"),
    ],
)
def test_validator_agrees_no_equivocation(halt, direct_vm, case, expected):
    """The real check: run the captured validator against the leader's result."""
    submit(halt, direct_vm, case)
    assert direct_vm.run_validator() is True, f"validator disagreed on {case}"


# --------------------------------------------------------------------- Partial Field Matching


def test_validator_ignores_rationale(halt, direct_vm):
    """Same enum, wildly different rationale -> must still agree.

    This is the single most important property of the whole design. Two different models will
    essentially never write the same sentence; if rationale were compared, every proof would
    equivocate forever.
    """
    submit(halt, direct_vm, "real_exploit")
    doctored = {
        "verdict": "CONFIRMED_EXPLOIT",
        "rationale": "A completely different sentence written by a different model entirely.",
        "digest": {"tx_found": False},
    }
    assert direct_vm.run_validator(leader_result=doctored) is True


def test_validator_compares_the_enum(halt, direct_vm):
    """Different enum -> must disagree, even though the rationale is identical."""
    submit(halt, direct_vm, "real_exploit")
    doctored = {
        "verdict": "FALSE_REPORT",
        "rationale": halt.get_evidence("real_exploit").rationale,
        "digest": {},
    }
    assert direct_vm.run_validator(leader_result=doctored) is False


def test_validator_rejects_illegal_enum(halt, direct_vm):
    """A leader result outside the enum must not be accepted as agreement."""
    submit(halt, direct_vm, "real_exploit")
    doctored = {"verdict": "DEFINITELY_A_HACK", "rationale": "x", "digest": {}}
    assert direct_vm.run_validator(leader_result=doctored) is False


def test_validator_rejects_missing_verdict(halt, direct_vm):
    submit(halt, direct_vm, "benign")
    assert direct_vm.run_validator(leader_result={"rationale": "no verdict at all"}) is False


# --------------------------------------------------------------------- R4 injection posture


def test_injected_claim_does_not_override_evidence(halt, direct_vm):
    """The claim asks for CONFIRMED_EXPLOIT; the evidence is benign. Evidence wins."""
    submit(halt, direct_vm, "injected")
    assert halt.get_verdict("injected") == "FALSE_REPORT"


def test_out_of_enum_model_output_is_coerced(halt, direct_vm):
    """A model that invents a fourth option is treated as having said nothing useful."""
    import json

    direct_vm.mock_llm(".*", json.dumps({"verdict": "TOTALLY_EXPLOITED", "rationale": "trust me"}))
    direct_vm._llm_mocks = direct_vm._llm_mocks[-1:]
    submit(halt, direct_vm, "real_exploit", case_id="coerced")
    assert halt.get_verdict("coerced") == "INSUFFICIENT_EVIDENCE"

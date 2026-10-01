"""M1/M2 -- record, bounded freeze, and self-lifting expiry.

The differentiator claim is that a wrong freeze lifts itself with no human action. These
tests are what make that claim checkable rather than asserted.
"""

import pytest

from conftest import OWNER, SUBMITTER, advance_time, submit  # noqa: F401


# --------------------------------------------------------------------- record shape


def test_confirmed_exploit_arms_a_bounded_freeze(halt, direct_vm):
    submit(halt, direct_vm, "real_exploit")
    p = halt.get_evidence("real_exploit")
    assert p.verdict == "CONFIRMED_EXPLOIT"
    assert p.frozen is True
    assert p.expires_at > p.submitted_at, "every freeze must carry an expiry"
    assert halt.is_frozen("real_exploit") is True
    assert int(halt.seconds_remaining("real_exploit")) > 0


def test_false_report_freezes_nothing(halt, direct_vm):
    submit(halt, direct_vm, "benign")
    p = halt.get_evidence("benign")
    assert p.verdict == "FALSE_REPORT"
    assert p.frozen is False
    assert p.expires_at == ""
    assert halt.is_frozen("benign") is False


def test_evidence_is_public_and_stable_field_only(halt, direct_vm):
    """The record must show what was judged without exposing volatile raw data."""
    submit(halt, direct_vm, "real_exploit")
    ev = halt.get_evidence("real_exploit").evidence
    assert ev.tx_found is True
    assert ev.receipt_ok is True
    assert ev.value_band == "LARGE"      # band, not the raw wei amount
    assert ev.log_band == "MANY"
    assert "0x23b872dd" in ev.repeated_selectors
    assert ev.signature and "value=LARGE" in ev.signature


def test_stats_and_listing(halt, direct_vm):
    submit(halt, direct_vm, "real_exploit")
    submit(halt, direct_vm, "benign")
    stats = halt.stats()
    assert stats["submits"] == 2
    assert stats["freezes"] == 1
    assert list(halt.list_cases()) == ["real_exploit", "benign"]


# --------------------------------------------------------------------- auto-expiry


def test_freeze_lifts_itself_with_no_human(halt, direct_vm):
    """Advance past the window: is_frozen must report False with nobody's permission."""
    submit(halt, direct_vm, "real_exploit")
    assert halt.is_frozen("real_exploit") is True

    # Warp the chain clock past the recorded expiry.
    expiry = halt.get_evidence("real_exploit").expires_at
    advance_time(direct_vm, _plus(expiry, 60))

    assert halt.is_frozen("real_exploit") is False
    assert int(halt.seconds_remaining("real_exploit")) == 0


def test_reap_expired_is_permissionless_and_idempotent(halt, direct_vm):
    submit(halt, direct_vm, "real_exploit")
    expiry = halt.get_evidence("real_exploit").expires_at
    advance_time(direct_vm, _plus(expiry, 60))

    direct_vm.sender = SUBMITTER
    assert halt.reap_expired("real_exploit") is True, "any caller may lift it"
    assert halt.get_evidence("real_exploit").frozen is False

    assert halt.reap_expired("real_exploit") is False, "second call has nothing to lift"


def test_reap_before_expiry_is_a_no_op(halt, direct_vm):
    submit(halt, direct_vm, "real_exploit")
    direct_vm.sender = SUBMITTER
    assert halt.reap_expired("real_exploit") is False
    assert halt.get_evidence("real_exploit").frozen is True


def _plus(iso: str, seconds: int) -> str:
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(seconds=seconds)
    return base.isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------- guards


def test_duplicate_case_id_is_rejected(halt, direct_vm):
    submit(halt, direct_vm, "real_exploit")
    with pytest.raises(BaseException) as exc:
        submit(halt, direct_vm, "benign", case_id="real_exploit")
    assert "already submitted" in str(exc.value)


@pytest.mark.parametrize("bad", ["not json", '["a"]', '{"claim":"x"}', '{"case_id":"c"}'])
def test_degenerate_payloads_are_refused(halt, direct_vm, bad):
    """Refuse degenerate input rather than judging a trivial case."""
    with pytest.raises(BaseException) as exc:
        halt.submit_proof(bad)
    assert any(w in str(exc.value) for w in ("JSON", "object", "missing"))


def test_only_owner_may_change_admin_settings(halt, direct_vm):
    direct_vm.sender = OWNER
    halt.set_default_freeze_seconds(600)
    assert halt.stats()["default_freeze_seconds"] == 600

    direct_vm.sender = SUBMITTER
    with pytest.raises(BaseException) as exc:
        halt.set_default_freeze_seconds(300)
    assert "only owner" in str(exc.value)


def test_freeze_seconds_are_bounded(halt, direct_vm):
    direct_vm.sender = OWNER
    with pytest.raises(BaseException):
        halt.set_default_freeze_seconds(0)
    with pytest.raises(BaseException):
        halt.set_default_freeze_seconds(999999)


def test_unknown_case_id_reads_fail_loudly(halt):
    with pytest.raises(BaseException) as exc:
        halt.get_verdict("nope")
    assert "unknown case_id" in str(exc.value)

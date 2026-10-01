"""M0b: empirically resolve R1 (EVM emit availability) under local GLSim direct mode."""

from gltest.direct import pytest_plugin  # noqa: F401  (registers fixtures)


def test_evm_interface_behaviour(direct_deploy):
    probe = direct_deploy("contracts/probe_r1.py", target="0x" + "11" * 20)
    probe.read_target()
    print("DETAIL:", probe.detail)
    print("VIEW_OK:", int(probe.view_ok), "EMIT_OK:", int(probe.emit_ok))

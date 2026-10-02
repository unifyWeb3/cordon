"""M0b: empirically resolve R1 (EVM emit availability) under local GLSim direct mode."""

from gltest.direct import pytest_plugin  # noqa: F401  (registers fixtures)
from conftest import SDK_VERSION


def test_evm_interface_behaviour(direct_deploy):
    probe = direct_deploy("contracts/probe_r1.py", target="0x" + "11" * 20, sdk_version=SDK_VERSION)
    probe.read_target()
    print("DETAIL:", probe.detail)
    print("VIEW_OK:", int(probe.view_ok), "EMIT_OK:", int(probe.emit_ok))

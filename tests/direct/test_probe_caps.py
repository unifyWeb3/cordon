from gltest.direct import pytest_plugin  # noqa: F401


def test_capabilities(direct_deploy):
    p = direct_deploy("contracts/probe_caps.py")
    p.probe()
    print("NOTE:", p.note)

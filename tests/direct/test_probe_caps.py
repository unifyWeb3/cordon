from gltest.direct import pytest_plugin  # noqa: F401
from conftest import SDK_VERSION


def test_capabilities(direct_deploy):
    p = direct_deploy("contracts/probe_caps.py", sdk_version=SDK_VERSION)
    p.probe()
    print("NOTE:", p.note)

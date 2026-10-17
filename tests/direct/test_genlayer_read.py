"""The relay's GenLayer read path.

`deploy/genlayer_read.py` exists because the SDK client could not do this job, and the reasons
are recorded in `state/MEMORY.md`. Two of them are worth re-stating here, because they are what
the tests below are actually about:

1. `genlayer-py` (0.18.0) reports the LIVE contract as "not found" -- `gen_call failed
   (code=-32001)` -- at the correct endpoint, correct chain and correct address, while
   `genlayer-js` reads it happily. `AGENTS.md`: never conclude "the contract is gone" from a
   Python SDK `gen_call` failure.
2. `read_contract` raises `GenLayerError` unless an account is connected, so reading PUBLIC
   state through it would require a GenLayer private key. A relay should hold none.

So the reader keeps the SDK's *encoder* (still reliable) and does its own keyless transport.

THE COMPARISON IS NOT A TAUTOLOGY
---------------------------------
`test_encode_call_matches_the_sdk_read_path` drives the SDK's real `read_contract` against a
fake provider and compares the `data` it puts on the wire against `encode_call`. Re-deriving
`serialize([calldata.encode(...), b"\x00"])` inside the test would only re-assert the same
expression; calling the SDK's own entry point is what makes this a cross-check.

WHAT IS NOT VERIFIED HERE
-------------------------
That a live Studionet node answers this request. There is no `.env` and no key in this checkout,
so no live endpoint is reachable. The unit tests below use a local stub. Live reads remain
unverified from here, and the Stage 2 report says so.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from genlayer_py.abi import calldata
from genlayer_py.contracts.actions import read_contract
from genlayer_py.exceptions import GenLayerError
from genlayer_py.types import TransactionHashVariant

from genlayer_read import (
    READ_SENDER,
    GenLayerReadError,
    GenLayerReader,
    decode_result,
    encode_call,
    studionet_rpc_url,
)
from rpc_stub import LocalRpc, RpcError

ADDRESS = "0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774B"


class _FakeProvider:
    """Captures what the SDK would put on the wire, and returns a decodable result."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def make_request(self, method, params):
        self.calls.append({"method": method, "params": params})
        return {"result": calldata.encode("ok").hex()}


class _FakeClient:
    def __init__(self) -> None:
        self.provider = _FakeProvider()
        self.local_account = SimpleNamespace(address="0x" + "ab" * 20)


# ------------------------------------------------------- agreement with the SDK's read path


@pytest.mark.parametrize(
    "method, args",
    [
        ("list_cases", []),
        ("get_evidence", ["live-drain-run2"]),
        ("get_evidence", ["case with spaces"]),
        ("stats", []),
    ],
)
def test_encode_call_matches_the_sdk_read_path(method, args):
    """Byte-for-byte against the SDK's own `read_contract`, not against a copy of its code."""
    client = _FakeClient()
    read_contract(client, ADDRESS, method, args, {})

    sent = client.provider.calls[-1]
    assert sent["method"] == "gen_call"
    request = sent["params"][0]
    assert request["data"] == encode_call(method, args), (
        "the reader's calldata has drifted from the SDK's read_contract"
    )
    assert request["type"] == "read"
    assert request["to"] == ADDRESS


def test_the_reader_asks_for_finalized_state():
    """The record is created at finality, so a non-final read could see a half-written case.

    The SDK's default is `latest-nonfinal`; this reader deliberately overrides it, and the test
    pins that so the override cannot quietly disappear.
    """
    client = _FakeClient()
    read_contract(client, ADDRESS, "list_cases", [], {})
    sdk_default = client.provider.calls[-1]["params"][0]["transaction_hash_variant"]

    assert sdk_default == TransactionHashVariant.LATEST_NONFINAL.value == "latest-nonfinal"

    seen: dict = {}

    def handler(method, params):
        seen.update(params[0])
        return "0x" + calldata.encode(["a"]).hex()

    rpc = LocalRpc(handler)
    try:
        GenLayerReader(rpc.url).call(ADDRESS, "list_cases", [])
    finally:
        rpc.close()

    assert seen["transaction_hash_variant"] == "latest-final"
    assert seen["transaction_hash_variant"] != sdk_default


def test_the_read_request_is_keyless():
    """No account, no key, no signature: the request is a plain public read.

    Asserted on the request that actually went over HTTP. `READ_SENDER` is checked too, but the
    wire is the thing that matters -- the SDK raises without an account, which is precisely the
    defect this module routes around.
    """
    seen: dict = {}

    def handler(method, params):
        seen.update(params[0])
        return "0x" + calldata.encode("ok").hex()

    rpc = LocalRpc(handler)
    try:
        GenLayerReader(rpc.url).call(ADDRESS, "get_evidence", ["c"])
    finally:
        rpc.close()

    assert seen["from"] == READ_SENDER == "0x" + "00" * 20
    assert set(seen) == {"type", "to", "from", "data", "transaction_hash_variant"}
    assert seen["to"] == ADDRESS

    # And the module carries no signing surface at all.
    import genlayer_read

    source = open(genlayer_read.__file__).read()
    for forbidden in ("Account", "private_key", "unsafe_sign_hash", "create_client"):
        assert forbidden not in source, f"{forbidden} has no place in a keyless reader"


def test_the_sdk_would_refuse_this_read_without_an_account():
    """The defect being routed around, demonstrated rather than described."""
    client = _FakeClient()
    client.local_account = None

    with pytest.raises(GenLayerError) as exc:
        read_contract(client, ADDRESS, "list_cases", [], {})
    assert "No account" in str(exc.value)

    # The reader does the same read with no account at all.
    def handler(method, params):
        return "0x" + calldata.encode(["one-case"]).hex()

    rpc = LocalRpc(handler)
    try:
        assert GenLayerReader(rpc.url).call(ADDRESS, "list_cases", []) == ["one-case"]
    finally:
        rpc.close()


# ------------------------------------------------------- decoding


def test_decode_result_round_trips_values():
    values = [["live-drain-run2", "other"], {"verdict": "CONFIRMED_EXPLOIT", "frozen": True}]
    for value in values:
        assert decode_result("0x" + calldata.encode(value).hex()) == value
        # The SDK assumes the node omits the 0x; some nodes include it. Both must work.
        assert decode_result(calldata.encode(value).hex()) == value


@pytest.mark.parametrize("blob", ["", "0x", "0x0"])
def test_an_empty_result_decodes_to_none(blob):
    assert decode_result(blob) is None


def test_the_reader_decodes_a_case_list_and_a_record():
    record = {
        "case_id": "live-drain-run2",
        "target": "0x" + "22" * 20,
        "evidence_mode": "jsonrpc",
        "verdict": "CONFIRMED_EXPLOIT",
        "frozen": True,
        "expires_at": "2026-10-17T09:00:00Z",
        "evidence": {"tx_to": "0x" + "22" * 20},
    }

    def handler(method, params):
        request = params[0]
        # Route on the exact calldata a node would receive, rather than re-deriving the
        # encoding the test is meant to be checking.
        if request["data"] == encode_call("list_cases", []):
            return "0x" + calldata.encode(["live-drain-run2"]).hex()
        return "0x" + calldata.encode(record).hex()

    rpc = LocalRpc(handler)
    try:
        reader = GenLayerReader(rpc.url)
        assert reader.call(ADDRESS, "list_cases", []) == ["live-drain-run2"]
        assert reader.call(ADDRESS, "get_evidence", ["live-drain-run2"]) == record
    finally:
        rpc.close()


# ------------------------------------------------------- failure modes


def test_a_node_error_is_raised_not_swallowed():
    """The documented `-32001 not found`. It must not read as "this contract has no cases"."""
    def handler(method, params):
        raise RpcError(-32001, f"Contract {ADDRESS} not found")

    rpc = LocalRpc(handler)
    try:
        with pytest.raises(GenLayerReadError) as exc:
            GenLayerReader(rpc.url).call(ADDRESS, "list_cases", [])
        assert "-32001" in str(exc.value)
        assert "not found" in str(exc.value)
    finally:
        rpc.close()


def test_an_absent_result_is_an_error_not_an_empty_list():
    """A null/absent `result` is the shape that used to read as "no cases"."""
    rpc = LocalRpc(lambda method, params: None)
    try:
        with pytest.raises(GenLayerReadError) as exc:
            GenLayerReader(rpc.url).call(ADDRESS, "list_cases", [])
        assert "empty result" in str(exc.value)
    finally:
        rpc.close()


def test_an_undecodable_result_is_an_error():
    rpc = LocalRpc(lambda method, params: "0xdeadbeefdeadbeef")
    try:
        with pytest.raises(GenLayerReadError) as exc:
            GenLayerReader(rpc.url).call(ADDRESS, "list_cases", [])
        assert "undecodable" in str(exc.value)
    finally:
        rpc.close()


def test_a_transport_failure_is_an_error():
    reader = GenLayerReader("http://127.0.0.1:1/definitely-not-listening", timeout=2)
    with pytest.raises(GenLayerReadError) as exc:
        reader.call(ADDRESS, "list_cases", [])
    assert "transport failure" in str(exc.value)


def test_a_non_json_response_is_an_error():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            payload = b"<html>this is not JSON</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        with pytest.raises(GenLayerReadError) as exc:
            GenLayerReader(f"http://{host}:{port}").call(ADDRESS, "list_cases", [])
        assert "non-JSON" in str(exc.value)
    finally:
        server.shutdown()
        server.server_close()


def test_studionet_rpc_url_comes_from_the_pinned_sdk():
    """Not hardcoded: if upstream moves it, this breaks loudly instead of reading stale."""
    url = studionet_rpc_url()
    assert url.startswith("http")
    assert "genlayer" in url


def test_the_reader_sends_one_request_per_call_and_nothing_else():
    """A read must not fan out: extra requests would make the relay's view of the record
    non-atomic, and the relay's whole argument is that it re-derives from one fresh read."""
    rpc = LocalRpc(lambda method, params: "0x" + calldata.encode([]).hex())
    try:
        reader = GenLayerReader(rpc.url)
        reader.call(ADDRESS, "list_cases", [])
        assert len(rpc.requests) == 1
        reader.call(ADDRESS, "get_evidence", ["x"])
        assert len(rpc.requests) == 2
        assert all(r["method"] == "gen_call" for r in rpc.requests)
    finally:
        rpc.close()


def test_the_arguments_are_the_ones_asked_for():
    """`get_evidence` must carry the exact case id, or the relay reads another case."""
    seen: list = []

    def handler(method, params):
        seen.append(json.loads(json.dumps(params[0])))
        return "0x" + calldata.encode({}).hex()

    rpc = LocalRpc(handler)
    try:
        GenLayerReader(rpc.url).call(ADDRESS, "get_evidence", ["live-drain-run2"])
    finally:
        rpc.close()

    assert seen[0]["data"] == encode_call("get_evidence", ["live-drain-run2"])
    assert seen[0]["data"] != encode_call("get_evidence", ["live-drain-run1"])

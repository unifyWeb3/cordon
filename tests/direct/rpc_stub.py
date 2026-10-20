"""A local JSON-RPC endpoint for tests, plus a py-evm backed handler.

Two jobs, both about not faking the layer under test:

1. `LocalRpc` gives a real HTTP endpoint on 127.0.0.1, so a client under test does real HTTP
   with real JSON instead of having `requests` monkeypatched. The previous relay read failure
   was a *transport* problem, and a transport problem cannot be tested by stubbing the
   transport.
2. `py_evm_handler` bridges those calls into an in-process `EthereumTester`, so `Evm.send` --
   including its signed raw transaction and its nonce handling -- actually executes. That is
   where the previous relay had a real defect, and a mocked receipt would not have shown it.

WHAT THIS STUB CHANGES, AND WHY THAT IS HONEST
----------------------------------------------
py-evm is a consensus-rule EVM, not a node. It differs from a real RPC endpoint in ways that
are about *serving* rather than about *executing*, and the stub absorbs them so the client
under test can keep sending what a real chain expects:

  * py-evm requires `from` on a call; real nodes default it to the zero address.
  * py-evm prices a call at `gas * base fee` and rejects a sender who cannot afford it. The
    zero address never can. The stub substitutes a funded sender -- and the tests then assert
    on `rpc.requests` that the client really did send the zero address, which is the property
    that actually matters and is not something py-evm's acceptance could demonstrate anyway.
  * py-evm's dicts are snake_case and want ints; JSON-RPC is camelCase with hex quantities.
    Translating here means a client that got the wire format wrong still fails.
  * py-evm's receipt contains `bytes`. Serialised to hex, as a node does.

One consequence worth stating plainly: a `gasPrice` low enough to be rejected by a real
Base Sepolia node would still be accepted here, because py-evm accepts whatever clears its
base fee. The relay's live gas behaviour is NOT verified by these tests.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from eth_tester.exceptions import TransactionNotFound

ZERO_ADDRESS = "0x" + "00" * 20


class RpcError(Exception):
    """Raised by a handler to return a JSON-RPC error object."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _hex(value: int) -> str:
    return hex(value)


def _jsonify(value: Any) -> Any:
    """Bytes -> 0x-hex, recursively, so a receipt can go on the wire."""
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    return value


# eth-tester's dictionaries are snake_case (`gas_price`) and it rejects unknown keys outright,
# whereas JSON-RPC is camelCase (`gasPrice`). The translation lives in the stub, not the client:
# a client that spoke snake_case would be wrong on a real node, and the relay is checked against
# a real chain's shape.
_FIELD_MAP = {
    "gasPrice": "gas_price",
    "maxFeePerGas": "max_fee_per_gas",
    "maxPriorityFeePerGas": "max_priority_fee_per_gas",
    "accessList": "access_list",
    "chainId": "chain_id",
}

# Hex-quantity fields JSON-RPC sends as strings, which eth-tester wants as plain ints.
_NUMERIC = {
    "gas",
    "gas_price",
    "max_fee_per_gas",
    "max_priority_fee_per_gas",
    "value",
    "nonce",
    "chain_id",
}

# The other direction: eth-tester's receipt keys -> the names a node puts on the wire.
_RECEIPT_FIELDS = {
    "block_hash": "blockHash",
    "block_number": "blockNumber",
    "contract_address": "contractAddress",
    "cumulative_gas_used": "cumulativeGasUsed",
    "effective_gas_price": "effectiveGasPrice",
    "gas_used": "gasUsed",
    "logs_bloom": "logsBloom",
    "state_root": "stateRoot",
    "transaction_hash": "transactionHash",
    "transaction_index": "transactionIndex",
}


def _to_tester_tx(tx: dict) -> dict:
    """JSON-RPC (camelCase, hex-quantity) -> eth-tester (snake_case, int)."""
    out = {}
    for key, value in tx.items():
        key = _FIELD_MAP.get(key, key)
        if key in _NUMERIC and isinstance(value, str):
            value = int(value, 16)
        out[key] = value
    return out


def py_evm_handler(tester) -> Callable[[str, list], Any]:
    """The JSON-RPC methods the relay uses, backed by an in-process EVM.

    Returns hex-encoded numbers exactly as a real node does, so the client cannot accidentally
    depend on getting Python ints. `status` in particular is a hex string: the relay compares it
    after `int(..., 16)`, and handing it an int here would hide a bug that only appears against
    a real chain.
    """

    def handler(method: str, params: list) -> Any:
        if method == "eth_chainId":
            return _hex(tester.backend.chain.chain_id)

        if method == "eth_getTransactionCount":
            # eth-tester spells this `get_nonce`, not `get_transaction_count`.
            block = params[1] if len(params) > 1 else "latest"
            return _hex(tester.get_nonce(params[0], block))

        if method == "eth_getBlockByNumber":
            block = tester.get_block_by_number(params[0] if params else "latest")
            return _jsonify(
                {
                    "number": _hex(block["number"]),
                    "timestamp": _hex(block["timestamp"]),
                    "hash": block["hash"],
                }
            )

        if method == "eth_gasPrice":
            # A real node quotes what the next block needs, and py-evm enforces it: a legacy
            # transaction whose gas_price is below the block's base fee is rejected outright
            # ("Sender's max fee per gas (0) is lower than block's base fee per gas"). So this is
            # read from the chain rather than invented. The relay never asks -- it sends a fixed
            # 1 gwei -- but `deploy/deploy_target.py` does, because a deployment should not carry
            # a price that only happens to work.
            block = tester.get_block_by_number("latest")
            return _hex(block.get("base_fee_per_gas") or 1_000_000_000)

        if method == "eth_getCode":
            address = params[0]
            block = params[1] if len(params) > 1 else "latest"
            return _jsonify(tester.get_code(address, block))

        if method == "eth_call":
            tx = _to_tester_tx(params[0])
            # Substituted, not preserved: see the module docstring. The tests assert the real
            # sender on the wire.
            tx["from"] = tester.get_accounts()[0]
            tx.pop("gas_price", None)
            tx.pop("gas", None)
            return tester.call(tx, params[1] if len(params) > 1 else "latest")

        if method == "eth_estimateGas":
            tx = _to_tester_tx(params[0])
            tx.setdefault("from", tester.get_accounts()[0])
            # eth-tester forwards this to `create_unsigned_transaction`, which in this version
            # has no `chain_id` kwarg. Real nodes accept it in eth_estimateGas, so the client
            # sends it and the stub drops it -- the alternative is a client that omits a field
            # real chains expect, which is how the previous relay broke.
            tx.pop("chain_id", None)
            return _hex(tester.estimate_gas(tx))

        if method == "eth_sendRawTransaction":
            # eth-tester wants the hex STRING here, not decoded bytes -- the opposite of what it
            # accepts for a transaction dict. Its return type also varies by version, so
            # normalise both directions rather than assuming one.
            raw = params[0]
            if isinstance(raw, bytes):
                raw = "0x" + raw.hex()
            out = tester.send_raw_transaction(raw)
            if isinstance(out, str):
                return out if out.startswith("0x") else "0x" + out
            return "0x" + bytes(out).hex()

        if method == "eth_getTransactionReceipt":
            try:
                receipt = tester.get_transaction_receipt(params[0])
            except TransactionNotFound:
                return None
            if receipt is None:
                return None
            # eth-tester spells its receipt keys in snake_case; a node spells them in camelCase,
            # and the translation belongs here rather than in the client -- same reason the relay
            # sends `gasPrice` and not `gas_price`. A client that read `contract_address` would
            # fail only on the live chain. `deploy/deploy_target.py` reads `contractAddress` out
            # of this receipt, which is how the gap was found.
            out = {_RECEIPT_FIELDS.get(key, key): value for key, value in receipt.items()}
            out["status"] = _hex(int(receipt["status"]))
            out["gasUsed"] = _hex(int(receipt.get("gas_used", 0)))
            out["blockNumber"] = _hex(int(receipt["block_number"]))
            return _jsonify(out)

        raise RpcError(-32601, f"method not found: {method}")

    return handler


class RawRpc:
    """An HTTP endpoint that returns exactly what a test dictates.

    `LocalRpc` always answers 200 with a valid JSON-RPC envelope, which is right for testing
    the protocol and useless for testing the failures *around* it: a 502 from a proxy, a body
    that is HTML, or an endpoint that accepts the connection and then never answers (a
    timeout). Those are the failures that were actually observed in the field, and they cannot
    be exercised by stubbing the transport -- so this is a real socket returning real bytes.
    """

    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        content_type: str = "application/json",
        delay: float = 0.0,
    ) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type
        self.delay = delay
        self.requests: list[dict] = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 (http.server API)
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) or b"{}"
                try:
                    outer.requests.append(json.loads(raw))
                except ValueError:
                    outer.requests.append({"_undecodable": raw})
                if outer.delay:
                    # Long enough for the client's own timeout to fire mid-request.
                    time.sleep(outer.delay)
                self.send_response(outer.status)
                self.send_header("Content-Type", outer.content_type)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                try:
                    self.wfile.write(outer.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client timed out and went away, which is the point

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class LocalRpc:
    """A threaded HTTP JSON-RPC server on an ephemeral port."""

    def __init__(self, handler: Callable[[str, list], Any]) -> None:
        self.handler = handler
        self.requests: list[dict] = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 (http.server API)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    outer.requests.append(body)
                    try:
                        result = outer.handler(body.get("method"), body.get("params") or [])
                        response = {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
                    except RpcError as exc:
                        response = {
                            "jsonrpc": "2.0",
                            "id": body.get("id"),
                            "error": {"code": exc.code, "message": exc.message},
                        }
                    payload = json.dumps(response).encode()
                except Exception as exc:  # noqa: BLE001
                    # Serialisation failures used to escape `do_POST` and close the socket,
                    # which the client sees as a bare RemoteDisconnected with no clue why. Turn
                    # it into a legible node error instead.
                    payload = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {
                                "code": -32700,
                                "message": f"stub could not serialise a response: "
                                f"{type(exc).__name__}: {exc}",
                            },
                        }
                    ).encode()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):  # keep the test output readable
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

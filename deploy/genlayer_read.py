"""Keyless GenLayer reads: raw `gen_call` over plain HTTPS.

WHY NOT `genlayer_py`'s client
-----------------------------
Two independent reasons, both documented in `state/MEMORY.md` and the pinned SDK source:

1. `MEMORY.md` records that `genlayer-py` 0.18.0 answered
   `gen_call failed (code=-32001): Contract 0x37E08A26... not found` at the correct endpoint,
   correct chain and correct address, while `genlayer-js` 1.1.8 read the same contract. That was
   reproduced twice, and it did **not** reproduce against the redeployed contract on 2026-10-17:
   the same SDK version reads `0x95be4d88…` for both the schema and `stats()`. So the failure was
   specific to that deployment rather than to the endpoint or to the SDK as a whole — and
   `AGENTS.md` still says never to conclude "the contract is gone" from one Python SDK
   `gen_call` failure.
2. `genlayer_py/contracts/actions.py` raises `GenLayerError` from `read_contract` unless an
   account is connected. Reading PUBLIC state would therefore require a GenLayer private key,
   which is wrong for a relay that should hold no privileged access at all. **This reason is
   structural and did not change with the redeployment** — it is what keeps this module on the
   keyless path.

So this module does the one thing the SDK is still reliable for -- producing the calldata
blob -- and does the transport itself with `requests`. No account, no key, no client object.

NOTE ON VERIFICATION
--------------------
The encoding below is verified against the pinned SDK by `tests/direct/test_genlayer_read.py`
(byte-for-byte comparison with `genlayer_py`'s own `serialize([calldata.encode(...), b"\\x00"])`).
It has NOT been verified against a live Studionet node from this checkout: there is no `.env`
and no `.venv-deploy` here, so no live endpoint or key is available. The unit tests use a
local fake JSON-RPC server.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from genlayer_py.abi import calldata
from genlayer_py.abi.transactions import serialize
from genlayer_py.contracts.utils import make_calldata_object

# The zero address as `from`. gen_call only reads, and passing a zero sender means this path
# genuinely needs no account. Kept in one place so a future switch to a real sender is visible.
READ_SENDER = "0x" + "00" * 20


class GenLayerReadError(RuntimeError):
    """Any failure to obtain a decoded read result. Never returns a partial value.

    The endpoint value is deliberately NOT part of these messages: `AGENTS.md` forbids printing
    a `.env` value, "public endpoints included", and the caller knows which endpoint it passed.
    """


def studionet_rpc_url() -> str:
    """Studionet's public endpoint, read from the pinned SDK config.

    Taken from `genlayer_py` rather than hardcoded for the same reason the rest of this repo
    pins versions: if it moves upstream, this breaks loudly instead of quietly reading a stale
    endpoint. Callers must NOT print the result -- see `AGENTS.md` on endpoint values.
    """
    from genlayer_py.chains.studionet import studionet as sn

    urls = sn.rpc_urls["default"]["http"]
    return urls[0]


def encode_call(method: str, args: list | None = None) -> str:
    """Method name + args -> the `data` blob for a gen_call read.

    Identical to what `genlayer_py`'s `read_contract` puts on the wire, which is why the SDK is
    still imported for encoding even though its client is not used.
    """
    obj = make_calldata_object(method=method, args=args or [], kwargs=[])
    return serialize([calldata.encode(obj), b"\x00"])


def decode_result(blob: str) -> Any:
    """gen_call result hex -> decoded value. `None` for an empty/absent result."""
    if not blob or blob in ("0x", "0x0"):
        return None
    text = blob[2:] if blob.startswith("0x") else blob
    return calldata.decode(bytes.fromhex(text))


class GenLayerReader:
    """Minimal keyless reader for one GenLayer RPC endpoint."""

    def __init__(self, rpc_url: str, timeout: int = 40) -> None:
        self.rpc_url = rpc_url
        self.timeout = timeout

    def call(self, address: str, method: str, args: list | None = None) -> Any:
        params = [
            {
                "type": "read",
                "to": address,
                "from": READ_SENDER,
                "data": encode_call(method, args),
                "transaction_hash_variant": "latest-final",
            }
        ]
        try:
            response = requests.post(
                self.rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "gen_call", "params": params},
                timeout=self.timeout,
            )
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            # Must be caught BEFORE RequestException: requests' JSONDecodeError inherits from
            # BOTH ValueError and RequestException, so the transport branch would swallow it and
            # report a bad body as a network fault. That sends the reader debugging the network
            # when the endpoint actually returned HTML -- a captive portal, or the wrong URL.
            raise GenLayerReadError(f"{method}: non-JSON response: {exc}") from exc
        except requests.RequestException as exc:
            # Covers connect failures AND timeouts (`ReadTimeout` is a `RequestException`).
            raise GenLayerReadError(f"{method}: transport failure: {exc}") from exc
        except ValueError as exc:
            raise GenLayerReadError(f"{method}: non-JSON response: {exc}") from exc

        # Checked AFTER the body is parsed so a JSON-RPC error object can be quoted, which is
        # the most useful part, and BEFORE the result is interpreted: without this, a 502 from a
        # proxy -- very often a JSON body with no `result` -- is reported as "empty result",
        # i.e. as a fact about the contract instead of about the connection.
        if response.status_code >= 400:
            detail = ""
            if isinstance(payload, dict) and payload.get("error"):
                detail = f": {json.dumps(payload['error'])}"
            raise GenLayerReadError(
                f"{method}: HTTP {response.status_code} from the endpoint{detail}"
            )

        if not isinstance(payload, dict):
            raise GenLayerReadError(
                f"{method}: malformed JSON-RPC envelope ({type(payload).__name__})"
            )
        if payload.get("error"):
            raise GenLayerReadError(f"{method}: {json.dumps(payload['error'])}")

        result = payload.get("result")
        if result is None:
            # genlayer-py surfaces this exact shape when the node cannot see the contract.
            # Report it as itself rather than letting it read as "contract has no cases".
            raise GenLayerReadError(
                f"{method}: the endpoint returned no result (an absent `result` is not an "
                "empty answer; the Python SDK reports a live contract this way -- see "
                "state/MEMORY.md)"
            )

        try:
            decoded = decode_result(result if isinstance(result, str) else "0x" + result)
        except Exception as exc:  # noqa: BLE001
            raise GenLayerReadError(f"{method}: undecodable result: {exc}") from exc

        if decoded is None:
            # The *other* spelling of "no value": a present-but-empty body. `decode_result`
            # returns None for it, which is right for a pure decoder and wrong to hand back from
            # a reader whose callers do `record["verdict"]` -- they would get a TypeError from a
            # different module. One condition, one outcome.
            raise GenLayerReadError(
                f"{method}: the endpoint returned an empty value; refusing to report an empty "
                "read as a result"
            )
        return decoded

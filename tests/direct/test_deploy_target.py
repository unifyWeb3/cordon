"""`deploy/deploy_target.py`, exercised against an in-process EVM before it touches a chain.

This script sends the one transaction in this repository that cannot be undone, so the tests here
are about the transaction it builds rather than about the chain it points at. It is built, signed
and executed on `eth-tester` through the same JSON-RPC shape a real node speaks (`rpc_stub.py`),
which is what makes it possible to check the encoding, the gasPrice requirement and the
"record the hash before broadcasting" rule without spending anything.

What these tests cannot establish is the live run: `--dry-run` against Base Sepolia, and then the
real deployment. The script's docstring says so, and so does `state/MEMORY.md`.
"""

from __future__ import annotations

import json

import pytest
from eth_abi import decode as abi_decode
from eth_utils import to_checksum_address

from deploy_target import RefusedToDeploy, Rpc, compile_pool, creation_data, deploy, verify_contract
from evm_harness import Pool, evm, keys, pool_artifact  # noqa: F401 (fixtures)
from rpc_stub import LocalRpc, RpcError, py_evm_handler

MAX_WINDOW = 3600


def test_creation_data_is_the_bytecode_followed_by_the_encoded_constructor_args():
    """The creation blob is `bytecode || abi.encode(address[], uint256)`, byte for byte.

    Decoded rather than string-compared, so the assertion is about the constructor arguments the
    pool will actually receive.
    """
    attester = "0x" + "22" * 20
    data = creation_data("0x60016002", attester, MAX_WINDOW)
    body = bytes.fromhex(data[2:])

    assert body[:4] == bytes.fromhex("60016002")
    attesters, max_window = abi_decode(["address[]", "uint256"], body[4:])
    assert [to_checksum_address(a) for a in attesters] == [to_checksum_address(attester)]
    assert max_window == MAX_WINDOW


def test_the_deployer_creates_the_pool_with_the_configured_attester(
    evm, keys, pool_artifact, tmp_path  # noqa: F811
):
    """Deploy through the real JSON-RPC surface, then read the contract back.

    The deployed address comes out of the receipt, and every assertion after that is a call
    against the chain — a receipt that says `status: 1` while the constructor ignored its
    arguments would pass a receipt-only check and fail here.
    """
    abi, bytecode = pool_artifact
    rpc = LocalRpc(py_evm_handler(evm))
    attester = to_checksum_address(evm.get_accounts()[1])
    deployer_key = keys[3]
    out = tmp_path / "target.json"

    record = deploy(
        rpc_url=rpc.url,
        private_key=deployer_key,
        attester=attester,
        max_window=MAX_WINDOW,
        bytecode=bytecode,
        out_path=out,
    )

    pool = Pool(evm, abi, record["contractAddress"])
    assert pool.call("isAttester", attester) is True
    assert pool.call("isAttester", "0x" + "00" * 20) is False
    assert pool.call("attesterCount") == 1
    assert pool.call("MAX_WINDOW") == MAX_WINDOW
    assert pool.call("owner") == record["deployer"]
    assert pool.call("frozenUntil") == 0
    assert pool.call("isFrozen") is False

    # The read-back table agrees, on the same chain the transaction executed on.
    checks = verify_contract(
        Rpc(rpc.url),
        record["contractAddress"],
        attester=attester,
        max_window=MAX_WINDOW,
        deployer=record["deployer"],
    )
    failed = [(name, detail) for name, passed, detail in checks if not passed]
    assert not failed, failed

    # The record is on disk with the hash and the address, and the address in it is the one the
    # chain has code at.
    written = json.loads(out.read_text())
    assert written["txHash"] == record["txHash"]
    assert written["contractAddress"] == record["contractAddress"]
    assert written["status"] == "mined"
    assert len(Rpc(rpc.url).code(record["contractAddress"])) > 2


def test_verification_fails_when_believed_about_a_different_attester(
    evm, keys, pool_artifact, tmp_path  # noqa: F811
):
    """`verify_contract` must read the chain, not repeat the deployment's intentions.

    Deployed with one attester and verified as if it had been another: the read-back table is the
    only thing that can catch that, so it has to disagree.
    """
    abi, bytecode = pool_artifact
    rpc = LocalRpc(py_evm_handler(evm))
    attester = to_checksum_address(evm.get_accounts()[1])
    someone_else = to_checksum_address(evm.get_accounts()[2])

    record = deploy(
        rpc_url=rpc.url,
        private_key=keys[3],
        attester=attester,
        max_window=MAX_WINDOW,
        bytecode=bytecode,
        out_path=tmp_path / "target.json",
    )

    ok = verify_contract(
        Rpc(rpc.url),
        record["contractAddress"],
        attester=attester,
        max_window=MAX_WINDOW,
        deployer=record["deployer"],
    )
    assert all(passed for _, passed, _ in ok), ok

    wrong = verify_contract(
        Rpc(rpc.url),
        record["contractAddress"],
        attester=someone_else,
        max_window=MAX_WINDOW,
        deployer=record["deployer"],
    )
    failed = [name for name, passed, _ in wrong if not passed]
    assert "isAttester(attester) is true" in failed, wrong

    # And it is not merely "some check failed": the checks that do not depend on which attester
    # was named still pass, so the failure is about the attester and nothing else.
    still_ok = [name for name, passed, _ in wrong if passed]
    assert "attesterCount()" in still_ok and "MAX_WINDOW()" in still_ok
    assert "owner() is the deployer" in still_ok


def test_the_tx_hash_is_on_disk_before_the_transaction_is_broadcast(
    evm, keys, pool_artifact, tmp_path  # noqa: F811
):
    """A killed script must not lose the hash of a transaction it has already sent.

    The node refuses the broadcast here, which is the worst case for that rule: the transaction
    was never mined, so the record on disk is the only trace of what was signed. It has to exist,
    and it has to say that it was not sent.
    """
    abi, bytecode = pool_artifact
    inner = py_evm_handler(evm)

    def refusing(method, params):
        if method == "eth_sendRawTransaction":
            raise RpcError(-32000, "insufficient funds for gas * price + value")
        return inner(method, params)

    out = tmp_path / "target.json"
    with pytest.raises(RuntimeError) as exc:
        deploy(
            rpc_url=LocalRpc(refusing).url,
            private_key=keys[4],
            attester=to_checksum_address(evm.get_accounts()[1]),
            max_window=MAX_WINDOW,
            bytecode=bytecode,
            out_path=out,
        )
    assert "insufficient funds" in str(exc.value)

    record = json.loads(out.read_text())
    assert record["txHash"].startswith("0x")
    assert len(record["txHash"]) == 66
    assert record["status"] == "signed-not-sent"
    assert record["contractAddress"] is None


@pytest.mark.parametrize(
    "attester,max_window,expected",
    [
        ("0x" + "00" * 20, MAX_WINDOW, "zero address"),
        ("not-an-address", MAX_WINDOW, "not an address"),
        ("0x" + "22" * 20, 0, "must be positive"),
    ],
)
def test_a_deployment_that_could_not_work_is_refused_before_anything_is_spent(
    attester, max_window, expected, tmp_path
):
    """The refusals happen before the first RPC call, so the endpoint here is deliberately dead.

    A wrong attester or a zero window is caught by the pool's constructor too — after the
    transaction is mined, at the cost of the fee, with a revert reason instead of an argument.
    """
    with pytest.raises(RefusedToDeploy) as exc:
        deploy(
            rpc_url="http://127.0.0.1:1",  # nothing listens here; it is never contacted
            private_key="0x" + "11" * 32,
            attester=attester,
            max_window=max_window,
            bytecode="0x6001",
            out_path=tmp_path / "target.json",
        )
    assert expected in str(exc.value)


def test_the_deployer_compiles_the_same_bytecode_the_tests_execute(pool_artifact):  # noqa: F811
    """The artifact this script sends is the artifact the EVM tests run.

    Same compiler invocation, same flags, same source path — so the deployment cannot execute
    bytecode that nothing has tested. If this fails, one of those three drifted.
    """
    abi, bytecode = compile_pool()
    assert bytecode == pool_artifact[1]

    names = {entry["name"] for entry in abi if entry.get("type") == "function"}
    assert "freezeFromAttestation" in names
    assert "freeze" not in names, "the owner pause must not be back in the interface"

"""Deploy `HaltablePool.sol` to a live EVM chain with one attester, and verify it there.

Why this file exists: `demo-target` compiles the pool with the npm `solcjs` WASM build, and
`freeze_watcher.py` broadcasts a transaction somebody else has already signed — but nothing in
this repo sent a *contract creation* transaction. There is no `forge`, no `cast` and no `solc`
binary on the development host (linux/aarch64, where the upstream static solc is amd64-only), so
the creation transaction is built and signed here.

The order of the steps is the point:

  1. **Compile fresh, from source, into a directory this run owns.** `out/` is never read. The
     test harness already lost a session to a stale artifact under a guessed name and reported a
     successful execution of a contract it had never compiled; a deployment is the worst possible
     place to repeat that.
  2. **Sign a legacy transaction, `gasPrice` included.** Base is an OP-stack L2 and `eth-account`
     rejects a transaction without it ("Transaction must include these fields: {'gasPrice'}").
  3. **Record the transaction hash in the output file BEFORE broadcasting it.** The GenLayer
     deploy in the same stage as this file was killed by a timeout *after* it had sent its
     transaction, and the hash existed only in the killed process's output buffer; recovering it
     meant reading the explorer and then confirming the address against the node. A hash written
     before the send cannot be lost that way.
  4. **Verify against the chain, not against the receipt.** `status: 0x1` proves that a
     transaction was mined, not that *this* contract sits at that address with the immutables this
     deployment meant to set. Every constructor-set value is read back, and the deployed runtime
     code is checked for the interface it must have — and for the one it must not.

Exit code is 0 only if every check passes; the checks are printed as expected-vs-actual.

Reads key names only — `BASE_SEPOLIA_PRIVATE_KEY`, `BASE_SEPOLIA_RPC_URL` — and prints neither a
key nor an endpoint value (`AGENTS.md`). Everything printed is public: chain id, the deployer and
contract addresses, the attester, gas numbers, the transaction hash.

    .venv-deploy/bin/python deploy/deploy_target.py --attester 0x...
    .venv-deploy/bin/python deploy/deploy_target.py --attester 0x... --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import requests  # noqa: E402
from eth_abi import decode as abi_decode  # noqa: E402
from eth_abi import encode as abi_encode  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_utils import is_address, keccak, to_checksum_address  # noqa: E402

POOL_SOURCE = ROOT / "demo-target" / "src" / "HaltablePool.sol"
SOLC_JS = ROOT / "demo-target" / "node_modules" / ".bin" / "solcjs"
OUT_ROOT = ROOT / "demo-target" / "out"

DEFAULT_OUT = Path("/tmp/opencode/target-deployment.json")
DEFAULT_MAX_WINDOW = 3600
ZERO_ADDRESS = "0x" + "00" * 20

# A 4-byte selector appears in the deployed runtime code as a PUSH4 iff that function exists:
# solc's dispatcher compares the incoming selector against a constant per public function. This
# was checked against the pool in both directions -- `isAttester(address)` and
# `freezeFromAttestation(...)` are found; `attesters(address)` (a name that does not exist) and
# `freeze(string,uint256)` (the function stage 2 removed) are not. That is the mistake worth
# catching here: the previous live target had a different interface, an owner pause instead of an
# attestation.
REQUIRED_SELECTORS = [
    "freezeFromAttestation(bytes32,bytes32,bool,uint256,bytes)",
    "isAttester(address)",
    "isFrozen()",
    "unfreeze(string)",
    "MAX_WINDOW()",
]
FORBIDDEN_SELECTORS = [
    # Removed deliberately: no owner pause, and no caller-chosen deadline.
    "freeze(string,uint256)",
]


class RefusedToDeploy(RuntimeError):
    """The deployment was refused before spending, or before believing anything."""


def selector(signature: str) -> str:
    return keccak(text=signature)[:4].hex()


def _as_encoded(type_: str, value):
    """`0x`-hex -> bytes for the byte types.

    `eth-abi` accepts a hex string for `address` and only `bytes` for `bytes32`/`bytes`, so the
    two cannot be passed the same way. Getting this wrong fails inside the encoder with a message
    naming the *value* rather than the argument, which is a confusing way to spend five minutes.
    """
    if isinstance(value, str) and value.startswith("0x") and type_.startswith("bytes"):
        return bytes.fromhex(value[2:])
    return value


def compile_pool() -> tuple[list, str]:
    """`demo-target/src/HaltablePool.sol` -> (abi, bytecode). Fresh, never from `out/`."""
    return compile_source(POOL_SOURCE, "HaltablePool")


def compile_source(source: Path, artifact: str | None = None) -> tuple[list, str]:
    """One Solidity file -> (abi, bytecode). Fresh, never from `out/`.

    Same rule as `tests/direct/evm_harness.py`: an empty directory, one compiler invocation, take
    whatever single artifact appears, fail loudly on anything else. `solcjs` names its output
    after the input path *as it was handed to the compiler*, so the artifact name is never
    constructed by hand.

    `artifact` names the contract to take when the file declares more than one (interfaces and
    test harnesses do). Without it the compile must yield exactly one artifact.
    """
    solc = str(SOLC_JS) if SOLC_JS.exists() else shutil.which("solcjs")
    if not solc:
        raise RefusedToDeploy(
            f"no compiler: neither {SOLC_JS} nor a `solcjs` on PATH. "
            "Run `npm install` in demo-target/ (it pins solc 0.8.24)."
        )
    if not source.exists():
        raise RefusedToDeploy(f"source not found: {source}")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="deploy-", dir=OUT_ROOT))
    result = subprocess.run(
        [solc, "--bin", "--abi", "--optimize", "-o", str(out), str(source)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    abi_files = sorted(out.glob(f"*_{artifact}.abi" if artifact else "*.abi"))
    bin_files = sorted(out.glob(f"*_{artifact}.bin" if artifact else "*.bin"))
    if result.returncode != 0 or len(abi_files) != 1 or len(bin_files) != 1:
        produced = ", ".join(sorted(p.name for p in out.iterdir())) or "nothing"
        raise RefusedToDeploy(
            f"solc did not produce exactly one artifact for {source.name} "
            f"(exit={result.returncode}, abi={len(abi_files)}, bin={len(bin_files)}, "
            f"produced: {produced})\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    bytecode = bin_files[0].read_text().strip()
    if not bytecode:
        raise RefusedToDeploy(f"solc produced an empty bytecode file: {bin_files[0].name}")
    return json.loads(abi_files[0].read_text()), bytecode


def creation_data(bytecode: str, attester: str, max_window: int) -> str:
    """Creation code followed by `abi.encode(address[] attesters_, uint256 maxWindow_)`."""
    body = bytecode[2:] if bytecode.startswith("0x") else bytecode
    return "0x" + body + abi_encode(["address[]", "uint256"], [[attester], max_window]).hex()


class Rpc:
    """The calls a deployment needs. The endpoint value stays out of every message."""

    def __init__(self, url: str, timeout: int = 30) -> None:
        self.url = url
        self.timeout = timeout

    def call(self, method: str, params: list):
        try:
            response = requests.post(
                self.url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=self.timeout,
            )
            payload = response.json()
        except ValueError as exc:
            # Before RequestException-like branches: requests' JSONDecodeError inherits from both,
            # and a captive portal returning HTML is a different fault from an unreachable node.
            raise RuntimeError(f"{method}: the endpoint did not answer with JSON: {exc}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"{method}: the endpoint did not answer: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"{method}: malformed JSON-RPC envelope ({type(payload).__name__})")
        if payload.get("error"):
            raise RuntimeError(f"{method}: {payload['error']}")
        return payload.get("result")

    def uint(self, method: str, params: list) -> int:
        result = self.call(method, params)
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RuntimeError(f"{method}: expected a hex quantity, got {result!r}")
        return int(result, 16)

    def chain_id(self) -> int:
        return self.uint("eth_chainId", [])

    def gas_price(self) -> int:
        return self.uint("eth_gasPrice", [])

    def nonce(self, address: str) -> int:
        return self.uint("eth_getTransactionCount", [address, "pending"])

    def code(self, address: str, block: str = "latest") -> str:
        code = self.call("eth_getCode", [address, block])
        return code if isinstance(code, str) else "0x"

    def send_raw(self, raw: str) -> str:
        return self.call("eth_sendRawTransaction", [raw])

    def call_contract(
        self, to: str, signature: str, args: list | None = None, block: str = "latest"
    ) -> str:
        """`to` + a Solidity signature (optionally with arguments) -> the raw return data.

        The argument types come from the signature itself, so a read here cannot disagree with
        the selector that was hashed from it.

        `block` exists because `"latest"` is not a fact: a public load-balanced endpoint can
        answer consecutive requests from nodes at different heads, so a read taken immediately
        after a receipt can describe the state *before* the transaction. A verification that
        must be final names the receipt's own block.
        """
        data = "0x" + selector(signature)
        if args:
            types = [t.strip() for t in signature[signature.index("(") + 1 : -1].split(",")]
            data += abi_encode(types, [_as_encoded(t, v) for t, v in zip(types, args)]).hex()
        out = self.call("eth_call", [{"to": to, "data": data}, block])
        if not isinstance(out, str) or len(out) <= 2:
            raise RuntimeError(f"{signature} returned nothing at {to} (block {block})")
        return out

    def read_uint(
        self, to: str, signature: str, args: list | None = None, block: str = "latest"
    ) -> int:
        return int(self.call_contract(to, signature, args, block=block), 16)

    def read_address(self, to: str, signature: str, block: str = "latest") -> str:
        raw = bytes.fromhex(self.call_contract(to, signature, block=block)[2:])
        return to_checksum_address(raw[-20:])

    def receipt(self, tx_hash: str, tries: int = 45, interval: float = 2.0):
        """Wait for the receipt, bounded.

        `tries * interval` is the whole budget and it is deliberately under two minutes: a
        broadcast transaction that has not been mined by then is a question for a human, not for
        a longer loop.
        """
        for _ in range(tries):
            receipt = self.call("eth_getTransactionReceipt", [tx_hash])
            if receipt:
                return receipt
            time.sleep(interval)
        raise RuntimeError(
            f"no receipt for {tx_hash} after {tries * interval:.0f}s; the transaction may still "
            f"be pending -- do not re-send it, check the hash"
        )


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def deploy(
    *,
    rpc_url: str,
    private_key: str,
    attester: str,
    max_window: int,
    bytecode: str,
    out_path: Path,
    dry_run: bool = False,
) -> dict:
    """Build, sign, broadcast and mine the creation transaction. Returns the record written out."""
    if not is_address(attester):
        raise RefusedToDeploy(f"attester is not an address: {attester!r}")
    attester = to_checksum_address(attester)
    if attester == ZERO_ADDRESS:
        raise RefusedToDeploy("attester is the zero address; the pool's constructor rejects it")
    if max_window <= 0:
        raise RefusedToDeploy(f"max_window must be positive, got {max_window}")

    account = Account.from_key(private_key)
    rpc = Rpc(rpc_url)

    tx = {
        "from": account.address,
        "value": "0x0",
        "data": creation_data(bytecode, attester, max_window),
        "nonce": hex(rpc.nonce(account.address)),
        "chainId": rpc.chain_id(),
        # Legacy, with gasPrice: see the module docstring. An EIP-1559-only transaction is
        # rejected outright by eth-account on this chain.
        "gasPrice": hex(rpc.gas_price()),
    }
    estimate = int(rpc.call("eth_estimateGas", [tx]), 16)
    # Headroom: the estimate is a simulation against the state at the time it ran, and a
    # deployment that runs out of gas reverts and still costs the fee.
    tx["gas"] = hex(estimate * 5 // 4)

    signed = account.sign_transaction(tx)
    tx_hash = "0x" + bytes(signed.hash).hex()
    raw = "0x" + bytes(signed.raw_transaction).hex()

    record = {
        "chainId": tx["chainId"],
        "deployer": account.address,
        "attester": attester,
        "maxWindow": max_window,
        "txHash": tx_hash,
        "contractAddress": None,
        "gasEstimate": estimate,
        "gasLimit": int(tx["gas"], 16),
        "gasPrice": tx["gasPrice"],
        "status": "signed-not-sent",
    }
    _write(out_path, record)  # before the send, deliberately

    print(f"  chain id         : {tx['chainId']}")
    print(f"  deployer         : {account.address}")
    print(f"  attester         : {attester}   (constructor argument)")
    print(f"  maxWindow        : {max_window}")
    print(f"  gas              : estimate {estimate}, sending {int(tx['gas'], 16)}")
    print(f"  tx hash          : {tx_hash}")
    print(f"  recorded         : {out_path} (before broadcasting)")

    if dry_run:
        print("  dry run          : built and signed, NOT broadcast")
        return record

    sent = rpc.send_raw(raw)
    if not isinstance(sent, str) or sent.lower() != tx_hash.lower():
        raise RuntimeError(f"the node returned {sent!r} for a signed tx {tx_hash}; not believing it")
    record["status"] = "sent"
    _write(out_path, record)

    receipt = rpc.receipt(tx_hash)
    if int(receipt["status"], 16) != 1:
        raise RuntimeError(f"deployment reverted on chain (tx {tx_hash}); nothing was created")
    address = receipt.get("contractAddress")
    if not address:
        raise RefusedToDeploy(f"receipt reports success but has no contractAddress: {receipt}")
    record["contractAddress"] = to_checksum_address(address)
    record["blockNumber"] = receipt.get("blockNumber")
    record["gasUsed"] = receipt.get("gasUsed")
    record["status"] = "mined"
    _write(out_path, record)
    return record


def verify_contract(
    rpc: Rpc,
    address: str,
    *,
    attester: str,
    max_window: int,
    deployer: str,
    block: str = "latest",
) -> list[tuple[str, bool, str]]:
    """Read the deployed contract back off the chain. Returns [(check, passed, expected vs actual)].

    `block` should be the deployment receipt's own block: see `Rpc.call_contract` on why
    `"latest"` can still describe the pre-deployment state right after a success receipt.
    """
    code = rpc.code(address, block)
    checks: list[tuple[str, bool, str]] = [
        ("runtime code present", len(code) > 2, f"expected >0 bytes, got {len(code) // 2 - 1}"),
    ]

    for signature in REQUIRED_SELECTORS:
        present = selector(signature) in code
        checks.append(
            (f"has {signature}", present, f"expected its selector in the code, {'found' if present else 'absent'}")
        )
    for signature in FORBIDDEN_SELECTORS:
        absent = selector(signature) not in code
        checks.append(
            (f"lacks {signature}", absent, f"expected no {selector(signature)}, {'absent' if absent else 'FOUND'}")
        )

    reads = [
        ("attesterCount()", "attesterCount()", 1, None),
        ("MAX_WINDOW()", "MAX_WINDOW()", max_window, None),
        ("isAttester(attester) is true", "isAttester(address)", 1, [attester]),
        # Together with `attesterCount() == 1` this says the set has exactly one member and it is
        # the requested attester -- not merely that the requested one was added.
        ("isAttester(zero address) is false", "isAttester(address)", 0, [ZERO_ADDRESS]),
        ("frozenUntil()", "frozenUntil()", 0, None),
        ("isFrozen()", "isFrozen()", 0, None),
    ]
    for name, signature, expected, args in reads:
        got = rpc.read_uint(address, signature, args, block)
        checks.append((name, got == expected, f"expected {expected}, got {got}"))

    # The function the Python attester has to agree with, read as a call rather than a selector:
    # its inputs and its 32-byte output both have to be there for a signature to verify at all.
    digest = rpc.call_contract(
        address,
        "attestationDigest(bytes32,bytes32,bool,uint256)",
        ["0x" + "11" * 32, "0x" + "22" * 32, True, max_window],
        block,
    )
    checks.append(
        (
            "attestationDigest(...) returns 32 bytes",
            len(digest) == 66,
            f"expected 32 bytes, got {(len(digest) - 2) // 2}",
        )
    )

    owner = rpc.read_address(address, "owner()", block)
    checks.append(
        (
            "owner() is the deployer",
            owner == to_checksum_address(deployer),
            f"expected {to_checksum_address(deployer)}, got {owner}",
        )
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="deploy HaltablePool.sol and verify it on chain")
    parser.add_argument("--attester", required=True, help="the attester address (passed to the constructor)")
    parser.add_argument(
        "--max-window",
        type=int,
        default=DEFAULT_MAX_WINDOW,
        help=f"longest accepted freeze window in seconds (default {DEFAULT_MAX_WINDOW})",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="where to record the hash and address")
    parser.add_argument("--dry-run", action="store_true", help="build and sign, print, do not broadcast")
    parser.add_argument("--rpc-url", default=None, help="override BASE_SEPOLIA_RPC_URL (tests use a stub)")
    args = parser.parse_args(argv)

    key = os.environ.get("BASE_SEPOLIA_PRIVATE_KEY")
    rpc_url = args.rpc_url or os.environ.get("BASE_SEPOLIA_RPC_URL")
    missing = [
        name
        for name, value in (("BASE_SEPOLIA_PRIVATE_KEY", key), ("BASE_SEPOLIA_RPC_URL", rpc_url))
        if not value
    ]
    if missing:
        print(
            f"missing {', '.join(missing)}: set them in the environment or the repo-root .env "
            f"(names are reported, values never are)",
            file=sys.stderr,
        )
        return 2

    try:
        _abi, bytecode = compile_pool()
        print(f"  source           : {POOL_SOURCE.relative_to(ROOT)} -> {len(bytecode) // 2} bytes")
        record = deploy(
            rpc_url=rpc_url,
            private_key=key,
            attester=args.attester,
            max_window=args.max_window,
            bytecode=bytecode,
            out_path=Path(args.out),
            dry_run=args.dry_run,
        )
        if args.dry_run:
            return 0
        checks = verify_contract(
            Rpc(rpc_url),
            record["contractAddress"],
            attester=record["attester"],
            max_window=record["maxWindow"],
            deployer=record["deployer"],
            # Pinned to the receipt's own block: a load-balanced RPC can otherwise answer this
            # read from a node whose head predates the deployment (observed 2026-10-20).
            block=record["blockNumber"] or "latest",
        )
    except (RefusedToDeploy, RuntimeError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"  contract         : {record['contractAddress']}")
    print(f"  block            : {record['blockNumber']}  gasUsed {record['gasUsed']}")
    print("  verification      (read back off the chain, not taken from the receipt):")
    passed = True
    for name, ok, detail in checks:
        passed &= ok
        print(f"    {'PASS' if ok else 'FAIL'}  {name:<38} {detail}")
    record["verified"] = {name: ok for name, ok, _ in checks}
    _write(Path(args.out), record)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""In-process EVM harness: compiles `HaltablePool.sol` and runs it on py-evm.

Why this exists
---------------
`HaltablePool` now accepts a freeze only from a signed attestation. If the tests only
inspected the ABI, the `ecrecover` path, the domain separator and the expiry checks would all
ship unverified -- which is the exact failure mode `AGENTS.md` exists to prevent. So the
Solidity is *executed* here, with real signatures.

Toolchain
---------
`solc-js` (WASM) from `demo-target/node_modules`, not a native `solc`. The upstream
`solc-static-linux` binary is amd64-only and this project is developed and tested on
linux/aarch64, where it cannot execute at all.

Two failure modes are kept apart on purpose, because collapsing them is how a run ends up
green while verifying nothing:

  * **No compiler on the machine** -> ``SolcMissing``, and the tests SKIP, by name, with the
    one command that fixes it. Skipping is a deliberate trade: requiring node for a Python
    suite is real friction. It is not a quiet trade -- ``conftest.py`` fails the session on
    an unaccepted skip, see ``pytest_sessionfinish`` there.
  * **Compiler present and it refused the source** -> ``SolcCompileFailed``, which is a hard
    error and never a skip. Broken Solidity must not be able to turn the run green.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_tester import EthereumTester, PyEVMBackend
from eth_utils import keccak, to_checksum_address

ROOT = Path(__file__).resolve().parent.parent.parent
SOLC_BIN = ROOT / "demo-target" / "node_modules" / ".bin" / "solcjs"
POOL_SOURCE = ROOT / "demo-target" / "src" / "HaltablePool.sol"
HARNESS_OUT = ROOT / "demo-target" / "out" / "harness"

SKIP_REASON = (
    "solc-js is not installed, so HaltablePool.sol CANNOT be compiled or executed and the "
    "attestation/ecrecover path is UNVERIFIED by this run. Install with: "
    "cd demo-target && npm install"
)


class SolcMissing(RuntimeError):
    """No Solidity compiler is present at all. Tests skip, and the session says so."""


class SolcCompileFailed(RuntimeError):
    """A compiler is present and it would not produce a usable artifact. Never a skip."""


def find_solc() -> str:
    if SOLC_BIN.exists():
        return str(SOLC_BIN)
    found = shutil.which("solcjs")
    if found:
        return found
    raise SolcMissing(SKIP_REASON)


def compile_pool() -> tuple[list, str]:
    """Compile `HaltablePool.sol` -> (abi, bytecode-hex).

    Recompiles on every call, into a directory this harness owns and empties first. Both
    halves of that sentence are load-bearing, and both were learned by watching this file
    lie:

      * **The artifact name is never guessed.** `solcjs` names its output after the source
        path it was handed, *relative to the current directory*. Invoked from the repo root
        with `demo-target/src/HaltablePool.sol` it writes
        `demo-target_src_HaltablePool_sol_HaltablePool.abi`; invoked from inside
        `demo-target/` with `src/HaltablePool.sol` it writes
        `src_HaltablePool_sol_HaltablePool.abi`. So a harness that hardcodes one of those
        names finds nothing in a clean checkout -- and, worse, *does* find the artifact left
        behind by `npm run build`, runs old bytecode, and reports a successful execution of
        a contract it never compiled. That is exactly the defect class `AGENTS.md` warns
        about, and this file had it. Now: empty the directory, run solc, take whatever
        single artifact appears, and fail loudly if it is not exactly one of each.
      * **Compiling unconditionally** means an edited `.sol` can never be tested through a
        stale artifact. It costs a few seconds once per session.
    """
    if HARNESS_OUT.exists():
        shutil.rmtree(HARNESS_OUT)
    HARNESS_OUT.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [find_solc(), "--bin", "--abi", "--optimize",
         "-o", str(HARNESS_OUT), str(POOL_SOURCE)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )

    abi_files = sorted(HARNESS_OUT.glob("*.abi"))
    bin_files = sorted(HARNESS_OUT.glob("*.bin"))
    if result.returncode != 0 or len(abi_files) != 1 or len(bin_files) != 1:
        produced = ", ".join(sorted(p.name for p in HARNESS_OUT.iterdir())) or "nothing"
        raise SolcCompileFailed(
            f"solc did not produce exactly one artifact for HaltablePool.sol "
            f"(exit={result.returncode}, abi={len(abi_files)}, bin={len(bin_files)}, "
            f"produced: {produced})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )

    bytecode = bin_files[0].read_text().strip()
    if not bytecode:
        raise SolcCompileFailed(f"solc produced an empty bytecode file: {bin_files[0].name}")
    return json.loads(abi_files[0].read_text()), bytecode


class Pool:
    """Thin ABI wrapper over a deployed HaltablePool, so tests read like the Solidity."""

    def __init__(self, tester: EthereumTester, abi: list, address: str) -> None:
        self.t = tester
        self.abi = abi
        self.address = to_checksum_address(address)

    def _entry(self, name: str) -> dict:
        for entry in self.abi:
            if entry.get("type") == "function" and entry.get("name") == name:
                return entry
        raise KeyError(name)

    def _calldata(self, name: str, args: list) -> str:
        entry = self._entry(name)
        types = [i["type"] for i in entry["inputs"]]
        selector = keccak(text=f"{name}({','.join(types)})")[:4].hex()
        return "0x" + selector + abi_encode(types, args).hex()

    def call(self, name: str, *args, sender: str | None = None):
        """Read-only call. Returns the single output value, or a tuple for multi-output.

        `address` outputs are checksummed, so tests can compare them directly against the
        addresses pytest's fixtures hand out. Without this, `pool.call("owner") == accounts[0]`
        is False purely because one side came back lowercase -- a confusing way to fail.
        """
        entry = self._entry(name)
        outputs = [o["type"] for o in entry["outputs"]]
        raw = self.t.call(
            {
                "from": sender or self.t.get_accounts()[0],
                "to": self.address,
                "data": self._calldata(name, list(args)),
            }
        )
        if not outputs:
            return None
        values = list(abi_decode(outputs, bytes.fromhex(raw[2:])))
        for i, out_type in enumerate(outputs):
            if out_type == "address":
                values[i] = to_checksum_address(values[i])
        return values[0] if len(values) == 1 else tuple(values)

    @property
    def block_time(self) -> int:
        """Current chain timestamp.

        Deadlines must be computed from this, never from the host clock: the tests run on a
        chain whose time is its own, and `maxWindow` is measured against block time.
        """
        return self.t.get_block_by_number("latest")["timestamp"]

    def _tx(self, sender: str, name: str, args: list, gas: int, value: int) -> dict:
        tx: dict = {
            "from": sender,
            "to": self.address,
            "data": self._calldata(name, args),
            "gas": gas,
        }
        if value:
            tx["value"] = value
        return tx

    def send(self, sender: str, name: str, *args, gas: int = 400_000, value: int = 0) -> dict:
        """State-changing call -> receipt.

        Returns the receipt WITHOUT asserting anything. `py-evm` reports a reverted
        transaction as `status: 0` and does NOT raise, so a caller that ignores the status
        will read a failed call as a success -- which is the exact defect class this repo
        keeps hitting. Use `expect_ok` or `expect_revert` unless you mean to inspect the
        status yourself.
        """
        h = self.t.send_transaction(self._tx(sender, name, list(args), gas, value))
        return self.t.get_transaction_receipt(h)

    def expect_ok(self, sender: str, name: str, *args, gas: int = 400_000, value: int = 0) -> dict:
        """Send and require the receipt to report success."""
        receipt = self.send(sender, name, *args, gas=gas, value=value)
        assert receipt["status"] == 1, (
            f"{name} did not succeed on the target (receipt status=0); "
            f"reason: {self.revert_reason(name, *args, sender=sender, value=value)}"
        )
        return receipt

    def revert_reason(self, name: str, *args, sender: str | None = None, value: int = 0) -> str:
        """Run the call through `eth_call` and return the revert string.

        `eth_call` raises with the decoded reason, unlike `send_transaction`, which reports
        `status: 0` silently.
        """
        from eth_tester.exceptions import TransactionFailed

        try:
            self.t.call(
                self._tx(sender or self.t.get_accounts()[0], name, list(args), 1_000_000, value)
            )
        except TransactionFailed as exc:
            return str(exc)
        return ""

    def expect_revert(self, name: str, *args, sender: str | None = None) -> str:
        """Require the call to revert, and return the revert string for comparison.

        Uses `eth_call` so the reason is available. Also confirms via a real transaction that
        nothing was written, so "reverted" cannot be satisfied by a call that quietly did
        nothing on the eth_call path but succeeded on the send path.

        CLOCK WARNING for time-dependent reverts: the confirmation transaction is mined into a
        NEW block, and py-evm stamps a new block at `max(parent + 1, wall_clock)`. Time moves
        forward, so a condition that held at `eth_call` time can stop holding:
        `expiresAt <= block.timestamp + MAX_WINDOW` gets EASIER to satisfy as time passes.
        A caller testing such a bound must leave a margin of seconds, not sit exactly on it,
        or this helper will report a false failure. Same class of mistake as deadlines taken
        from the host clock -- see `AGENTS.md` on Base Sepolia running ahead.
        """
        reason = self.revert_reason(name, *args, sender=sender)
        assert reason, f"{name} was expected to revert but did not"
        receipt = self.send(sender or self.t.get_accounts()[0], name, *args)
        assert receipt["status"] == 0, (
            f"{name} reverted under eth_call ({reason!r}) but SUCCEEDED as a transaction"
        )
        return reason

    def advance_to(self, timestamp: int) -> int:
        """Move chain time to `timestamp` and return the new latest block timestamp.

        `time_travel` only queues the timestamp for the NEXT block, so a block has to be mined
        before the new time is visible. Without the mine, `isFrozen()` still reads the old
        clock and the test silently asserts against a stale timestamp.

        Used to prove the window closes on its own: `isFrozen()` is a pure read of the
        deadline, so once `block.timestamp` passes it the pool is open again with no
        transaction from anyone.
        """
        self.t.time_travel(timestamp)
        self.t.mine_block()
        return self.t.get_block_by_number("latest")["timestamp"]


def deploy_pool(
    tester: EthereumTester,
    abi: list,
    bytecode: str,
    attesters: list[str],
    max_window: int = 3600,
    deployer: str | None = None,
) -> Pool:
    ctor = abi_encode(["address[]", "uint256"], [attesters, max_window]).hex()
    sender = deployer or tester.get_accounts()[0]
    h = tester.send_transaction(
        {"from": sender, "data": "0x" + bytecode + ctor, "gas": 5_000_000}
    )
    receipt = tester.get_transaction_receipt(h)
    assert receipt["status"] == 1, "HaltablePool deployment reverted"
    return Pool(tester, abi, receipt["contract_address"])


def deployment_revert_reason(tester: EthereumTester, abi: list, bytecode: str,
                             attesters: list[str], max_window: int = 3600,
                             deployer: str | None = None) -> str:
    """Revert string a bad constructor would produce. "" if it would succeed.

    Uses `eth_call` because a reverting deployment via `send_transaction` returns
    `status: 0` and `contract_address: None` without raising, so `pytest.raises` would not
    fire on it.
    """
    from eth_tester.exceptions import TransactionFailed

    ctor = abi_encode(["address[]", "uint256"], [attesters, max_window]).hex()
    try:
        tester.call(
            {
                "from": deployer or tester.get_accounts()[0],
                "data": "0x" + bytecode + ctor,
                "gas": 5_000_000,
            }
        )
    except TransactionFailed as exc:
        return str(exc)
    return ""


# --------------------------------------------------------------------- fixtures


# Set to a reason string when the whole module skipped for want of a compiler, so
# `conftest.pytest_sessionfinish` can refuse to call that run green.
SOLC_SKIPPED: str | None = None


@pytest.fixture(scope="session")
def pool_artifact():
    """(abi, bytecode). Skips the whole module, but only if there is no compiler at all.

    `SolcCompileFailed` is deliberately not caught: a compiler that is present and refuses
    the source is a broken contract, and it must be an error.
    """
    global SOLC_SKIPPED
    try:
        return compile_pool()
    except SolcMissing as exc:
        SOLC_SKIPPED = str(exc)
        pytest.skip(str(exc))


@pytest.fixture
def evm():
    """A fresh chain per test, so freeze state never leaks between tests."""
    return EthereumTester(PyEVMBackend())


@pytest.fixture
def keys(evm):
    """Private keys for the ten pre-funded accounts, in `get_accounts()` order.

    Returned as `0x`-prefixed hex strings rather than `eth_keys.PrivateKey` objects, because
    that is what every consumer here wants: `Account.unsafe_sign_hash`, `Account.from_key`,
    and `Evm(rpc, key)`. The objects themselves have no `.hex()` and no `.to_0x_hex()`.
    """
    return [k.to_hex() for k in evm.backend.account_keys]


@pytest.fixture
def accounts(evm):
    return [to_checksum_address(a) for a in evm.get_accounts()]


@pytest.fixture
def attester(accounts, keys):
    """The signing key. NOT the relay: see `relay` below."""
    return accounts[1], keys[1]


@pytest.fixture
def relay(accounts, keys):
    """The relay's key. Holds gas only -- it is not an attester and cannot freeze."""
    return accounts[2], keys[2]


def sign(digest: bytes, private_key) -> bytes:
    """Sign a raw 32-byte EIP-712 digest -> 65-byte (r||s||v) with v in {27,28}."""
    signed = Account.unsafe_sign_hash(digest, private_key=private_key)
    signature = signed.signature
    assert len(signature) == 65
    assert signature[64] in (27, 28), f"unexpected v: {signature[64]}"
    return signature

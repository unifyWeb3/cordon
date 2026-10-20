"""Prove what can be proven about a deployed HaltablePool's code, from the chain.

WHY NOT JUST ETH_GETCODE == SOLC OUTPUT
---------------------------------------
`HaltablePool` has two immutables, `attesterCount` and `DOMAIN_SEPARATOR` (and `MAX_WINDOW`, which
happens to hold 3600). The deployed runtime therefore contains *values* written by the constructor,
so a plain comparison with a fresh compile can never be byte-equal: `DOMAIN_SEPARATOR` binds
`block.chainid` and `address(this)`, and a fresh compile has neither. What makes the comparison
stronger than "same length" is that `solc` appends a CBOR metadata blob containing the default
`solc` release plus the IPFS CID of the metadata JSON, which hashes the source path, the source
bytes, the compiler version and the optimizer settings:

  1. compile the source afresh, with the *same command* `deploy_target.py` uses
     (`solcjs --bin --abi --optimize -o <dir> <path>`), and read the creation bytecode;
  2. also compile with standard-JSON, only to get `deployedBytecode` and the immutable-reference
     offsets that solc itself reports;
  3. check that the tail of the creation bytecode is exactly that deployed bytecode -- that is what
     makes the creation-bytecode run comparable with `eth_getCode`;
  4. fetch the runtime with `eth_getCode`, mask the immutable ranges on both sides, and require the
     remainder to be byte-identical. That covers every opcode, every constant and the metadata blob;
  5. read each immutable word out of the live code and check it against the value the constructor
     should have written for THIS pool on THIS chain.

What this cannot prove, and the script repeats in its own output: that the creation *transaction*
carried this bytecode (creation code is not recoverable from a chain without tracing, and the node
is a public load-balanced endpoint that does not serve debug traces), nor when it was sent or by
whom. Those are receipt facts, recorded by `deploy_target.py` at deploy time.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address

ROOT = Path(__file__).resolve().parent.parent
POOL_SOURCE = ROOT / "demo-target" / "src" / "HaltablePool.sol"
SOLC_JS = ROOT / "demo-target" / "node_modules" / ".bin" / "solcjs"
DEFAULT_RPC = "https://base-sepolia-rpc.publicnode.com"


class ChainError(RuntimeError):
    pass


def find_solc() -> str:
    solc = str(SOLC_JS) if SOLC_JS.exists() else shutil.which("solcjs")
    if not solc:
        raise SystemExit(f"no compiler: neither {SOLC_JS} nor a solcjs on PATH")
    return solc


def _compile_standard_json(solc: str, source: Path, source_key: str) -> dict:
    """`deployedBytecode` + immutable offsets. Only solc knows where its immutables live."""
    standard = {
        "language": "Solidity",
        "sources": {source_key: {"content": source.read_text()}},
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {"*": {"*": ["evm.deployedBytecode"]}},
        },
    }
    # `solcjs --standard-json` reads STDIN, and it writes its JSON with async writes followed by an
    # immediate exit: against a pipe the tail is lost (observed: 65,618 of 248,104 bytes, which
    # fails to parse as an "unterminated string"). A file descriptor makes the writes synchronous.
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "out.json"
        with raw.open("wb") as fh:
            subprocess.run(
                [solc, "--standard-json"],
                input=json.dumps(standard).encode(),
                stdout=fh,
                stderr=subprocess.PIPE,
                check=True,
            )
        text = raw.read_text()
    # Progress noise ("no SMT solvers available") is printed on STDOUT ahead of the JSON.
    result = json.loads(text[text.find("{") :])
    errors = [e for e in result.get("errors", []) if e.get("severity") == "error"]
    if errors:
        raise SystemExit("compile failed: " + "; ".join(e["formattedMessage"] for e in errors))
    return result["contracts"][source_key][next(iter(result["contracts"][source_key]))]


def compile_with_deploy_method(solc: str, source: Path) -> tuple[bytes, bytes, list[tuple[int, int]]]:
    """The bytecode `deploy_target.py` builds, plus the runtime and immutable offsets.

    The CLI invocation is deliberately identical to `deploy_target.compile_pool` -- including the
    source path as written on the command line, because that string goes into the metadata and
    therefore into the metadata hash that ends up on chain.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        subprocess.run([solc, "--bin", "--abi", "--optimize", "-o", str(out), str(source)],
                       capture_output=True, check=True)
        bins = list(out.glob("*.bin"))
        if len(bins) != 1:
            raise SystemExit(f"solc produced {len(bins)} .bin artifacts, expected exactly 1")
        creation = bytes.fromhex(bins[0].read_text().strip())

    rel = source.relative_to(ROOT).as_posix()
    artifact = _compile_standard_json(solc, source, rel)
    deployed = bytes.fromhex(artifact["evm"]["deployedBytecode"]["object"])
    refs = artifact["evm"]["deployedBytecode"].get("immutableReferences") or {}
    ranges = [
        (int(place["start"]), int(place["start"]) + int(place["length"]), ident)
        for ident, places in refs.items()
        for place in places
    ]
    return creation, deployed, ranges


def rpc(url: str, method: str, params: list):
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=45)
    if r.status_code != 200:
        raise ChainError(f"{method}: HTTP {r.status_code}")
    body = r.json()
    if "error" in body:
        raise ChainError(f"{method}: {body['error']}")
    return body["result"]


def expected_domain_separator(chain_id: int, pool: str) -> bytes:
    domain_typehash = keccak(text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
    return keccak(
        abi_encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [domain_typehash, keccak(text="CordonVerdictAttestation"), keccak(text="1"), chain_id, pool],
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--address", required=True)
    parser.add_argument("--rpc", default=DEFAULT_RPC)
    parser.add_argument("--attester-count", type=int, default=1)
    parser.add_argument("--max-window", type=int, default=3600)
    args = parser.parse_args(argv)

    pool = to_checksum_address(args.address)
    solc = find_solc()
    creation, compiled, ranges = compile_with_deploy_method(solc, POOL_SOURCE)

    live_hex = rpc(args.rpc, "eth_getCode", [pool, "latest"])
    if live_hex in ("0x", ""):
        raise SystemExit(f"no code at {pool} -- wrong address or wrong chain")
    live = bytes.fromhex(live_hex[2:])
    chain_id = int(rpc(args.rpc, "eth_chainId", []), 16)

    print(f"compiler                 : solcjs {subprocess.run([solc, '--version'], capture_output=True, text=True).stdout.strip()}")
    print(f"pool                     : {pool}")
    print(f"chain id                 : {chain_id}")
    print(f"creation bytes (compiled): {len(creation)}")
    print(f"runtime bytes (compiled) : {len(compiled)}")
    print(f"runtime bytes (on chain) : {len(live)}")
    print(f"live sha256              : {hashlib.sha256(live).hexdigest()}")
    print(f"live keccak256           : 0x{keccak(live).hex()}")
    print(f"compiled keccak256       : 0x{keccak(compiled).hex()}  (immutables zero, as solc emits)")

    # The constructor copies the runtime out of the creation code, so the creation tx's bytecode
    # contains this exact tail. Checked rather than assumed.
    tail_is_runtime = len(creation) > len(compiled) and creation[-len(compiled) :] == compiled
    print(f"creation tail is runtime : {tail_is_runtime}")
    if not tail_is_runtime:
        print("  (metadata or codegen differs between the CLI and standard-JSON compiles)")
        print(f"  creation tail sha256   : {hashlib.sha256(creation[-len(compiled):]).hexdigest()}")

    masked_live = bytearray(live)
    masked_compiled = bytearray(compiled)
    for start, end, _ in ranges:
        for buf in (masked_live, masked_compiled):
            buf[start:end] = b"\x00" * (end - start)
    same = len(live) == len(compiled) and bytes(masked_live) == bytes(masked_compiled)
    diffs = [i for i in range(min(len(live), len(compiled))) if masked_live[i] != masked_compiled[i]]
    print(f"immutable ranges (solc)  : {[(s, e) for s, e, _ in ranges]}")
    print(f"equal outside immutables : {same}" + ("" if same else f"  ({len(diffs)} differing bytes at {diffs[:20]})"))

    expected = {
        "DOMAIN_SEPARATOR": expected_domain_separator(chain_id, pool),
        f"attesterCount={args.attester_count}": args.attester_count.to_bytes(32, "big"),
        f"MAX_WINDOW={args.max_window}": args.max_window.to_bytes(32, "big"),
    }
    print(f"expected DOMAIN_SEPARATOR: 0x{expected['DOMAIN_SEPARATOR'].hex()}")
    immutable_ok = True
    for start, end, ident in ranges:
        word = live[start:end]
        if end - start != 32:
            print(f"  ref {ident[:10]} at {start} is {end - start} bytes, not a 32-byte word")
            immutable_ok = False
            continue
        label = next((name for name, value in expected.items() if value == word), "NEITHER")
        print(f"  ref {ident[:10]} at {start}: 0x{word.hex()[:16]}...{word.hex()[-8:]} -> {label}")
        immutable_ok &= label != "NEITHER"

    ok = same and immutable_ok and tail_is_runtime
    print()
    print("VERDICT:", "the on-chain runtime is the fresh compile of this source, modulo exactly the"
          " constructor-written immutables, and each of those holds the value this pool should have"
          if ok else "MISMATCH -- see offsets above")
    print("NOT PROVEN: that the creation transaction carried this bytecode (creation code is not")
    print("            recoverable without tracing), nor when or by whom it was sent. Those are")
    print("            receipt facts -- see deploy/out/*.json from the deploy run.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

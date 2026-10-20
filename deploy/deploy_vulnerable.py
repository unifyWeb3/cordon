"""Deploy `VulnerableDemoPool.sol` and verify it on chain.

Same discipline as `deploy_target.py` (which deploys the non-vulnerable demo pool): compile
fresh, record the signed transaction BEFORE broadcasting, then read the deployed contract back
off the chain at the receipt's own block and print expected vs actual.

The extra check here is the flawed entry point: the deployed runtime must contain
`claimRewards(uint256)`'s selector. That is a *presence* check only -- the exploit itself is
executed by `deploy/staged_exploit.py` and asserted in `tests/direct/test_vulnerable_demo_pool.py`.

    .venv-deploy/bin/python deploy/deploy_vulnerable.py \
        --attester 0x... --max-window 3600 --out deploy/out/vulnerable-2026-10-20.json
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import deploy_target as D  # noqa: E402

VULNERABLE_SOURCE = ROOT / "demo-target" / "src" / "VulnerableDemoPool.sol"
DEFAULT_OUT = ROOT / "deploy" / "out" / "vulnerable-pool.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="deploy VulnerableDemoPool.sol and verify it")
    parser.add_argument("--attester", required=True)
    parser.add_argument("--max-window", type=int, default=3600)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--rpc-url", default=None)
    args = parser.parse_args(argv)

    key = os.environ.get("BASE_SEPOLIA_PRIVATE_KEY")
    rpc_url = args.rpc_url or os.environ.get("BASE_SEPOLIA_RPC_URL")
    missing = [
        name
        for name, value in (("BASE_SEPOLIA_PRIVATE_KEY", key), ("BASE_SEPOLIA_RPC_URL", rpc_url))
        if not value
    ]
    if missing:
        print(f"missing {', '.join(missing)} (names only)", file=sys.stderr)
        return 2

    try:
        _abi, bytecode = D.compile_source(VULNERABLE_SOURCE, "VulnerableDemoPool")
        print(f"  source           : {VULNERABLE_SOURCE.relative_to(ROOT)} -> {len(bytecode) // 2} bytes")
        record = D.deploy(
            rpc_url=rpc_url,
            private_key=key,
            attester=args.attester,
            max_window=args.max_window,
            bytecode=bytecode,
            out_path=Path(args.out),
        )
        rpc = D.Rpc(rpc_url)
        checks = D.verify_contract(
            rpc,
            record["contractAddress"],
            attester=record["attester"],
            max_window=record["maxWindow"],
            deployer=record["deployer"],
            block=record["blockNumber"] or "latest",
        )
        code = rpc.code(record["contractAddress"], record["blockNumber"] or "latest")
        flawed = D.selector("claimRewards(uint256)") in code
        checks.append(
            (
                "has claimRewards(uint256)",
                flawed,
                f"expected its selector in the code, {'found' if flawed else 'ABSENT'}",
            )
        )
        credit_capped = D.selector("withdraw(uint256)") in code
        checks.append(
            (
                "still has withdraw(uint256)",
                credit_capped,
                f"expected its selector in the code, {'found' if credit_capped else 'ABSENT'}",
            )
        )
    except (D.RefusedToDeploy, RuntimeError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"  contract         : {record['contractAddress']}")
    print(f"  block            : {record['blockNumber']} ({int(record['blockNumber'], 16)})"
          f"  gasUsed {int(record['gasUsed'], 16)}")
    print("  verification      (pinned to the deployment's own block):")
    passed = True
    for name, ok, detail in checks:
        passed &= ok
        print(f"    {'PASS' if ok else 'FAIL'}  {name:<40} {detail}")
    record["verified"] = {name: ok for name, ok, _ in checks}
    Path(args.out).write_text(pathlib_json(record) + "\n")
    print(f"  recorded         : {args.out}")
    return 0 if passed else 1


def pathlib_json(record: dict) -> str:
    import json

    return json.dumps(record, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())

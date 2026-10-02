"""Record real adjudication timings for the landing replay.

Why this exists
---------------
The replay in `web/src/components/HeroRun.tsx` compresses a real run, so we need a real run to
compress. LIVE-RUN.md recorded lifecycle *states* and verdicts but no durations.

Method, stated plainly so the numbers can be judged:
  * one fresh `case_id` per case -- `submit_proof` rejects duplicates, and mutating a case that
    README.md and the rubric self-review both cite would make those documents wrong
  * `gen_getTransactionStatus` polled as fast as the RPC will answer
  * the timestamp recorded is when WE OBSERVED the state, not when the node produced it, so every
    duration carries up to one poll interval of positive error

Writes `web/src/lib/sample-run.json`. Never prints a value from .env.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from eth_account import Account  # noqa: E402
from genlayer_py import create_client  # noqa: E402
from genlayer_py.chains.studionet import studionet as sn  # noqa: E402

HALT = "0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774b"
OUT = ROOT / "web" / "src" / "lib" / "sample-run.json"

# Suffix lets us record a fresh run without mutating the cases the docs cite.
CASES = [
	("live-drain-run2", "0x0822131fff60d8f5a2c62647869ed30638b543eb6e15bbb11b3b62b1581cb144",
	 "Attacker drained the protocol: the same transferFrom selector fires fourteen times inside "
	 "one transaction, sweeping the pool."),
	("live-real-tx-run2", "0xa7329a50fd54721c60a2d01deccbf8def3ed1ff03a31e03a40d06d135dcb19d7",
	 "Attacker drained the protocol with a repeated unbounded transferFrom in a single transaction."),
	("live-missing-run2", "0x0000000000000000000000000000000000000000000000000000000000000001",
	 "Definitely an exploit, trust me."),
]


def record(client, case_id: str, tx: str, claim: str) -> dict:
	payload = json.dumps({
		"case_id": case_id,
		"target": "0x" + "22" * 20,
		"tx_hash": tx,
		"claim": claim,
	})
	t0 = time.perf_counter()
	tx_id = client.write_contract(address=HALT, function_name="submit_proof",
	                              args=[payload], kwargs={}, value=0)
	print(f"  {case_id}: tx {tx_id}")

	trail: list[dict] = []
	seen: list[str] = []
	ms = 0
	deadline = time.time() + 420
	while time.time() < deadline:
		try:
			st = client.provider.make_request("gen_getTransactionStatus", [tx_id]).get("result")
		except Exception:  # noqa: BLE001 - transient; keep polling
			time.sleep(0.4)
			continue
		if st and (not seen or seen[-1] != st):
			ms = int((time.perf_counter() - t0) * 1000)
			seen.append(st)
			# `trail` is positional: entry i is the segment spent arriving at seen[i].
			trail.append(
				{"state": st,
				 "startedAt": trail[-1]["endedAt"] if trail else 0,
				 "endedAt": ms}
			)
			print(f"      {st:<12} @{ms} ms")
			if st == "FINALIZED":
				break
		time.sleep(0.4)

	consensus = None
	try:
		t = client.get_transaction(tx_id)
		consensus = t.get("result_name")
	except Exception:  # noqa: BLE001
		pass

	proof = client.read_contract(HALT, "get_evidence", [case_id], [])
	ev = proof.get("evidence") or {}
	# Index the trail by its recorded state, not by `seen` (which holds bare state names).
	to_accepted = next(
		(seg["endedAt"] for seg in trail if seg.get("state") == "ACCEPTED"), None
	)
	to_final = trail[-1]["endedAt"] if trail else None
	return {
		"id": case_id,
		"genlayerTx": tx_id,
		"targetChainTx": tx,
		"verdict": proof.get("verdict"),
		"rationale": proof.get("rationale"),
		"claim": proof.get("claim"),
		"submittedAt": proof.get("submitted_at"),
		"evidence": {
			"valueBand": ev.get("value_band"),
			"logBand": ev.get("log_band"),
			"inputSelector": ev.get("input_selector"),
			"receiptStatus": ev.get("receipt_status"),
			"repeatedTopic": (ev.get("repeated_selectors") or "").split(",")[0] or None,
			"txFound": ev.get("tx_found"),
		},
		"states": seen,
		"trail": trail,
		"timing": {
			"toAcceptedMs": to_accepted,
			"toFinalizedMs": to_final,
			"consensus": consensus,
			"pollIntervalMs": 400,
			"note": "Observed client-side, polling gen_getTransactionStatus every ~400ms. "
			        "Each duration therefore carries up to ~400ms of positive observation error.",
		},
	}


def main() -> int:
	client = create_client(chain=sn, account=Account.from_key(
		__import__("os").environ["GENLAYER_PRIVATE_KEY"]))
	recorded = []
	for case_id, tx, claim in CASES:
		print(f"recording {case_id} ...")
		try:
			recorded.append(record(client, case_id, tx, claim))
		except Exception as exc:  # noqa: BLE001
			print(f"  FAILED {type(exc).__name__}: {exc}")

	doc = {
		"provenance": {
			"network": "Studionet",
			"chainId": 61999,
			"contract": HALT,
			"recordedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
			"note": "Real adjudications against a deployed contract. Every field is the run's own; "
			        "the replay loop only decides when each step comes into view.",
		},
		"cases": recorded,
	}
	OUT.parent.mkdir(parents=True, exist_ok=True)
	OUT.write_text(json.dumps(doc, indent=2) + "\n")
	print(f"\nwrote {OUT} ({len(recorded)} cases)")
	for c in recorded:
		print(f"  {c['id']:<22} {c['verdict']:<22} "
		      f"accept={c['timing']['toAcceptedMs']}ms finalize={c['timing']['toFinalizedMs']}ms")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
